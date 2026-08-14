"""Tables per master spec §7: repos, runs, targets, divergences, cassettes, run_events, api_tokens.

Integrity is a schema property, not a code comment (BUNDLE_SCHEMA.md rule 1): every divergence row
carries NOT NULL minimized input columns and a NOT NULL repro script — the database refuses
anything less, mirroring the bundle writer.

Engine enums (`Verdict`, `DivergenceClass`, …) are imported from `tempest.model` — the single
Python definition (CLAUDE.md §9). They are stored as VARCHAR (`native_enum=False`) so SQLite and
Postgres render identically. API-lifecycle enums (`RunStatus`) live in `tempest_api.schemas`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Double, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tempest.model import (
    DivergenceClass,
    Lang,
    ReasonCode,
    Severity,
    TargetClassification,
    Verdict,
)
from tempest_api.db.base import Base
from tempest_api.db.types import JSONPayload
from tempest_api.schemas.enums import RunStatus


def utcnow() -> datetime:
    """Naive UTC timestamp — stored identically on SQLite and Postgres (ADR-0009)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _enum(enum_cls: type[StrEnum]) -> Enum:
    """VARCHAR-backed enum column; member names == values for every Tempest enum."""
    return Enum(enum_cls, native_enum=False, create_constraint=False)


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    runs: Mapped[list[Run]] = relationship(back_populates="repo")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id"), index=True)
    base_sha: Mapped[str] = mapped_column(String(40))
    head_sha: Mapped[str] = mapped_column(String(40))
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), index=True)
    verdict: Mapped[Verdict | None] = mapped_column(_enum(Verdict), index=True)
    # Manifest fields — null until a bundle is ingested; stored verbatim, never re-derived.
    schema_version: Mapped[int | None] = mapped_column(Integer)
    engine_version: Mapped[str | None] = mapped_column(Text)
    bundle_created_at: Mapped[str | None] = mapped_column(Text)
    base_deps: Mapped[str | None] = mapped_column(Text)
    head_deps: Mapped[str | None] = mapped_column(Text)
    budget_max_inputs: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    repo: Mapped[Repo] = relationship(back_populates="runs", lazy="joined", innerjoin=True)
    targets: Mapped[list[Target]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Target.position",
    )
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RunEvent.seq",
    )


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("run_id", "position", name="uq_targets_run_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # bundle order — round-trips exactly
    file_path: Mapped[str] = mapped_column(Text)
    module: Mapped[str] = mapped_column(Text)
    qualname: Mapped[str] = mapped_column(Text)
    lang: Mapped[Lang] = mapped_column(_enum(Lang))
    classification: Mapped[TargetClassification] = mapped_column(_enum(TargetClassification))
    verdict: Mapped[Verdict] = mapped_column(_enum(Verdict))
    reason_code: Mapped[ReasonCode | None] = mapped_column(_enum(ReasonCode))
    reason_detail: Mapped[str | None] = mapped_column(Text)
    inputs_run: Mapped[int] = mapped_column(Integer)
    equivalent_inputs: Mapped[int] = mapped_column(Integer)
    unprovable_inputs: Mapped[int] = mapped_column(Integer)
    changed_line_coverage: Mapped[float] = mapped_column(Double)

    run: Mapped[Run] = relationship(back_populates="targets")
    divergences: Mapped[list[Divergence]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Divergence.position",
    )


class Divergence(Base):
    """One observed behavior difference. The minimized input and the repro script are NOT NULL
    at the database level — a divergence without its evidence cannot be stored (Law L1)."""

    __tablename__ = "divergences"
    __table_args__ = (
        UniqueConstraint("target_id", "position", name="uq_divergences_target_position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    divergence_class: Mapped[DivergenceClass] = mapped_column(_enum(DivergenceClass))
    severity: Mapped[Severity] = mapped_column(_enum(Severity))
    detail: Mapped[str] = mapped_column(Text)
    args_literal: Mapped[str] = mapped_column(Text)
    kwargs_literal: Mapped[str] = mapped_column(Text)
    minimized_args: Mapped[str] = mapped_column(Text, nullable=False)
    minimized_kwargs: Mapped[str] = mapped_column(Text, nullable=False)
    shrink_path: Mapped[list[str]] = mapped_column(JSONPayload)
    base_summary: Mapped[str] = mapped_column(Text)
    head_summary: Mapped[str] = mapped_column(Text)
    repro_filename: Mapped[str] = mapped_column(Text, nullable=False)
    repro_script: Mapped[str] = mapped_column(Text, nullable=False)

    target: Mapped[Target] = relationship(back_populates="divergences")


class Cassette(Base):
    """Determinism-layer interaction ledger (master spec §7). v1 bundles do not carry cassettes
    yet — ingestion populates this table once Phase 2 cassettes reach the bundle schema."""

    __tablename__ = "cassettes"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(Text)
    ledger: Mapped[list[dict[str, Any]]] = mapped_column(JSONPayload)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RunEvent(Base):
    """Append-only run lifecycle ledger; the SSE stream (later phase) replays these rows."""

    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONPayload)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[Run] = relationship(back_populates="events")


class ApiToken(Base):
    """PAT-style CLI tokens, hashed at rest (ADR-0007). Issuance endpoints land with the auth
    phase; the table is part of the §7 schema."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
