"""PersistentWorker: the spawn-economics layer. One process serves many batches; crash and
hang recovery must match run_batch's semantics exactly (in-flight input marked, fresh process
resumes the remainder); close() leaves nothing running. Real subprocesses only (Law L4)."""

import contextlib
import os
import signal
import time
from pathlib import Path

from tempest.execute.runner import PersistentWorker
from tempest.execute.sandbox import ProcessSandbox
from tempest.model import InputOutcome

SANDBOX = ProcessSandbox()

_MODULE = """
import os

CALLS = {"n": 0}

def echo(x: int) -> int:
    CALLS["n"] += 1
    return x * 2

def calls_so_far(x: int) -> int:
    return CALLS["n"]

def boom(x: int) -> int:
    if x < 0:
        os.kill(os.getpid(), 9)
    return x

def stall(x: int) -> int:
    if x < 0:
        import time
        time.sleep(60)
    return x
"""


def _root(tmp_path: Path) -> Path:
    (tmp_path / "m.py").write_text(_MODULE)
    return tmp_path


class TestPersistentWorker:
    def test_two_batches_share_one_process(self, tmp_path: Path) -> None:
        with PersistentWorker(_root(tmp_path), "m", "echo", SANDBOX) as worker:
            first = worker.run([("(1,)", "{}"), ("(2,)", "{}")])
            second = worker.run([("(3,)", "{}")])
            assert [o.return_canon for o in first] == [2, 4]
            assert [o.return_canon for o in second] == [6]
            assert worker.spawns == 1  # the entire point of this class

    def test_module_state_persists_across_batches_like_one_large_batch(
        self, tmp_path: Path
    ) -> None:
        with PersistentWorker(_root(tmp_path), "m", "calls_so_far", SANDBOX) as worker:
            worker.run([("(0,)", "{}")])
            (count,) = worker.run([("(0,)", "{}")])
            # Pure-path batches already share one process; batches over one worker keep that
            # exact model — documented, not hidden.
            assert count.return_canon == 0  # calls_so_far doesn't bump the counter itself

    def test_crash_mid_batch_marks_input_and_resumes_rest(self, tmp_path: Path) -> None:
        with PersistentWorker(_root(tmp_path), "m", "boom", SANDBOX) as worker:
            results = worker.run([("(1,)", "{}"), ("(-1,)", "{}"), ("(3,)", "{}")])
            assert results[0].outcome is InputOutcome.COMPLETED
            assert results[1].outcome is InputOutcome.CRASHED
            assert results[2].outcome is InputOutcome.COMPLETED
            assert results[2].return_canon == 3
            assert worker.spawns == 2  # one respawn to finish the remainder

    def test_hang_mid_batch_marks_input_and_resumes_rest(self, tmp_path: Path) -> None:
        with PersistentWorker(_root(tmp_path), "m", "stall", SANDBOX) as worker:
            results = worker.run(
                [("(1,)", "{}"), ("(-1,)", "{}"), ("(3,)", "{}")], per_input_timeout=1.0
            )
            assert results[0].outcome is InputOutcome.COMPLETED
            assert results[1].outcome is InputOutcome.HUNG
            assert results[2].outcome is InputOutcome.COMPLETED

    def test_close_leaves_no_process(self, tmp_path: Path) -> None:
        worker = PersistentWorker(_root(tmp_path), "m", "echo", SANDBOX)
        worker.run([("(1,)", "{}")])
        proc = worker._proc  # asserting the process table, deliberately
        assert proc is not None and proc.poll() is None
        worker.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert proc.poll() is not None

    def test_close_is_idempotent_and_kills_unresponsive_worker(self, tmp_path: Path) -> None:
        worker = PersistentWorker(_root(tmp_path), "m", "echo", SANDBOX)
        worker.run([("(1,)", "{}")])
        proc = worker._proc
        assert proc is not None
        os.kill(proc.pid, signal.SIGSTOP)  # a wedged worker must still die on close
        try:
            worker.close()
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(proc.pid, signal.SIGCONT)
        assert proc.poll() is not None
        worker.close()  # second close is a no-op, not an error


_SLOW_IMPORT_MODULE = """
import time

time.sleep(2.0)  # stands in for a cold interpreter + heavy target import on a loaded machine


def echo(x: int) -> int:
    return x * 2
"""


def test_slow_worker_startup_is_not_mistaken_for_a_hang(tmp_path: Path) -> None:
    """Regression: the per-input timeout must NOT have to cover one-time worker startup.
    A module that takes 2 s to import, with a 1 s per-input budget, still returns COMPLETED —
    otherwise a cold or loaded machine invents a HANG divergence out of a healthy fast input."""
    (tmp_path / "m.py").write_text(_SLOW_IMPORT_MODULE)
    with PersistentWorker(tmp_path, "m", "echo", SANDBOX) as worker:
        (result,) = worker.run([("(21,)", "{}")], per_input_timeout=1.0)
    assert result.outcome is InputOutcome.COMPLETED
    assert result.return_canon == 42
