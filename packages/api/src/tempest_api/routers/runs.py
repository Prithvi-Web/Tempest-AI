"""Run endpoints (master spec §8): create (idempotent), list (cursor pagination), detail,
and bundle upload."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tempest.model import Verdict
from tempest_api import serialize
from tempest_api.bundlestore import bundle_store
from tempest_api.db.models import Divergence, Repo, Run, RunEvent, Target
from tempest_api.db.session import get_session
from tempest_api.errors import ApiError, error_responses
from tempest_api.ingest import ingest_zip_bytes, parse_bundle_zip
from tempest_api.ledger import append_run_event
from tempest_api.schemas import (
    ErrorCode,
    Page,
    RunCreate,
    RunCreated,
    RunDetail,
    RunEventOut,
    RunStatus,
    RunSummary,
    decode_cursor,
    encode_cursor,
)

router = APIRouter(tags=["runs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
IdempotencyKeyDep = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        max_length=200,
        description="Replaying the same key with the same body returns the original run_id.",
    ),
]

_TARGET_COUNT = (
    select(func.count(Target.id)).where(Target.run_id == Run.id).correlate(Run).scalar_subquery()
)
_DIVERGENCE_COUNT = (
    select(func.count(Divergence.id))
    .join(Target, Divergence.target_id == Target.id)
    .where(Target.run_id == Run.id)
    .correlate(Run)
    .scalar_subquery()
)


@router.post(
    "/v1/runs",
    status_code=202,
    operation_id="createRun",
    responses=error_responses(409, 422),
)
async def create_run(
    body: RunCreate, session: SessionDep, idempotency_key: IdempotencyKeyDep = None
) -> RunCreated:
    """Create a pending run; the CLI uploads its bundle to it afterwards. Returns 202."""
    if idempotency_key is not None:
        existing = await session.scalar(select(Run).where(Run.idempotency_key == idempotency_key))
        if existing is not None:
            return _replay_or_conflict(existing, body, idempotency_key)
    repo = await get_or_create_repo(session, body.repo)
    run = Run(
        repo_id=repo.id,
        base_sha=body.base_sha,
        head_sha=body.head_sha,
        status=RunStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    session.add(run)
    try:
        await session.flush()
        await append_run_event(
            session,
            run.id,
            "run.created",
            stage="created",
            message=(
                f"run created for {body.repo}: "
                f"{body.base_sha[:12]}..{body.head_sha[:12]} awaiting its bundle"
            ),
            extra={"repo": body.repo, "base_sha": body.base_sha, "head_sha": body.head_sha},
        )
        await session.commit()
    except IntegrityError:
        # Concurrent request landed the same idempotency key first: replay its outcome.
        await session.rollback()
        existing = await session.scalar(select(Run).where(Run.idempotency_key == idempotency_key))
        if existing is None or idempotency_key is None:
            raise
        return _replay_or_conflict(existing, body, idempotency_key)
    return RunCreated(run_id=run.id)


def _replay_or_conflict(existing: Run, body: RunCreate, idempotency_key: str) -> RunCreated:
    same_request = (
        existing.repo.name == body.repo
        and existing.base_sha == body.base_sha
        and existing.head_sha == body.head_sha
    )
    if same_request:
        return RunCreated(run_id=existing.id)
    raise ApiError(
        409,
        ErrorCode.IDEMPOTENCY_CONFLICT,
        f"Idempotency-Key {idempotency_key!r} was already used for a different run request — "
        "use a fresh key per distinct run",
        {"existing_run_id": existing.id},
    )


async def get_or_create_repo(session: AsyncSession, name: str) -> Repo:
    repo = await session.scalar(select(Repo).where(Repo.name == name))
    if repo is not None:
        return repo
    repo = Repo(name=name)
    session.add(repo)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        repo = await session.scalar(select(Repo).where(Repo.name == name))
        if repo is None:
            raise
    return repo


@router.get("/v1/runs", operation_id="listRuns", responses=error_responses(400, 422))
async def list_runs(
    session: SessionDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    status: RunStatus | None = None,
    verdict: Verdict | None = None,
) -> Page[RunSummary]:
    """Newest-first run listing. Each run appears exactly once across a cursor walk."""
    stmt = select(Run, _TARGET_COUNT, _DIVERGENCE_COUNT).order_by(Run.id.desc()).limit(limit + 1)
    if cursor is not None:
        try:
            stmt = stmt.where(Run.id < decode_cursor(cursor))
        except ValueError as exc:
            raise ApiError(400, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    if status is not None:
        stmt = stmt.where(Run.status == status)
    if verdict is not None:
        stmt = stmt.where(Run.verdict == verdict)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        serialize.run_summary(run, target_count=tc, divergence_count=dc) for run, tc, dc in rows
    ]
    next_cursor = encode_cursor(items[-1].id) if has_more else None
    return Page[RunSummary](items=items, next_cursor=next_cursor)


@router.get("/v1/runs/{run_id}", operation_id="getRun", responses=error_responses(404, 422))
async def get_run(run_id: int, session: SessionDep) -> RunDetail:
    run = await _load_run_with_children(session, run_id)
    return serialize.run_detail(run)


@router.get(
    "/v1/runs/{run_id}/events",
    operation_id="listRunEvents",
    responses=error_responses(404, 422),
)
async def list_run_events(run_id: int, session: SessionDep) -> list[RunEventOut]:
    """The run's lifecycle ledger, oldest first, as plain JSON — the desktop polls this beside
    run status. (Not SSE; a streaming endpoint arrives with the orchestration phase.)"""
    if await session.get(Run, run_id) is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"run {run_id} does not exist", {"run_id": run_id})
    events = await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    )
    return [serialize.run_event(e) for e in events]


@router.post(
    "/v1/runs/import",
    operation_id="importRunBundle",
    responses=error_responses(400, 422),
)
async def import_run_bundle(file: UploadFile, session: SessionDep) -> RunDetail:
    """Import a portable `.tempest.zip` produced elsewhere: repo + run are created from the
    manifest, then the bundle takes the exact upload ingestion path. Idempotent by content —
    re-importing the same bytes returns the run that already holds them."""
    data = await file.read()
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(select(Run).where(Run.bundle_digest == digest))
    if existing is not None:
        return serialize.run_detail(await _load_run_with_children(session, existing.id))
    bundle = parse_bundle_zip(data)  # 400 BUNDLE_INVALID on non-bundles, before any row
    manifest = bundle.manifest
    repo = await get_or_create_repo(session, manifest.repo)
    run = Run(
        repo_id=repo.id,
        base_sha=manifest.base_sha,
        head_sha=manifest.head_sha,
        status=RunStatus.PENDING,
    )
    session.add(run)
    await session.flush()
    await append_run_event(
        session,
        run.id,
        "run.imported",
        stage="created",
        message=f"run imported from {file.filename or 'a .tempest bundle'} ({manifest.repo})",
        extra={"repo": manifest.repo, "digest": digest},
    )
    await ingest_zip_bytes(session, run, data)
    await session.commit()
    return serialize.run_detail(await _load_run_with_children(session, run.id))


@router.get(
    "/v1/runs/{run_id}/bundle",
    operation_id="exportRunBundle",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}},
        **error_responses(404, 422),
    },
)
async def export_run_bundle(run_id: int, session: SessionDep) -> Response:
    """Hand back the run's `.tempest.zip` byte-identical to what was ingested (L7) — the
    portable artifact another Tempest imports with POST /v1/runs/import."""
    run = await session.get(Run, run_id)
    if run is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"run {run_id} does not exist", {"run_id": run_id})
    if run.bundle_digest is None:
        raise ApiError(
            404,
            ErrorCode.NOT_FOUND,
            f"run {run_id} has no stored bundle — it is still pending, or was ingested before "
            "the bundle store existed (re-prove it to make it exportable)",
            {"run_id": run_id},
        )
    try:
        data = bundle_store().get(run.bundle_digest)
    except KeyError:
        raise ApiError(
            404,
            ErrorCode.NOT_FOUND,
            f"run {run_id}'s bundle blob is missing from the store (digest "
            f"{run.bundle_digest[:12]}…) — it may have been removed from disk externally",
            {"run_id": run_id, "digest": run.bundle_digest},
        ) from None
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="run-{run_id}.tempest.zip"'},
    )


@router.post(
    "/v1/runs/{run_id}/bundle",
    operation_id="uploadRunBundle",
    responses=error_responses(400, 404, 409, 422),
)
async def upload_run_bundle(run_id: int, file: UploadFile, session: SessionDep) -> RunDetail:
    """Ingest a CLI-produced `.tempest.zip` (multipart field `file`) into this pending run.
    Rejected bundles write nothing; the fan-out is one transaction."""
    run = await session.get(Run, run_id)
    if run is None:
        raise ApiError(
            404,
            ErrorCode.NOT_FOUND,
            f"run {run_id} does not exist — create it "
            "with POST /v1/runs before uploading its bundle",
            {"run_id": run_id},
        )
    await ingest_zip_bytes(session, run, await file.read())
    await session.commit()
    return serialize.run_detail(await _load_run_with_children(session, run_id))


async def _load_run_with_children(session: AsyncSession, run_id: int) -> Run:
    run = await session.get(
        Run,
        run_id,
        options=[selectinload(Run.targets).selectinload(Target.divergences)],
        populate_existing=True,
    )
    if run is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"run {run_id} does not exist", {"run_id": run_id})
    return run
