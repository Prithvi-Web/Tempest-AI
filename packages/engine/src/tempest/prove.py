"""The `tempest prove` pipeline: stages 1→9 wired end to end for one base..head pair."""

import os
from collections.abc import Callable
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
from tempest.config import is_ignored
from tempest.envrepro.worktree import MaterializedEnv, materialize
from tempest.execute.cancel import CancelScope, cancel_scope
from tempest.execute.dual import (
    FoundDivergence,
    TargetOutcome,
    prove_impure_target,
    prove_target,
)
from tempest.execute.powerstate import wait_while_paused
from tempest.execute.runner import PersistentWorker
from tempest.execute.sandbox import ProcessSandbox, Sandbox, SandboxSelection, select_sandbox
from tempest.generate.inputs import Budget
from tempest.generate.mining import mine_literals
from tempest.harness.llm import (
    InstanceAdapter,
    SynthesisDeclined,
    remediation_hint,
    synthesis_enabled,
    synthesize_instance_adapter,
)
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
from tempest.targets.diff import FileDiff, changed_files
from tempest.targets.symbols import (
    ClassifiedSymbol,
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
    ignore_globs: tuple[str, ...] = ()
    # L11: the scope a caller cancels from another thread (children die instantly, the prove
    # unwinds with ProveCancelled), and where battery/thermal pause reports its reason.
    cancel: CancelScope | None = None
    on_pause: Callable[[str], None] | None = None


@dataclass(frozen=True)
class ProveResult:
    bundle: RunBundle
    bundle_dir: Path
    zip_path: Path
    sandbox_kind: str
    sandbox_reason: str | None
    sandbox_tier: str = "unknown"
    sandbox_assurance: str = "unknown"


def _select_sandbox(repo: Path) -> SandboxSelection:
    """Pick the isolation backend and record its tier (ADR-0003/0008/0015):
    first-party fixtures → trusted ProcessSandbox; user repos → the tier ladder
    (T1 Docker → T2 Seatbelt → UNPROVEN). Never silently unsandboxed."""
    marker = repo / ".tempest-first-party"
    if (
        marker.exists()
        and marker.read_text(encoding="utf-8").strip() == _FIRST_PARTY_MARKER
        and os.environ.get("TEMPEST_DEV") == "1"
    ):
        return SandboxSelection(
            ProcessSandbox(), tier="fixture", kind="process-first-party", assurance="trusted"
        )
    # TEMPEST_DOCKER points at an alternative container binary (e.g. podman).
    # TEMPEST_NO_SEATBELT=1 forces the ladder past T2 — used by the escape suite to isolate a
    # tier under test, and to exercise the genuine no-tier (SANDBOX_UNAVAILABLE) path.
    return select_sandbox(
        docker_binary=os.environ.get("TEMPEST_DOCKER", "docker"),
        allow_seatbelt=os.environ.get("TEMPEST_NO_SEATBELT") != "1",
    )


def _module_name(rel_path: str) -> str:
    parts = Path(rel_path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def run_prove(cfg: ProveConfig) -> ProveResult:
    if cfg.cancel is None:
        return _run_prove(cfg)
    with cancel_scope(cfg.cancel):  # every child runner._spawn breeds registers here
        return _run_prove(cfg)


def _checkpoint(cfg: ProveConfig) -> None:
    """Between units of work (L11): unwind if cancelled, hold while on battery/thermal."""
    if cfg.cancel is not None:
        cfg.cancel.raise_if_cancelled()
    wait_while_paused(cancel=cfg.cancel, notify=cfg.on_pause)


def _run_prove(cfg: ProveConfig) -> ProveResult:
    repo = cfg.repo.resolve()
    cache = repo / ".tempest" / "cache"
    base_env = materialize(repo, cfg.base, cache)
    head_env = materialize(repo, cfg.head, cache)
    diffs = changed_files(repo, cfg.base, cfg.head, patterns=("*.py", "*.ts", "*.tsx"))
    selection = _select_sandbox(repo)
    sandbox = selection.sandbox
    sandbox_kind, sandbox_reason = selection.kind, selection.reason
    compare_cfg = CompareConfig(float_rel_tol=cfg.float_rel_tol)
    mined = mine_literals(head_env.worktree) if sandbox is not None else []

    records: list[TargetRecord] = []
    repro_scripts: dict[str, str] = {}

    for fd in diffs:
        if is_ignored(fd.path, cfg.ignore_globs):
            continue  # [ignore].globs in tempest.toml — the user declared this path out of scope
        if fd.status != "modified":
            # Added symbols/files have no base counterpart to differ FROM — new code cannot
            # change existing behavior by itself; its effect is proven through changed callers.
            # Deleted files likewise have no head side to execute.
            continue
        if fd.path.endswith((".ts", ".tsx")):
            # §14.1: TypeScript execution (record/replay + coverage) is not wired yet — the
            # change is surfaced as UNPROVEN, never silently out of scope.
            records.append(_ts_unexercised_record(fd))
            continue
        head_src = (head_env.worktree / fd.path).read_text(encoding="utf-8")
        base_symbols = all_symbol_names((base_env.worktree / fd.path).read_text(encoding="utf-8"))
        module = _module_name(fd.path)
        for sym in enclosing_symbols(head_src, set(fd.changed_head_lines)):
            _checkpoint(cfg)  # L11: cancellable + battery/thermal pause between targets
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
                    _unreachable_or_synthesized_record(
                        fd,
                        module,
                        sym,
                        classified,
                        head_src,
                        base_env,
                        head_env,
                        sandbox,
                        mined,
                        compare_cfg,
                        cfg,
                        repro_scripts,
                    )
                )
                continue
            changed_in_span = frozenset(
                line for line in fd.changed_head_lines if sym.span[0] <= line <= sym.span[1]
            )
            budget = Budget(max_inputs=cfg.max_inputs, seed=cfg.seed)
            if classified.classification is TargetClassification.IMPURE_RECORDABLE:
                outcome = prove_impure_target(
                    base_env.worktree,
                    head_env.worktree,
                    module,
                    sym.symbol,
                    changed_lines=changed_in_span,
                    sandbox=sandbox,
                    budget=budget,
                    mined=mined,
                    cfg=compare_cfg,
                )
            else:
                # One worker pair serves every batch for this target (spawn economics); the
                # 3x divergence confirmations inside stay on fresh process pairs (§14.2).
                with (
                    PersistentWorker(base_env.worktree, module, sym.symbol, sandbox) as base_worker,
                    PersistentWorker(head_env.worktree, module, sym.symbol, sandbox) as head_worker,
                ):
                    outcome = prove_target(
                        base_env.worktree,
                        head_env.worktree,
                        module,
                        sym.symbol,
                        changed_lines=changed_in_span,
                        sandbox=sandbox,
                        budget=budget,
                        mined=mined,
                        cfg=compare_cfg,
                        worker_pair=(base_worker, head_worker),
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
                    classification=classified.classification,
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
        sandbox_tier=selection.tier,
        sandbox_assurance=selection.assurance,
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
        sandbox_tier=selection.tier,
        sandbox_assurance=selection.assurance,
    )


def _ts_unexercised_record(fd: FileDiff) -> TargetRecord:
    return TargetRecord(
        file_path=fd.path,
        module=_module_name(fd.path),
        qualname="__file__",
        lang=Lang.TYPESCRIPT,
        classification=TargetClassification.UNREACHABLE,
        verdict=Verdict.UNPROVEN,
        reason_code=ReasonCode.RECORD_REPLAY_UNAVAILABLE,
        reason_detail=(
            f"`{fd.path}` changed but TypeScript execution (record/replay + coverage) is not "
            "wired yet (Phase 3, in progress) — this change was NOT exercised and is not "
            "being blessed"
        ),
        inputs_run=0,
        equivalent_inputs=0,
        unprovable_inputs=0,
        changed_line_coverage=0.0,
        divergences=(),
    )


def _is_instance_method(sym: SymbolSpan) -> bool:
    return sym.owner_class is not None and not sym.is_static and not sym.is_classmethod


def _unreachable_or_synthesized_record(
    fd: FileDiff,
    module: str,
    sym: SymbolSpan,
    classified: ClassifiedSymbol,
    head_src: str,
    base_env: MaterializedEnv,
    head_env: MaterializedEnv,
    sandbox: Sandbox,
    mined: list[object],
    compare_cfg: CompareConfig,
    cfg: ProveConfig,
    repro_scripts: dict[str, str],
) -> TargetRecord:
    """The honest ladder for an unreachable target: attempt AI constructor synthesis for
    instance methods (key configured → adapter → normal differential), state a declined
    adapter plainly, and otherwise keep TARGET_UNREACHABLE — with the remediation hint
    when a key would change the answer (HANDOFF-WORLD-CLASS 2.1)."""
    detail = classified.reason_detail or "target unreachable"
    if _is_instance_method(sym):
        outcome = synthesize_instance_adapter(
            cache_dir=cfg.repo / ".tempest" / "adapters",
            base_root=base_env.worktree,
            head_root=head_env.worktree,
            module=module,
            owner_class=sym.owner_class or "",
            method=sym.symbol.rsplit(".", 1)[-1],
            head_source=head_src,
            sandbox=sandbox,
            seed=cfg.seed,
        )
        if isinstance(outcome, InstanceAdapter):
            return _synthesized_record(
                fd,
                module,
                sym,
                outcome,
                base_env,
                head_env,
                sandbox,
                mined,
                compare_cfg,
                cfg,
                repro_scripts,
            )
        if isinstance(outcome, SynthesisDeclined):
            return _unproven_record(
                fd.path,
                module,
                sym,
                classified.classification,
                ReasonCode.SYNTHESIS_DECLINED,
                outcome.detail,
            )
        if not synthesis_enabled():
            detail += remediation_hint()
    return _unproven_record(
        fd.path,
        module,
        sym,
        classified.classification,
        classified.reason_code or ReasonCode.TARGET_UNREACHABLE,
        detail,
    )


def _synthesized_record(
    fd: FileDiff,
    module: str,
    sym: SymbolSpan,
    adapter: InstanceAdapter,
    base_env: MaterializedEnv,
    head_env: MaterializedEnv,
    sandbox: Sandbox,
    mined: list[object],
    compare_cfg: CompareConfig,
    cfg: ProveConfig,
    repro_scripts: dict[str, str],
) -> TargetRecord:
    """The normal differential, executed through the validated adapter. Coverage stays
    honest: the worker traces the REAL module\'s file (trace_module), so changed-line
    coverage and the coverage-guided top-up see the method the diff actually touched."""
    changed_in_span = frozenset(
        line for line in fd.changed_head_lines if sym.span[0] <= line <= sym.span[1]
    )
    budget = Budget(max_inputs=cfg.max_inputs, seed=cfg.seed)
    with (
        PersistentWorker(
            base_env.worktree, adapter.module, adapter.qualname, sandbox, trace_module=module
        ) as base_worker,
        PersistentWorker(
            head_env.worktree, adapter.module, adapter.qualname, sandbox, trace_module=module
        ) as head_worker,
    ):
        outcome = prove_target(
            base_env.worktree,
            head_env.worktree,
            adapter.module,
            adapter.qualname,
            changed_lines=changed_in_span,
            sandbox=sandbox,
            budget=budget,
            mined=mined,
            cfg=compare_cfg,
            worker_pair=(base_worker, head_worker),
            trace_module=module,
        )
    adapter_source = (head_env.worktree / f"{adapter.module}.py").read_text(encoding="utf-8")
    return _finished_record(
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
        classification=TargetClassification.SYNTHESIZED,
        exec_module=adapter.module,
        exec_qualname=adapter.qualname,
        adapter_source=adapter_source,
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
    *,
    classification: TargetClassification = TargetClassification.PURE_CANDIDATE,
    exec_module: str | None = None,
    exec_qualname: str | None = None,
    adapter_source: str | None = None,
) -> TargetRecord:
    # Synthesized targets execute through the adapter while keeping the REAL method as
    # their displayed identity — minimization and repros must use the executable pair.
    run_module = exec_module or module
    run_qualname = exec_qualname or sym.symbol
    divergence_records: list[DivergenceRecord] = []
    seen_minimized: set[tuple[DivergenceClass, str, str]] = set()
    for i, d in enumerate(outcome.divergences):
        minimized = _minimize(
            d, base_env, head_env, run_module, run_qualname, sandbox, compare_cfg, cfg
        )
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
            module=run_module,
            qualname=run_qualname,
            adapter_source=adapter_source,
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
        classification=classification,
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
    # One fresh worker pair per divergence: shrink probes share it (the same state model as
    # the detection batch), instead of paying two interpreter spawns per shrink attempt.
    with (
        PersistentWorker(base_env.worktree, module, qualname, sandbox) as base_worker,
        PersistentWorker(head_env.worktree, module, qualname, sandbox) as head_worker,
    ):

        def rerun(args_l: str, kwargs_l: str) -> Diverged | None:
            (b,) = base_worker.run([(args_l, kwargs_l)])
            (h,) = head_worker.run([(args_l, kwargs_l)])
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
