"""API-owned enums. Engine vocabulary (`Verdict`, `DivergenceClass`, `ReasonCode`, …) is defined
once in `tempest.model` and must be imported from there — never redefined here (CLAUDE.md §9).
"""

from enum import StrEnum


class RunStatus(StrEnum):
    """Run lifecycle. This phase reaches PENDING (created) and COMPLETE (bundle ingested);
    orchestration states are added — deliberately breaking the generated TS — when arq lands."""

    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


class ErrorCode(StrEnum):
    """Stable machine-readable codes for the `{error: {code, message, details?}}` envelope.
    Renderers switch on these; the strings are frozen."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RUN_NOT_PENDING = "RUN_NOT_PENDING"
    BUNDLE_INVALID = "BUNDLE_INVALID"
    BUNDLE_SCHEMA_UNSUPPORTED = "BUNDLE_SCHEMA_UNSUPPORTED"
    BUNDLE_MISMATCH = "BUNDLE_MISMATCH"
    INTERNAL = "INTERNAL"
