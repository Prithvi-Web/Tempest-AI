"""No orphaned workers on unwind (review finding 3, L11).

Workers are session leaders (`start_new_session=True`), so an exception unwinding through
`run_batch`/`PersistentWorker.run` used to leak a live worker that survived the CLI process —
and Ctrl-C on `tempest prove` had no CancelScope at all, so every in-flight worker kept
running after the CLI died. Pinned here with REAL processes: targets record their worker pid
on disk, a real KeyboardInterrupt/SIGINT lands mid-input, and the pids must be gone.
"""

import _thread
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tempest.cli.main import app
from tempest.execute.runner import PersistentWorker, run_batch
from tempest.execute.sandbox import ProcessSandbox

from .test_targets_diff import commit_head, make_repo

REPO_ROOT = Path(__file__).resolve().parents[4]
SANDBOX = ProcessSandbox()
_MARKER = "tempest-first-party-fixture-v1"


def _pid_recording_module(pids_dir: Path, *, sleep_s: float, tail: str = "    return x\n") -> str:
    return (
        "import os\nimport time\n\n\n"
        "def f(x: int) -> int:\n"
        f"    open(os.path.join({str(pids_dir)!r}, str(os.getpid())), 'w').close()\n"
        f"    time.sleep({sleep_s})\n" + tail
    )


def _wait_for_a_pid(pids_dir: Path, *, alive_check: subprocess.Popen[bytes] | None = None) -> None:
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if any(pids_dir.iterdir()):
            return
        if alive_check is not None and alive_check.poll() is not None:
            raise AssertionError("the prove finished before any worker started")
        time.sleep(0.05)
    raise AssertionError("no worker ever started")


def _assert_pids_die(pids_dir: Path, *, within_s: float, since: float) -> None:
    deadline = since + within_s
    for entry in pids_dir.iterdir():
        pid = int(entry.name)
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            assert time.monotonic() < deadline, f"worker {pid} outlived its prove (orphan)"
            time.sleep(0.05)


def _interrupt_main_once_a_worker_runs(pids_dir: Path) -> threading.Thread:
    def watch() -> None:
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if any(pids_dir.iterdir()):
                time.sleep(0.2)  # let the worker settle into its sleep
                _thread.interrupt_main()
                return
            time.sleep(0.05)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


class TestUnwindKillsWorkers:
    def test_run_batch_unwind_reaps_the_live_worker(self, tmp_path: Path) -> None:
        pids_dir = tmp_path / "pids"
        pids_dir.mkdir()
        (tmp_path / "m.py").write_text(_pid_recording_module(pids_dir, sleep_s=300))
        _interrupt_main_once_a_worker_runs(pids_dir)
        with pytest.raises(KeyboardInterrupt):
            run_batch(tmp_path, "m", "f", [("(1,)", "{}")], SANDBOX, per_input_timeout=60.0)
        _assert_pids_die(pids_dir, within_s=5.0, since=time.monotonic())

    def test_persistent_worker_unwind_retires_the_live_worker(self, tmp_path: Path) -> None:
        pids_dir = tmp_path / "pids"
        pids_dir.mkdir()
        (tmp_path / "m.py").write_text(_pid_recording_module(pids_dir, sleep_s=300))
        worker = PersistentWorker(tmp_path, "m", "f", SANDBOX)
        try:
            _interrupt_main_once_a_worker_runs(pids_dir)
            with pytest.raises(KeyboardInterrupt):
                worker.run([("(1,)", "{}")], per_input_timeout=60.0)
            assert worker._proc is None  # retired on the unwind path, not leaked
            _assert_pids_die(pids_dir, within_s=5.0, since=time.monotonic())
        finally:
            worker.close()


class TestCliSigint:
    def test_sigint_kills_every_worker_within_two_seconds_and_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        """Real `tempest prove` subprocess on a slow fixture repo, real SIGINT mid-input:
        the CLI must exit nonzero saying so, and every sandbox worker that ever started
        (session leaders — a dead CLI does NOT take them down by itself) must be gone
        within 2 seconds of the CLI exiting."""
        pids_dir = tmp_path / "pids"
        pids_dir.mkdir()
        slow = _pid_recording_module(pids_dir, sleep_s=8)
        repo = make_repo(tmp_path, {"m.py": slow})
        (repo / ".tempest-first-party").write_text(_MARKER + "\n")
        commit_head(
            repo, {"m.py": _pid_recording_module(pids_dir, sleep_s=8, tail="    return x + 1\n")}
        )
        env = os.environ.copy()
        env["TEMPEST_DEV"] = "1"
        env["TEMPEST_NO_POWER_PAUSE"] = "1"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from tempest.cli.main import app\napp()",
                "prove",
                "--base",
                "base",
                "--head",
                "head",
                "--repo",
                str(repo),
                "--max-inputs",
                "2",
            ],
            cwd=REPO_ROOT,  # child coverage data lands where the session combines it
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_a_pid(pids_dir, alive_check=proc)
            time.sleep(0.3)  # the worker is now inside its 8 s input
            proc.send_signal(signal.SIGINT)
            out, _ = proc.communicate(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        exited_at = time.monotonic()
        assert proc.returncode != 0, out.decode(errors="replace")
        assert b"cancelled" in out.lower(), out.decode(errors="replace")
        _assert_pids_die(pids_dir, within_s=2.0, since=exited_at)

    def test_prove_off_the_main_thread_runs_without_a_signal_handler(self, tmp_path: Path) -> None:
        """Signal handlers only exist on the main thread; an embedded (threaded) prove must
        still work — the CancelScope is wired, the Ctrl-C hook simply is not."""
        repo = make_repo(tmp_path, {"m.py": "def f(x: int) -> int:\n    return x * 2\n"})
        (repo / ".tempest-first-party").write_text(_MARKER + "\n")
        commit_head(repo, {"m.py": "def f(x: int) -> int:\n    return x * 2 + 1\n"})
        os.environ["TEMPEST_DEV"] = "1"
        results: dict[str, object] = {}

        def invoke() -> None:
            results["result"] = CliRunner().invoke(
                app,
                [
                    "prove",
                    "--base",
                    "base",
                    "--head",
                    "head",
                    "--repo",
                    str(repo),
                    "--max-inputs",
                    "2",
                ],
            )

        thread = threading.Thread(target=invoke)
        thread.start()
        thread.join(timeout=300)
        assert not thread.is_alive(), "threaded prove wedged"
        result = results["result"]
        assert getattr(result, "exit_code", None) == 1, getattr(result, "output", "")
        assert "DIVERGENT" in getattr(result, "output", "")
