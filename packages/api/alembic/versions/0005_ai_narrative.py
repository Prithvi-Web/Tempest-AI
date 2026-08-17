"""Add divergences.ai_narrative (ADR-0029, HANDOFF-WORLD-CLASS 2.4).

Nullable BY DESIGN: the narrative is a readability layer generated from the evidence by
the user's own model (BYOK) — keyless runs store NULL and lose nothing verdict-bearing.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("divergences", sa.Column("ai_narrative", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("divergences", "ai_narrative")
