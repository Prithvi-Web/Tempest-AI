"""Settings endpoints (HANDOFF-WORLD-CLASS §3.2) — the screen's whole contract.

Real app, real file, real bundle store (L4). What is pinned here: the round trip persists;
validation is refused with the §8 envelope, not a 500; an environment variable that outranks
the file is NAMED in the response (the screen must never claim a change it cannot make); a
damaged settings.json still renders — 200, defaults shown, the exact problem stated; and the
key ping never stores anything.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tempest.settings import SETTINGS_SCHEMA_VERSION, Settings, save_settings, settings_path
from tempest_api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    for var in (
        "TEMPEST_SYNC_SHARE_SOURCE",
        "TEMPEST_BUNDLE_BUDGET_BYTES",
        "TEMPEST_TELEMETRY",
        "TEMPEST_SYNC_SERVER_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return TestClient(create_app())


class TestRead:
    def test_defaults_and_the_facts_the_screen_needs(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        body = client.get("/v1/settings").json()
        assert body == {
            "version": SETTINGS_SCHEMA_VERSION,
            "sync_server_url": None,
            "sync_share_source": False,
            "bundle_budget_bytes": 0,
            "telemetry_enabled": False,
            "env_overrides": [],
            "data_dir": str(tmp_path),
            "store_bytes": 0,
            "problem": None,
        }

    def test_store_bytes_reports_what_the_bundle_store_really_holds(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        blob_dir = tmp_path / "bundles" / "aa"
        blob_dir.mkdir(parents=True)
        (blob_dir / ("a" * 64 + ".tempest.zip")).write_bytes(b"x" * 1234)
        assert client.get("/v1/settings").json()["store_bytes"] == 1234


class TestWrite:
    def test_round_trip_persists_to_the_file_and_back(self, client: TestClient) -> None:
        payload = {
            "sync_server_url": "https://team.example.com",
            "sync_share_source": True,
            "bundle_budget_bytes": 5_000_000,
            "telemetry_enabled": True,
        }
        put = client.put("/v1/settings", json=payload)
        assert put.status_code == 200, put.text
        for key, value in payload.items():
            assert put.json()[key] == value
        assert client.get("/v1/settings").json()["sync_server_url"] == "https://team.example.com"
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
        assert stored["telemetry_enabled"] is True
        assert stored["version"] == SETTINGS_SCHEMA_VERSION

    def test_a_non_http_url_is_refused_with_the_error_envelope(self, client: TestClient) -> None:
        resp = client.put(
            "/v1/settings",
            json={
                "sync_server_url": "ftp://nope",
                "sync_share_source": False,
                "bundle_budget_bytes": 0,
                "telemetry_enabled": False,
            },
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "http://" in resp.json()["error"]["message"]

    def test_a_negative_budget_is_refused(self, client: TestClient) -> None:
        resp = client.put(
            "/v1/settings",
            json={
                "sync_server_url": None,
                "sync_share_source": False,
                "bundle_budget_bytes": -5,
                "telemetry_enabled": False,
            },
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_writing_repairs_a_damaged_file(self, client: TestClient) -> None:
        settings_path().write_text("{corrupt", encoding="utf-8")
        assert client.get("/v1/settings").json()["problem"] is not None
        resp = client.put(
            "/v1/settings",
            json={
                "sync_server_url": None,
                "sync_share_source": False,
                "bundle_budget_bytes": 0,
                "telemetry_enabled": True,
            },
        )
        assert resp.status_code == 200
        assert client.get("/v1/settings").json() == {**resp.json()}
        assert client.get("/v1/settings").json()["problem"] is None


class TestHonesty:
    def test_an_environment_override_is_named_not_hidden(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_settings(Settings(telemetry_enabled=False))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        body = client.get("/v1/settings").json()
        assert body["telemetry_enabled"] is True
        assert body["env_overrides"] == [
            {"field": "telemetry_enabled", "variable": "TEMPEST_TELEMETRY"}
        ]

    def test_a_write_under_an_override_still_reports_the_override(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        resp = client.put(
            "/v1/settings",
            json={
                "sync_server_url": None,
                "sync_share_source": False,
                "bundle_budget_bytes": 0,
                "telemetry_enabled": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["telemetry_enabled"] is True  # the environment still wins
        assert resp.json()["env_overrides"] == [
            {"field": "telemetry_enabled", "variable": "TEMPEST_TELEMETRY"}
        ]
        # …and the user's intent WAS recorded, so removing the export takes effect.
        assert json.loads(settings_path().read_text())["telemetry_enabled"] is False

    def test_a_damaged_file_renders_defaults_and_states_the_problem(
        self, client: TestClient
    ) -> None:
        settings_path().write_text('{"version": 999}', encoding="utf-8")
        body = client.get("/v1/settings")
        assert body.status_code == 200
        assert body.json()["telemetry_enabled"] is False
        assert "newer version of Tempest" in body.json()["problem"]
        assert "showing defaults" in body.json()["problem"]


class TestKeyPing:
    def test_no_key_configured_answers_actionably_and_stores_nothing(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = client.post("/v1/settings/ai-key/test")
        assert resp.status_code == 200
        assert resp.json() == {
            "ok": False,
            "detail": "no API key is configured — add one above, then test it.",
            "model": None,
        }
        # Nothing about the ping is persisted: the data dir is untouched by it.
        assert not settings_path().exists()
        assert list(tmp_path.iterdir()) == []


class TestDiagnostics:
    def test_the_bundle_is_written_locally_and_described(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        import zipfile

        resp = client.post("/v1/diagnostics")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        written = tmp_path / "diagnostics" / body["filename"]
        assert written.exists()
        assert body["bytes"] == written.stat().st_size > 0
        assert "REVIEW EVERY FILE BEFORE SENDING" in body["manifest"]
        with zipfile.ZipFile(written) as archive:
            assert "MANIFEST.txt" in archive.namelist()

    def test_the_filename_is_a_bare_name_the_host_can_safely_join(self, client: TestClient) -> None:
        filename = client.post("/v1/diagnostics").json()["filename"]
        assert "/" not in filename and ".." not in filename
        assert filename.endswith(".zip")


class TestUnwritableStorage:
    """Genuinely unwritable, never simulated (L4): the data dir is pointed at a FILE, so every
    mkdir underneath it fails exactly as a full or read-only disk would."""

    @pytest.fixture
    def blocked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory\n")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(blocker))
        monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
        return TestClient(create_app())

    def test_settings_that_cannot_be_written_say_so_with_the_path(
        self, blocked: TestClient
    ) -> None:
        resp = blocked.put(
            "/v1/settings",
            json={
                "sync_server_url": None,
                "sync_share_source": False,
                "bundle_budget_bytes": 0,
                "telemetry_enabled": True,
            },
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "INTERNAL"
        assert "settings.json" in resp.json()["error"]["message"]

    def test_a_diagnostic_bundle_that_cannot_be_written_says_so(self, blocked: TestClient) -> None:
        resp = blocked.post("/v1/diagnostics")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "INTERNAL"
        assert "could not be written" in resp.json()["error"]["message"]
