"""Structured-log shapes for the in-app viewer (Phase 17). Extras stay engine-side; the
viewer contract is the four core fields every record carries."""

from pydantic import BaseModel


class LogRecordOut(BaseModel):
    ts: str
    level: str
    component: str
    message: str
