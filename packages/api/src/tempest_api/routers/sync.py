"""Sync endpoints (Phase 13): the presence primitive a pushing peer needs for delta-only
sync, and the push trigger the desktop/CLI calls against a configured team server."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.bundlestore import bundle_store
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
async def check_bundle_presence(body: BundlePresenceRequest) -> BundlePresenceResponse:
    """Which of these content digests this server's store already holds — the delta-only
    primitive: a pushing peer sends only what is missing."""
    held = bundle_store().digests()
    present = [d for d in body.digests if d in held]
    missing = [d for d in body.digests if d not in held]
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
