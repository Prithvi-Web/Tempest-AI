"""Watch-mode shapes (ADR-0029 in the app): the continuous agent's live state.

A watched commit produces an ORDINARY run, so this surface deliberately carries no verdicts
of its own — it carries run ids, and the runs carry the evidence. One source of truth (L1).
"""

from pydantic import BaseModel, Field

from tempest.model import Verdict
from tempest_api.schemas.enums import RunStatus


class WatchStartRequest(BaseModel):
    repo_path: str = Field(min_length=1)
    interval_seconds: float = Field(default=15.0, ge=1.0, le=3600.0)
    max_inputs: int = Field(default=300, ge=1)


class WatchRun(BaseModel):
    """One proven commit in this session, read back from its run row."""

    run_id: int
    head_sha: str
    status: RunStatus
    verdict: Verdict | None
    divergence_count: int


class WatchStatus(BaseModel):
    watching: bool
    repo_path: str | None
    repo_name: str | None
    interval_seconds: float
    last_sha: str | None
    active_run_id: int | None
    runs: list[WatchRun]
    problem: str | None
