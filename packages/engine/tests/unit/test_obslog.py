"""Structured JSON-lines observability log (Phase 17.3): one JSON object per line in
`log_dir()/tempest.jsonl`, size-rotated with numbered backups; `read_records` merges rotated
files oldest-to-newest (newest-last), skips corrupt lines, and filters by minimum level.
The logging path must never raise — a full disk must not break a prove."""

import json
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tempest import obslog
from tempest.cli.logs import logs_app
from tempest.obslog import get_logger, log_dir, read_records

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test logs into its own TEMPEST_DATA_DIR — never the developer's ~/.tempest."""
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))


def _log_file(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "tempest.jsonl"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


class TestLogDir:
    def test_env_var_wins(self, tmp_path: Path) -> None:
        assert log_dir() == tmp_path / "logs"

    def test_defaults_to_home_dot_tempest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_DATA_DIR")
        assert log_dir() == Path.home() / ".tempest" / "logs"


class TestJsonLines:
    def test_one_valid_json_object_per_line_with_core_fields(self, tmp_path: Path) -> None:
        get_logger("engine").info("hello world")
        lines = _lines(_log_file(tmp_path))
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["level"] == "INFO"
        assert record["component"] == "engine"
        assert record["message"] == "hello world"
        ts = datetime.fromisoformat(record["ts"])
        assert ts.tzinfo is not None and ts.utcoffset() == UTC.utcoffset(None)

    def test_extras_merge_into_the_record(self, tmp_path: Path) -> None:
        get_logger("engine").info(
            "proved", extra={"tempest_extra": {"target": "pkg.fn", "inputs": 42}}
        )
        record = json.loads(_lines(_log_file(tmp_path))[-1])
        assert record["target"] == "pkg.fn"
        assert record["inputs"] == 42

    def test_extras_cannot_clobber_core_fields(self, tmp_path: Path) -> None:
        get_logger("engine").info("real", extra={"tempest_extra": {"message": "forged"}})
        record = json.loads(_lines(_log_file(tmp_path))[-1])
        assert record["message"] == "real"


class TestGetLoggerIdempotency:
    def test_two_calls_leave_exactly_one_handler(self, tmp_path: Path) -> None:
        first = get_logger("idem")
        second = get_logger("idem")
        assert first is second
        assert len(first.handlers) == 1
        first.info("once")
        assert len(_lines(_log_file(tmp_path))) == 1


class TestRotation:
    def test_rotation_produces_a_numbered_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(obslog, "_MAX_BYTES", 400)
        logger = get_logger("rotate")
        for i in range(60):
            logger.info(f"filler record number {i:03d}")
        backup = _log_file(tmp_path).with_name("tempest.jsonl.1")
        assert backup.exists()
        assert _log_file(tmp_path).exists()
        for line in _lines(backup):
            assert isinstance(json.loads(line), dict)


class TestReadRecords:
    def test_merges_rotated_files_newest_last(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir(parents=True)

        def entry(message: str) -> str:
            return json.dumps(
                {
                    "ts": "2026-08-14T00:00:00+00:00",
                    "level": "INFO",
                    "component": "engine",
                    "message": message,
                }
            )

        (logs / "tempest.jsonl.2").write_text(entry("oldest") + "\n", encoding="utf-8")
        (logs / "tempest.jsonl.1").write_text(entry("middle") + "\n", encoding="utf-8")
        (logs / "tempest.jsonl").write_text(entry("newest") + "\n", encoding="utf-8")
        assert [r["message"] for r in read_records()] == ["oldest", "middle", "newest"]

    def test_limit_keeps_only_the_newest(self, tmp_path: Path) -> None:
        logger = get_logger("engine")
        for i in range(5):
            logger.info(f"record {i}")
        assert [r["message"] for r in read_records(limit=2)] == ["record 3", "record 4"]

    def test_level_is_a_minimum_and_case_insensitive(self) -> None:
        logger = get_logger("engine")
        logger.debug("dbg")
        logger.info("inf")
        logger.warning("wrn")
        logger.error("err")
        assert [r["message"] for r in read_records(level="warning")] == ["wrn", "err"]
        assert [r["message"] for r in read_records(level="ERROR")] == ["err"]

    def test_corrupt_lines_are_skipped(self, tmp_path: Path) -> None:
        logger = get_logger("engine")
        logger.info("before")
        with _log_file(tmp_path).open("a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
            fh.write("[1, 2, 3]\n")
        logger.info("after")
        assert [r["message"] for r in read_records()] == ["before", "after"]

    def test_no_log_files_means_empty_list(self) -> None:
        assert read_records() == []

    def test_unknown_level_is_a_hard_error(self) -> None:
        with pytest.raises(ValueError, match="LOUD"):
            read_records(level="LOUD")


class TestNeverRaises:
    def test_full_disk_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger = get_logger("disk")
        logger.info("opens the stream")
        handler = logger.handlers[0]
        assert isinstance(handler, RotatingFileHandler)

        def full_disk(_: str) -> int:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(handler.stream, "write", full_disk)
        logger.info("must not raise", extra={"tempest_extra": {"k": "v"}})


class TestLogsCli:
    def test_show_renders_one_human_line_per_record(self) -> None:
        logger = get_logger("cli")
        logger.info("first message")
        logger.warning("second message")
        result = runner.invoke(logs_app, ["show"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("INFO [cli] first message")
        assert lines[1].endswith("WARNING [cli] second message")

    def test_show_json_prints_raw_json_lines(self) -> None:
        get_logger("cli").info("as json")
        result = runner.invoke(logs_app, ["show", "--json"])
        assert result.exit_code == 0, result.output
        records = [json.loads(line) for line in result.output.splitlines()]
        assert [r["message"] for r in records] == ["as json"]

    def test_show_honors_limit_and_level(self) -> None:
        logger = get_logger("cli")
        for i in range(3):
            logger.info(f"info {i}")
        logger.error("boom")
        limited = runner.invoke(logs_app, ["show", "--limit", "1"])
        assert limited.exit_code == 0
        assert len(limited.output.splitlines()) == 1
        assert limited.output.splitlines()[0].endswith("ERROR [cli] boom")
        levelled = runner.invoke(logs_app, ["show", "--level", "error"])
        assert levelled.exit_code == 0
        assert levelled.output.splitlines()[-1].endswith("ERROR [cli] boom")
        assert len(levelled.output.splitlines()) == 1

    def test_show_with_no_logs_is_quietly_empty(self) -> None:
        result = runner.invoke(logs_app, ["show"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_show_unknown_level_exits_2_with_the_valid_vocabulary(self) -> None:
        result = runner.invoke(logs_app, ["show", "--level", "LOUD"])
        assert result.exit_code == 2
        assert "LOUD" in result.stderr
        assert "ERROR" in result.stderr
