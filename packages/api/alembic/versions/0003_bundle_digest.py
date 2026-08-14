"""Add bundle_digest to runs (ADR-0017, content-addressed bundle store).

The sha256 of the ingested `.tempest.zip`, referencing the blob in `<data_dir>/bundles/`.
Nullable: rows ingested before Phase 11 have no stored blob.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("bundle_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "bundle_digest")
