"""API-owned enums. Engine vocabulary (`Verdict`, `DivergenceClass`, `ReasonCode`, …) is defined
once in `tempest.model` and must be imported from there — never redefined here (CLAUDE.md §9).
"""

from enum import StrEnum


class RunStatus(StrEnum):
    """Run lifecycle. PENDING (created) → COMPLETE (bundle ingested), or CANCELLED (the user
    stopped the prove — honest terminal state, no verdict ever claimed, L2/L11); further
    orchestration states are added — deliberately breaking the generated TS — when arq lands."""

    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


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
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    REF_NOT_FOUND = "REF_NOT_FOUND"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    WATCH_ALREADY_ACTIVE = "WATCH_ALREADY_ACTIVE"
    INTERNAL = "INTERNAL"
