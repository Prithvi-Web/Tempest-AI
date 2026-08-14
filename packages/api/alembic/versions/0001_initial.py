"""initial schema — repos, runs, targets, divergences, cassettes, run_events, api_tokens

Enum values and lengths are frozen here on purpose (migrations are history); the
migration/model parity test in packages/api/tests/test_migrations.py proves this file and the
SQLAlchemy models produce the same schema. Divergence evidence columns (minimized input, repro
script) are NOT NULL at the database level — BUNDLE_SCHEMA.md rule 1 as a constraint.

Revision ID: 0001
Revises:
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:  # type: ignore[type-arg]  # JSON payloads are untyped
    """JSONB on Postgres, JSON elsewhere — same rendering as tempest_api.db.types.JSONPayload."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _enum(*values: str) -> sa.Enum:
    return sa.Enum(*values, native_enum=False, create_constraint=False)


_RUN_STATUS = ("PENDING", "COMPLETE")
_VERDICT = ("DIVERGENT", "EQUIVALENT_UNDER_BUDGET", "UNPROVEN", "ERROR")
_LANG = ("PYTHON", "TYPESCRIPT")
_CLASSIFICATION = ("PURE_CANDIDATE", "IMPURE_RECORDABLE", "UNREACHABLE")
_REASON_CODE = (
    "TARGET_UNREACHABLE",
    "ENV_REPRODUCTION_FAILED",
    "HARNESS_SYNTHESIS_FAILED",
    "UNINTERCEPTABLE_EFFECT",
    "NONDETERMINISTIC_BASE",
    "SANDBOX_UNAVAILABLE",
    "VALUE_UNSERIALIZABLE",
    "RECORD_REPLAY_UNAVAILABLE",
)
_DIVERGENCE_CLASS = (
    "RETURN_VALUE",
    "EXCEPTION_TYPE",
    "EXCEPTION_MESSAGE",
    "EFFECT_SEQUENCE",
    "EFFECT_ARGUMENTS",
    "CASSETTE_MISS",
    "CRASH",
    "HANG",
    "OUTPUT_STREAM",
)
_SEVERITY = ("LOW", "NORMAL", "HEADLINE")


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.Integer(), sa.ForeignKey("repos.id"), nullable=False),
        sa.Column("base_sha", sa.String(length=40), nullable=False),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("status", _enum(*_RUN_STATUS), nullable=False),
        sa.Column("verdict", _enum(*_VERDICT), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("bundle_created_at", sa.Text(), nullable=True),
        sa.Column("base_deps", sa.Text(), nullable=True),
        sa.Column("head_deps", sa.Text(), nullable=True),
        sa.Column("budget_max_inputs", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_runs_repo_id", "runs", ["repo_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_verdict", "runs", ["verdict"])

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("qualname", sa.Text(), nullable=False),
        sa.Column("lang", _enum(*_LANG), nullable=False),
        sa.Column("classification", _enum(*_CLASSIFICATION), nullable=False),
        sa.Column("verdict", _enum(*_VERDICT), nullable=False),
        sa.Column("reason_code", _enum(*_REASON_CODE), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("inputs_run", sa.Integer(), nullable=False),
        sa.Column("equivalent_inputs", sa.Integer(), nullable=False),
        sa.Column("unprovable_inputs", sa.Integer(), nullable=False),
        sa.Column("changed_line_coverage", sa.Double(), nullable=False),
        sa.UniqueConstraint("run_id", "position", name="uq_targets_run_position"),
    )
    op.create_index("ix_targets_run_id", "targets", ["run_id"])

    op.create_table(
        "divergences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("divergence_class", _enum(*_DIVERGENCE_CLASS), nullable=False),
        sa.Column("severity", _enum(*_SEVERITY), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("args_literal", sa.Text(), nullable=False),
        sa.Column("kwargs_literal", sa.Text(), nullable=False),
        # BUNDLE_SCHEMA.md rule 1 as DDL: a divergence without evidence cannot be stored.
        sa.Column("minimized_args", sa.Text(), nullable=False),
        sa.Column("minimized_kwargs", sa.Text(), nullable=False),
        sa.Column("shrink_path", _json(), nullable=False),
        sa.Column("base_summary", sa.Text(), nullable=False),
        sa.Column("head_summary", sa.Text(), nullable=False),
        sa.Column("repro_filename", sa.Text(), nullable=False),
        sa.Column("repro_script", sa.Text(), nullable=False),
        sa.UniqueConstraint("target_id", "position", name="uq_divergences_target_position"),
    )
    op.create_index("ix_divergences_target_id", "divergences", ["target_id"])

    op.create_table(
        "cassettes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("ledger", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cassettes_run_id", "cassettes", ["run_id"])
    op.create_index("ix_cassettes_target_id", "cassettes", ["target_id"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_index("ix_run_events_run_id", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_cassettes_target_id", table_name="cassettes")
    op.drop_index("ix_cassettes_run_id", table_name="cassettes")
    op.drop_table("cassettes")
    op.drop_index("ix_divergences_target_id", table_name="divergences")
    op.drop_table("divergences")
    op.drop_index("ix_targets_run_id", table_name="targets")
    op.drop_table("targets")
    op.drop_index("ix_runs_verdict", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_repo_id", table_name="runs")
    op.drop_table("runs")
    op.drop_table("repos")
