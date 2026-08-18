"""Stage 9: schema-versioned run bundles — one producer, many renderers (Law L7).

The writer enforces the spec-§7 integrity rule: a divergence without a minimized input and a
repro script does not get written. Round-trip is total: read(write(b)) == b."""

from pathlib import Path

import pytest

from tempest.bundle.bundle import (
    BundleIntegrityError,
    DivergenceRecord,
    RunBundle,
    RunManifest,
    TargetRecord,
    read_bundle,
    run_verdict,
    write_bundle,
)
from tempest.model import (
    BUNDLE_SCHEMA_VERSION,
    DivergenceClass,
    Lang,
    ReasonCode,
    Severity,
    TargetClassification,
    Verdict,
)


def _divergence(repro: str | None = "clamp_0.py") -> DivergenceRecord:
    return DivergenceRecord(
        divergence_class=DivergenceClass.RETURN_VALUE,
        severity=Severity.NORMAL,
        detail="return values differ",
        args_literal="(-7,)",
        kwargs_literal="{}",
        minimized_args="(0,)" if repro else None,
        minimized_kwargs="{}" if repro else None,
        shrink_path=("args[0]: -7→0",),
        base_summary="returned 0",
        head_summary="returned 1",
        repro_filename=repro,
    )


def _target(divs: tuple[DivergenceRecord, ...]) -> TargetRecord:
    return TargetRecord(
        file_path="m.py",
        module="m",
        qualname="clamp",
        lang=Lang.PYTHON,
        classification=TargetClassification.PURE_CANDIDATE,
        verdict=Verdict.DIVERGENT if divs else Verdict.EQUIVALENT_UNDER_BUDGET,
        reason_code=None,
        reason_detail=None,
        inputs_run=42,
        equivalent_inputs=40,
        unprovable_inputs=0,
        changed_line_coverage=1.0,
        divergences=divs,
    )


def _unproven_target() -> TargetRecord:
    return TargetRecord(
        file_path="n.py",
        module="n",
        qualname="closure.inner",
        lang=Lang.PYTHON,
        classification=TargetClassification.UNREACHABLE,
        verdict=Verdict.UNPROVEN,
        reason_code=ReasonCode.TARGET_UNREACHABLE,
        reason_detail="`inner` is a closure",
        inputs_run=0,
        equivalent_inputs=0,
        unprovable_inputs=0,
        changed_line_coverage=0.0,
        divergences=(),
    )


def _bundle() -> RunBundle:
    targets = (_target((_divergence(),)), _unproven_target())
    return RunBundle(
        manifest=RunManifest(
            schema_version=BUNDLE_SCHEMA_VERSION,
            engine_version="0.1.0",
            repo="pyfix",
            base_sha="a" * 40,
            head_sha="b" * 40,
            created_at="2026-08-13T00:00:00Z",
            verdict=run_verdict(targets),
            base_deps="no-lockfile",
            head_deps="no-lockfile",
            budget_max_inputs=300,
        ),
        targets=targets,
        repro_scripts={"clamp_0.py": "#!/usr/bin/env python3\nprint('repro')\n"},
    )


class TestRoundTrip:
    def test_read_write_read_is_identity(self, tmp_path: Path) -> None:
        bundle = _bundle()
        out = write_bundle(bundle, tmp_path / "run1")
        assert read_bundle(tmp_path / "run1") == bundle
        assert out.exists() and out.suffix == ".zip"

    def test_zip_contains_manifest_and_repros(self, tmp_path: Path) -> None:
        import zipfile

        out = write_bundle(_bundle(), tmp_path / "run1")
        names = zipfile.ZipFile(out).namelist()
        assert "manifest.json" in names
        assert "targets.json" in names
        assert "repros/clamp_0.py" in names


class TestIntegrity:
    def test_divergence_without_minimized_repro_is_refused(self, tmp_path: Path) -> None:
        bad = RunBundle(
            manifest=_bundle().manifest,
            targets=(_target((_divergence(repro=None),)),),
            repro_scripts={},
        )
        with pytest.raises(BundleIntegrityError):
            write_bundle(bad, tmp_path / "bad")

    def test_missing_repro_script_body_is_refused(self, tmp_path: Path) -> None:
        bundle = _bundle()
        stripped = RunBundle(manifest=bundle.manifest, targets=bundle.targets, repro_scripts={})
        with pytest.raises(BundleIntegrityError):
            write_bundle(stripped, tmp_path / "bad")


class TestRunVerdict:
    def test_error_outranks_everything(self) -> None:
        """Tempest's own failure is the loudest claim (L2): an ERROR target makes the RUN
        ERROR, even beside a divergence — a broken engine must never look like a finding."""
        error_target = TargetRecord(
            file_path="e.py",
            module="e",
            qualname="boom",
            lang=Lang.PYTHON,
            classification=TargetClassification.PURE_CANDIDATE,
            verdict=Verdict.ERROR,
            reason_code=None,
            reason_detail="internal trace recorded",
            inputs_run=1,
            equivalent_inputs=0,
            unprovable_inputs=0,
            changed_line_coverage=0.0,
            divergences=(),
        )
        assert run_verdict((error_target, _target((_divergence(),)))) is Verdict.ERROR

    def test_any_divergent_wins(self) -> None:
        assert run_verdict((_target((_divergence(),)), _unproven_target())) is Verdict.DIVERGENT

    def test_all_unproven_is_unproven(self) -> None:
        assert run_verdict((_unproven_target(),)) is Verdict.UNPROVEN

    def test_equivalent_plus_unproven_is_equivalent_under_budget(self) -> None:
        assert run_verdict((_target(()), _unproven_target())) is Verdict.EQUIVALENT_UNDER_BUDGET

    def test_no_targets_is_unproven(self) -> None:
        assert run_verdict(()) is Verdict.UNPROVEN
