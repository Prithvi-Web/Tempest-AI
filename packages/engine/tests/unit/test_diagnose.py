"""`tempest diagnose` (Phase 17): one redacted, inspectable archive — planted secrets and
home-identifying paths must not appear in ANY member; the user sees the manifest before
anything is sent anywhere (nothing is ever sent automatically)."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tempest.cli.main import app
from tempest.crashlog import capture_crash
from tempest.obslog import get_logger
from tempest.telemetry import record_run_aggregate

runner = CliRunner()

PLANTED = "diagnose-planted-secret-4242"


def _populate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_DIAG_PLANTED_TOKEN", PLANTED)
    monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
    logger = get_logger("diagnose-test")
    logger.info("engine started for %s", f"/Users/prithvivinay/secret-repo with {PLANTED}")
    record_run_aggregate(verdict="DIVERGENT", sandbox_tier="T2", unproven_reasons=(), duration_ms=5)
    try:
        raise ValueError(f"crash carrying {PLANTED}")
    except ValueError as exc:
        assert capture_crash(exc) is not None


def test_diagnose_produces_a_redacted_inspectable_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _populate_data_dir(tmp_path, monkeypatch)
    out = tmp_path / "diag.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "inspect" in result.output.lower(), "the user is told to review before sending"

    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        names = set(archive.namelist())
        assert "MANIFEST.txt" in names
        assert "report.json" in names
        assert "logs.jsonl" in names
        assert any(n.startswith("crashes/") for n in names)
        assert "telemetry.json" in names
        for name in names:
            content = archive.read(name).decode("utf-8", errors="replace")
            assert PLANTED not in content, f"planted secret leaked into {name}"
            assert "prithvivinay" not in content, f"home identity leaked into {name}"
        manifest = archive.read("MANIFEST.txt").decode()
        for name in sorted(names - {"MANIFEST.txt"}):
            assert name in manifest, "the manifest lists every member"
        report = json.loads(archive.read("report.json"))
        assert "sandbox" in report and "checks" in report


def test_diagnose_works_on_an_empty_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    out = tmp_path / "diag-empty.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        assert "report.json" in set(archive.namelist())
