"""Local-store open path (ADR-0016) pinned by DIRECT calls to `db.local_store`.

test_migrations proves the same lifecycle through the app lifespan; these tests drive
`prepare_local_store` / `check_not_newer` / `install_sqlite_pragmas` / `sqlite_file_path`
themselves on real files: URL classification, WAL + FK pragmas actually taking effect, fresh
stamping, the idempotent re-open, refuse-newer at both gates (the read-only check and the
in-`_prepare` defense it backs up — the latter reachable only when the gate is bypassed,
which is exactly what calling prepare directly does), real forward migration from 0001, the
stamp-only 0003→0004 step, and FTS trigger liveness on an adopted legacy store."""

import asyncio
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from tempest.model import DivergenceClass, Lang, Severity, TargetClassification, Verdict
from tempest_api.db import Base
from tempest_api.db.local_store import (
    HEAD_REVISION,
    NewerDatabaseError,
    check_not_newer,
    install_sqlite_pragmas,
    prepare_local_store,
    sqlite_file_path,
)
from tempest_api.db.models import Divergence, Repo, Run, Target
from tempest_api.db.session import create_engine_and_factory
from tempest_api.schemas import RunStatus

API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return config


def _prepare(db_path: Path) -> None:
    engine, _ = create_engine_and_factory(f"sqlite+aiosqlite:///{db_path}")

    async def scenario() -> None:
        try:
            await prepare_local_store(engine)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def _stamp(db_path: Path) -> str | None:
    with sqlite3.connect(db_path) as conn:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return None if row is None else str(row[0])


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")}


class TestSqliteFilePath:
    def test_non_sqlite_urls_have_no_file(self) -> None:
        assert sqlite_file_path("postgresql+asyncpg://u:p@localhost/db") is None

    def test_memory_and_empty_sqlite_urls_have_no_file(self) -> None:
        assert sqlite_file_path("sqlite+aiosqlite:///:memory:") is None
        assert sqlite_file_path("sqlite+aiosqlite://") is None

    def test_file_backed_sqlite_url_resolves(self, tmp_path: Path) -> None:
        db = tmp_path / "store.db"
        assert sqlite_file_path(f"sqlite+aiosqlite:///{db}") == db


def test_pragmas_take_effect_on_every_connection(tmp_path: Path) -> None:
    db = tmp_path / "pragma.db"
    engine, _ = create_engine_and_factory(f"sqlite+aiosqlite:///{db}")
    install_sqlite_pragmas(engine)

    async def scenario() -> tuple[object, object]:
        try:
            async with engine.connect() as conn:
                journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
                fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
                return journal, fk
        finally:
            await engine.dispose()

    journal, fk = asyncio.run(scenario())
    assert journal == "wal", "readers must stay unblocked during ingest writes"
    assert fk == 1, "budget pruning relies on ON DELETE CASCADE actually firing"


def test_the_registered_connect_hook_configures_a_raw_dbapi_connection(tmp_path: Path) -> None:
    """The pool hook itself, applied to a plain DBAPI connection: the exact listener
    `install_sqlite_pragmas` registered is fetched from the engine's event registry and run
    against real sqlite3 — pinning WHAT the hook sets, independent of pool plumbing."""
    engine, _ = create_engine_and_factory(f"sqlite+aiosqlite:///{tmp_path / 'hooked.db'}")
    install_sqlite_pragmas(engine)
    hooks = [
        fn
        for fn in engine.sync_engine.pool.dispatch.connect
        if getattr(fn, "__name__", "") == "_on_connect"
    ]
    assert len(hooks) == 1, "exactly one connect-time configurator of ours"

    conn = sqlite3.connect(tmp_path / "hooked.db")
    try:
        hooks[0](conn, None)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
        asyncio.run(engine.dispose())


class TestCheckNotNewer:
    def test_memory_and_missing_files_pass(self, tmp_path: Path) -> None:
        check_not_newer("sqlite+aiosqlite:///:memory:")  # nothing on disk to refuse
        check_not_newer(f"sqlite+aiosqlite:///{tmp_path / 'never-created.db'}")

    def test_unstamped_legacy_store_passes(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        engine = sa.create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(engine)
        engine.dispose()
        check_not_newer(f"sqlite+aiosqlite:///{db}")  # adopted later, never refused

    def test_known_stamp_passes_and_newer_stamp_is_refused_readonly(self, tmp_path: Path) -> None:
        db = tmp_path / "stamped.db"
        _prepare(db)
        url = f"sqlite+aiosqlite:///{db}"
        check_not_newer(url)  # head-stamped: fine
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE alembic_version SET version_num = '9999'")
            conn.commit()
        before = db.read_bytes()
        with pytest.raises(NewerDatabaseError, match="written by a newer"):
            check_not_newer(url)
        assert db.read_bytes() == before, "the refusal must not write a byte"


class TestPrepareLocalStore:
    def test_fresh_file_is_created_and_stamped_then_reopens_unchanged(self, tmp_path: Path) -> None:
        db = tmp_path / "fresh.db"
        _prepare(db)
        assert _stamp(db) == HEAD_REVISION
        assert "bundle_digest" in _columns(db, "runs")
        before = _stamp(db)
        _prepare(db)  # the already-at-head early return: byte-stable stamp
        assert _stamp(db) == before == HEAD_REVISION

    def test_unknown_stamp_is_refused_by_the_in_prepare_defense(self, tmp_path: Path) -> None:
        db = tmp_path / "newer.db"
        _prepare(db)
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE alembic_version SET version_num = '9999'")
            conn.commit()
        # check_not_newer normally rejects first; calling prepare directly bypasses it, which
        # is precisely the case the defense-in-depth raise exists for.
        with pytest.raises(NewerDatabaseError, match="unknown to this app"):
            _prepare(db)
        assert _stamp(db) == "9999", "the refused store must not have been advanced"

    def test_0001_store_is_forward_migrated_in_place(self, tmp_path: Path) -> None:
        db = tmp_path / "older.db"
        command.upgrade(_alembic_config(db), "0001")
        assert _columns(db, "runs").isdisjoint({"sandbox_tier", "bundle_digest"})
        _prepare(db)
        assert _stamp(db) == HEAD_REVISION
        assert {"sandbox_tier", "sandbox_assurance", "bundle_digest"} <= _columns(db, "runs")

    def test_0003_store_advances_on_a_stamp_only_step(self, tmp_path: Path) -> None:
        # 0003→0004 only changes declared VARCHAR widths, invisible to SQLite: the forward
        # step is empty and the stamp still must advance.
        db = tmp_path / "widths.db"
        command.upgrade(_alembic_config(db), "0003")
        before = _columns(db, "runs")
        _prepare(db)
        assert _stamp(db) == HEAD_REVISION
        assert _columns(db, "runs") == before

    def test_empty_alembic_version_table_is_treated_as_unstamped(self, tmp_path: Path) -> None:
        db = tmp_path / "empty-stamp.db"
        engine = sa.create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
        engine.dispose()
        _prepare(db)
        assert _stamp(db) == HEAD_REVISION


def _insert_divergence(engine: sa.Engine, *, repo: str, detail: str) -> None:
    with Session(engine) as s:
        planted = Repo(name=repo)
        s.add(planted)
        s.flush()
        run = Run(
            repo_id=planted.id, base_sha="a" * 40, head_sha="b" * 40, status=RunStatus.COMPLETE
        )
        s.add(run)
        s.flush()
        target = Target(
            run_id=run.id,
            position=0,
            file_path="m.py",
            module="m",
            qualname="f",
            lang=Lang.PYTHON,
            classification=TargetClassification.PURE_CANDIDATE,
            verdict=Verdict.DIVERGENT,
            inputs_run=1,
            equivalent_inputs=0,
            unprovable_inputs=0,
            changed_line_coverage=1.0,
        )
        s.add(target)
        s.flush()
        s.add(
            Divergence(
                target_id=target.id,
                position=0,
                divergence_class=DivergenceClass.RETURN_VALUE,
                severity=Severity.NORMAL,
                detail=detail,
                args_literal="()",
                kwargs_literal="{}",
                minimized_args="()",
                minimized_kwargs="{}",
                shrink_path=[],
                base_summary="b",
                head_summary="h",
                repro_filename="r.py",
                repro_script="print('r')\n",
            )
        )
        s.commit()


def test_adopted_store_rebuilds_the_index_and_keeps_triggers_live(tmp_path: Path) -> None:
    """A pre-Phase-11 store carrying divergence rows is adopted with those rows SEARCHABLE
    (the open path detects the empty index via the _docsize shadow table and rebuilds), and
    rows written AFTER adoption are indexed immediately by the triggers."""
    db = tmp_path / "legacy.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    _insert_divergence(engine, repo="adopted", detail="legacy xylophone regression")
    engine.dispose()

    _prepare(db)
    assert _stamp(db) == HEAD_REVISION, "carrying rows must not derail adoption stamping"
    with sqlite3.connect(db) as conn:
        inherited = conn.execute(
            "SELECT COUNT(*) FROM divergences_fts WHERE divergences_fts MATCH 'xylophone'"
        ).fetchone()[0]
    assert inherited == 1, "rows the store carried before adoption must be rebuilt into FTS"

    engine = sa.create_engine(f"sqlite:///{db}")
    _insert_divergence(engine, repo="adopted-after", detail="fresh glockenspiel regression")
    engine.dispose()
    with sqlite3.connect(db) as conn:
        fresh = conn.execute(
            "SELECT COUNT(*) FROM divergences_fts WHERE divergences_fts MATCH 'glockenspiel'"
        ).fetchone()[0]
    assert fresh == 1, "rows written after adoption must be indexed by the triggers"
