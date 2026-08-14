"""Shared vocabulary for every stage, the bundle, the API, and (via OpenAPI) the frontend.

These enums are defined once, here. The API schemas re-export them; the frontend consumes them
as generated TS union types (CLAUDE.md §9). Adding a variant here is *supposed* to break the TS
build until the frontend handles it.
"""

from enum import StrEnum

BUNDLE_SCHEMA_VERSION = 1
"""Integer schema version stamped into every run bundle manifest (docs/BUNDLE_SCHEMA.md)."""


class Verdict(StrEnum):
    """The only verdicts Tempest can emit (Law L2)."""

    DIVERGENT = "DIVERGENT"
    EQUIVALENT_UNDER_BUDGET = "EQUIVALENT_UNDER_BUDGET"
    UNPROVEN = "UNPROVEN"
    ERROR = "ERROR"


class DivergenceClass(StrEnum):
    """Taxonomy of observable behavior differences (master spec stage 7)."""

    RETURN_VALUE = "RETURN_VALUE"
    EXCEPTION_TYPE = "EXCEPTION_TYPE"
    EXCEPTION_MESSAGE = "EXCEPTION_MESSAGE"
    EFFECT_SEQUENCE = "EFFECT_SEQUENCE"
    EFFECT_ARGUMENTS = "EFFECT_ARGUMENTS"
    CASSETTE_MISS = "CASSETTE_MISS"
    CRASH = "CRASH"
    HANG = "HANG"
    OUTPUT_STREAM = "OUTPUT_STREAM"


class ReasonCode(StrEnum):
    """Machine-readable blocking reasons attached to every UNPROVEN verdict (Law L2)."""

    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    ENV_REPRODUCTION_FAILED = "ENV_REPRODUCTION_FAILED"
    HARNESS_SYNTHESIS_FAILED = "HARNESS_SYNTHESIS_FAILED"
    UNINTERCEPTABLE_EFFECT = "UNINTERCEPTABLE_EFFECT"
    NONDETERMINISTIC_BASE = "NONDETERMINISTIC_BASE"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    VALUE_UNSERIALIZABLE = "VALUE_UNSERIALIZABLE"


class TargetClassification(StrEnum):
    """Stage-1 classification of a changed symbol."""

    PURE_CANDIDATE = "PURE_CANDIDATE"
    IMPURE_RECORDABLE = "IMPURE_RECORDABLE"
    UNREACHABLE = "UNREACHABLE"


class Stage(StrEnum):
    """The nine engine stages, in data-flow order."""

    TARGET_SELECTION = "TARGET_SELECTION"
    ENV_REPRODUCTION = "ENV_REPRODUCTION"
    HARNESS_SYNTHESIS = "HARNESS_SYNTHESIS"
    DETERMINISM = "DETERMINISM"
    INPUT_GENERATION = "INPUT_GENERATION"
    DUAL_EXECUTION = "DUAL_EXECUTION"
    COMPARISON = "COMPARISON"
    MINIMIZATION = "MINIMIZATION"
    REPORT_ASSEMBLY = "REPORT_ASSEMBLY"


class Severity(StrEnum):
    """Reporting severity: -0.0 vs 0.0 is LOW; a head-only crash is HEADLINE."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HEADLINE = "HEADLINE"


class Lang(StrEnum):
    PYTHON = "PYTHON"
    TYPESCRIPT = "TYPESCRIPT"
