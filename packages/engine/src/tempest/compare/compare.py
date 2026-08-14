"""Observation comparison — computes the DivergenceClass verdict input (master spec stage 7).

Precedence: unrepresentable → outcome (hang/crash) → exceptions → return value → effects → streams.
Timing is never consulted. Equality is decided over canonical trees only.
"""

import math
from dataclasses import dataclass

from tempest.compare.normalize import normalize_message
from tempest.model import DivergenceClass, InputOutcome, Observation, Severity


@dataclass(frozen=True)
class CompareConfig:
    """The documented, configurable equivalence relation. Defaults: exact."""

    float_rel_tol: float | None = None


@dataclass(frozen=True)
class Equal:
    pass


@dataclass(frozen=True)
class Diverged:
    divergence_class: DivergenceClass
    severity: Severity
    detail: str
    first_divergent_effect: int | None = None


@dataclass(frozen=True)
class Unprovable:
    """This input's behavior could not be compared — surfaces as UNPROVEN, never as equal."""

    reason: str


type CompareResult = Equal | Diverged | Unprovable


def compare(base: Observation, head: Observation, cfg: CompareConfig) -> CompareResult:
    if base.unrepresentable is not None:
        return Unprovable(reason=f"base observation unrepresentable: {base.unrepresentable}")
    if head.unrepresentable is not None:
        return Unprovable(reason=f"head observation unrepresentable: {head.unrepresentable}")

    if base.outcome is not head.outcome:
        if InputOutcome.HUNG in (base.outcome, head.outcome):
            return Diverged(
                DivergenceClass.HANG,
                Severity.HEADLINE,
                f"base {base.outcome.lower()}, head {head.outcome.lower()}",
            )
        return Diverged(
            DivergenceClass.CRASH,
            Severity.HEADLINE,
            f"base {base.outcome.lower()} (exit {base.exit_status}), "
            f"head {head.outcome.lower()} (exit {head.exit_status})",
        )
    if base.outcome is InputOutcome.CRASHED:
        if base.exit_status != head.exit_status:
            return Diverged(
                DivergenceClass.CRASH,
                Severity.HEADLINE,
                f"both crashed but differently: base exit {base.exit_status}, "
                f"head exit {head.exit_status}",
            )
        return Equal()
    if base.outcome is InputOutcome.HUNG:
        return Equal()

    exception_result = _compare_exceptions(base, head)
    if exception_result is not None:
        return exception_result

    if base.return_present and head.return_present:
        equal, sign_only = _values_equal(base.return_canon, head.return_canon, cfg)
        if not equal:
            return Diverged(
                DivergenceClass.RETURN_VALUE,
                Severity.LOW if sign_only else Severity.NORMAL,
                "signed-zero difference (-0.0 vs 0.0)" if sign_only else "return values differ",
            )

    effect_result = _compare_effects(base, head)
    if effect_result is not None:
        return effect_result

    if normalize_message(base.stdout) != normalize_message(head.stdout):
        return Diverged(DivergenceClass.OUTPUT_STREAM, Severity.NORMAL, "stdout differs")
    if normalize_message(base.stderr) != normalize_message(head.stderr):
        return Diverged(DivergenceClass.OUTPUT_STREAM, Severity.NORMAL, "stderr differs")

    return Equal()


def _compare_exceptions(base: Observation, head: Observation) -> Diverged | None:
    if (base.raised is None) != (head.raised is None):
        raiser = "head" if head.raised is not None else "base"
        info = head.raised if head.raised is not None else base.raised
        assert info is not None
        return Diverged(
            DivergenceClass.EXCEPTION_TYPE,
            Severity.NORMAL,
            f"{raiser} raised {info.module}.{info.type_name}, the other side returned",
        )
    if base.raised is None or head.raised is None:
        return None
    if (base.raised.type_name, base.raised.module) != (head.raised.type_name, head.raised.module):
        return Diverged(
            DivergenceClass.EXCEPTION_TYPE,
            Severity.NORMAL,
            f"base raised {base.raised.module}.{base.raised.type_name}, "
            f"head raised {head.raised.module}.{head.raised.type_name}",
        )
    if normalize_message(base.raised.message) != normalize_message(head.raised.message):
        return Diverged(
            DivergenceClass.EXCEPTION_MESSAGE,
            Severity.NORMAL,
            f"same exception type ({base.raised.type_name}), messages differ after normalization",
        )
    return None


def _compare_effects(base: Observation, head: Observation) -> Diverged | None:
    for i, (b, h) in enumerate(zip(base.effects, head.effects, strict=False)):
        if (b.surface, b.call) != (h.surface, h.call):
            return Diverged(
                DivergenceClass.EFFECT_SEQUENCE,
                Severity.NORMAL,
                f"effect #{i}: base {b.surface} {b.call!r} vs head {h.surface} {h.call!r}",
                first_divergent_effect=i,
            )
        if b.args_fingerprint != h.args_fingerprint:
            return Diverged(
                DivergenceClass.EFFECT_ARGUMENTS,
                Severity.NORMAL,
                f"effect #{i} ({b.surface} {b.call!r}): arguments differ",
                first_divergent_effect=i,
            )
    if len(base.effects) != len(head.effects):
        i = min(len(base.effects), len(head.effects))
        longer = "head" if len(head.effects) > len(base.effects) else "base"
        extra = (head.effects if longer == "head" else base.effects)[i]
        return Diverged(
            DivergenceClass.EFFECT_SEQUENCE,
            Severity.NORMAL,
            f"{longer} issued an extra effect at #{i}: {extra.surface} {extra.call!r}",
            first_divergent_effect=i,
        )
    return None


def _values_equal(a: object, b: object, cfg: CompareConfig) -> tuple[bool, bool]:
    """Deep equality over canonical trees → (equal, every_difference_is_signed_zero)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.get("__t") != b.get("__t"):
            return False, False
        tag = a.get("__t")
        if tag == "float":
            return _floats_equal(str(a["v"]), str(b["v"]), cfg)
        if tag in ("list", "tuple", "set", "frozenset"):
            return _sequences_equal(list(a["v"]), list(b["v"]), cfg)
        if tag == "dict":
            return _pairs_equal(list(a["v"]), list(b["v"]), cfg)
        if tag == "obj":
            if a.get("type") != b.get("type"):
                return False, False
            return _pairs_equal(list(a["v"]), list(b["v"]), cfg)
        if tag == "bytes":
            return (a["v"] == b["v"], False)
        return (a == b, False)
    if isinstance(a, dict) or isinstance(b, dict):
        return False, False
    if isinstance(a, bool) or isinstance(b, bool):
        return (a is b, False)
    return (a == b and type(a) is type(b), False)


def _floats_equal(ahex: str, bhex: str, cfg: CompareConfig) -> tuple[bool, bool]:
    if ahex == bhex:
        return True, False
    af = math.nan if ahex == "nan" else float.fromhex(ahex)
    bf = math.nan if bhex == "nan" else float.fromhex(bhex)
    if math.isnan(af) and math.isnan(bf):
        return True, False
    if math.isnan(af) or math.isnan(bf):
        return False, False
    if af == 0.0 and bf == 0.0:
        # Same magnitude, different sign bit. Exact mode reports it as a distinct LOW-severity
        # class; tolerance mode treats it as equal.
        if cfg.float_rel_tol is not None:
            return True, False
        return False, True
    if cfg.float_rel_tol is not None and math.isclose(af, bf, rel_tol=cfg.float_rel_tol):
        return True, False
    return False, False


def _sequences_equal(xs: list[object], ys: list[object], cfg: CompareConfig) -> tuple[bool, bool]:
    if len(xs) != len(ys):
        return False, False
    equal = True
    sign_only = True
    for x, y in zip(xs, ys, strict=True):
        child_equal, child_sign_only = _values_equal(x, y, cfg)
        if not child_equal:
            equal = False
            if not child_sign_only:
                sign_only = False
    return (True, False) if equal else (False, sign_only)


def _pairs_equal(xs: list[object], ys: list[object], cfg: CompareConfig) -> tuple[bool, bool]:
    """Compare [key, value] pair lists (already canonically sorted)."""
    if len(xs) != len(ys):
        return False, False
    equal = True
    sign_only = True
    for x, y in zip(xs, ys, strict=True):
        if not (isinstance(x, list) and isinstance(y, list) and len(x) == 2 and len(y) == 2):
            return (x == y, False)
        key_equal, _ = _values_equal(x[0], y[0], cfg)
        if not key_equal:
            return False, False
        child_equal, child_sign_only = _values_equal(x[1], y[1], cfg)
        if not child_equal:
            equal = False
            if not child_sign_only:
                sign_only = False
    return (True, False) if equal else (False, sign_only)
