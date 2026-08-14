"""Divergence endpoints (master spec §8), including the repro script download — the product
artifact a user re-runs themselves (Law L7)."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from tempest_api import serialize
from tempest_api.db.models import Divergence
from tempest_api.db.session import get_session
from tempest_api.errors import ApiError, error_responses
from tempest_api.schemas import DivergenceDetail, ErrorCode

router = APIRouter(tags=["divergences"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class PythonSourceResponse(PlainTextResponse):
    media_type = "text/x-python"


@router.get(
    "/v1/divergences/{divergence_id}",
    operation_id="getDivergence",
    responses=error_responses(404, 422),
)
async def get_divergence(divergence_id: int, session: SessionDep) -> DivergenceDetail:
    divergence = await _load(session, divergence_id)
    return serialize.divergence_detail(divergence)


@router.get(
    "/v1/divergences/{divergence_id}/repro.py",
    operation_id="getDivergenceRepro",
    response_class=PythonSourceResponse,
    responses=error_responses(404, 422),
)
async def get_divergence_repro(divergence_id: int, session: SessionDep) -> PythonSourceResponse:
    """The standalone reproduction script, byte-for-byte as the bundle carried it."""
    divergence = await _load(session, divergence_id)
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", divergence.repro_filename) or "repro.py"
    return PythonSourceResponse(
        divergence.repro_script,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _load(session: AsyncSession, divergence_id: int) -> Divergence:
    divergence = await session.get(
        Divergence,
        divergence_id,
        options=[joinedload(Divergence.target)],
        populate_existing=True,
    )
    if divergence is None:
        raise ApiError(
            404,
            ErrorCode.NOT_FOUND,
            f"divergence {divergence_id} does not exist",
            {"divergence_id": divergence_id},
        )
    return divergence
