"""Regression pins for the adversarial-review findings (C1/C2/M1/M3/M4/M5 + minors): each
test reproduces the reviewer's exact failing sequence and must fail before its fix."""

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tempest_api.bundlestore import BundleStore
from tempest_api.db.session import create_engine_and_factory

API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


class TestC2PragmasOnEveryEngine:
    def test_factory_engines_enforce_foreign_keys_and_wal(self, tmp_path: Path) -> None:
        """C2: the prove-thread engine skipped install_sqlite_pragmas — FK cascades silently
        off. Every sqlite engine from the factory must now enforce both pragmas."""
        import asyncio

        async def probe() -> tuple[int, str]:
            engine, _ = create_engine_and_factory(f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}")
            try:
                async with engine.connect() as conn:
                    fk = (await conn.execute(sa.text("PRAGMA foreign_keys"))).scalar_one()
                    mode = (await conn.execute(sa.text("PRAGMA journal_mode"))).scalar_one()
                return int(fk), str(mode)
            finally:
                await engine.dispose()

        fk, mode = asyncio.run(probe())
        assert fk == 1, "foreign keys must be ON for every factory engine (cascades depend on it)"
        assert mode == "wal"


class TestC1GcOnlyAfterCommit:
    def test_budgetless_ingest_never_garbage_collects(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C1: gc ran on EVERY ingest against an uncommitted snapshot — a concurrent ingest's
        just-written blob was deleted. With no budget set, ingest must not gc at all; the
        stranger blob (stand-in for a concurrent request's flushed-not-committed put) survives."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("TEMPEST_BUNDLE_BUDGET_BYTES", raising=False)
        store = BundleStore(tmp_path / "data" / "bundles")
        stranger = store.put(b"a concurrent request's uncommitted bundle bytes")

        api.ingest(api.make_bundle())
        assert stranger in store.digests(), "no budget → ingest must never delete other blobs"

    def test_budget_prune_still_collects_only_committed_garbage(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        z1 = api.zip_bytes(api.make_bundle(repo="r0", head_sha="0" * 40))
        z2 = api.zip_bytes(api.make_bundle(repo="r1", head_sha="1" * 40))
        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", str(len(z1) + len(z2) - 1))

        first = api.create_run_id(repo="r0", base_sha="a" * 40, head_sha="0" * 40)
        assert api.upload_zip(first, z1).status_code == 200
        second = api.create_run_id(repo="r1", base_sha="a" * 40, head_sha="1" * 40)
        assert api.upload_zip(second, z2).status_code == 200

        store = BundleStore(tmp_path / "data" / "bundles")
        import hashlib

        assert store.digests() == {hashlib.sha256(z2).hexdigest()}, (
            "budget pruning (row + blob, post-commit) must still work end to end"
        )


class TestM1IngestNeverPrunesItself:
    def test_uploading_to_an_old_pending_run_does_not_delete_it(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1: prune order is created_at, so an old PENDING run ingesting late deleted ITSELF
        and the client got a 404 for a successful upload."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        old_pending = api.create_run_id(repo="early", base_sha="a" * 40, head_sha="e" * 40)

        filler = api.zip_bytes(api.make_bundle(repo="filler", head_sha="f" * 40))
        own = api.zip_bytes(api.make_bundle(repo="early", head_sha="e" * 40))
        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "1")
        filler_run = api.create_run_id(repo="filler", base_sha="a" * 40, head_sha="f" * 40)
        assert api.upload_zip(filler_run, filler).status_code == 200

        resp = api.upload_zip(old_pending, own)
        assert resp.status_code == 200, f"an ingest must never prune its own run: {resp.text}"
        assert api.get_json(f"/v1/runs/{old_pending}")["status"] == "COMPLETE"


class TestM3LegacyAdoptionRepairsSchema:
    def test_unstamped_old_schema_store_is_forward_repaired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M3: adoption stamped head without adding the columns newer revisions introduced —
        bricking every Run query permanently. An unstamped 0001-era store must open and work."""
        from fastapi.testclient import TestClient

        from tempest_api.app import create_app

        legacy = tmp_path / "legacy-old.db"
        command.upgrade(_alembic_config(legacy), "0001")
        with sqlite3.connect(legacy) as conn:
            conn.execute("DROP TABLE alembic_version")  # simulate the pre-phase-11 create_all era
            conn.commit()

        monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{legacy}")
        with TestClient(create_app()) as client:
            assert client.get("/v1/runs").status_code == 200, (
                "adopted stores must be repaired to head, not stamped and bricked"
            )
        with sqlite3.connect(legacy) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
        assert "bundle_digest" in cols and "sandbox_tier" in cols


class TestM4PresenceIsDatabaseTruth:
    def test_orphan_blob_without_run_row_reports_missing(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M4: presence answered from disk blobs — a crash between blob write and DB commit
        made every peer skip the bundle forever. Presence must be DB truth."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        store = BundleStore(tmp_path / "data" / "bundles")
        orphan = store.put(b"blob that never got its run row (crash mid-import)")

        result = api.client.post("/v1/bundles/presence", json={"digests": [orphan]}).json()
        assert result["missing"] == [orphan], "an orphan blob is NOT present — the run is truth"

        ingested = api.ingest(api.make_bundle())
        exported = api.client.get(f"/v1/runs/{ingested}/bundle").content
        import hashlib

        real = hashlib.sha256(exported).hexdigest()
        result = api.client.post("/v1/bundles/presence", json={"digests": [real]}).json()
        assert result["present"] == [real]


class TestM5ImportHealsMissingBlob:
    def test_reimport_restores_an_externally_deleted_blob(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        data = api.zip_bytes(api.make_bundle())
        first = api.client.post(
            "/v1/runs/import", files={"file": ("a.tempest.zip", data, "application/zip")}
        )
        assert first.status_code == 200
        run_id = first.json()["id"]

        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        store = BundleStore(tmp_path / "data" / "bundles")
        store.gc(referenced=set())  # externally lose every blob

        second = api.client.post(
            "/v1/runs/import", files={"file": ("b.tempest.zip", data, "application/zip")}
        )
        assert second.status_code == 200 and second.json()["id"] == run_id
        assert store.get(digest) == data, "the idempotent path must restore the missing blob"
        assert api.client.get(f"/v1/runs/{run_id}/bundle").content == data


class TestMinorHardening:
    def test_corrupt_telemetry_file_never_breaks_recording(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M2: JSONDecodeError escaped and flipped finished proves to ERROR."""
        from tempest.telemetry import record_run_aggregate, telemetry_path

        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        telemetry_path().parent.mkdir(parents=True, exist_ok=True)
        telemetry_path().write_text("{torn garbage")
        record_run_aggregate(
            verdict="DIVERGENT", sandbox_tier="T2", unproven_reasons=(), duration_ms=1
        )
        payload = json.loads(telemetry_path().read_text())
        assert payload["runs"] == 1, "corrupt state is replaced by a fresh payload, never a raise"

    def test_double_bundle_submit_is_409_not_500(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """m3: the race loser died with a 500 on the unique constraint."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)
        data = api.zip_bytes(bundle)
        assert api.upload_zip(run_id, data).status_code == 200
        again = api.upload_zip(run_id, data)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "RUN_NOT_PENDING"

    def test_zip_bomb_is_rejected_before_extraction(self, api) -> None:
        """m7: unbounded extractall — a hostile sync peer could exhaust the server."""
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", b"\0" * (600 * 1024 * 1024))
        run_resp = api.create_run_id(repo="bomb", base_sha="a" * 40, head_sha="b" * 40)
        resp = api.upload_zip(run_resp, bomb.getvalue())
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "BUNDLE_INVALID"
