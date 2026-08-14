"""Shared vocabulary for every stage, the bundle, the API, and (via OpenAPI) the frontend.

These enums are defined once, here. The API schemas re-export them; the frontend consumes them
as generated TS union types (CLAUDE.md §9). Adding a variant here is *supposed* to break the TS
build until the frontend handles it.
"""

from dataclasses import dataclass, field
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


class InputOutcome(StrEnum):
    """How a single invocation ended. Crash/hang are observations, not runner failures."""

    COMPLETED = "COMPLETED"
    CRASHED = "CRASHED"
    HUNG = "HUNG"


@dataclass(frozen=True)
class RaisedInfo:
    """A target-raised exception — a legitimate observation, never an adapter failure."""

    type_name: str
    module: str
    message: str


@dataclass(frozen=True)
class Timing:
    """Recorded for the UI. NEVER compared (Law: timing is not a divergence signal)."""

    wall_ns: int
    cpu_ns: int


@dataclass(frozen=True)
class EffectEntry:
    """One interaction in the ordered effect ledger (stage 4 cassette)."""

    surface: str
    call: str
    ordinal: int
    args_fingerprint: str


@dataclass(frozen=True)
class Observation:
    """Everything observable about one invocation of one revision (master spec stage 6)."""

    outcome: InputOutcome
    return_present: bool
    return_canon: object | None
    raised: RaisedInfo | None
    effects: tuple[EffectEntry, ...] = ()
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0
    timing: Timing = field(default_factory=lambda: Timing(wall_ns=0, cpu_ns=0))
    unrepresentable: str | None = None
