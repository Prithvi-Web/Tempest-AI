"""Append-only `run_events` writer — the one place a ledger row is shaped.

Every event's payload carries `{stage, level, message}` (what the polled `listRunEvents`
endpoint renders) plus any machine-readable extras. Sequence numbers are per-run max+1;
writers for one run are sequential (the creating request first, then the single registered
prove thread or upload request), so the read-then-insert cannot race itself.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.db.models import RunEvent


async def append_run_event(
    session: AsyncSession,
    run_id: int,
    event_type: str,
    *,
    stage: str,
    message: str,
    level: str = "info",
    extra: dict[str, Any] | None = None,
) -> None:
    """Add the next ledger row for `run_id` to `session`; the caller commits."""
    next_seq = await session.scalar(
        select(func.coalesce(func.max(RunEvent.seq), 0) + 1).where(RunEvent.run_id == run_id)
    )
    payload: dict[str, Any] = {"stage": stage, "level": level, "message": message}
    if extra:
        payload.update(extra)
    session.add(
        RunEvent(
            run_id=run_id,
            seq=next_seq if next_seq is not None else 1,
            event_type=event_type,
            payload=payload,
        )
    )
