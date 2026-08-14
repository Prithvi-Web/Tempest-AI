"""The handwritten initial migration and the SQLAlchemy models must describe the same schema —
otherwise dev (create_all on sqlite) and prod (alembic on Postgres) silently drift (ADR-0009)."""

from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tempest_api.db import Base

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
        if table == "alembic_version":
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
