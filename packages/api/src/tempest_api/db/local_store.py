"""Local SQLite store lifecycle (Phase 11, ADR-0016).

The desktop's SQLite file is the primary store (L8). Opening it is a versioned act: a fresh
database is created and stamped at the migration head; a database written by an older app is
forward-migrated in place; a database written by a NEWER app is refused before a single byte
is written — an old binary must never guess at a schema it does not know.

The frozen sidecar cannot ship the alembic script directory, so the revision chain lives here
as code; `test_revision_chain_matches_alembic_scripts` pins it to `packages/api/alembic/` and
the forward-migration test proves the mirrored steps land on a schema identical to
`alembic upgrade head`.
"""

import sqlite3
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import ConnectionPoolEntry

from tempest_api.db.base import Base

REVISION_CHAIN: tuple[str, ...] = ("0001", "0002", "0003", "0004", "0005")
HEAD_REVISION: str = REVISION_CHAIN[-1]

# Forward steps, keyed by from-revision; each mirrors the alembic script that takes the schema
# one revision further. SQLite ALTERs only — anything heavier gets a new strategy and an ADR.
# A step may be EMPTY when the revision only changes declared VARCHAR widths (0004): SQLite's
# type affinity ignores them, so the stamp advances with nothing to run; the forward-migration
# equivalence test compares types width-insensitively for exactly this reason.
_FORWARD_STEPS: dict[str, tuple[str, ...]] = {
    "0001": (
        "ALTER TABLE runs ADD COLUMN sandbox_tier TEXT",
        "ALTER TABLE runs ADD COLUMN sandbox_assurance TEXT",
    ),
    "0002": ("ALTER TABLE runs ADD COLUMN bundle_digest TEXT",),
    "0003": (),
    "0004": ("ALTER TABLE divergences ADD COLUMN ai_narrative TEXT",),
}


class NewerDatabaseError(RuntimeError):
    """The database on disk was written by a newer Tempest than this one (refuse-newer)."""


def sqlite_file_path(url: str) -> Path | None:
    """The on-disk file behind a sqlite URL, or None for :memory:/non-sqlite URLs."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    if parsed.database in (None, "", ":memory:"):
        return None
    assert parsed.database is not None
    return Path(parsed.database)


def check_not_newer(url: str) -> None:
    """Refuse a database stamped with a revision this app does not know — read-only, so the
    refused file (and its journal mode) is left byte-identical for the newer app that owns it."""
    path = sqlite_file_path(url)
    if path is None or not path.exists():
        return
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return  # unstamped legacy store — adopted and stamped by prepare_local_store
    finally:
        conn.close()
    if row is not None and str(row[0]) not in REVISION_CHAIN:
        raise NewerDatabaseError(
            f"database {path} is stamped with schema revision {row[0]!r}, which this version of "
            f"Tempest does not know (its newest is {HEAD_REVISION!r}). It was written by a newer "
            "Tempest. Update this app to open it; nothing has been modified."
        )


def install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """WAL journal mode on every connection — the local store is a concurrently-read desktop
    database, and WAL keeps readers unblocked during ingest writes. Foreign keys are enforced
    so ON DELETE CASCADE behaves exactly as it does on Postgres (budget pruning relies on it)."""

    if getattr(engine.sync_engine, "_tempest_pragmas_installed", False):
        return  # idempotent: the factory auto-installs; explicit callers must not double-hook
    engine.sync_engine._tempest_pragmas_installed = True  # type: ignore[attr-defined]

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _read_stamp(conn: sa.Connection) -> str | None:
    if not sa.inspect(conn).has_table("alembic_version"):
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    return None if row is None else str(row[0])


def _prepare(conn: sa.Connection) -> None:
    stamp = _read_stamp(conn)
    if stamp == HEAD_REVISION:
        return
    if stamp is None:
        # Fresh file — or an unstamped legacy store from ANY pre-Phase-11 era. Adoption must
        # not assume the schema equals head (review M3: an old-era store stamped head is
        # bricked forever — create_all never adds columns). Run every forward step
        # idempotently first: adding a column that exists fails cleanly and is skipped.
        if sa.inspect(conn).has_table("runs"):
            for statements in _FORWARD_STEPS.values():
                for statement in statements:
                    try:
                        conn.execute(text(statement))
                    except sa.exc.OperationalError as exc:  # duplicate column — already there
                        if "duplicate column" not in str(exc).lower():
                            raise
        Base.metadata.create_all(conn)
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": HEAD_REVISION},
        )
        return
    if stamp not in REVISION_CHAIN:  # defense in depth — check_not_newer runs first
        raise NewerDatabaseError(
            f"database is stamped {stamp!r}, unknown to this app (newest {HEAD_REVISION!r})"
        )
    for revision in REVISION_CHAIN[REVISION_CHAIN.index(stamp) : -1]:
        for statement in _FORWARD_STEPS[revision]:
            conn.execute(text(statement))
    conn.execute(text("UPDATE alembic_version SET version_num = :head"), {"head": HEAD_REVISION})


# FTS over divergences (Phase 11): an external-content FTS5 index kept in sync by triggers —
# ingest inserts index, budget-pruning cascade deletes de-index, no code path can forget.
# SQLite-only adjunct (Postgres searches with ILIKE); not part of the alembic chain, created
# idempotently on every open and rebuilt when adopted stores have unindexed rows.
_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS divergences_fts USING fts5("
    "detail, base_summary, head_summary, content='divergences', content_rowid='id')",
    "CREATE TRIGGER IF NOT EXISTS divergences_fts_ai AFTER INSERT ON divergences BEGIN "
    "INSERT INTO divergences_fts(rowid, detail, base_summary, head_summary) "
    "VALUES (new.id, new.detail, new.base_summary, new.head_summary); END",
    "CREATE TRIGGER IF NOT EXISTS divergences_fts_ad AFTER DELETE ON divergences BEGIN "
    "INSERT INTO divergences_fts(divergences_fts, rowid, detail, base_summary, head_summary) "
    "VALUES ('delete', old.id, old.detail, old.base_summary, old.head_summary); END",
)


def _ensure_fts(conn: sa.Connection) -> None:
    for statement in _FTS_DDL:
        conn.execute(text(statement))
    # COUNT(*) on an external-content FTS5 table reads the CONTENT table, so it can never see
    # missing index entries; the _docsize shadow table has one row per actually-indexed document.
    indexed = conn.execute(text("SELECT COUNT(*) FROM divergences_fts_docsize")).scalar()
    stored = conn.execute(text("SELECT COUNT(*) FROM divergences")).scalar()
    if indexed != stored:
        conn.execute(text("INSERT INTO divergences_fts(divergences_fts) VALUES ('rebuild')"))


async def prepare_local_store(engine: AsyncEngine) -> None:
    """Create, adopt, or forward-migrate the store — one transaction, so a failed migration
    leaves the previous schema intact (never corrupts)."""
    async with engine.begin() as conn:
        await conn.run_sync(_prepare)
        await conn.run_sync(_ensure_fts)
