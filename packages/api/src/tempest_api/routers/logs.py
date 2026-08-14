"""In-app log viewer endpoint (Phase 17): the sidecar serves its own structured log
(`tempest.obslog`, rotation-aware, newest last). Local data about Tempest itself — never
user source; the diagnostic-bundle path re-redacts before anything is shareable."""

from typing import Annotated

from fastapi import APIRouter, Query

from tempest.obslog import read_records
from tempest_api.errors import error_responses
from tempest_api.schemas.logs import LogRecordOut

router = APIRouter(tags=["logs"])


@router.get("/v1/logs", operation_id="listLogs", responses=error_responses(422))
async def list_logs(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    level: Annotated[str | None, Query()] = None,
) -> list[LogRecordOut]:
    """Recent engine/sidecar log records, newest last; `level` is a minimum severity."""
    try:
        records = read_records(limit=limit, level=level)
    except ValueError:
        records = []  # unknown level names are a filter miss, not a 500
    return [
        LogRecordOut(
            ts=str(record.get("ts", "")),
            level=str(record.get("level", "")),
            component=str(record.get("component", "")),
            message=str(record.get("message", "")),
        )
        for record in records
    ]
