"""Sync endpoints (Phase 13): the presence primitive a pushing peer needs for delta-only
sync, and the push trigger the desktop/CLI calls against a configured team server."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.bundlestore import bundle_store
from tempest_api.db.models import Run
from tempest_api.db.session import get_session
from tempest_api.errors import error_responses
from tempest_api.schemas.sync import (
    BundlePresenceRequest,
    BundlePresenceResponse,
    SyncPushRequest,
    SyncReport,
)
from tempest_api.sync import push_all

router = APIRouter(tags=["sync"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/v1/bundles/presence",
    operation_id="checkBundlePresence",
    responses=error_responses(422),
)
async def check_bundle_presence(
    body: BundlePresenceRequest, session: SessionDep
) -> BundlePresenceResponse:
    """Which of these content digests this server can actually SERVE — the delta-only
    primitive. Present means a committed run row AND the blob on disk (review M4: a crash
    between blob write and commit must not make peers skip the bundle forever; a lost blob
    must invite a re-push so the import path can heal it)."""
    rows = set(
        (
            await session.execute(
                sa.select(Run.bundle_digest).where(Run.bundle_digest.in_(body.digests))
            )
        )
        .scalars()
        .all()
    )
    held = bundle_store().digests()
    present = [d for d in body.digests if d in rows and d in held]
    missing = [d for d in body.digests if d not in rows or d not in held]
    return BundlePresenceResponse(present=present, missing=missing)


@router.post(
    "/v1/sync/push",
    operation_id="syncPush",
    responses=error_responses(422),
)
async def sync_push(body: SyncPushRequest, session: SessionDep) -> SyncReport:
    """Push every local bundle the server lacks. Never raises on an unreachable server —
    the report says what remains queued (the store is the durable queue)."""
    return await push_all(session, body.server_url)
