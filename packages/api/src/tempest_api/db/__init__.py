"""Persistence layer: SQLAlchemy 2.x async models + engine/session wiring (master spec §7).

Local dev and tests run on aiosqlite; CI/prod run Postgres 16 (ADR-0009). JSON payload columns
are JSONB on Postgres and JSON elsewhere via a TypeDecorator. Schema changes ship as Alembic
migrations in `packages/api/alembic/`.
"""

from tempest_api.db.base import Base
from tempest_api.db.session import (
    DEFAULT_DATABASE_URL,
    create_engine_and_factory,
    database_url,
    get_session,
)
from tempest_api.db.types import JSONPayload

__all__ = [
    "DEFAULT_DATABASE_URL",
    "Base",
    "JSONPayload",
    "create_engine_and_factory",
    "database_url",
    "get_session",
]
