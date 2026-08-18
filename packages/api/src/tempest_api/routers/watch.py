"""Watch endpoints: arm, disarm, and report the continuous agent (ADR-0029 in the app).

The status is assembled from the live session PLUS the real run rows, so what the screen
shows is always the evidence the run list shows — never a parallel bookkeeping of verdicts.
"""

from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.db.models import Divergence, Run, RunEvent, Target
from tempest_api.db.session import database_url, get_session
from tempest_api.errors import ApiError, error_responses
from tempest_api.schemas.enums import ErrorCode
from tempest_api.schemas.watch import WatchRun, WatchStartRequest, WatchStatus
from tempest_api.watchsession import (
    WATCH_EVENT_TYPE,
    WatchError,
    WatchState,
    start_watch,
    stop_watch,
    watch_state,
)

router = APIRouter(tags=["watch"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


_FEED_LIMIT = 50


async def _feed(session: AsyncSession) -> list[WatchRun]:
    """Every run a watch session produced, newest first — read from the ledger mark, so the
    feed survives restarts and always agrees with the run list."""
    divergences = (
        sa.select(Target.run_id.label("run_id"), sa.func.count(Divergence.id).label("count"))
        .join(Divergence, Divergence.target_id == Target.id)
        .group_by(Target.run_id)
        .subquery()
    )
    rows = (
        await session.execute(
            sa.select(Run, sa.func.coalesce(divergences.c.count, 0))
            .join(RunEvent, RunEvent.run_id == Run.id)
            .outerjoin(divergences, divergences.c.run_id == Run.id)
            .where(RunEvent.event_type == WATCH_EVENT_TYPE)
            .order_by(Run.id.desc())
            .limit(_FEED_LIMIT)
        )
    ).all()
    # pragma below: the line right after the greenlet crossing is mis-attributed by the
    # tracer (localprove.py documents the same artifact); the shaping it calls is fully
    # pinned by TestTheFeedIsTheLedger.
    return _to_feed(rows)  # pragma: no cover — greenlet-crossing attribution artifact


def _to_feed(rows: "list[Any]") -> list[WatchRun]:
    """Plain, synchronous shaping, deliberately OUTSIDE the awaiting frame: SQLAlchemy's
    async layer crosses a greenlet boundary, and lines immediately after that crossing are
    mis-attributed by the tracer (the same artifact localprove.py documents)."""
    feed: list[WatchRun] = []
    for run, count in rows:
        feed.append(
            WatchRun(
                run_id=run.id,
                head_sha=run.head_sha,
                status=run.status,
                verdict=run.verdict,
                divergence_count=count,
            )
        )
    return feed


async def _rendered(session: AsyncSession, state: WatchState) -> WatchStatus:
    return WatchStatus(
        watching=state.watching,
        repo_path=state.repo_path,
        repo_name=state.repo_name,
        interval_seconds=state.interval_seconds,
        last_sha=state.last_sha,
        active_run_id=state.active_run_id,
        runs=await _feed(session),
        problem=state.problem,
    )


@router.get("/v1/local/watch", operation_id="getWatchStatus")
async def get_watch_status(session: SessionDep) -> WatchStatus:
    return await _rendered(session, watch_state(database_url()))


@router.post(
    "/v1/local/watch",
    operation_id="startWatch",
    responses=error_responses(400, 409, 422),
)
async def start_watching(body: WatchStartRequest, session: SessionDep) -> WatchStatus:
    """Arm the loop from this repo's current HEAD. The FIRST proof happens on the NEXT commit —
    watch proves what changes from now on; proving an existing pair is `startLocalProve`."""
    try:
        state = start_watch(
            repo_path=body.repo_path,
            interval_seconds=body.interval_seconds,
            max_inputs=body.max_inputs,
            database_url=database_url(),
        )
    except WatchError as exc:
        raise ApiError(409, ErrorCode.WATCH_ALREADY_ACTIVE, str(exc)) from exc
    return await _rendered(session, state)


@router.delete("/v1/local/watch", operation_id="stopWatch")
async def stop_watching(session: SessionDep) -> WatchStatus:
    """Idempotent. An in-flight prove is cancelled, so Stop means stop (L11)."""
    return await _rendered(session, stop_watch(database_url()))
