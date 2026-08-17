"""The TypeScript differential (wave 1, ADR-0028) — same laws, second language.

Orchestrates the node worker (`ts_worker.mjs` + `ts_shims.mjs`) over base and head and
computes verdicts with the SAME comparator as Python targets (`compare.compare`) — one
taxonomy, one honesty vocabulary. Wave-1 rules, each stated where it bites:

- L3 first: base runs TWICE in fresh processes; any self-disagreement is
  NONDETERMINISTIC_BASE for that target — never compared, never retried until it agrees.
- Every candidate divergence is re-confirmed on a fresh process pair; a divergence that
  does not reproduce is discarded as flaky, never reported.
- Inputs come from the sidecar's typed per-parameter value pools, drawn deterministically
  from the run seed. Specials (NaN, ±Infinity, undefined) travel as tagged JSON and are
  decoded at the call boundary.
- Input minimization is deferred (wave 2): repro scripts embed the found input verbatim.
"""

import json
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tempest.compare.compare import CompareConfig, Diverged, Equal, Unprovable, compare
from tempest.execute.sandbox import Sandbox
from tempest.generate.inputs import Budget
from tempest.model import (
    DivergenceClass,
    InputOutcome,
    Observation,
    RaisedInfo,
    ReasonCode,
    Severity,
    Verdict,
)

_WORKER = Path(__file__).with_name("ts_worker.mjs")
_SHIMS = Path(__file__).with_name("ts_shims.mjs")
_BOOT_TIMEOUT_S = 30.0
_PER_INPUT_TIMEOUT_S = 5.0


class TsExecUnavailableError(Exception):
    """Node (or the worker files) cannot run here; the message says exactly what to fix."""


@dataclass(frozen=True)
class TsDivergenceFound:
    args_json: str  # JSON array literal of the input
    divergence_class: DivergenceClass
    severity: Severity
    detail: str
    base_summary: str
    head_summary: str


@dataclass(frozen=True)
class TsOutcome:
    verdict: Verdict
    reason_code: ReasonCode | None
    reason_detail: str | None
    inputs_run: int
    equivalent_inputs: int
    unprovable_inputs: int
    changed_line_coverage: float
    divergences: tuple[TsDivergenceFound, ...]


def _node_binary() -> str:
    node = shutil.which("node")
    if node is None:
        raise TsExecUnavailableError(
            "TypeScript execution needs `node` (>= 22.6) on PATH — install Node.js and rerun"
        )
    return node


def generate_ts_inputs(param_pools: list[dict[str, object]], budget: Budget) -> list[list[object]]:
    """Deterministic draws from the sidecar's typed pools. Round one walks each pool in
    order (every pool value appears early); later rounds draw seeded random combinations."""
    rng = random.Random(budget.seed)
    pools: list[list[object]] = []
    for param in param_pools:
        raw_values = param.get("values")
        values: list[object] = list(raw_values) if isinstance(raw_values, list) else []
        raw_specials = param.get("specials")
        for special in raw_specials if isinstance(raw_specials, list) else []:
            if isinstance(special, str):
                values.append({"__tempest_special__": special})
        if not values:
            values = [None]
        pools.append(values)
    if not pools:
        return [[]]  # zero-arg target: the single empty invocation IS the input space
    longest = max(len(p) for p in pools)
    inputs: list[list[object]] = []
    seen: set[str] = set()
    for i in range(longest):
        candidate = [p[i % len(p)] for p in pools]
        key = json.dumps(candidate, sort_keys=True)
        if key not in seen:
            seen.add(key)
            inputs.append(candidate)
        if len(inputs) >= budget.max_inputs:
            return inputs
    attempts = 0
    while len(inputs) < budget.max_inputs and attempts < budget.max_inputs * 20:
        attempts += 1
        candidate = [rng.choice(p) for p in pools]
        key = json.dumps(candidate, sort_keys=True)
        if key not in seen:
            seen.add(key)
            inputs.append(candidate)
    return inputs


def _run_batch(
    root: Path,
    target_file: str,
    export_name: str,
    inputs: list[list[object]],
    sandbox: Sandbox,
    seed: int,
) -> list[dict[str, object]]:
    """One worker process over the whole batch; one parsed observation dict per input."""
    with tempfile.TemporaryDirectory(prefix="tempest-ts-scratch-") as scratch_dir:
        return _run_batch_in(
            root, target_file, export_name, inputs, sandbox, seed, Path(scratch_dir)
        )


def _run_batch_in(
    root: Path,
    target_file: str,
    export_name: str,
    inputs: list[list[object]],
    sandbox: Sandbox,
    seed: int,
    scratch: Path,
) -> list[dict[str, object]]:
    shutil.copyfile(_WORKER, scratch / "ts_worker.mjs")
    shutil.copyfile(_SHIMS, scratch / "ts_shims.mjs")
    job_path = scratch / "ts_job.json"
    job_path.write_text(
        json.dumps(
            {"target_file": str(root / target_file), "export_name": export_name, "inputs": inputs}
        ),
        encoding="utf-8",
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "TEMPEST_JS_SEED": str(seed),
        # --max-old-space-size IS the JS memory containment (with the CPU rlimit, the batch
        # wall budget, and the group kill): V8 cannot run under RLIMIT_AS — Wasm and the
        # pointer cage reserve multi-GiB VIRTUAL ranges up front (Linux-only failure; macOS
        # never enforces AS, so only real Linux CI could reveal it).
        "NODE_OPTIONS": "--disable-warning=ExperimentalWarning --max-old-space-size=256",
    }
    cmd = [
        _node_binary(),
        "--experimental-strip-types",
        "--import",
        str(scratch / "ts_shims.mjs"),
        str(scratch / "ts_worker.mjs"),
        str(job_path),
    ]
    proc = sandbox.popen(cmd, cwd=root, env=env, scratch=scratch, stdin_pipe=False, v8=True)
    timeout = _BOOT_TIMEOUT_S + _PER_INPUT_TIMEOUT_S * max(1, len(inputs))
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        raise TsExecUnavailableError(
            f"the node worker exceeded its {timeout:.0f}s batch budget (possible hang)"
        ) from exc
    lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line]
    parsed: list[dict[str, object]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except ValueError:
            continue  # target console noise on the real fd is possible pre-capture — skip
        if isinstance(payload, dict):
            parsed.append(payload)
    fatal = next((p for p in parsed if "fatal" in p), None)
    if fatal is not None:
        raise TsImportFailed(str(fatal.get("error") or "import failed"))
    by_index = {p.get("index"): p for p in parsed if isinstance(p.get("index"), int)}
    missing = [i for i in range(len(inputs)) if i not in by_index]
    if missing:
        raise TsExecUnavailableError(
            f"the node worker died mid-batch (exit {proc.returncode}); "
            f"missing observations for inputs {missing[:5]}"
        )
    return [by_index[i] for i in range(len(inputs))]


class TsImportFailed(Exception):
    """The target module failed to import (or the export is not a function) — an honest
    per-target UNPROVEN, phrased for the developer."""


def _observation(payload: dict[str, object]) -> Observation:
    raised_raw = payload.get("raised")
    raised = None
    if isinstance(raised_raw, dict):
        raised = RaisedInfo(
            type_name=str(raised_raw.get("type") or "Error"),
            module="js",
            message=str(raised_raw.get("message") or ""),
        )
    executed = payload.get("executed_lines")
    executed_lines = (
        frozenset(int(x) for x in executed if isinstance(x, int))
        if isinstance(executed, list)
        else frozenset()
    )
    return Observation(
        outcome=InputOutcome.COMPLETED,
        return_present=bool(payload.get("return_present")),
        return_canon=payload.get("return_canon"),
        raised=raised,
        stdout=str(payload.get("stdout") or ""),
        stderr=str(payload.get("stderr") or ""),
        unrepresentable=(
            str(payload.get("unrepresentable")) if payload.get("unrepresentable") else None
        ),
        executed_lines=executed_lines,
    )


def _summary(obs: Observation) -> str:
    if obs.raised is not None:
        return f"raised {obs.raised.type_name}: {obs.raised.message}"
    if obs.unrepresentable:
        return f"unrepresentable: {obs.unrepresentable}"
    return f"returned {json.dumps(obs.return_canon, sort_keys=True)}"


def prove_ts_target(
    base_root: Path,
    head_root: Path,
    *,
    rel_path: str,
    export_name: str,
    param_pools: list[dict[str, object]],
    changed_lines: frozenset[int],
    sandbox: Sandbox,
    budget: Budget,
    cfg: CompareConfig | None = None,
) -> TsOutcome:
    cfg = cfg or CompareConfig()
    inputs = generate_ts_inputs(param_pools, budget)

    def batch(root: Path, subset: list[list[object]]) -> list[Observation]:
        payloads = _run_batch(root, rel_path, export_name, subset, sandbox, budget.seed)
        return [_observation(p) for p in payloads]

    try:
        base_one = batch(base_root, inputs)
        base_two = batch(base_root, inputs)  # L3: the base must agree with itself first
        for i, (a, b) in enumerate(zip(base_one, base_two, strict=True)):
            if isinstance(compare(a, b, cfg), Diverged):
                return TsOutcome(
                    verdict=Verdict.UNPROVEN,
                    reason_code=ReasonCode.NONDETERMINISTIC_BASE,
                    reason_detail=(
                        f"base disagrees with itself on input {json.dumps(inputs[i])} — "
                        "determinism could not be reached under the JS shims (wave 1 pins "
                        "Date/Math.random/performance/crypto only)"
                    ),
                    inputs_run=len(inputs),
                    equivalent_inputs=0,
                    unprovable_inputs=0,
                    changed_line_coverage=0.0,
                    divergences=(),
                )
        head_obs = batch(head_root, inputs)
    except TsImportFailed as err:
        return TsOutcome(
            verdict=Verdict.UNPROVEN,
            reason_code=ReasonCode.HARNESS_SYNTHESIS_FAILED,
            reason_detail=f"could not invoke `{export_name}` in `{rel_path}`: {err}",
            inputs_run=0,
            equivalent_inputs=0,
            unprovable_inputs=0,
            changed_line_coverage=0.0,
            divergences=(),
        )

    equivalent = 0
    unprovable = 0
    divergences: list[TsDivergenceFound] = []
    executed_union: set[int] = set()
    for i, (b_obs, h_obs) in enumerate(zip(base_one, head_obs, strict=True)):
        executed_union |= b_obs.executed_lines | h_obs.executed_lines
        result = compare(b_obs, h_obs, cfg)
        if isinstance(result, Equal):
            equivalent += 1
        elif isinstance(result, Unprovable):
            unprovable += 1
        elif isinstance(result, Diverged) and _confirm(  # pragma: no branch — the False
            # arm (a divergence that stops reproducing) is pinned DIRECTLY in
            # TestConfirmDiscipline; reaching it through this loop would need a divergence
            # that is deterministically flaky across fresh processes — a contradiction.
            base_root,
            head_root,
            rel_path,
            export_name,
            inputs[i],
            result,
            sandbox,
            budget.seed,
            cfg,
        ):
            divergences.append(
                TsDivergenceFound(
                    args_json=json.dumps(inputs[i]),
                    divergence_class=result.divergence_class,
                    severity=result.severity,
                    detail=result.detail,
                    base_summary=_summary(b_obs),
                    head_summary=_summary(h_obs),
                )
            )

    changed_hit = executed_union & changed_lines
    coverage = 100.0 * len(changed_hit) / len(changed_lines) if changed_lines else 0.0
    if divergences:
        return TsOutcome(
            verdict=Verdict.DIVERGENT,
            reason_code=None,
            reason_detail=None,
            inputs_run=len(inputs),
            equivalent_inputs=equivalent,
            unprovable_inputs=unprovable,
            changed_line_coverage=coverage,
            divergences=tuple(divergences),
        )
    if equivalent == 0:
        return TsOutcome(
            verdict=Verdict.UNPROVEN,
            reason_code=ReasonCode.VALUE_UNSERIALIZABLE,
            reason_detail=(
                f"0 of {len(inputs)} inputs produced a comparable observation "
                f"({unprovable} unprovable)"
            ),
            inputs_run=len(inputs),
            equivalent_inputs=0,
            unprovable_inputs=unprovable,
            changed_line_coverage=coverage,
            divergences=(),
        )
    return TsOutcome(
        verdict=Verdict.EQUIVALENT_UNDER_BUDGET,
        reason_code=None,
        reason_detail=None,
        inputs_run=len(inputs),
        equivalent_inputs=equivalent,
        unprovable_inputs=unprovable,
        changed_line_coverage=coverage,
        divergences=(),
    )


def _confirm(
    base_root: Path,
    head_root: Path,
    rel_path: str,
    export_name: str,
    args: list[object],
    first: Diverged,
    sandbox: Sandbox,
    seed: int,
    cfg: CompareConfig,
) -> bool:
    """A divergence is evidence only if it reproduces identically on fresh process pairs
    (§14.2's discipline, JS edition): same class both times, or it is flaky and discarded."""
    for _ in range(2):
        (b,) = (
            _observation(p)
            for p in _run_batch(base_root, rel_path, export_name, [args], sandbox, seed)
        )
        (h,) = (
            _observation(p)
            for p in _run_batch(head_root, rel_path, export_name, [args], sandbox, seed)
        )
        rerun = compare(b, h, cfg)
        if not isinstance(rerun, Diverged) or rerun.divergence_class != first.divergence_class:
            return False
    return True


def render_ts_repro_script(
    *,
    symbol: str,
    rel_path: str,
    export_name: str,
    args_json: str,
    base_sha: str,
    head_sha: str,
    base_summary: str,
    head_summary: str,
) -> str:
    """Self-contained node repro (L7): run from the repo root at either revision."""
    return f"""#!/usr/bin/env node
// Tempest minimized reproduction — `{symbol}` (TypeScript).
//
//   git checkout {base_sha[:12]} && node --experimental-strip-types this_file.mjs
//   git checkout {head_sha[:12]} && node --experimental-strip-types this_file.mjs
//
// Generated by Tempest. Evidence, not opinion.

import {{ pathToFileURL }} from "node:url";

const ARGS = {args_json};
const BASE_OBSERVED = {json.dumps(base_summary)};
const HEAD_OBSERVED = {json.dumps(head_summary)};

const mod = await import(pathToFileURL({json.dumps(rel_path)}).href);
const fn = mod[{json.dumps(export_name)}];
console.log(`calling {symbol}(${{JSON.stringify(ARGS).slice(1, -1)}})`);
try {{
  const result = await fn(...ARGS);
  console.log(`returned ${{JSON.stringify(result)}}`);
}} catch (err) {{
  console.log(`raised   ${{err?.constructor?.name}}: ${{err?.message}}`);
}}
console.log("");
console.log("tempest observed:");
console.log(`  base {base_sha[:12]}: ${{BASE_OBSERVED}}`);
console.log(`  head {head_sha[:12]}: ${{HEAD_OBSERVED}}`);
"""
