"""Fd-level protocol isolation (review finding 4).

`redirect_stdout` is Python-level only: user code writing to REAL fd 1 — `os.write(1, ...)`,
a spawned subprocess inheriting stdout, an import-time print — used to interleave with the
worker's JSONL protocol and could forge results or ERROR the whole prove. The worker now dups
the protocol fd at startup and repoints fd 1 at a capture file whose bytes are folded into the
input's observed stdout (evidence, not corruption).

The runner side is hardened symmetrically: a garbled protocol line poisons only the input it
was read for, and every sentinel-drain slip retires the worker. With user code locked out of
the protocol fd, the one honest way left to garble the stream is a REAL filter subprocess
spliced into the worker's stdout — `FilterSandbox` below does exactly that (Law L4)."""

import json
import shlex
import subprocess
from pathlib import Path

from tempest.execute.runner import PersistentWorker, introspect_target, run_batch
from tempest.execute.sandbox import ProcessSandbox
from tempest.model import InputOutcome

from .test_fix_exec_synthetic_unprovable import _ProgramSandbox
from .test_worker_direct import invoke_job, make_scratch, run_worker, write_module

# A REAL subprocess speaking the serve protocol up to (and not including) the sentinel:
# boot → batch_ack → one result → exit. The runner's stdout genuinely EOFs where batch_end
# belongs — the one stream shape a filter pipeline cannot produce (sh holds the pipe open).
_SERVE_THEN_DIE_BEFORE_SENTINEL = (
    "import json\n"
    "import sys\n"
    "\n"
    "sys.stdout.write(json.dumps({'boot': True}) + '\\n')\n"
    "sys.stdout.flush()\n"
    "request = json.loads(sys.stdin.readline())\n"
    "sys.stdout.write(json.dumps({'batch_ack': True}) + '\\n')\n"
    "index = request['inputs'][0]['index']\n"
    "result = {'index': index, 'return_present': True, 'return_canon': 7, 'raised': None,\n"
    "          'stdout': '', 'stderr': '', 'wall_ns': 1, 'cpu_ns': 1}\n"
    "sys.stdout.write(json.dumps(result) + '\\n')\n"
    "sys.stdout.flush()\n"
)

SANDBOX = ProcessSandbox()

_FAKE_RESULT_LINE = json.dumps(
    {
        "index": 0,
        "return_present": True,
        "return_canon": 123,
        "raised": None,
        "stdout": "",
        "stderr": "",
        "wall_ns": 1,
        "cpu_ns": 1,
    }
)


class TestWorkerFdIsolation:
    """The worker subprocess itself, via the real `python -m tempest.execute._worker` run."""

    def test_os_write_to_fd1_is_captured_stdout_not_protocol(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path,
            "wfd1",
            "import os\n\n\ndef f(x: int) -> int:\n"
            "    os.write(1, b'fd-garbage\\n')\n"
            "    return x * 2\n",
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wfd1", [("(3,)", "{}")]))
        assert payload["outcome"] == "COMPLETED"
        assert payload["return_canon"] == 6
        assert "fd-garbage" in payload["stdout"]

    def test_spawned_subprocess_stdout_is_captured_not_protocol(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path,
            "wfd2",
            "import subprocess\n\n\ndef f(x: int) -> int:\n"
            "    subprocess.run(['/bin/echo', 'hi'], check=True)\n"
            "    return x + 1\n",
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wfd2", [("(4,)", "{}")]))
        assert payload["return_canon"] == 5
        assert "hi" in payload["stdout"]

    def test_import_time_print_does_not_corrupt_the_protocol(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path,
            "wfd3",
            "print('import noise')\n\n\ndef f(x: int) -> int:\n    return x\n",
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wfd3", [("(9,)", "{}")]))
        assert payload["return_canon"] == 9
        assert "import noise" in payload["stdout"]

    def test_forged_protocol_line_is_neutralized_into_stdout_evidence(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path,
            "wfd4",
            "import os\n"
            f"FAKE = {_FAKE_RESULT_LINE!r}\n"
            "\n\ndef f(x: int) -> int:\n"
            "    os.write(1, (FAKE + '\\n').encode())\n"
            "    return x * 2\n",
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wfd4", [("(7,)", "{}")]))
        assert payload["return_canon"] == 14  # the REAL result, never the forged 123
        assert "123" in payload["stdout"]  # the forgery is observed as plain output


class TestRunnerAgainstHostileFd1:
    def test_run_batch_survives_fd1_injection_with_honest_outcomes(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text(
            "import os\n\n\ndef f(x: int) -> int:\n"
            "    os.write(1, b'not a protocol line\\n')\n"
            "    return x * 10\n"
        )
        first, second = run_batch(tmp_path, "m", "f", [("(1,)", "{}"), ("(2,)", "{}")], SANDBOX)
        assert first.outcome is InputOutcome.COMPLETED and first.return_canon == 10
        assert second.outcome is InputOutcome.COMPLETED and second.return_canon == 20
        assert "not a protocol line" in first.stdout

    def test_persistent_worker_is_not_poisoned_by_forged_result_lines(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text(
            "import os\n"
            f"FAKE = {_FAKE_RESULT_LINE!r}\n"
            "\n\ndef f(x: int) -> int:\n"
            "    os.write(1, (FAKE + '\\n').encode())\n"
            "    return x * 2\n"
        )
        with PersistentWorker(tmp_path, "m", "f", SANDBOX) as worker:
            (result,) = worker.run([("(7,)", "{}")])
            assert result.return_canon == 14  # never the forged 123
            assert "123" in result.stdout
            assert worker._proc is not None  # the stream stayed trustworthy: no retire
            (again,) = worker.run([("(8,)", "{}")])
            assert again.return_canon == 16
            assert worker.spawns == 1


# ── A REAL filter subprocess spliced into the worker's stdout ──────────────────────────────
# With user code locked out of the protocol fd, a garbled stream can only come from harness
# -level corruption. The filter reproduces that corruption honestly: the worker runs
# unmodified, its protocol lines genuinely flow through (and are tampered with by) another
# real process.

_INJECT_ONCE = """\
import os
import sys

count = 0
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    count += 1
    if count == {after} and not os.path.exists({flag!r}):
        open({flag!r}, "w").close()
        sys.stdout.write({text!r} + "\\n")
        sys.stdout.flush()
"""

_PREPEND_GARBAGE = """\
import sys

sys.stdout.write("this is not json\\n")
sys.stdout.write("123\\n")
sys.stdout.flush()
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
"""

_WITHHOLD_AFTER = """\
import sys
import time

count = 0
for line in sys.stdin:
    count += 1
    if count > {after}:
        time.sleep(60)  # withhold everything from here on, stay alive
    sys.stdout.write(line)
    sys.stdout.flush()
"""

_EXIT_AFTER = """\
import sys

count = 0
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    count += 1
    if count == {after}:
        sys.exit(0)
"""


class FilterSandbox:
    """ProcessSandbox whose worker stdout flows through a REAL filter subprocess (sh pipeline,
    same session/pgroup so kill paths still sweep everything)."""

    def __init__(self, filter_body: str) -> None:
        self._inner = ProcessSandbox()
        self._filter_body = filter_body

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
        script = scratch / "protocol_filter.py"
        script.write_text(self._filter_body)
        pipeline = (
            " ".join(shlex.quote(part) for part in cmd)
            + " | "
            + shlex.quote(cmd[0])
            + " "
            + shlex.quote(str(script))
        )
        return self._inner.popen(
            ["/bin/sh", "-c", pipeline], cwd=cwd, env=env, scratch=scratch, stdin_pipe=stdin_pipe
        )


class TestGarbledProtocolRecovery:
    def test_run_batch_garbled_line_poisons_one_input_and_recovers_the_rest(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x * 2\n")
        # invoke stream: line 1 = boot, then results — garble the first result slot, once.
        sandbox = FilterSandbox(
            _INJECT_ONCE.format(after=1, flag=str(tmp_path / "spent"), text="**garble**")
        )
        first, second = run_batch(tmp_path, "m", "f", [("(1,)", "{}"), ("(2,)", "{}")], sandbox)
        assert first.outcome is InputOutcome.CRASHED
        assert "garbled worker protocol line" in first.stderr
        assert second.outcome is InputOutcome.COMPLETED  # a fresh worker finished the rest
        assert second.return_canon == 4

    def test_persistent_worker_garbled_result_poisons_one_input_and_recovers(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x * 2\n")
        # serve stream: 1 = boot, 2 = batch_ack, then results — garble the first result, once.
        sandbox = FilterSandbox(
            _INJECT_ONCE.format(after=2, flag=str(tmp_path / "spent"), text="**garble**")
        )
        with PersistentWorker(tmp_path, "m", "f", sandbox) as worker:
            first, second = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            assert worker.spawns == 2  # the poisoned stream cost a respawn, not the batch
        assert first.outcome is InputOutcome.CRASHED
        assert "garbled worker protocol line" in first.stderr
        assert second.outcome is InputOutcome.COMPLETED
        assert second.return_canon == 4

    def test_garbled_sentinel_retires_the_worker_but_keeps_the_result(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
        # 1 = boot, 2 = ack, 3 = the only result — garble where batch_end belongs.
        sandbox = FilterSandbox(
            _INJECT_ONCE.format(after=3, flag=str(tmp_path / "spent"), text="not batch_end")
        )
        with PersistentWorker(tmp_path, "m", "f", sandbox) as worker:
            (result,) = worker.run([("(1,)", "{}")], per_input_timeout=2.0)
            assert result.return_canon == 2
            assert worker._proc is None  # a stream we cannot trust is never reused

    def test_withheld_sentinel_times_out_and_retires_the_worker(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
        sandbox = FilterSandbox(_WITHHOLD_AFTER.format(after=3))
        with PersistentWorker(tmp_path, "m", "f", sandbox) as worker:
            (result,) = worker.run([("(1,)", "{}")], per_input_timeout=2.0)
            assert result.return_canon == 2
            assert worker._proc is None  # sentinel never arrived inside the budget

    def test_filter_death_swallowing_the_sentinel_retires_the_worker(self, tmp_path: Path) -> None:
        # The filter exits after the result line, but the sh pipeline (and the live worker)
        # keep the runner's pipe write-end open — so the sentinel simply never arrives and
        # the drain times out. True stream-EOF at the drain is pinned separately below.
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
        sandbox = FilterSandbox(_EXIT_AFTER.format(after=3))
        with PersistentWorker(tmp_path, "m", "f", sandbox) as worker:
            (result,) = worker.run([("(1,)", "{}")], per_input_timeout=2.0)
            assert result.return_canon == 2
            assert worker._proc is None  # the stream died under us: retire, never reuse

    def test_stream_eof_at_the_sentinel_retires_the_worker(self, tmp_path: Path) -> None:
        # A scripted serve-protocol worker (real subprocess) that speaks boot → ack → result
        # and then EXITS: the runner's stdout truly EOFs exactly where batch_end belongs.
        (tmp_path / "m.py").write_text("def f(x: int) -> int:\n    return x\n")
        with PersistentWorker(
            tmp_path, "m", "f", _ProgramSandbox(_SERVE_THEN_DIE_BEFORE_SENTINEL)
        ) as worker:
            (result,) = worker.run([("(1,)", "{}")], per_input_timeout=5.0)
            assert result.return_canon == 7
            assert worker._proc is None  # EOF at the drain: retired, never reused

    def test_introspection_skips_garbled_lines_instead_of_crashing(self, tmp_path: Path) -> None:
        (tmp_path / "m.py").write_text("def f(a: int, b: str = 'x') -> str:\n    return b * a\n")
        info = introspect_target(tmp_path, "m", "f", FilterSandbox(_PREPEND_GARBAGE))
        assert info is not None
        assert [p.name for p in info.params] == ["a", "b"]
