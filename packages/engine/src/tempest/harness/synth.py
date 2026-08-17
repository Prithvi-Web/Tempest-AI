"""Adapter synthesis (deterministic, type-driven — ADR-0006).

An adapter is accepted ONLY by executing it: the probe must invoke the target with the invocation
machinery succeeding. A target that raises on the probe is a legitimate observation and still a
valid adapter. Three failed probe attempts → UNPROVEN(HARNESS_SYNTHESIS_FAILED) with the attempts
attached — never a trivial fallback that "works" by not exercising anything.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from tempest.envrepro.deps import deps_note
from tempest.execute.runner import (
    TargetIntrospection,
    introspect_target,
    run_batch,
)
from tempest.execute.sandbox import Sandbox
from tempest.generate.inputs import Budget, generate_inputs
from tempest.model import InputOutcome, ReasonCode

_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ValidatedAdapter:
    module: str
    qualname: str
    cache_key: str  # "<module>.<qualname>@<file-hash>"
    introspection: TargetIntrospection
    probe_args: str
    probe_kwargs: str
    validated_by_execution: bool
    # True when every completing probe RAISED: the invocation machinery works, but nothing
    # demonstrates a clean pass through the target. Legitimate for mirrored-parameter
    # adapters (the target may raise by design); the type-driven rung treats it as
    # "my constructor guess may be the thing raising" and gives up (ADR-0026).
    probe_raised: bool = False


@dataclass(frozen=True)
class SynthesisFailure:
    module: str
    qualname: str
    reason_code: ReasonCode
    detail: str
    attempts: int


def _file_hash(root: Path, module: str) -> str:
    rel = Path(*module.split("."))
    for base in (root, root / "src"):
        for candidate in (base / f"{rel}.py", base / rel / "__init__.py"):
            if candidate.exists():
                return hashlib.sha256(candidate.read_bytes()).hexdigest()[:16]
    return "missing-file"


def synthesize(
    root: Path, module: str, qualname: str, *, sandbox: Sandbox, seed: int = 0
) -> ValidatedAdapter | SynthesisFailure:
    introspection = introspect_target(root, module, qualname, sandbox)
    if introspection is None:
        return SynthesisFailure(
            module=module,
            qualname=qualname,
            reason_code=ReasonCode.HARNESS_SYNTHESIS_FAILED,
            detail=(
                f"could not introspect `{module}.{qualname}` — the module failed to import or "
                "the symbol does not exist in this revision"
                + (f" (dependencies: {note})" if (note := deps_note(root)) else "")
            ),
            attempts=1,
        )

    probes = generate_inputs(
        introspection, mined=[], budget=Budget(max_inputs=_MAX_ATTEMPTS, seed=seed)
    )
    if not probes:
        # generate_inputs always emits at least one candidate for any introspectable signature
        # (its first round is always novel), so this fallback is unreachable today; it stays as
        # a guard so a future, choosier generator can never leave a target probe-less.
        probes_literals = [("()", "{}")]  # pragma: no cover — defensive; generator emits ≥1
    else:
        probes_literals = [(p.args_literal, p.kwargs_literal) for p in probes]

    failures: list[str] = []
    raised_completion: ValidatedAdapter | None = None
    for args_literal, kwargs_literal in probes_literals[:_MAX_ATTEMPTS]:
        (obs,) = run_batch(
            root,
            module,
            qualname,
            [(args_literal, kwargs_literal)],
            sandbox,
            per_input_timeout=10.0,
        )
        if obs.outcome is InputOutcome.COMPLETED:
            accepted = ValidatedAdapter(
                module=module,
                qualname=qualname,
                cache_key=f"{module}.{qualname}@{_file_hash(root, module)}",
                introspection=introspection,
                probe_args=args_literal,
                probe_kwargs=kwargs_literal,
                validated_by_execution=True,
                probe_raised=obs.raised is not None,
            )
            if obs.raised is None:
                return accepted  # a clean pass is the strongest acceptance — take it
            if raised_completion is None:
                raised_completion = accepted  # keep looking for a clean probe first
            continue
        failures.append(f"probe {args_literal} → {obs.outcome} (exit {obs.exit_status})")
    if raised_completion is not None:
        return raised_completion

    return SynthesisFailure(
        module=module,
        qualname=qualname,
        reason_code=ReasonCode.HARNESS_SYNTHESIS_FAILED,
        detail="all probe invocations failed: " + "; ".join(failures),
        attempts=len(failures),
    )
