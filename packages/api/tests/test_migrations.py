"""The handwritten initial migration and the SQLAlchemy models must describe the same schema —
otherwise dev (create_all on sqlite) and prod (alembic on Postgres) silently drift (ADR-0009)."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from tempest_api.app import create_app
from tempest_api.db import Base
from tempest_api.db.local_store import HEAD_REVISION, REVISION_CHAIN, NewerDatabaseError

API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


def _schema_snapshot(db_path: Path) -> dict[str, Any]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    snapshot: dict[str, Any] = {}
    for table in inspector.get_table_names():
        # alembic bookkeeping and the FTS index (an adjunct rebuilt from `divergences`, not
        # schema-of-record — see local_store._ensure_fts) are not part of the parity contract.
        if table == "alembic_version" or table.startswith("divergences_fts"):
            continue
        snapshot[table] = {
            "columns": {
                column["name"]: (str(column["type"]), bool(column["nullable"]))
                for column in inspector.get_columns(table)
            },
            "uniques": sorted(
                tuple(sorted(uc["column_names"])) for uc in inspector.get_unique_constraints(table)
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), bool(index["unique"]))
                for index in inspector.get_indexes(table)
            ),
        }
    engine.dispose()
    return snapshot


def test_initial_migration_matches_the_models(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(migrated), "head")

    from_models = tmp_path / "models.db"
    engine = sa.create_engine(f"sqlite:///{from_models}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrated_schema = _schema_snapshot(migrated)
    model_schema = _schema_snapshot(from_models)
    assert sorted(migrated_schema) == sorted(model_schema)
    for table in model_schema:
        assert migrated_schema[table] == model_schema[table], f"schema drift in table {table!r}"


def test_migration_downgrades_cleanly(tmp_path: Path) -> None:
    db = tmp_path / "cycle.db"
    config = _alembic_config(db)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert _schema_snapshot(db) == {}


# ── Phase 11: local-store lifecycle — WAL, stamping, forward migration, refuse-newer ──────────
#
# The desktop's SQLite file is the primary store. Opening it must: stamp fresh databases at the
# migration head, forward-migrate databases written by an older app, and REFUSE (cleanly, without
# writing a byte) databases written by a newer app. All through the real app lifespan.


def _open_app(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    return TestClient(create_app())


def _stamp(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return None if row is None else str(row[0])


def test_fresh_db_is_stamped_at_head_with_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "fresh.db"
    with _open_app(db, monkeypatch) as client:
        assert client.get("/v1/health").status_code == 200
    assert _stamp(db) == HEAD_REVISION
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_older_db_is_forward_migrated_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "older.db"
    command.upgrade(_alembic_config(old), REVISION_CHAIN[0])

    with _open_app(old, monkeypatch) as client:
        assert client.get("/v1/health").status_code == 200

    reference = tmp_path / "reference.db"
    command.upgrade(_alembic_config(reference), "head")
    assert _stamp(old) == HEAD_REVISION
    assert _schema_snapshot(old) == _schema_snapshot(reference)


def test_newer_db_is_refused_without_modification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    newer = tmp_path / "newer.db"
    command.upgrade(_alembic_config(newer), "head")
    with sqlite3.connect(newer) as conn:
        conn.execute("UPDATE alembic_version SET version_num = '9999'")
        conn.commit()

    before = newer.read_bytes()
    with pytest.raises(NewerDatabaseError, match="newer"), _open_app(newer, monkeypatch):
        pass
    assert newer.read_bytes() == before, "a refused database must not be modified"


def test_legacy_unstamped_db_is_adopted_and_stamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-Phase-11 local stores were created by create_all with no version stamp; the parity
    # test above proves that schema equals the migration head, so adoption stamps it as such.
    legacy = tmp_path / "legacy.db"
    engine = sa.create_engine(f"sqlite:///{legacy}")
    Base.metadata.create_all(engine)
    engine.dispose()
    assert _stamp(legacy) is None

    with _open_app(legacy, monkeypatch) as client:
        assert client.get("/v1/health").status_code == 200
    assert _stamp(legacy) == HEAD_REVISION


def test_revision_chain_matches_alembic_scripts() -> None:
    """Drift gate: the in-code chain (what the frozen sidecar knows) must equal the alembic
    script directory (what develops the schema). One truth, generated discipline (L12 spirit)."""
    directory = ScriptDirectory(str(API_DIR / "alembic"))
    scripted = [script.revision for script in directory.walk_revisions("base", "heads")]
    scripted.reverse()  # walk_revisions yields head-first
    assert tuple(scripted) == REVISION_CHAIN
    assert directory.get_current_head() == HEAD_REVISION
