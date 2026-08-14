"""Dialect-aware column types (ADR-0009)."""

from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import JSON, TypeDecorator, TypeEngine


class JSONPayload(TypeDecorator[Any]):
    """JSONB on PostgreSQL, plain JSON everywhere else (aiosqlite in local dev/tests).

    One declared type, two renderings — the models never branch on dialect (ADR-0009).
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())
