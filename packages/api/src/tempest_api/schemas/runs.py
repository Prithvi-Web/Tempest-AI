"""Run shapes (master spec §8). Manifest fields (docs/BUNDLE_SCHEMA.md) are null until a bundle
is ingested and are stored/served verbatim — the API never re-derives a verdict (Law L2)."""

from datetime import datetime

from pydantic import BaseModel, Field

from tempest.model import Verdict
from tempest_api.schemas.enums import RunStatus
from tempest_api.schemas.targets import TargetSummary

_SHA_PATTERN = r"^[0-9a-f]{40}$"


class RunCreate(BaseModel):
    repo: str = Field(min_length=1, max_length=200)
    base_sha: str = Field(pattern=_SHA_PATTERN)
    head_sha: str = Field(pattern=_SHA_PATTERN)


class RunCreated(BaseModel):
    run_id: int


class CancelAccepted(BaseModel):
    """202 for cancelRun: children are already signalled; the run lands in CANCELLED."""

    run_id: int
    cancelling: bool


class RunSummary(BaseModel):
    id: int
    repo: str
    base_sha: str
    head_sha: str
    status: RunStatus
    verdict: Verdict | None
    created_at: datetime
    target_count: int
    divergence_count: int


class RunDetail(RunSummary):
    schema_version: int | None
    engine_version: str | None
    bundle_created_at: str | None
    base_deps: str | None
    head_deps: str | None
    budget_max_inputs: int | None
    sandbox_tier: str | None
    sandbox_assurance: str | None
    targets: list[TargetSummary]
