"""Differential proof of one target: base vs head under identical conditions.

Failure-mode defenses built in (master spec §14):
- §14.2 flaky comparison: every candidate divergence is re-run 3x on both sides in fresh
  process pairs; a base that disagrees with itself → UNPROVEN(NONDETERMINISTIC_BASE), never
  a head bug; a divergence that vanishes or drifts class → discarded as flaky.
- §14.5 in-process leakage: every run is a separate worker process pair.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from tempest.compare.canonical import Canon, canonical_bytes
from tempest.compare.compare import CompareConfig, Diverged, Equal, Unprovable, compare
from tempest.execute.runner import run_batch
from tempest.execute.sandbox import Sandbox
from tempest.generate.inputs import Budget, CandidateInput, generate_inputs
from tempest.generate.mutate import mutate_input
from tempest.harness.synth import SynthesisFailure, synthesize
from tempest.model import (
    DivergenceClass,
    InputOutcome,
    Observation,
    ReasonCode,
    Severity,
    Verdict,
)

_MAX_CONFIRMATIONS = 8
_CONFIRM_ATTEMPTS = 3


class ConfirmOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    FLAKY = "FLAKY"
    NONDETERMINISTIC_BASE = "NONDETERMINISTIC_BASE"


@dataclass(frozen=True)
class FoundDivergence:
    args_literal: str
    kwargs_literal: str
    divergence_class: DivergenceClass
    severity: Severity
    detail: str
    base_summary: str
    head_summary: str
    minimized_args: str | None = None
    minimized_kwargs: str | None = None
    shrink_path: tuple[str, ...] = ()
    repro_script: str | None = None


@dataclass(frozen=True)
class TargetOutcome:
    module: str
    qualname: str
    verdict: Verdict
    reason_code: ReasonCode | None
    reason_detail: str | None
    inputs_run: int
    equivalent_inputs: int
    unprovable_inputs: int
    changed_line_coverage: float
    divergences: tuple[FoundDivergence, ...]


def observation_summary(obs: Observation) -> str:
    if obs.outcome is InputOutcome.HUNG:
        return "hung (per-input timeout)"
    if obs.outcome is InputOutcome.CRASHED:
        return f"crashed (exit {obs.exit_status})"
    if obs.raised is not None:
        return f"raised {obs.raised.type_name}: {obs.raised.message}"[:200]
    if obs.unrepresentable is not None:
        return f"returned an unrepresentable value ({obs.unrepresentable})"
    return f"returned {canonical_bytes(cast(Canon, obs.return_canon)).decode()[:200]}"


def confirm_divergence(
    rerun: Callable[[int], tuple[Diverged | None, bool, bool]],
    attempts: int = _CONFIRM_ATTEMPTS,
) -> ConfirmOutcome:
    """rerun(attempt) → (fresh pair comparison, base self-consistent, head self-consistent)."""
    first_class: DivergenceClass | None = None
    for attempt in range(attempts):
        diverged, base_ok, head_ok = rerun(attempt)
        if not base_ok:
            return ConfirmOutcome.NONDETERMINISTIC_BASE
        if diverged is None or not head_ok:
            return ConfirmOutcome.FLAKY
        if first_class is None:
            first_class = diverged.divergence_class
        elif diverged.divergence_class is not first_class:
            return ConfirmOutcome.FLAKY
    return ConfirmOutcome.CONFIRMED


def prove_target(
    base_root: Path,
    head_root: Path,
    module: str,
    qualname: str,
    *,
    changed_lines: frozenset[int],
    sandbox: Sandbox,
    budget: Budget,
    mined: list[object] | None = None,
    cfg: CompareConfig | None = None,
) -> TargetOutcome:
    cfg = cfg or CompareConfig()
    adapter = synthesize(head_root, module, qualname, sandbox=sandbox, seed=budget.seed)
    if isinstance(adapter, SynthesisFailure):
        return _unproven(module, qualname, adapter.reason_code, adapter.detail)

    candidates = generate_inputs(adapter.introspection, mined=mined or [], budget=budget)
    literals = [(c.args_literal, c.kwargs_literal) for c in candidates]
    base_obs = run_batch(base_root, module, qualname, literals, sandbox)
    head_obs = run_batch(head_root, module, qualname, literals, sandbox)

    # One coverage-guided top-up round: mutate the inputs that reached changed lines.
    if changed_lines and len(literals) < budget.max_inputs:
        hitters = [i for i, obs in enumerate(head_obs) if obs.executed_lines & changed_lines][:10]
        mutants: list[tuple[str, str]] = []
        for j, i in enumerate(hitters):
            for k in range(3):
                mutants.append(
                    mutate_input(literals[i][0], literals[i][1], seed=budget.seed + j * 31 + k)
                )
        mutants = [m for m in mutants if m not in set(literals)][
            : budget.max_inputs - len(literals)
        ]
        if mutants:
            base_obs += run_batch(base_root, module, qualname, mutants, sandbox)
            head_obs += run_batch(head_root, module, qualname, mutants, sandbox)
            literals += mutants
            candidates += [
                CandidateInput(args_literal=a, kwargs_literal=k, provenance="MUTATED")
                for a, k in mutants
            ]

    equivalent = 0
    unprovable = 0
    confirmed: list[FoundDivergence] = []
    seen_classes: set[tuple[str, DivergenceClass]] = set()

    for (args_l, kwargs_l), b_obs, h_obs in zip(literals, base_obs, head_obs, strict=True):
        result = compare(b_obs, h_obs, cfg)
        if isinstance(result, Equal):
            equivalent += 1
            continue
        if isinstance(result, Unprovable):
            unprovable += 1
            continue
        if len(confirmed) >= _MAX_CONFIRMATIONS:
            continue
        dedupe_key = (args_l, result.divergence_class)
        if dedupe_key in seen_classes:
            continue
        seen_classes.add(dedupe_key)

        history: dict[str, list[Observation]] = {"base": [], "head": []}

        def rerun(
            attempt: int,
            args_l: str = args_l,
            kwargs_l: str = kwargs_l,
            history: dict[str, list[Observation]] = history,
        ) -> tuple[Diverged | None, bool, bool]:
            (b,) = run_batch(base_root, module, qualname, [(args_l, kwargs_l)], sandbox)
            (h,) = run_batch(head_root, module, qualname, [(args_l, kwargs_l)], sandbox)
            base_ok = all(isinstance(compare(b, prev, cfg), Equal) for prev in history["base"])
            head_ok = all(isinstance(compare(h, prev, cfg), Equal) for prev in history["head"])
            history["base"].append(b)
            history["head"].append(h)
            pair = compare(b, h, cfg)
            return (pair if isinstance(pair, Diverged) else None), base_ok, head_ok

        confirmation = confirm_divergence(rerun)
        if confirmation is ConfirmOutcome.NONDETERMINISTIC_BASE:
            return _unproven(
                module,
                qualname,
                ReasonCode.NONDETERMINISTIC_BASE,
                f"base revision disagrees with itself on input {args_l} — comparison under "
                "uncontrolled nondeterminism is meaningless (Law L3); nothing is reported "
                "as a head bug",
            )
        if confirmation is ConfirmOutcome.FLAKY:
            unprovable += 1
            continue
        assert isinstance(result, Diverged)
        confirmed.append(
            FoundDivergence(
                args_literal=args_l,
                kwargs_literal=kwargs_l,
                divergence_class=result.divergence_class,
                severity=result.severity,
                detail=result.detail,
                base_summary=observation_summary(b_obs),
                head_summary=observation_summary(h_obs),
            )
        )

    covered = frozenset().union(*(o.executed_lines for o in head_obs)) if head_obs else frozenset()
    coverage = len(covered & changed_lines) / len(changed_lines) if changed_lines else 1.0

    verdict = Verdict.DIVERGENT if confirmed else Verdict.EQUIVALENT_UNDER_BUDGET
    return TargetOutcome(
        module=module,
        qualname=qualname,
        verdict=verdict,
        reason_code=None,
        reason_detail=None,
        inputs_run=len(literals),
        equivalent_inputs=equivalent,
        unprovable_inputs=unprovable,
        changed_line_coverage=coverage,
        divergences=tuple(confirmed),
    )


def _unproven(module: str, qualname: str, reason_code: ReasonCode, detail: str) -> TargetOutcome:
    return TargetOutcome(
        module=module,
        qualname=qualname,
        verdict=Verdict.UNPROVEN,
        reason_code=reason_code,
        reason_detail=detail,
        inputs_run=0,
        equivalent_inputs=0,
        unprovable_inputs=0,
        changed_line_coverage=0.0,
        divergences=(),
    )


def prove_impure_target(
    base_root: Path,
    head_root: Path,
    module: str,
    qualname: str,
    *,
    changed_lines: frozenset[int],
    sandbox: Sandbox,
    budget: Budget,
    mined: list[object] | None = None,
    cfg: CompareConfig | None = None,
    loopback_routes: dict[str, object] | None = None,
    loopback_port: int = 0,
) -> TargetOutcome:
    """IMPURE_RECORDABLE flow: record once on base → verify replay stability on base →
    replay head from the identical cassette (Law L3: identical conditions or UNPROVEN)."""
    from tempest.execute.runner import DeterminismJob

    cfg = cfg or CompareConfig()
    adapter = synthesize(head_root, module, qualname, sandbox=sandbox, seed=budget.seed)
    if isinstance(adapter, SynthesisFailure):
        return _unproven(module, qualname, adapter.reason_code, adapter.detail)

    candidates = generate_inputs(adapter.introspection, mined=mined or [], budget=budget)
    literals = [(c.args_literal, c.kwargs_literal) for c in candidates]

    record_job = DeterminismJob(
        mode="record", loopback_routes=loopback_routes, loopback_port=loopback_port
    )
    base_rec = run_batch(base_root, module, qualname, literals, sandbox, determinism=record_job)
    surface = next((o.uninterceptable for o in base_rec if o.uninterceptable), None)
    if surface is not None:
        return _unproven(
            module,
            qualname,
            ReasonCode.UNINTERCEPTABLE_EFFECT,
            f"could not exercise `{module}.{qualname}` — {surface}",
        )

    cassettes: dict[int, object] = {i: o.cassette for i, o in enumerate(base_rec)}
    replay_job = DeterminismJob(mode="replay", cassettes=cassettes, loopback_port=loopback_port)
    base_rep = run_batch(base_root, module, qualname, literals, sandbox, determinism=replay_job)
    for i, (rec, rep) in enumerate(zip(base_rec, base_rep, strict=True)):
        if not isinstance(compare(rec, rep, cfg), Equal):
            return _unproven(
                module,
                qualname,
                ReasonCode.NONDETERMINISTIC_BASE,
                f"base replay does not reproduce its own recording on input "
                f"{literals[i][0]} — determinism could not be reached (Law L3)",
            )

    head_obs = run_batch(head_root, module, qualname, literals, sandbox, determinism=replay_job)
    surface = next((o.uninterceptable for o in head_obs if o.uninterceptable), None)
    if surface is not None:
        return _unproven(
            module,
            qualname,
            ReasonCode.UNINTERCEPTABLE_EFFECT,
            f"could not exercise `{module}.{qualname}` on head — {surface}",
        )

    equivalent = 0
    unprovable = 0
    confirmed: list[FoundDivergence] = []

    for (args_l, kwargs_l), b_obs, h_obs in zip(literals, base_rec, head_obs, strict=True):
        result = compare(b_obs, h_obs, cfg)
        if isinstance(result, Equal):
            equivalent += 1
            continue
        if isinstance(result, Unprovable):
            unprovable += 1
            continue
        if len(confirmed) >= _MAX_CONFIRMATIONS:
            continue

        def rerun(
            attempt: int, args_l: str = args_l, kwargs_l: str = kwargs_l
        ) -> tuple[Diverged | None, bool, bool]:
            (fresh_rec,) = run_batch(
                base_root,
                module,
                qualname,
                [(args_l, kwargs_l)],
                sandbox,
                determinism=DeterminismJob(
                    mode="record", loopback_routes=loopback_routes, loopback_port=loopback_port
                ),
            )
            single_replay = DeterminismJob(
                mode="replay", cassettes={0: fresh_rec.cassette}, loopback_port=loopback_port
            )
            (fresh_rep,) = run_batch(
                base_root,
                module,
                qualname,
                [(args_l, kwargs_l)],
                sandbox,
                determinism=single_replay,
            )
            base_ok = isinstance(compare(fresh_rec, fresh_rep, cfg), Equal)
            (fresh_head,) = run_batch(
                head_root,
                module,
                qualname,
                [(args_l, kwargs_l)],
                sandbox,
                determinism=single_replay,
            )
            pair = compare(fresh_rec, fresh_head, cfg)
            return (pair if isinstance(pair, Diverged) else None), base_ok, True

        confirmation = confirm_divergence(rerun)
        if confirmation is ConfirmOutcome.NONDETERMINISTIC_BASE:
            return _unproven(
                module,
                qualname,
                ReasonCode.NONDETERMINISTIC_BASE,
                f"base record/replay disagrees with itself on input {args_l} (Law L3)",
            )
        if confirmation is ConfirmOutcome.FLAKY:
            unprovable += 1
            continue
        assert isinstance(result, Diverged)
        confirmed.append(
            FoundDivergence(
                args_literal=args_l,
                kwargs_literal=kwargs_l,
                divergence_class=result.divergence_class,
                severity=result.severity,
                detail=result.detail,
                base_summary=observation_summary(b_obs),
                head_summary=observation_summary(h_obs),
            )
        )

    covered = frozenset().union(*(o.executed_lines for o in head_obs)) if head_obs else frozenset()
    coverage = len(covered & changed_lines) / len(changed_lines) if changed_lines else 1.0
    verdict = Verdict.DIVERGENT if confirmed else Verdict.EQUIVALENT_UNDER_BUDGET
    return TargetOutcome(
        module=module,
        qualname=qualname,
        verdict=verdict,
        reason_code=None,
        reason_detail=None,
        inputs_run=len(literals),
        equivalent_inputs=equivalent,
        unprovable_inputs=unprovable,
        changed_line_coverage=coverage,
        divergences=tuple(confirmed),
    )
