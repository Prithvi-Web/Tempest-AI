"""GET /v1/logs (Phase 17): the sidecar serves its own structured log to the desktop viewer,
and a local prove writes real records into it."""

from pathlib import Path

import pytest

from tempest.obslog import get_logger


def test_logs_endpoint_serves_structured_records(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    get_logger("test-component").info("engine warmed up")
    get_logger("test-component").warning("something odd")

    records = api.get_json("/v1/logs", params={"limit": 10})
    messages = [r["message"] for r in records]
    assert "engine warmed up" in messages and "something odd" in messages
    newest = records[-1]
    assert newest["level"] == "WARNING"
    assert newest["component"] == "test-component"
    assert newest["ts"]

    errors_only = api.get_json("/v1/logs", params={"limit": 10, "level": "ERROR"})
    assert errors_only == []


def test_logs_endpoint_empty_state(api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "empty"))
    assert api.get_json("/v1/logs") == []
