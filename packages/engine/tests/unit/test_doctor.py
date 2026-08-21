"""`tempest doctor` (Phase 17): a copy-pasteable health report — sandbox tier, execution
smoke, data dir + disk, power state — honest exit code, machine-readable with --json."""

import json

import pytest
from typer.testing import CliRunner

from tempest.cli.main import app

runner = CliRunner()


def _this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """`doctor` reports on THE MACHINE IT RUNS ON, so a tier-ladder SIMULATION must not reach it.

    `make verify-linux-denominator` exports `TEMPEST_NO_SEATBELT=1` to force fixture repositories
    past T2 (ADR-0058). Left in place here, these three tests would assert that a Mac with a
    working Seatbelt has no sandbox at all — a faithful report about a machine that does not
    exist, and a failure that says nothing about `doctor`. The test below that WANTS a tier-less
    machine sets both flags itself, which is where that decision belongs.
    """
    monkeypatch.delenv("TEMPEST_NO_SEATBELT", raising=False)


def test_doctor_reports_healthy_on_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    _this_machine(monkeypatch)
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "sandbox" in out and ("T1" in out or "T2" in out)
    assert "python" in out
    assert "data dir" in out
    assert "disk free" in out
    assert "FAIL" not in out


def test_doctor_json_is_machine_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    _this_machine(monkeypatch)
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["sandbox"]["tier"] in ("T1", "T2")
    assert payload["checks"]["data_dir_writable"] is True
    assert payload["checks"]["execution_smoke"] is True


def test_doctor_fails_honestly_when_no_sandbox_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_NO_SEATBELT", "1")
    monkeypatch.setenv("TEMPEST_DOCKER", "/nonexistent/docker-binary")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1, "no sandbox available must be a FAIL, never a shrug"
    assert "FAIL" in result.output


def test_doctor_reports_power_pause_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _this_machine(monkeypatch)
    monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "on battery power (forced)")
    result = runner.invoke(app, ["doctor"])
    assert "on battery power (forced)" in result.output
    assert result.exit_code == 0, "a pause condition is a warning, not a failure"
