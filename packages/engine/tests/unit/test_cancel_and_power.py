"""L11 mechanics (Phase 11): cancel kills every registered child fast and refuses new spawns;
battery/thermal pause engages via the probe and cancel unblocks a paused prove."""

import subprocess
import threading
import time

import pytest

from tempest.execute.cancel import CancelScope, ProveCancelled, cancel_scope, current_scope
from tempest.execute.powerstate import power_pause_reason, wait_while_paused


def _sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sleep", "60"], start_new_session=True)


class TestCancelScope:
    def test_cancel_kills_registered_children_under_two_seconds(self) -> None:
        scope = CancelScope()
        children = [_sleeper() for _ in range(3)]
        for child in children:
            scope.register(child)

        started = time.perf_counter()
        scope.cancel()
        for child in children:
            child.wait(timeout=2.0)
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0, f"children took {elapsed:.2f}s to die"
        assert all(child.returncode is not None for child in children)

    def test_register_on_a_cancelled_scope_kills_immediately(self) -> None:
        scope = CancelScope()
        scope.cancel()
        child = _sleeper()
        scope.register(child)  # closes the cancel/spawn race: late registrants die too
        child.wait(timeout=2.0)
        assert child.returncode is not None

    def test_raise_if_cancelled(self) -> None:
        scope = CancelScope()
        scope.raise_if_cancelled()
        scope.cancel()
        with pytest.raises(ProveCancelled):
            scope.raise_if_cancelled()

    def test_cancel_scope_context_sets_current(self) -> None:
        assert current_scope() is None
        scope = CancelScope()
        with cancel_scope(scope):
            assert current_scope() is scope
        assert current_scope() is None


class TestPowerPause:
    def test_forced_reason_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "on battery power (forced)")
        assert power_pause_reason() == "on battery power (forced)"

    def test_disable_kills_real_probes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_FORCE_POWER_PAUSE", raising=False)
        monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
        assert power_pause_reason() is None

    def test_pause_engages_and_resumes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # NO_POWER_PAUSE underneath keeps the resume deterministic on a battery-powered dev
        # machine (FORCE > NO > real probes); removing FORCE must resume regardless of pmset.
        monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
        monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "thermal pressure (forced)")
        reasons: list[str] = []
        finished = threading.Event()

        def pause_then_return() -> None:
            wait_while_paused(cancel=None, notify=reasons.append, poll_s=0.05)
            finished.set()

        thread = threading.Thread(target=pause_then_return, daemon=True)
        thread.start()
        time.sleep(0.2)
        assert not finished.is_set(), "the pause must hold while the condition persists"
        assert reasons == ["thermal pressure (forced)"], "the pause reason is reported once"
        monkeypatch.delenv("TEMPEST_FORCE_POWER_PAUSE")
        assert finished.wait(timeout=2.0), "clearing the condition must resume the prove"

    def test_cancel_unblocks_a_paused_prove(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "on battery power (forced)")
        scope = CancelScope()
        outcome: list[str] = []
        finished = threading.Event()

        def pause_until_cancelled() -> None:
            try:
                wait_while_paused(cancel=scope, notify=None, poll_s=0.05)
            except ProveCancelled:
                outcome.append("cancelled")
            finished.set()

        thread = threading.Thread(target=pause_until_cancelled, daemon=True)
        thread.start()
        time.sleep(0.15)
        scope.cancel()
        assert finished.wait(timeout=2.0), "cancel must unblock a paused prove in <2s"
        assert outcome == ["cancelled"]
