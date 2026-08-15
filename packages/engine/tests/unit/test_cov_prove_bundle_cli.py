"""Prove-pipeline scope honesty (added/deleted files, src layout, unreproducible divergence),
bundle-writer integrity, and CLI honesty surfaces: schema refusal, reduced-assurance flag,
missing repro scripts in CI comments, and doctor's real failure probes."""

import io
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from tempest.bundle.bundle import BundleIntegrityError, RunBundle, write_bundle
from tempest.cli.ci_comment import render_ci_comment
from tempest.cli.doctor import _data_dir_writable, _execution_smoke, _git_version
from tempest.cli.main import app
from tempest.cli.report import render_report
from tempest.compare.compare import CompareConfig
from tempest.envrepro.worktree import MaterializedEnv
from tempest.execute.dual import FoundDivergence
from tempest.execute.sandbox import ProcessSandbox
from tempest.model import BUNDLE_SCHEMA_VERSION, DivergenceClass, Severity, Verdict
from tempest.prove import ProveConfig, _minimize, _module_name, run_prove

from .test_bundle import _bundle, _divergence, _target
from .test_targets_diff import commit_head, make_repo

runner = CliRunner()

_MARKER = "tempest-first-party-fixture-v1"


class TestModuleName:
    def test_src_layout_prefix_is_stripped(self) -> None:
        assert _module_name("src/pkg/mod.py") == "pkg.mod"

    def test_flat_layout_maps_directly(self) -> None:
        assert _module_name("pkg/mod.py") == "pkg.mod"
        assert _module_name("m.py") == "m"


class TestProveScopeAddedDeleted:
    def test_added_and_deleted_files_produce_no_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # New code has no base counterpart to differ FROM; deleted code has no head side to
        # execute. Neither may fabricate a record — and an empty run is UNPROVEN, not blessed.
        repo = make_repo(
            tmp_path,
            {
                "keep.py": "def f(x):\n    return x\n",
                "gone.py": "def g(x):\n    return x\n",
            },
        )
        (repo / ".tempest-first-party").write_text(_MARKER + "\n")
        commit_head(repo, {"new.py": "def h(x):\n    return x * 2\n"}, delete=["gone.py"])
        monkeypatch.setenv("TEMPEST_DEV", "1")
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=4))
        assert result.bundle.targets == ()
        assert result.bundle.manifest.verdict is Verdict.UNPROVEN
        assert result.zip_path.exists()


class TestUnreproducibleDivergence:
    def test_minimize_keeps_the_original_input_when_nothing_reproduces(
        self, tmp_path: Path
    ) -> None:
        # Base and head are IDENTICAL, so the claimed divergence cannot reproduce; the
        # minimizer must fall back to the original input as the evidence, untouched.
        src = "def f(x):\n    return x + 1\n"
        base_dir, head_dir = tmp_path / "base", tmp_path / "head"
        for d in (base_dir, head_dir):
            d.mkdir()
            (d / "m.py").write_text(src)

        def env(worktree: Path, sha: str) -> MaterializedEnv:
            return MaterializedEnv(
                revision=sha * 40,
                worktree=worktree,
                python=Path(sys.executable),
                env={},
                deps_fingerprint="no-lockfile",
            )

        claimed = FoundDivergence(
            args_literal="(3,)",
            kwargs_literal="{}",
            divergence_class=DivergenceClass.RETURN_VALUE,
            severity=Severity.NORMAL,
            detail="claimed but not reproducible",
            base_summary="returned 4",
            head_summary="returned 5",
        )
        cfg = ProveConfig(repo=tmp_path, base="base", head="head", minimize_attempts=5)
        out = _minimize(
            claimed,
            env(base_dir, "a"),
            env(head_dir, "b"),
            "m",
            "f",
            ProcessSandbox(),
            CompareConfig(),
            cfg,
        )
        assert out.minimized_args == "(3,)"
        assert out.minimized_kwargs == "{}"
        assert out.shrink_path == ()


class TestBundleIntegrity:
    def test_divergence_with_minimized_input_but_no_repro_is_refused(self, tmp_path: Path) -> None:
        bad = RunBundle(
            manifest=_bundle().manifest,
            targets=(_target((replace(_divergence(), repro_filename=None),)),),
            repro_scripts={},
        )
        with pytest.raises(BundleIntegrityError, match="no repro script"):
            write_bundle(bad, tmp_path / "bad")


class TestCiCommentCli:
    def test_bundle_from_a_newer_engine_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "run"
        bundle_dir.mkdir()
        (bundle_dir / "manifest.json").write_text(
            f'{{"schema_version": {BUNDLE_SCHEMA_VERSION + 1}}}\n'
        )
        (bundle_dir / "targets.json").write_text("[]\n")
        result = runner.invoke(app, ["ci-comment", "--bundle", str(bundle_dir)])
        assert result.exit_code == 2
        assert "error:" in result.stderr
        assert "upgrade tempest" in result.stderr


class TestCiCommentRenderer:
    def test_missing_repro_script_is_flagged_and_no_shrink_line_when_unminimized(self) -> None:
        d = replace(
            _divergence(),
            minimized_args="(-7,)",  # identical to args_literal → nothing was shrunk
            minimized_kwargs="{}",
            shrink_path=(),
            repro_filename="ghost.py",  # not present in repro_scripts
        )
        bundle = RunBundle(manifest=_bundle().manifest, targets=(_target((d,)),), repro_scripts={})
        out = render_ci_comment(bundle)
        assert "missing from this bundle" in out
        assert "unverified until re-run" in out
        assert "Found via" not in out, "an unshrunk input must not claim a shrink history"


class TestReducedAssuranceFlag:
    def test_reduced_assurance_tier_is_impossible_to_miss(self) -> None:
        bundle = _bundle()
        flagged = RunBundle(
            manifest=replace(bundle.manifest, sandbox_tier="T3", sandbox_assurance="reduced"),
            targets=bundle.targets,
            repro_scripts=bundle.repro_scripts,
        )
        sink = io.StringIO()
        render_report(flagged, Console(file=sink, width=120, force_terminal=False))
        assert "REDUCED ASSURANCE" in sink.getvalue()


class TestDoctorProbes:
    def test_git_unspawnable_reports_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))  # a PATH where git truly cannot spawn
        assert _git_version() is None

    def test_execution_smoke_fails_when_the_interpreter_cannot_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "executable", str(tmp_path / "missing-python"))
        assert _execution_smoke() is False

    def test_unwritable_data_dir_reports_false(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where the data dir should be\n")
        assert _data_dir_writable(blocker) is False
