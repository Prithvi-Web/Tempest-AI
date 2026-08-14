"""Error envelope (master spec §8): every non-2xx response body is `{error: {code, message,
details?}}` with a stable `ErrorCode`. Error messages are the product — always actionable."""

from typing import Any

from pydantic import BaseModel

from tempest_api.schemas.enums import ErrorCode


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody
