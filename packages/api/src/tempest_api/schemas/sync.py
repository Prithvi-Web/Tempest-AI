"""Sync shapes (Phase 13). The report is honest arithmetic: pushed + skipped + failed +
remaining always accounts for every candidate bundle the local store holds."""

from pydantic import BaseModel, Field


class BundlePresenceRequest(BaseModel):
    digests: list[str] = Field(max_length=1000)


class BundlePresenceResponse(BaseModel):
    present: list[str]
    missing: list[str]


class SyncPushRequest(BaseModel):
    server_url: str = Field(min_length=1, max_length=2000)


class SyncReport(BaseModel):
    candidates: int
    pushed: int
    skipped: int
    failed: int
    remaining: int
    errors: list[str]
