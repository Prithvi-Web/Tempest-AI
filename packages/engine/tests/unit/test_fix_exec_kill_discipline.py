"""Kill discipline (review finding 2): `os.killpg` after a process has been REAPED targets a
pgid the kernel may already have recycled for an unrelated process — the kill must be guarded
by `proc.returncode`, which is only ever set by the reaping `wait()`/`poll()` on our own child.

The processes here are real children (Law L4). The one seam is a *delegating* spy wrapped
around `os.killpg`: every recorded call still reaches the real syscall, because "no killpg was
issued" is unobservable from process state once a pid could have been recycled — the spy
records the negative space, it never fakes an execution result.
"""

import platform
import signal
import subprocess
import time
from types import SimpleNamespace

import pytest

from tempest.execute import cancel as cancel_module
from tempest.execute import runner
from tempest.execute.cancel import CancelScope, cancel_scope


def _sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sleep", "60"], start_new_session=True)


def _reaped() -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(["sleep", "0"], start_new_session=True)
    proc.wait()  # fully reaped: from here the pid/pgid may be recycled by the OS
    return proc


# On Linux the kernel keeps a dead-but-unreaped leader's pgid signalable (killpg succeeds
# on a zombie group), so the exited-unreaped fallback scenario cannot be staged there — it is
# macOS-reachable only (EPERM). The fallback arms carry matching darwin-only pragmas.
_ZOMBIE_GROUPS_UNSTAGEABLE = platform.system() != "Darwin"


def _zombie() -> subprocess.Popen[bytes]:
    """A child that has EXITED but is NOT reaped: returncode is None (killpg is still legal
    per the guard) yet its process group can no longer be signalled — killpg raises ESRCH on
    Linux and EPERM on macOS, driving the direct-kill fallback for real."""
    import os

    proc = subprocess.Popen(["sleep", "0"], start_new_session=True)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)  # probe without reaping (poll() would set returncode)
        except (ProcessLookupError, PermissionError):
            return proc
        time.sleep(0.02)
    raise AssertionError("child never became a zombie")


class _KillpgSpy:
    """Records (pgid, sig) and DELEGATES to the real os.killpg — a recorder, not a fake."""

    def __init__(self) -> None:
        import os

        self.calls: list[tuple[int, int]] = []
        self._real = os.killpg

    def __call__(self, pgid: int, sig: int) -> None:
        self.calls.append((pgid, sig))
        self._real(pgid, sig)


class TestRunnerKill:
    def test_kill_on_a_reaped_process_never_issues_killpg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proc = _reaped()
        spy = _KillpgSpy()
        monkeypatch.setattr(runner, "os", SimpleNamespace(killpg=spy))
        runner._kill(proc)  # must be a no-op signal-wise: the pgid may belong to a stranger
        assert spy.calls == []
        assert proc.returncode is not None

    def test_kill_on_a_live_process_kills_its_group_and_reaps_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proc = _sleeper()
        spy = _KillpgSpy()
        monkeypatch.setattr(runner, "os", SimpleNamespace(killpg=spy))
        runner._kill(proc)
        assert spy.calls == [(proc.pid, signal.SIGKILL)]
        assert proc.returncode is not None

    def test_second_kill_is_signal_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = _sleeper()
        runner._kill(proc)  # real kill + reap
        spy = _KillpgSpy()
        monkeypatch.setattr(runner, "os", SimpleNamespace(killpg=spy))
        runner._kill(proc)  # double-kill call sites must be harmless, not a recycled-pgid kill
        assert spy.calls == []

    @pytest.mark.skipif(_ZOMBIE_GROUPS_UNSTAGEABLE, reason="zombie pgids stay signalable on Linux")
    def test_kill_of_an_exited_unreaped_child_falls_back_to_direct_kill(self) -> None:
        proc = _zombie()
        assert proc.returncode is None  # unreaped: the guard rightly allows a kill attempt
        runner._kill(proc)  # killpg raises for real; the direct-kill fallback then reaps
        assert proc.returncode is not None

    def test_kill_still_unregisters_from_the_current_scope(self) -> None:
        scope = CancelScope()
        with cancel_scope(scope):
            proc = _sleeper()
            scope.register(proc)
            runner._kill(proc)
            assert proc.pid not in scope._procs


class TestCancelKillGroup:
    def test_kill_group_on_a_reaped_process_never_issues_killpg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proc = _reaped()
        spy = _KillpgSpy()
        monkeypatch.setattr(cancel_module, "os", SimpleNamespace(killpg=spy))
        cancel_module._kill_group(proc)
        assert spy.calls == []

    @pytest.mark.skipif(_ZOMBIE_GROUPS_UNSTAGEABLE, reason="zombie pgids stay signalable on Linux")
    def test_kill_group_on_an_exited_unreaped_child_falls_back_to_direct_kill(self) -> None:
        proc = _zombie()
        cancel_module._kill_group(proc)  # real killpg failure → suppressed direct kill
        proc.wait()
        assert proc.returncode is not None

    def test_cancel_kills_only_the_live_children(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scope = CancelScope()
        live = _sleeper()
        dead = _reaped()
        scope.register(live)
        scope.register(dead)
        spy = _KillpgSpy()
        monkeypatch.setattr(cancel_module, "os", SimpleNamespace(killpg=spy))
        started = time.perf_counter()
        scope.cancel()
        live.wait(timeout=2.0)
        assert time.perf_counter() - started < 2.0
        assert spy.calls == [(live.pid, signal.SIGKILL)]
