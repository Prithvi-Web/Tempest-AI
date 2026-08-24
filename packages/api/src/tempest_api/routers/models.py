"""Local model catalogue and downloads (ADR-0080) — the boundary-A surface.

Thin by design, like `routers/agents.py`: shapes and rules live in `modeldownloads`; this file
is routing and error mapping. Literal routes are declared before `/{model_id}` so a catalogue
id can never shadow one.
"""

from typing import Any

from fastapi import APIRouter

from tempest_api import modeldownloads
from tempest_api.errors import ApiError, error_responses
from tempest_api.schemas import ErrorCode

router = APIRouter(tags=["models"])


def _reject(exc: modeldownloads.ModelDownloadRejected) -> ApiError:
    """A rejection carries its reason to the client verbatim: these strings are written to be
    read by a person, and flattening them into "bad request" throws away the only part that
    tells them what to do (L15.3, L23)."""
    return ApiError(400, ErrorCode.VALIDATION_ERROR, str(exc))


@router.get("/v1/models/catalog", operation_id="listModelCatalog")
async def list_model_catalog() -> list[dict[str, Any]]:
    """Every row, with `installed`, `freeBytes` and `fitsOnDisk` alongside — so the size and
    the room for it are on screen BEFORE the download starts (L21)."""
    return modeldownloads.catalogue()


@router.post(
    "/v1/models/{model_id}/download",
    operation_id="startModelDownload",
    responses=error_responses(400, 422),
)
async def start_model_download(model_id: str) -> dict[str, Any]:
    try:
        return modeldownloads.start(model_id)
    except modeldownloads.ModelDownloadRejected as exc:
        raise _reject(exc) from exc


@router.get(
    "/v1/models/{model_id}/download",
    operation_id="getModelDownloadStatus",
    responses=error_responses(400, 422),
)
async def get_model_download_status(model_id: str) -> dict[str, Any]:
    try:
        return modeldownloads.status(model_id)
    except modeldownloads.ModelDownloadRejected as exc:
        raise _reject(exc) from exc


@router.post(
    "/v1/models/{model_id}/download/cancel",
    operation_id="cancelModelDownload",
    responses=error_responses(400, 422),
)
async def cancel_model_download(model_id: str) -> dict[str, Any]:
    try:
        return modeldownloads.cancel(model_id)
    except modeldownloads.ModelDownloadRejected as exc:
        raise _reject(exc) from exc


@router.delete(
    "/v1/models/{model_id}", operation_id="removeModel", responses=error_responses(400, 422)
)
async def remove_model(model_id: str) -> dict[str, Any]:
    try:
        return modeldownloads.remove(model_id)
    except modeldownloads.ModelDownloadRejected as exc:
        raise _reject(exc) from exc
