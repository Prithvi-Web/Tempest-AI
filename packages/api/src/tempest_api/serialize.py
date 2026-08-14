"""Row → schema mapping. One place, so every endpoint serves identical shapes for the same row.

Functions that walk relationships require them eagerly loaded (selectinload/joined) — the async
session never lazy-loads mid-serialization.
"""

import json

from tempest_api.db.models import Divergence, Run, RunEvent, Target
from tempest_api.schemas import (
    DivergenceDetail,
    DivergenceSummary,
    RunDetail,
    RunEventOut,
    RunSummary,
    TargetDetail,
    TargetSummary,
)


def run_event(event: RunEvent) -> RunEventOut:
    """`stage`/`level`/`message` come from the payload when present (every ledger-written row);
    rows from before the ledger helper fall back to the event type and a stable payload dump."""
    payload = event.payload
    stage = payload.get("stage")
    level = payload.get("level")
    message = payload.get("message")
    return RunEventOut(
        ts=event.created_at,
        stage=stage if isinstance(stage, str) else event.event_type,
        level=level if isinstance(level, str) else "info",
        message=message if isinstance(message, str) else json.dumps(payload, sort_keys=True),
    )


def divergence_summary(d: Divergence) -> DivergenceSummary:
    return DivergenceSummary(
        id=d.id,
        target_id=d.target_id,
        divergence_class=d.divergence_class,
        severity=d.severity,
        detail=d.detail,
        minimized_args=d.minimized_args,
        minimized_kwargs=d.minimized_kwargs,
    )


def divergence_detail(d: Divergence) -> DivergenceDetail:
    """Requires `d.target` loaded (for run_id)."""
    return DivergenceDetail(
        **divergence_summary(d).model_dump(),
        run_id=d.target.run_id,
        args_literal=d.args_literal,
        kwargs_literal=d.kwargs_literal,
        shrink_path=list(d.shrink_path),
        base_summary=d.base_summary,
        head_summary=d.head_summary,
        repro_filename=d.repro_filename,
    )


def target_summary(target: Target) -> TargetSummary:
    """Requires `target.divergences` loaded."""
    return TargetSummary(
        id=target.id,
        run_id=target.run_id,
        file_path=target.file_path,
        module=target.module,
        qualname=target.qualname,
        lang=target.lang,
        classification=target.classification,
        verdict=target.verdict,
        reason_code=target.reason_code,
        changed_line_coverage=target.changed_line_coverage,
        divergence_count=len(target.divergences),
    )


def target_detail(target: Target) -> TargetDetail:
    """Requires `target.divergences` loaded."""
    return TargetDetail(
        **target_summary(target).model_dump(),
        reason_detail=target.reason_detail,
        inputs_run=target.inputs_run,
        equivalent_inputs=target.equivalent_inputs,
        unprovable_inputs=target.unprovable_inputs,
        divergences=[divergence_summary(d) for d in target.divergences],
    )


def run_summary(run: Run, target_count: int, divergence_count: int) -> RunSummary:
    return RunSummary(
        id=run.id,
        repo=run.repo.name,
        base_sha=run.base_sha,
        head_sha=run.head_sha,
        status=run.status,
        verdict=run.verdict,
        created_at=run.created_at,
        target_count=target_count,
        divergence_count=divergence_count,
    )


def run_detail(run: Run) -> RunDetail:
    """Requires `run.targets` and each target's `divergences` loaded."""
    targets = [target_summary(t) for t in run.targets]
    summary = run_summary(
        run,
        target_count=len(targets),
        divergence_count=sum(t.divergence_count for t in targets),
    )
    return RunDetail(
        **summary.model_dump(),
        schema_version=run.schema_version,
        engine_version=run.engine_version,
        bundle_created_at=run.bundle_created_at,
        base_deps=run.base_deps,
        head_deps=run.head_deps,
        budget_max_inputs=run.budget_max_inputs,
        sandbox_tier=run.sandbox_tier,
        sandbox_assurance=run.sandbox_assurance,
        targets=targets,
    )
