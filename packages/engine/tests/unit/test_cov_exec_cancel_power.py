"""Cancel + power-pause edges left uncovered by the L11 suite (Law L4 — no mocks):

- `CancelScope.cancelled` and the `_kill_group` fallback run against REAL processes.
- The darwin pmset probe runs a REAL fake `pmset` executable on PATH (real subprocess
  execution, exactly how the probe consumes the tool). Only the platform *identity* is pinned
  per test — `platform.system()` cannot vary for real on one host, and pinning it is the only
  way the same test set measures both arms on macOS and Linux CI.
"""

import stat
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tempest.execute import powerstate
from tempest.execute.cancel import CancelScope
from tempest.execute.powerstate import _darwin_probe, power_pause_reason


class TestCancelScope:
    def test_cancelled_property_reflects_cancel(self) -> None:
        scope = CancelScope()
        assert scope.cancelled is False
        scope.cancel()
        assert scope.cancelled is True

    def test_registering_an_already_dead_process_after_cancel_is_harmless(self) -> None:
        # register() on a cancelled scope kills immediately; a process that was already
        # REAPED now takes _kill_group's returncode guard (review finding 2: killpg on a
        # reaped pid could hit a recycled pgid). The killpg-failure fallback is pinned with
        # an unreaped zombie in test_fix_exec_kill_discipline.py.
        scope = CancelScope()
        scope.cancel()
        proc = subprocess.Popen(["sleep", "0"], start_new_session=True)
        proc.wait()  # fully reaped: killpg on its pgid must fail for real
        scope.register(proc)  # must not raise
        assert proc.poll() is not None


def _fake_pmset(tmp_path: Path, batt: str, therm: str) -> Path:
    """A REAL executable named pmset answering `-g batt` / `-g therm` like the OS tool."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "pmset"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = "batt" ]; then\n'
        f"  printf '%s\\n' '{batt}'\n"
        "else\n"
        f"  printf '%s\\n' '{therm}'\n"
        "fi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@pytest.fixture(autouse=True)
def _fresh_probe_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(powerstate, "_probe_cache", None)
    monkeypatch.delenv("TEMPEST_FORCE_POWER_PAUSE", raising=False)


class TestDarwinProbe:
    """_darwin_probe consumes whatever `pmset` on PATH answers — driven by real fakes."""

    def test_battery_power_is_a_pause_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = _fake_pmset(tmp_path, "Now drawing from Battery Power", "")
        monkeypatch.setenv("PATH", str(bin_dir))
        assert _darwin_probe() == "on battery power"

    def test_thermal_speed_limit_below_100_is_a_pause_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = _fake_pmset(tmp_path, "Now drawing from AC Power", "CPU_Speed_Limit = 60")
        monkeypatch.setenv("PATH", str(bin_dir))
        assert _darwin_probe() == "thermal pressure (CPU speed limited to 60%)"

    def test_full_speed_and_ac_power_report_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = _fake_pmset(tmp_path, "Now drawing from AC Power", "CPU_Speed_Limit = 100")
        monkeypatch.setenv("PATH", str(bin_dir))
        assert _darwin_probe() is None

    def test_unparsable_limit_value_never_stalls_a_prove(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = _fake_pmset(tmp_path, "AC Power", "CPU_Speed_Limit = banana")
        monkeypatch.setenv("PATH", str(bin_dir))
        assert _darwin_probe() is None  # ValueError swallowed: broken probe means don't pause

    def test_missing_pmset_binary_never_stalls_a_prove(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        assert _darwin_probe() is None  # OSError swallowed


class TestPowerPauseReasonProbePath:
    """The platform gate + probe cache. platform.system() is pinned per test (the host OS
    cannot be varied for real); the pmset subprocess underneath is genuinely executed."""

    def test_non_darwin_platforms_report_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_NO_POWER_PAUSE", raising=False)
        monkeypatch.setattr(powerstate, "platform", SimpleNamespace(system=lambda: "Linux"))
        assert power_pause_reason() is None

    def test_darwin_probe_result_is_cached_within_the_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TEMPEST_NO_POWER_PAUSE", raising=False)
        monkeypatch.setattr(powerstate, "platform", SimpleNamespace(system=lambda: "Darwin"))
        bin_dir = _fake_pmset(tmp_path, "Now drawing from Battery Power", "")
        monkeypatch.setenv("PATH", str(bin_dir))

        assert power_pause_reason() == "on battery power"

        # Swap the underlying tool's answer: the cached reason must win inside the window.
        _fake_pmset(tmp_path, "Now drawing from AC Power", "")
        assert power_pause_reason() == "on battery power"

        # Age the cache out: the fresh (AC) answer must now be probed for real.
        cached = powerstate._probe_cache
        assert cached is not None
        monkeypatch.setattr(
            powerstate, "_probe_cache", (time.monotonic() - 2 * powerstate._PROBE_CACHE_S, "stale")
        )
        assert power_pause_reason() is None
