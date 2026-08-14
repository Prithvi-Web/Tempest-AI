from fastapi import APIRouter

import tempest
from tempest.model import BUNDLE_SCHEMA_VERSION
from tempest_api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/v1/health", operation_id="getHealth")
async def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        engine_version=tempest.__version__,
        schema_version=BUNDLE_SCHEMA_VERSION,
    )
