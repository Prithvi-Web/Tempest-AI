"""The `tempest prove` pipeline: stages 1→9 wired end to end for one base..head pair."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import tempest
from tempest.bundle.bundle import (
    DivergenceRecord,
    RunBundle,
    RunManifest,
    TargetRecord,
    run_verdict,
    write_bundle,
)
from tempest.compare.compare import CompareConfig, Diverged, compare
from tempest.envrepro.worktree import MaterializedEnv, materialize
from tempest.execute.dual import FoundDivergence, TargetOutcome, prove_target
from tempest.execute.runner import run_batch
from tempest.execute.sandbox import DockerSandbox, ProcessSandbox, Sandbox
from tempest.generate.inputs import Budget
from tempest.generate.mining import mine_literals
from tempest.minimize.ddmin import minimize_input
from tempest.minimize.repro import render_repro_script
from tempest.model import (
    BUNDLE_SCHEMA_VERSION,
    DivergenceClass,
    Lang,
    ReasonCode,
    TargetClassification,
    Verdict,
)
from tempest.targets.diff import changed_files
from tempest.targets.symbols import (
    SymbolSpan,
    all_symbol_names,
    classify_symbol,
    enclosing_symbols,
)

_FIRST_PARTY_MARKER = "tempest-first-party-fixture-v1"


@dataclass(frozen=True)
class ProveConfig:
    repo: Path
    base: str
    head: str
    max_inputs: int = 300
    seed: int = 0
    float_rel_tol: float | None = None
    out: Path | None = None
    minimize_attempts: int = 60


@dataclass(frozen=True)
class ProveResult:
    bundle: RunBundle
    bundle_dir: Path
    zip_path: Path
    sandbox_kind: str
    sandbox_reason: str | None


def _select_sandbox(repo: Path) -> tuple[Sandbox | None, str, str | None]:
    """ADR-0003/ADR-0008: first-party fixtures run in ProcessSandbox; user repos require Docker;
    no Docker → no execution, UNPROVEN(SANDBOX_UNAVAILABLE). Never silently unsandboxed."""
    marker = repo / ".tempest-first-party"
    if (
        marker.exists()
        and marker.read_text(encoding="utf-8").strip() == _FIRST_PARTY_MARKER
        and os.environ.get("TEMPEST_DEV") == "1"
    ):
        return ProcessSandbox(), "process-first-party", None
    docker = DockerSandbox()
    if docker.available():
        return docker, "docker", None
    return (
        None,
        "none",
        "no container runtime found (Law L6 forbids unsandboxed execution of repo code) — "
        "install Docker Desktop or run inside CI with Docker available",
    )


def _module_name(rel_path: str) -> str:
    parts = Path(rel_path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def run_prove(cfg: ProveConfig) -> ProveResult:
    repo = cfg.repo.resolve()
    cache = repo / ".tempest" / "cache"
    base_env = materialize(repo, cfg.base, cache)
    head_env = materialize(repo, cfg.head, cache)
    diffs = changed_files(repo, cfg.base, cfg.head)
    sandbox, sandbox_kind, sandbox_reason = _select_sandbox(repo)
    compare_cfg = CompareConfig(float_rel_tol=cfg.float_rel_tol)
    mined = mine_literals(head_env.worktree) if sandbox is not None else []

    records: list[TargetRecord] = []
    repro_scripts: dict[str, str] = {}

    for fd in diffs:
        if fd.status != "modified":
            # Added symbols/files have no base counterpart to differ FROM — new code cannot
            # change existing behavior by itself; its effect is proven through changed callers.
            # Deleted files likewise have no head side to execute.
            continue
        head_src = (head_env.worktree / fd.path).read_text(encoding="utf-8")
        base_symbols = all_symbol_names((base_env.worktree / fd.path).read_text(encoding="utf-8"))
        module = _module_name(fd.path)
        for sym in enclosing_symbols(head_src, set(fd.changed_head_lines)):
            if sym.symbol not in base_symbols:
                continue  # head-only symbol: proven via its changed callers, not vs a void
            classified = classify_symbol(head_src, sym)
            if sandbox is None:
                records.append(
                    _unproven_record(
                        fd.path,
                        module,
                        sym,
                        classified.classification,
                        ReasonCode.SANDBOX_UNAVAILABLE,
                        sandbox_reason or "sandbox unavailable",
                    )
                )
                continue
            if classified.classification is TargetClassification.UNREACHABLE:
                records.append(
                    _unproven_record(
                        fd.path,
                        module,
                        sym,
                        classified.classification,
                        classified.reason_code or ReasonCode.TARGET_UNREACHABLE,
                        classified.reason_detail or "target unreachable",
                    )
                )
                continue
            if classified.classification is TargetClassification.IMPURE_RECORDABLE:
                records.append(
                    _unproven_record(
                        fd.path,
                        module,
                        sym,
                        classified.classification,
                        ReasonCode.RECORD_REPLAY_UNAVAILABLE,
                        f"`{module}.{sym.symbol}` touches recordable IO; the record/replay "
                        "determinism layer (Phase 2, docs/PLAN.md) is required to prove it. "
                        "Nothing is blessed meanwhile.",
                    )
                )
                continue

            changed_in_span = frozenset(
                line for line in fd.changed_head_lines if sym.span[0] <= line <= sym.span[1]
            )
            outcome = prove_target(
                base_env.worktree,
                head_env.worktree,
                module,
                sym.symbol,
                changed_lines=changed_in_span,
                sandbox=sandbox,
                budget=Budget(max_inputs=cfg.max_inputs, seed=cfg.seed),
                mined=mined,
                cfg=compare_cfg,
            )
            records.append(
                _finished_record(
                    fd.path,
                    module,
                    sym,
                    outcome,
                    base_env,
                    head_env,
                    sandbox,
                    compare_cfg,
                    cfg,
                    repro_scripts,
                )
            )

    targets = tuple(records)
    manifest = RunManifest(
        schema_version=BUNDLE_SCHEMA_VERSION,
        engine_version=tempest.__version__,
        repo=repo.name,
        base_sha=base_env.revision,
        head_sha=head_env.revision,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        verdict=run_verdict(targets),
        base_deps=base_env.deps_fingerprint,
        head_deps=head_env.deps_fingerprint,
        budget_max_inputs=cfg.max_inputs,
    )
    bundle = RunBundle(manifest=manifest, targets=targets, repro_scripts=repro_scripts)
    out_dir = cfg.out or (
        repo / ".tempest" / "runs" / f"{base_env.revision[:12]}-{head_env.revision[:12]}"
    )
    zip_path = write_bundle(bundle, out_dir)
    return ProveResult(
        bundle=bundle,
        bundle_dir=out_dir,
        zip_path=zip_path,
        sandbox_kind=sandbox_kind,
        sandbox_reason=sandbox_reason,
    )


def _unproven_record(
    file_path: str,
    module: str,
    sym: SymbolSpan,
    classification: TargetClassification,
    reason_code: ReasonCode,
    reason_detail: str,
) -> TargetRecord:
    return TargetRecord(
        file_path=file_path,
        module=module,
        qualname=sym.symbol,
        lang=Lang.PYTHON,
        classification=classification,
        verdict=Verdict.UNPROVEN,
        reason_code=reason_code,
        reason_detail=reason_detail,
        inputs_run=0,
        equivalent_inputs=0,
        unprovable_inputs=0,
        changed_line_coverage=0.0,
        divergences=(),
    )


def _finished_record(
    file_path: str,
    module: str,
    sym: SymbolSpan,
    outcome: TargetOutcome,
    base_env: MaterializedEnv,
    head_env: MaterializedEnv,
    sandbox: Sandbox,
    compare_cfg: CompareConfig,
    cfg: ProveConfig,
    repro_scripts: dict[str, str],
) -> TargetRecord:
    divergence_records: list[DivergenceRecord] = []
    seen_minimized: set[tuple[DivergenceClass, str, str]] = set()
    for i, d in enumerate(outcome.divergences):
        minimized = _minimize(d, base_env, head_env, module, sym.symbol, sandbox, compare_cfg, cfg)
        dedupe_key = (
            d.divergence_class,
            minimized.minimized_args or d.args_literal,
            minimized.minimized_kwargs or d.kwargs_literal,
        )
        if dedupe_key in seen_minimized:
            continue  # several raw inputs shrank to the same evidence — one exhibit suffices
        seen_minimized.add(dedupe_key)
        safe = f"{module}.{sym.symbol}".replace(".", "_")
        filename = f"{safe}_{i}.py"
        repro_scripts[filename] = render_repro_script(
            symbol=f"{module}.{sym.symbol}",
            module=module,
            qualname=sym.symbol,
            args_literal=minimized.minimized_args or d.args_literal,
            kwargs_literal=minimized.minimized_kwargs or d.kwargs_literal,
            divergence_class=d.divergence_class,
            base_sha=base_env.revision,
            head_sha=head_env.revision,
            base_summary=d.base_summary,
            head_summary=d.head_summary,
        )
        divergence_records.append(
            DivergenceRecord(
                divergence_class=d.divergence_class,
                severity=d.severity,
                detail=d.detail,
                args_literal=d.args_literal,
                kwargs_literal=d.kwargs_literal,
                minimized_args=minimized.minimized_args or d.args_literal,
                minimized_kwargs=minimized.minimized_kwargs or d.kwargs_literal,
                shrink_path=minimized.shrink_path,
                base_summary=d.base_summary,
                head_summary=d.head_summary,
                repro_filename=filename,
            )
        )
    return TargetRecord(
        file_path=file_path,
        module=module,
        qualname=sym.symbol,
        lang=Lang.PYTHON,
        classification=TargetClassification.PURE_CANDIDATE,
        verdict=outcome.verdict,
        reason_code=outcome.reason_code,
        reason_detail=outcome.reason_detail,
        inputs_run=outcome.inputs_run,
        equivalent_inputs=outcome.equivalent_inputs,
        unprovable_inputs=outcome.unprovable_inputs,
        changed_line_coverage=outcome.changed_line_coverage,
        divergences=tuple(divergence_records),
    )


def _minimize(
    d: FoundDivergence,
    base_env: MaterializedEnv,
    head_env: MaterializedEnv,
    module: str,
    qualname: str,
    sandbox: Sandbox,
    compare_cfg: CompareConfig,
    cfg: ProveConfig,
) -> "_Minimized":
    def rerun(args_l: str, kwargs_l: str) -> Diverged | None:
        (b,) = run_batch(base_env.worktree, module, qualname, [(args_l, kwargs_l)], sandbox)
        (h,) = run_batch(head_env.worktree, module, qualname, [(args_l, kwargs_l)], sandbox)
        result = compare(b, h, compare_cfg)
        return result if isinstance(result, Diverged) else None

    result = minimize_input(
        rerun, d.args_literal, d.kwargs_literal, max_attempts=cfg.minimize_attempts
    )
    if result is None:
        return _Minimized(d.args_literal, d.kwargs_literal, ())
    return _Minimized(result.args_literal, result.kwargs_literal, result.shrink_path)


@dataclass(frozen=True)
class _Minimized:
    minimized_args: str
    minimized_kwargs: str
    shrink_path: tuple[str, ...]
