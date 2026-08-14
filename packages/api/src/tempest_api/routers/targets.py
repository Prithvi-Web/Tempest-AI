"""Target endpoints (master spec §8)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tempest_api import serialize
from tempest_api.db.models import Target
from tempest_api.db.session import get_session
from tempest_api.errors import ApiError, error_responses
from tempest_api.schemas import ErrorCode, TargetDetail

router = APIRouter(tags=["targets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/v1/targets/{target_id}", operation_id="getTarget", responses=error_responses(404, 422)
)
async def get_target(target_id: int, session: SessionDep) -> TargetDetail:
    target = await session.get(
        Target, target_id, options=[selectinload(Target.divergences)], populate_existing=True
    )
    if target is None:
        raise ApiError(
            404, ErrorCode.NOT_FOUND, f"target {target_id} does not exist", {"target_id": target_id}
        )
    return serialize.target_detail(target)
