"""Widen runs.status for the CANCELLED lifecycle state (L11 cancel, Phase 11).

VARCHAR-backed enums size to their longest member; adding CANCELLED (9 chars) grows the
declared width past the frozen 0001 definition. Values here are frozen strings on purpose
(migrations are history). SQLite's local store skips this as a no-op — its type affinity
ignores VARCHAR widths — see `db.local_store._FORWARD_STEPS`.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _enum(*values: str) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, create_constraint=False)


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "status",
            type_=_enum("PENDING", "COMPLETE", "CANCELLED"),
            existing_type=_enum("PENDING", "COMPLETE"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "status",
            type_=_enum("PENDING", "COMPLETE"),
            existing_type=_enum("PENDING", "COMPLETE", "CANCELLED"),
            existing_nullable=False,
        )
