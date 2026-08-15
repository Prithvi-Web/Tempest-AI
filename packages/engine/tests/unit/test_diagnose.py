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
from tempest.crashlog import capture_crash, crash_dir
from tempest.obslog import get_logger
from tempest.telemetry import record_run_aggregate

runner = CliRunner()

PLANTED = "diagnose-planted-secret-4242"
# Quote, backslash, and newline: JSON escaping rewrites all three, so redacting the
# serialized text against the raw value misses it (finding 5).
NASTY = 'diag"planted\\token\nvalue-99'


def _populate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_DIAG_PLANTED_TOKEN", PLANTED)
    monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
    logger = get_logger("diagnose-test")
    # The planted path must live under THIS machine's real home — the diagnose command
    # builds its redaction context from Path.home(), so a hardcoded /Users/… path is
    # invisible to the scrubber on Linux CI (first-run catch).
    logger.info("engine started for %s", f"{Path.home()}/secret-repo with {PLANTED}")
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
        home, username = str(Path.home()), Path.home().name
        for name in names:
            content = archive.read(name).decode("utf-8", errors="replace")
            assert PLANTED not in content, f"planted secret leaked into {name}"
            assert home not in content, f"home path leaked into {name}"
            assert username not in content, f"home identity leaked into {name}"
        manifest = archive.read("MANIFEST.txt").decode()
        for name in sorted(names - {"MANIFEST.txt"}):
            assert name in manifest, "the manifest lists every member"
        report = json.loads(archive.read("report.json"))
        assert "sandbox" in report and "checks" in report


def test_diagnose_redacts_values_the_json_escaping_would_hide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_DIAG_NASTY_TOKEN", NASTY)
    logger = get_logger("diagnose-nasty-test")
    logger.info("auth failed for %s", NASTY)
    # A list-valued extra rides along so structured payloads are scrubbed element-wise too.
    logger.info("cloning", extra={"tempest_extra": {"remotes": [f"observed {NASTY}", "ok"]}})
    out = tmp_path / "diag.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    escaped = json.dumps(NASTY)[1:-1]  # the JSON-escaped spelling of the same secret
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        for name in set(archive.namelist()):
            content = archive.read(name).decode("utf-8", errors="replace")
            assert NASTY not in content, f"raw planted secret leaked into {name}"
            assert escaped not in content, (
                f"JSON escaping hid the planted secret from the scrubber in {name} (finding 5)"
            )
        assert "[REDACTED:env]" in archive.read("logs.jsonl").decode()


def test_diagnose_report_reduces_data_dir_to_basename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tmp_path lives OUTSIDE $HOME on macOS and Linux alike — exactly the shape the home
    # rule cannot reach (finding 6).
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "diag-data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    out = tmp_path / "diag.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        report = json.loads(archive.read("report.json"))
        assert report["data_dir"] == "[PATH]/diag-data"


def test_diagnose_scrubs_env_sourced_repo_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_REDACT_REPO_NAMES", "planted-diag-repo")
    get_logger("diagnose-repo-test").info("proving planted-diag-repo now")
    try:
        raise RuntimeError("clone of planted-diag-repo failed")
    except RuntimeError as exc:
        assert capture_crash(exc) is not None
    out = tmp_path / "diag.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        for name in set(archive.namelist()):
            content = archive.read(name).decode("utf-8", errors="replace")
            assert "planted-diag-repo" not in content, (
                f"env-sourced repo name leaked into {name} (finding 3)"
            )


def test_diagnose_survives_a_corrupt_crash_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_NO_POWER_PAUSE", "1")
    monkeypatch.setenv("TEMPEST_DIAG_PLANTED_TOKEN", PLANTED)
    crash_dir().mkdir(parents=True, exist_ok=True)
    (crash_dir() / "crash-corrupt.json").write_text(f"{{not json {PLANTED}")
    out = tmp_path / "diag.zip"
    result = runner.invoke(app, ["diagnose", "--out", str(out)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as archive:
        content = archive.read("crashes/crash-corrupt.json").decode()
        assert PLANTED not in content, "an unparseable crash file still gets raw-text redaction"


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
