"""Infrastructure crashes are never comparable evidence (review finding 1b).

The catastrophic shape this file pins shut: a worker that dies BEFORE running any user code
(docker eating stdin, a container that cannot start, a respawn budget spent on boot failures)
used to synthesize identical CRASHED observations on base AND head — compare() said Equal and
a pure target earned EQUIVALENT_UNDER_BUDGET with ZERO user code executed (L2/L4 violation).

Now every harness-synthesized stand-in carries an explicit marker (`SyntheticObservation`);
compare() maps any synthetic side to Unprovable(WORKER_UNAVAILABLE) and the target verdict
degrades to UNPROVEN(HARNESS_SYNTHESIS_FAILED). Real user-code crashes (the target killing its
own process) remain comparable evidence, exactly as before. Every scenario here runs REAL
subprocesses (Law L4); the hostile sandboxes below spawn real children that genuinely die,
hang, or garble — nothing is simulated at the observation level.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tempest.compare.compare import (
    CompareConfig,
    Equal,
    SyntheticObservation,
    Unprovable,
    UnprovableKind,
)
from tempest.compare.compare import compare as compare_obs
from tempest.execute import runner
from tempest.execute.dual import _UnprovableTally, prove_impure_target, prove_target
from tempest.execute.runner import PersistentWorker, run_batch
from tempest.execute.sandbox import ProcessSandbox
from tempest.generate.inputs import Budget
from tempest.model import InputOutcome, ReasonCode, Verdict

CFG = CompareConfig()
SANDBOX = ProcessSandbox()

_ECHO = "def f(x: int) -> int:\n    return x * 2\n"


def _root(tmp_path: Path, src: str = _ECHO) -> Path:
    (tmp_path / "m.py").write_text(src)
    return tmp_path


def _fake_worker_sandbox_popen(
    inner: ProcessSandbox,
    program: str,
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    scratch: Path,
    stdin_pipe: bool,
) -> subprocess.Popen[bytes]:
    """Spawn a REAL child interpreter running `program` instead of the worker script — the
    honest way to produce a worker that dies/hangs/garbles before or after boot."""
    return inner.popen(
        [cmd[0], "-c", program], cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe
    )


class _ProgramSandbox:
    """A sandbox whose spawns run a fixed real program in the worker interpreter."""

    def __init__(self, program: str) -> None:
        self._inner = ProcessSandbox()
        self._program = program

    def available(self) -> bool:
        return True

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        return job

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        return _fake_worker_sandbox_popen(
            self._inner,
            self._program,
            cmd,
            cwd=cwd,
            env=env,
            scratch=scratch,
            stdin_pipe=stdin_pipe,
        )


_DEAD = "raise SystemExit(0)\n"  # exits before any protocol line: dead on arrival
_SILENT = "import time\ntime.sleep(60)\n"  # alive but never boots
_GARBLE_BOOT = "print('junk', flush=True)\nimport time\ntime.sleep(60)\n"
_BOOT_THEN_DIE = (  # boots, swallows one request, exits without acking it
    "import json, sys\n"
    "sys.stdout.write(json.dumps({'boot': True}) + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.readline()\n"
    "raise SystemExit(0)\n"
)
_BOOT_THEN_GARBLE_ACK = (  # boots, answers every request with a non-ack protocol line
    "import json, sys\n"
    "sys.stdout.write(json.dumps({'boot': True}) + '\\n')\n"
    "sys.stdout.flush()\n"
    "for _line in sys.stdin:\n"
    "    sys.stdout.write('123\\n')\n"
    "    sys.stdout.flush()\n"
)
_BOOT_THEN_SILENT = (  # boots, swallows the request, never acks, stays alive
    "import json, sys, time\n"
    "sys.stdout.write(json.dumps({'boot': True}) + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.readline()\n"
    "time.sleep(60)\n"
)


class _EOFStdinSandbox:
    """The docker-without--i failure reproduced on the host: the REAL worker runs, but its
    fd 0 is /dev/null while the runner holds a healthy-looking pipe — serve mode reads EOF
    instantly and exits cleanly after boot. Only stdin_pipe spawns are affected, exactly like
    T1 (introspect/invoke jobs never read stdin and kept working)."""

    def __init__(self) -> None:
        self._inner = ProcessSandbox()

    def available(self) -> bool:
        return True

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        return job

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        if not stdin_pipe:
            return self._inner.popen(cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=False)

        def child_setup() -> None:  # runs in the child between fork and exec
            fd = os.open(os.devnull, os.O_RDONLY)
            os.dup2(fd, 0)
            os.close(fd)

        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=child_setup,
        )


class _BootFailsOnceSandbox(_ProgramSandbox):
    """First spawn dies before boot; every later spawn is the real worker — the recovery
    path (respawn after an infrastructure failure, budget NOT exhausted) must still finish
    the batch honestly."""

    def __init__(self, marker: Path) -> None:
        super().__init__(_DEAD)
        self._marker = marker

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        if not self._marker.exists():
            self._marker.write_text("spent")
            return super().popen(cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe)
        return self._inner.popen(cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe)


class TestCompareRefusesSyntheticEvidence:
    def test_identical_synthetic_crashes_are_unprovable_never_equal(self) -> None:
        base = runner._synthetic_observation("worker died before booting (exit 0)")
        head = runner._synthetic_observation("worker died before booting (exit 0)")
        result = compare_obs(base, head, CFG)
        assert isinstance(result, Unprovable)
        assert result.kind is UnprovableKind.WORKER_UNAVAILABLE
        assert "base" in result.reason

    def test_synthetic_on_one_side_is_unprovable_and_names_the_side(self) -> None:
        real = runner._crashed_observation(-9)
        synth = runner._synthetic_observation("respawn budget exhausted")
        head_side = compare_obs(real, synth, CFG)
        assert isinstance(head_side, Unprovable)
        assert head_side.kind is UnprovableKind.WORKER_UNAVAILABLE
        assert "head" in head_side.reason

    def test_real_user_code_crashes_remain_comparable_evidence(self) -> None:
        # A target that kills its own process is an observation, not an infrastructure
        # failure: two identical REAL crashes still compare Equal (unchanged semantics).
        assert isinstance(
            compare_obs(runner._crashed_observation(-9), runner._crashed_observation(-9), CFG),
            Equal,
        )

    def test_tally_of_synthetic_inputs_maps_to_harness_synthesis_failed(self) -> None:
        tally = _UnprovableTally()
        tally.add(Unprovable(reason="worker never booted", kind=UnprovableKind.WORKER_UNAVAILABLE))
        code, detail = tally.unexercised_reason(3)
        assert code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert "worker never booted" in detail
        assert "nothing is being blessed" in detail


class TestRunBatchDeadOnArrival:
    def test_worker_dead_before_boot_yields_marked_synthetic_observations(
        self, tmp_path: Path
    ) -> None:
        obs = run_batch(
            _root(tmp_path), "m", "f", [("(1,)", "{}"), ("(2,)", "{}")], _ProgramSandbox(_DEAD)
        )
        assert all(isinstance(o, SyntheticObservation) for o in obs)
        assert all(o.outcome is InputOutcome.CRASHED and o.exit_status == -1 for o in obs)
        assert "died before booting" in obs[0].synthetic_reason  # type: ignore[attr-defined]
        # the regression: identical infra crashes on both "sides" must not compare Equal
        assert isinstance(compare_obs(obs[0], obs[1], CFG), Unprovable)

    def test_worker_hung_before_boot_is_synthetic_not_hung_evidence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        (obs,) = run_batch(_root(tmp_path), "m", "f", [("(1,)", "{}")], _ProgramSandbox(_SILENT))
        assert isinstance(obs, SyntheticObservation)
        assert "did not boot" in obs.synthetic_reason

    def test_garbled_pre_boot_stream_is_synthetic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        (obs,) = run_batch(
            _root(tmp_path), "m", "f", [("(1,)", "{}")], _ProgramSandbox(_GARBLE_BOOT)
        )
        assert isinstance(obs, SyntheticObservation)
        assert "protocol slip" in obs.synthetic_reason


class TestPersistentWorkerDeadOnArrival:
    def test_eof_stdin_worker_never_blesses_the_docker_stdin_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE finding-1 scenario: serve workers whose stdin is EOF die instantly on both
        revisions. Every input must come back marked synthetic and compare Unprovable —
        with the old unmarked _crashed_observation(0) both sides compared Equal."""
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        with PersistentWorker(_root(tmp_path), "m", "f", _EOFStdinSandbox()) as base_worker:
            base = base_worker.run([("(1,)", "{}"), ("(2,)", "{}")], per_input_timeout=1.0)
        with PersistentWorker(_root(tmp_path), "m", "f", _EOFStdinSandbox()) as head_worker:
            head = head_worker.run([("(1,)", "{}"), ("(2,)", "{}")], per_input_timeout=1.0)
        assert all(isinstance(o, SyntheticObservation) for o in base + head)
        for b, h in zip(base, head, strict=True):
            result = compare_obs(b, h, CFG)
            assert isinstance(result, Unprovable)
            assert result.kind is UnprovableKind.WORKER_UNAVAILABLE

    def test_dead_spawns_exhaust_the_budget_with_synthetic_fills(self, tmp_path: Path) -> None:
        with PersistentWorker(_root(tmp_path), "m", "f", _ProgramSandbox(_DEAD)) as worker:
            results = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            assert worker.spawns == 4  # 1 + _MAX_RESPAWNS_PER_RUN boot attempts
        assert all(isinstance(o, SyntheticObservation) for o in results)
        assert all(o.outcome is InputOutcome.CRASHED and o.exit_status == -1 for o in results)

    def test_boot_failure_once_recovers_without_attributing_anything(self, tmp_path: Path) -> None:
        sandbox = _BootFailsOnceSandbox(tmp_path / "first-spawn-died")
        with PersistentWorker(_root(tmp_path), "m", "f", sandbox) as worker:
            results = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            assert worker.spawns == 2  # the dead spawn cost a respawn, not an input
        assert [o.outcome for o in results] == [InputOutcome.COMPLETED] * 2
        assert [o.return_canon for o in results] == [2, 4]

    def test_boot_then_die_without_ack_is_never_attributed_to_an_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        with PersistentWorker(_root(tmp_path), "m", "f", _ProgramSandbox(_BOOT_THEN_DIE)) as worker:
            results = worker.run([("(1,)", "{}")], per_input_timeout=1.0)
        assert all(isinstance(o, SyntheticObservation) for o in results)
        assert "acknowledg" in results[0].synthetic_reason  # type: ignore[attr-defined]

    def test_garbled_ack_is_never_attributed_to_an_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        with PersistentWorker(
            _root(tmp_path), "m", "f", _ProgramSandbox(_BOOT_THEN_GARBLE_ACK)
        ) as worker:
            results = worker.run([("(1,)", "{}")], per_input_timeout=1.0)
        assert all(isinstance(o, SyntheticObservation) for o in results)

    def test_silent_ack_timeout_is_never_attributed_to_an_input(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        with PersistentWorker(
            _root(tmp_path), "m", "f", _ProgramSandbox(_BOOT_THEN_SILENT)
        ) as worker:
            results = worker.run([("(1,)", "{}")], per_input_timeout=0.5)
        assert all(isinstance(o, SyntheticObservation) for o in results)
        assert "acknowledg" in results[0].synthetic_reason  # type: ignore[attr-defined]


class TestVerdictsNeverBlessInfrastructure:
    def test_prove_target_on_eof_stdin_workers_is_unproven_not_equivalent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end pin for the catastrophe: pure-path prove over dead-on-arrival serve
        workers must be UNPROVEN with zero equivalent inputs — never EQUIVALENT_UNDER_BUDGET."""
        monkeypatch.setattr(runner, "_STARTUP_GRACE_S", 0.5)
        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir()
        head.mkdir()
        (base / "m.py").write_text(_ECHO)
        (head / "m.py").write_text("def f(x: int) -> int:\n    return x * 2 + 1\n")
        sandbox = _EOFStdinSandbox()
        with (
            PersistentWorker(base, "m", "f", sandbox) as base_worker,
            PersistentWorker(head, "m", "f", sandbox) as head_worker,
        ):
            outcome = prove_target(
                base,
                head,
                "m",
                "f",
                changed_lines=frozenset({2}),
                sandbox=sandbox,
                budget=Budget(max_inputs=4),
                worker_pair=(base_worker, head_worker),
            )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert outcome.equivalent_inputs == 0
        assert outcome.unprovable_inputs == outcome.inputs_run > 0

    def test_prove_impure_target_on_dead_determinism_workers_is_unproven(
        self, tmp_path: Path
    ) -> None:
        class _DeadForDeterminism(_ProgramSandbox):
            """Introspection/probing work; every determinism (record/replay) batch spawns a
            dead-on-arrival worker — the impure flow must degrade to UNPROVEN, not bless."""

            def __init__(self) -> None:
                super().__init__(_DEAD)
                self._next_is_determinism = False

            def translate_job(
                self, job: dict[str, object], *, workdir: Path, scratch: Path
            ) -> dict[str, object]:
                self._next_is_determinism = job.get("determinism") is not None
                return job

            def popen(
                self,
                cmd: list[str],
                *,
                cwd: Path,
                env: dict[str, str],
                scratch: Path,
                stdin_pipe: bool = False,
            ) -> subprocess.Popen[bytes]:
                if self._next_is_determinism:
                    return super().popen(
                        cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe
                    )
                return self._inner.popen(
                    cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe
                )

        base = tmp_path / "base"
        head = tmp_path / "head"
        base.mkdir()
        head.mkdir()
        src = "import time\n\n\ndef f(x: int) -> float:\n    return time.time() + x\n"
        (base / "m.py").write_text(src)
        (head / "m.py").write_text(src)
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset({5}),
            sandbox=_DeadForDeterminism(),
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert outcome.equivalent_inputs == 0


def test_worker_first_protocol_line_is_the_boot_announcement(tmp_path: Path) -> None:
    """The boot line is the contract the dead-on-arrival detection stands on — pin it at the
    raw subprocess level (the same channel the runner consumes)."""
    root = _root(tmp_path)
    import json
    import shutil
    import tempfile

    import tempest.compare.canonical as canonical_module
    import tempest.execute._worker as worker_module

    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir)
        shutil.copyfile(str(worker_module.__file__), scratch / "worker.py")
        shutil.copyfile(str(canonical_module.__file__), scratch / "canonical.py")
        job = {
            "mode": "invoke",
            "module": "m",
            "qualname": "f",
            "target_file": str(root / "m.py"),
            "sys_path": [str(root)],
            "scratch": str(scratch),
            "inputs": [{"index": 0, "args": "(3,)", "kwargs": "{}"}],
        }
        (scratch / "job.json").write_text(json.dumps(job))
        proc = subprocess.run(
            [sys.executable, "-s", "-B", str(scratch / "worker.py"), str(scratch / "job.json")],
            capture_output=True,
            timeout=60,
            check=False,
        )
    lines = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines[0] == {"boot": True}
    assert lines[1]["index"] == 0
