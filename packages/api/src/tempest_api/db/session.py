"""Async engine/session wiring.

DB URL comes from `TEMPEST_DATABASE_URL`; the default is a local aiosqlite file. Tests point it
at a temp file; CI/prod point it at Postgres 16 (ADR-0009).
"""

import os
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./tempest-dev.db"


def database_url() -> str:
    return os.environ.get("TEMPEST_DATABASE_URL", DEFAULT_DATABASE_URL)


def create_engine_and_factory(
    url: str | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url if url is not None else database_url())
    if engine.dialect.name == "sqlite":
        # Review C2: the prove-thread engine skipped the pragmas, leaving foreign_keys OFF —
        # budget pruning then orphaned targets/divergences/events silently. EVERY sqlite
        # engine gets WAL + FK enforcement here, not just the server's (ADR-0016).
        from tempest_api.db.local_store import install_sqlite_pragmas

        install_sqlite_pragmas(engine)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request; uncommitted work is discarded on exit,
    so a failed ingest writes nothing (BUNDLE_SCHEMA.md integrity, transactionally)."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with factory() as session:
        yield session
