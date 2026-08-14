"""Add sandbox_tier + sandbox_assurance to runs (ADR-0015, bundle schema v2).

The isolation tier a run used is surfaced in the UI so a degraded tier can never pass unnoticed.
Nullable: rows ingested from pre-v2 bundles simply have no recorded tier.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("sandbox_tier", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("sandbox_assurance", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "sandbox_assurance")
    op.drop_column("runs", "sandbox_tier")
