"""Run bundle schema + writer + reader (documented in docs/BUNDLE_SCHEMA.md).

One producer, many renderers: the CLI terminal report and the API ingester consume this exact
structure. Writer-enforced integrity: every divergence carries a minimized input and a repro
script or the bundle does not get written (spec §7 — a constraint, not a comment).
"""

import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from tempest.model import (
    BUNDLE_SCHEMA_VERSION,
    DivergenceClass,
    Lang,
    ReasonCode,
    Severity,
    TargetClassification,
    Verdict,
)


class BundleIntegrityError(Exception):
    pass


@dataclass(frozen=True)
class DivergenceRecord:
    divergence_class: DivergenceClass
    severity: Severity
    detail: str
    args_literal: str
    kwargs_literal: str
    minimized_args: str | None
    minimized_kwargs: str | None
    shrink_path: tuple[str, ...]
    base_summary: str
    head_summary: str
    repro_filename: str | None
    # Plain-English explanation generated FROM the evidence above by the user's own model
    # (BYOK, ADR-0029). Always labeled "AI narrative" on every surface; None when keyless
    # or when generation failed — the verdict and evidence never depend on it.
    ai_narrative: str | None = None


@dataclass(frozen=True)
class TargetRecord:
    file_path: str
    module: str
    qualname: str
    lang: Lang
    classification: TargetClassification
    verdict: Verdict
    reason_code: ReasonCode | None
    reason_detail: str | None
    inputs_run: int
    equivalent_inputs: int
    unprovable_inputs: int
    changed_line_coverage: float
    divergences: tuple[DivergenceRecord, ...]


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    engine_version: str
    repo: str
    base_sha: str
    head_sha: str
    created_at: str
    verdict: Verdict
    base_deps: str
    head_deps: str
    budget_max_inputs: int
    # The isolation tier this run actually used (ADR-0015). Recorded in every bundle so the tier
    # can never silently degrade unnoticed — it is surfaced in the CLI report, the UI, and CI.
    sandbox_tier: str = "unknown"
    sandbox_assurance: str = "unknown"


@dataclass(frozen=True)
class RunBundle:
    manifest: RunManifest
    targets: tuple[TargetRecord, ...]
    repro_scripts: dict[str, str]


def run_verdict(targets: tuple[TargetRecord, ...]) -> Verdict:
    if any(t.verdict is Verdict.ERROR for t in targets):
        return Verdict.ERROR
    if any(t.verdict is Verdict.DIVERGENT for t in targets):
        return Verdict.DIVERGENT
    if any(t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET for t in targets):
        return Verdict.EQUIVALENT_UNDER_BUDGET
    return Verdict.UNPROVEN


def _check_integrity(bundle: RunBundle) -> None:
    for target in bundle.targets:
        for d in target.divergences:
            where = f"{target.module}.{target.qualname}"
            if d.minimized_args is None or d.minimized_kwargs is None:
                raise BundleIntegrityError(
                    f"divergence in {where} has no minimized input — refusing to write (spec §7)"
                )
            if d.repro_filename is None:
                raise BundleIntegrityError(
                    f"divergence in {where} has no repro script — refusing to write (spec §7)"
                )
            if d.repro_filename not in bundle.repro_scripts:
                raise BundleIntegrityError(
                    f"repro script {d.repro_filename!r} for {where} missing from bundle"
                )


def write_bundle(bundle: RunBundle, out_dir: Path) -> Path:
    _check_integrity(bundle)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(
        json.dumps(asdict(bundle.manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "targets.json").write_text(
        json.dumps([asdict(t) for t in bundle.targets], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    repro_dir = out_dir / "repros"
    repro_dir.mkdir(exist_ok=True)
    for name, content in sorted(bundle.repro_scripts.items()):
        (repro_dir / name).write_text(content, encoding="utf-8")

    zip_path = out_dir.with_suffix(".tempest.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:

        def _add(path: Path, arcname: str) -> None:
            # The zip CONTAINER must be a pure function of bundle content (L7): entry
            # timestamps are pinned to the zip epoch and permissions to 0644, or re-zipping
            # identical content seconds apart yields different bytes — which broke delta
            # sync's content addressing on Linux CI (same-second timestamps hid it locally).
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

        _add(out_dir / "manifest.json", "manifest.json")
        _add(out_dir / "targets.json", "targets.json")
        for name in sorted(bundle.repro_scripts):
            _add(repro_dir / name, f"repros/{name}")
    return zip_path


def read_bundle(bundle_dir: Path) -> RunBundle:
    manifest_raw = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    targets_raw = json.loads((bundle_dir / "targets.json").read_text(encoding="utf-8"))
    repro_dir = bundle_dir / "repros"
    scripts = (
        {p.name: p.read_text(encoding="utf-8") for p in sorted(repro_dir.glob("*.py"))}
        if repro_dir.exists()
        else {}
    )
    return RunBundle(
        manifest=_manifest_from(manifest_raw),
        targets=tuple(_target_from(t) for t in targets_raw),
        repro_scripts=scripts,
    )


def _manifest_from(raw: dict[str, Any]) -> RunManifest:
    if raw["schema_version"] > BUNDLE_SCHEMA_VERSION:
        raise BundleIntegrityError(
            f"bundle schema v{raw['schema_version']} is newer than this engine understands "
            f"(v{BUNDLE_SCHEMA_VERSION}) — upgrade tempest"
        )
    return RunManifest(
        schema_version=int(raw["schema_version"]),
        engine_version=str(raw["engine_version"]),
        repo=str(raw["repo"]),
        base_sha=str(raw["base_sha"]),
        head_sha=str(raw["head_sha"]),
        created_at=str(raw["created_at"]),
        verdict=Verdict(raw["verdict"]),
        base_deps=str(raw["base_deps"]),
        head_deps=str(raw["head_deps"]),
        budget_max_inputs=int(raw["budget_max_inputs"]),
        # Forward-compatible read: a v1 bundle predates tiered sandboxing → "unknown".
        sandbox_tier=str(raw.get("sandbox_tier", "unknown")),
        sandbox_assurance=str(raw.get("sandbox_assurance", "unknown")),
    )


def _target_from(raw: dict[str, Any]) -> TargetRecord:
    return TargetRecord(
        file_path=str(raw["file_path"]),
        module=str(raw["module"]),
        qualname=str(raw["qualname"]),
        lang=Lang(raw["lang"]),
        classification=TargetClassification(raw["classification"]),
        verdict=Verdict(raw["verdict"]),
        reason_code=ReasonCode(raw["reason_code"]) if raw["reason_code"] else None,
        reason_detail=cast(str | None, raw["reason_detail"]),
        inputs_run=int(raw["inputs_run"]),
        equivalent_inputs=int(raw["equivalent_inputs"]),
        unprovable_inputs=int(raw["unprovable_inputs"]),
        changed_line_coverage=float(raw["changed_line_coverage"]),
        divergences=tuple(_divergence_from(d) for d in raw["divergences"]),
    )


def _divergence_from(raw: dict[str, Any]) -> DivergenceRecord:
    return DivergenceRecord(
        divergence_class=DivergenceClass(raw["divergence_class"]),
        severity=Severity(raw["severity"]),
        detail=str(raw["detail"]),
        args_literal=str(raw["args_literal"]),
        kwargs_literal=str(raw["kwargs_literal"]),
        minimized_args=cast(str | None, raw["minimized_args"]),
        minimized_kwargs=cast(str | None, raw["minimized_kwargs"]),
        shrink_path=tuple(raw["shrink_path"]),
        base_summary=str(raw["base_summary"]),
        head_summary=str(raw["head_summary"]),
        repro_filename=cast(str | None, raw["repro_filename"]),
        # v3 additive field: absent in v2-and-older bundles, None means "no narrative".
        ai_narrative=cast(str | None, raw.get("ai_narrative")),
    )
