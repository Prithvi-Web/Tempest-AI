"""Pydantic schemas — the single source of truth for every shape the frontend sees (CLAUDE.md §9).

Engine enums are NOT defined here; they live in `tempest.model` (one Python definition) and are
exported through OpenAPI wherever a schema references them. API-owned enums (`RunStatus`,
`ErrorCode`) live in `tempest_api.schemas.enums`.
"""

from tempest_api.schemas.divergences import DivergenceDetail, DivergenceSummary
from tempest_api.schemas.enums import ErrorCode, RunStatus
from tempest_api.schemas.errors import ErrorBody, ErrorEnvelope
from tempest_api.schemas.events import RunEventOut
from tempest_api.schemas.health import HealthResponse
from tempest_api.schemas.local import LocalProveRequest
from tempest_api.schemas.pagination import Page, decode_cursor, encode_cursor
from tempest_api.schemas.runs import CancelAccepted, RunCreate, RunCreated, RunDetail, RunSummary
from tempest_api.schemas.settings import (
    AiKeyTestResult,
    DiagnosticBundle,
    EnvOverride,
    SettingsIn,
    SettingsOut,
)
from tempest_api.schemas.targets import TargetDetail, TargetSummary
from tempest_api.schemas.watch import WatchRun, WatchStartRequest, WatchStatus

__all__ = [
    "AiKeyTestResult",
    "CancelAccepted",
    "DiagnosticBundle",
    "DivergenceDetail",
    "DivergenceSummary",
    "EnvOverride",
    "ErrorBody",
    "ErrorCode",
    "ErrorEnvelope",
    "HealthResponse",
    "LocalProveRequest",
    "Page",
    "RunCreate",
    "RunCreated",
    "RunDetail",
    "RunEventOut",
    "RunStatus",
    "RunSummary",
    "SettingsIn",
    "SettingsOut",
    "TargetDetail",
    "TargetSummary",
    "WatchRun",
    "WatchStartRequest",
    "WatchStatus",
    "decode_cursor",
    "encode_cursor",
]
