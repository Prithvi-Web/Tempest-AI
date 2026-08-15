"""Observability edges over the real log files: the zero-limit read, level filtering of
records that carry no usable level, and telemetry's must-never-break-a-prove write guarantee
exercised against a genuinely unwritable data dir."""

import json
from pathlib import Path

import pytest

from tempest.obslog import get_logger, read_records
from tempest.telemetry import record_run_aggregate, telemetry_path


class TestReadRecordsEdges:
    def test_zero_limit_returns_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        get_logger("covtest").info("a line that must not surface")
        assert read_records(limit=0) == []

    def test_level_filter_drops_records_without_a_usable_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        log_file = tmp_path / "logs" / "tempest.jsonl"
        log_file.parent.mkdir(parents=True)
        log_file.write_text(
            json.dumps({"level": "WARNING", "message": "keep me"})
            + "\n"
            + json.dumps({"message": "no level field"})
            + "\n"
            + json.dumps({"level": 42, "message": "non-string level"})
            + "\n",
            encoding="utf-8",
        )
        filtered = read_records(level="DEBUG")
        assert [r["message"] for r in filtered] == ["keep me"], (
            "records without a usable level must not satisfy a minimum-level filter"
        )
        unfiltered = read_records()
        assert len(unfiltered) == 3, "without a filter, malformed levels still surface"


class TestTelemetryNeverBreaksAProve:
    def test_unwritable_data_dir_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # TEMPEST_DATA_DIR points at a FILE: mkdir() genuinely fails with an OSError.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory\n")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(blocker))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        record_run_aggregate(
            verdict="UNPROVEN",
            sandbox_tier="none",
            unproven_reasons=("SANDBOX_UNAVAILABLE",),
            duration_ms=5,
        )  # must not raise — telemetry failing a prove would violate its contract
        assert blocker.read_text() == "not a directory\n", "the blocking file is untouched"
        assert not telemetry_path().exists()
