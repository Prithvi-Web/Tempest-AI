"""`POST /v1/ui-errors` — the frontend's crash honesty (HANDOFF-WORLD-CLASS §1.1).

A webview error must never vanish: the handler scrubs it through the REAL redaction engine
(production context — planted secrets below are the proof, not the code) and lands it in the
same obslog the LOGS view and diagnose read. The endpoint itself must be unbreakable: it is
called from a window error handler, so a failure here would erase the very evidence of a
failure — junk input still answers 200, and an unwritable log dir is swallowed by obslog's
own never-raise contract.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tempest_api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    return TestClient(create_app())


def _log_lines(tmp_path: Path) -> list[dict[str, object]]:
    log_file = tmp_path / "logs" / "tempest.jsonl"
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines()]


class TestRecorded:
    def test_a_ui_error_lands_in_the_obslog_and_the_logs_endpoint(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = client.post(
            "/v1/ui-errors",
            json={
                "message": "TypeError: x is not a function",
                "source": "window.error",
                "stack": "at RunView (RunView.tsx:41)",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"recorded": True}

        records = _log_lines(tmp_path)
        assert len(records) == 1
        record = records[0]
        assert record["level"] == "ERROR"
        assert record["component"] == "ui"
        message = str(record["message"])
        assert "TypeError: x is not a function" in message
        assert "window.error" in message
        assert "RunView.tsx:41" in message

        # …and the LOGS surface the user actually opens serves it back.
        served = client.get("/v1/logs", params={"level": "error"}).json()
        assert any("TypeError: x is not a function" in row["message"] for row in served)

    def test_a_stackless_rejection_is_still_recorded(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = client.post(
            "/v1/ui-errors",
            json={"message": "unhandledrejection: boom", "source": "unhandledrejection"},
        )
        assert resp.status_code == 200
        assert len(_log_lines(tmp_path)) == 1


class TestScrubbed:
    def test_planted_secrets_never_reach_the_log(self, client: TestClient, tmp_path: Path) -> None:
        """The message and stack pass the production redaction engine BEFORE the write —
        planted, letter-segmented fakes (trap 19), asserted absent from the raw file."""
        planted_key = "sk-" + "ant-" + "api03-" + "PLANTED" + "UIERROR" + "FIXTURE" + "AAAA"
        planted_email = "victim" + "@" + "example.com"
        home_path = str(Path.home() / "secret-project" / "app.tsx")
        client.post(
            "/v1/ui-errors",
            json={
                "message": f"fetch failed for {planted_email} with {planted_key}",
                "source": "window.error",
                "stack": f"at boot ({home_path}:3)",
            },
        )
        raw = (tmp_path / "logs" / "tempest.jsonl").read_text()
        assert planted_key not in raw
        assert planted_email not in raw
        assert str(Path.home()) not in raw
        assert "[REDACTED:credential]" in raw or "[REDACTED" in raw


class TestUnbreakable:
    def test_junk_shapes_are_refused_by_validation_not_a_500(self, client: TestClient) -> None:
        resp = client.post("/v1/ui-errors", json={"nope": 1})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_an_oversized_message_is_truncated_not_rejected(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """A crash-looping view can spew megabytes; the report survives, bounded."""
        resp = client.post(
            "/v1/ui-errors",
            json={"message": "x" * 100_000, "source": "window.error", "stack": "y" * 100_000},
        )
        assert resp.status_code == 200
        raw = (tmp_path / "logs" / "tempest.jsonl").read_text()
        assert len(raw) < 50_000
        assert "truncated" in raw
