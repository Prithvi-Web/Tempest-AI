"""Runner recovery paths that only hostile realities reach — all driven by REAL subprocesses
(Law L4): a worker whose stdin fd genuinely cannot be written, a target that injects protocol
lines straight onto fd 1 (the slip the drain defense exists for), imports that hang or fail,
and crash storms that exhaust the respawn budget.
"""

import contextlib
import os
import subprocess
from pathlib import Path

from tempest.execute.runner import PersistentWorker, introspect_target, run_batch
from tempest.execute.sandbox import ProcessSandbox
from tempest.model import InputOutcome

SANDBOX = ProcessSandbox()


class _ReadOnlyStdinSandbox:
    """A real ProcessSandbox whose worker stdin fd is remapped to a read-only /dev/null right
    after spawn: every later write is a REAL OSError (EBADF) from the OS, deterministically —
    the exact failure the persistent worker's respawn budget defends against. The worker
    process itself is spawned and killed for real."""

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
    ) -> "subprocess.Popen[bytes]":
        proc = self._inner.popen(cmd, cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe)
        if stdin_pipe and proc.stdin is not None:
            read_only = os.open(os.devnull, os.O_RDONLY)
            os.dup2(read_only, proc.stdin.fileno())
            os.close(read_only)
        return proc


def _write_module(tmp_path: Path, src: str) -> Path:
    (tmp_path / "m.py").write_text(src)
    return tmp_path


class TestIntrospection:
    def test_hung_import_times_out_to_none(self, tmp_path: Path) -> None:
        root = _write_module(
            tmp_path, "import time\ntime.sleep(60)\n\n\ndef f(x: int) -> int:\n    return x\n"
        )
        assert introspect_target(root, "m", "f", SANDBOX, timeout=2.0) is None


class TestRunBatchFatal:
    def test_missing_module_reports_fatal_and_dead_worker_honestly(self, tmp_path: Path) -> None:
        first, second = run_batch(
            tmp_path, "definitely_absent_mod", "f", [("(1,)", "{}"), ("(2,)", "{}")], SANDBOX
        )
        # The import fatal covers input 0; the worker's clean exit marks input 1 CRASHED.
        assert first.outcome is InputOutcome.CRASHED
        assert first.exit_status == 1
        assert "ModuleNotFoundError" in first.stderr
        assert second.outcome is InputOutcome.CRASHED

    def test_src_layout_package_resolves_and_runs(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("def f(x: int) -> int:\n    return x * 2\n")
        (result,) = run_batch(tmp_path, "pkg", "f", [("(3,)", "{}")], SANDBOX)
        assert result.outcome is InputOutcome.COMPLETED
        assert result.return_canon == 6


class TestPersistentWorkerFatal:
    def test_bad_literal_is_fatal_for_that_input_only(self, tmp_path: Path) -> None:
        root = _write_module(tmp_path, "def f(x: int) -> int:\n    return x * 2\n")
        with PersistentWorker(root, "m", "f", SANDBOX) as worker:
            bad, good = worker.run([("(unclosed", "{}"), ("(2,)", "{}")])
            assert bad.outcome is InputOutcome.CRASHED
            assert bad.exit_status == 1
            assert good.outcome is InputOutcome.COMPLETED
            assert good.return_canon == 4
            assert worker.spawns == 1  # a fatal input never costs a respawn

    def test_import_fatal_ends_the_batch_early_for_every_remaining_input(
        self, tmp_path: Path
    ) -> None:
        root = _write_module(tmp_path, "raise RuntimeError('broken at import')\n")
        with PersistentWorker(root, "m", "f", SANDBOX) as worker:
            first, second = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            assert first.outcome is InputOutcome.CRASHED
            assert "broken at import" in first.stderr
            assert second.outcome is InputOutcome.CRASHED
            assert second.stderr == "worker ended batch early"


class TestRespawnBudget:
    def test_crash_storm_exhausts_the_respawn_budget(self, tmp_path: Path) -> None:
        root = _write_module(
            tmp_path, "import os\n\n\ndef f(x: int) -> int:\n    os.kill(os.getpid(), 9)\n"
        )
        inputs = [(f"({i},)", "{}") for i in range(5)]
        with PersistentWorker(root, "m", "f", SANDBOX) as worker:
            results = worker.run(inputs)
            assert [r.outcome for r in results] == [InputOutcome.CRASHED] * 5
            assert worker.spawns == 4  # 1 + _MAX_RESPAWNS_PER_RUN, then the budget is spent
            assert results[4].exit_status == -1  # never even reached a worker

    def test_unwritable_stdin_exhausts_the_respawn_budget(self, tmp_path: Path) -> None:
        root = _write_module(tmp_path, "def f(x: int) -> int:\n    return x\n")
        with PersistentWorker(root, "m", "f", _ReadOnlyStdinSandbox()) as worker:
            results = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            assert [r.outcome for r in results] == [InputOutcome.CRASHED] * 2
            assert all(r.exit_status == -1 for r in results)
            assert worker.spawns == 4  # every spawn's stdin failed; the budget capped it


_FAKE_RESULT = {
    "index": 0,
    "return_present": True,
    "return_canon": 123,
    "raised": None,
    "stdout": "",
    "stderr": "",
    "wall_ns": 1,
    "cpu_ns": 1,
}

_SLIP_PREFIX = (
    "import json\nimport os\n\nFAKE = json.dumps(" + repr(_FAKE_RESULT) + ")\n\n\n"
    "def f(x: int) -> int:\n"
    "    os.write(1, (FAKE + '\\n').encode())\n"  # injected straight past the redirects
)


class TestProtocolSlip:
    """UPDATED for review finding 4: fd-level isolation means `os.write(1, ...)` can no
    longer reach the protocol stream at all — the two scenarios this class used to pin
    (a forged result line winning, the sentinel drain meeting it) are now impossible by
    design. What these targets produce today is honest evidence: the injected bytes land in
    the input's observed stdout and the REAL result wins. The drain/garble defenses are
    re-pinned through a real stdout filter in test_fix_exec_fd1_protocol.py."""

    def test_injected_result_line_is_stdout_evidence_and_the_real_result_wins(
        self, tmp_path: Path
    ) -> None:
        root = _write_module(tmp_path, _SLIP_PREFIX + "    return x * 2\n")
        with PersistentWorker(root, "m", "f", SANDBOX) as worker:
            (result,) = worker.run([("(7,)", "{}")])
            assert result.return_canon == 14  # the REAL result; the forged 123 never lands
            assert "123" in result.stdout  # ... it is observed output instead
            assert worker._proc is not None  # the stream stayed clean: no retire

    def test_injection_before_a_hang_stays_an_honest_hang(self, tmp_path: Path) -> None:
        root = _write_module(
            tmp_path, _SLIP_PREFIX + "    import time\n    time.sleep(60)\n    return x\n"
        )
        with PersistentWorker(root, "m", "f", SANDBOX) as worker:
            (result,) = worker.run([("(7,)", "{}")], per_input_timeout=3.0)
            # Pre-fix the forged line "answered" the input; now the input honestly HUNG.
            assert result.outcome is InputOutcome.HUNG
            assert worker._proc is None  # hang recovery retires the worker as always

    def test_drain_before_any_spawn_is_a_noop(self, tmp_path: Path) -> None:
        root = _write_module(tmp_path, "def f(x: int) -> int:\n    return x\n")
        worker = PersistentWorker(root, "m", "f", SANDBOX)
        with contextlib.closing(worker):
            worker._drain_sentinel(0.1)  # no stream yet: nothing to drain, nothing to retire
            assert worker._proc is None
