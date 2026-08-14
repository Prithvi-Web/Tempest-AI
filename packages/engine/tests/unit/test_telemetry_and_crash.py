"""Telemetry aggregates + crash capture (Phase 17, L9): counters only, opt-in, and every
crash record is scrubbed at write time — planted secrets must not reach disk."""

import json
from pathlib import Path

import pytest

from tempest.crashlog import capture_crash, crash_dir, install_crash_capture
from tempest.telemetry import record_run_aggregate, telemetry_enabled, telemetry_path


class TestTelemetryAggregates:
    def test_disabled_by_default_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("TEMPEST_TELEMETRY", raising=False)
        assert telemetry_enabled() is False
        record_run_aggregate(
            verdict="DIVERGENT", sandbox_tier="T2", unproven_reasons=(), duration_ms=1200
        )
        assert not telemetry_path().exists(), "opt-in means OFF writes nothing, ever"

    def test_opt_in_accumulates_counters_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        record_run_aggregate(
            verdict="DIVERGENT", sandbox_tier="T2", unproven_reasons=(), duration_ms=1200
        )
        record_run_aggregate(
            verdict="UNPROVEN",
            sandbox_tier="T2",
            unproven_reasons=("TARGET_UNREACHABLE", "TARGET_UNREACHABLE"),
            duration_ms=800,
        )
        payload = json.loads(telemetry_path().read_text())
        assert payload["runs"] == 2
        assert payload["verdicts"]["DIVERGENT"] == 1
        assert payload["tiers"]["T2"] == 2
        assert payload["unproven_reasons"]["TARGET_UNREACHABLE"] == 2
        assert payload["duration_ms_total"] == 2000

    def test_aggregate_file_carries_no_paths_or_identifiers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        record_run_aggregate(
            verdict="EQUIVALENT_UNDER_BUDGET",
            sandbox_tier="fixture",
            unproven_reasons=(),
            duration_ms=10,
        )
        raw = telemetry_path().read_text()
        assert str(Path.home()) not in raw
        assert "/" not in json.dumps(json.loads(raw)["verdicts"]), "enum names only, never paths"


class TestCrashCapture:
    def test_crash_record_is_scrubbed_at_write_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TEMPEST_PLANTED_SECRET_KEY", "crash-planted-value-9000")
        try:
            raise ValueError("boom near crash-planted-value-9000 in /Users/someone/repo/x.py")
        except ValueError as exc:
            path = capture_crash(exc)
        assert path is not None and path.exists()
        raw = path.read_text()
        assert "crash-planted-value-9000" not in raw, "planted secret must not reach disk"
        assert "ValueError" in raw, "the exception type survives for debugging"
        record = json.loads(raw)
        assert record["tempest_version"]
        assert "[source line removed]" in record["traceback"] or "boom" not in record["traceback"]

    def test_crashes_land_in_the_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        try:
            raise RuntimeError("plain crash")
        except RuntimeError as exc:
            path = capture_crash(exc)
        assert path is not None
        assert path.parent == crash_dir()
        assert crash_dir() == tmp_path / "crashes"

    def test_capture_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", "/dev/null/not-a-dir")
        try:
            raise RuntimeError("crash with a broken data dir")
        except RuntimeError as exc:
            assert capture_crash(exc) is None, "a broken disk must not turn a crash into two"

    def test_install_crash_capture_hooks_unhandled_exceptions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        original = sys.excepthook
        try:
            install_crash_capture()
            assert sys.excepthook is not original
            try:
                raise ValueError("unhandled by anyone")
            except ValueError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)
            records = list(crash_dir().glob("crash-*.json"))
            assert len(records) == 1
            assert "ValueError" in records[0].read_text()
        finally:
            sys.excepthook = original
