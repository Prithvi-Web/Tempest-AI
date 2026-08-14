"""The terminal report (all verdict shapes, the un-missable NOT PROVEN panel) and the CLI
end-to-end — including the honest paths: SANDBOX_UNAVAILABLE, IMPURE_RECORDABLE,
UNREACHABLE."""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from tempest.bundle.bundle import RunBundle
from tempest.cli.main import app
from tempest.cli.report import render_report
from tempest.model import Verdict

from .test_bundle import _bundle, _target, _unproven_target

runner = CliRunner()


def _render(bundle: RunBundle) -> str:
    sink = io.StringIO()
    render_report(bundle, Console(file=sink, width=100, force_terminal=False))
    return sink.getvalue()


class TestRenderReport:
    def test_divergent_bundle_shows_evidence_and_not_proven_panel(self) -> None:
        out = _render(_bundle())
        assert "DIVERGENT" in out
        assert "(0,)" in out  # the minimized input is the evidence
        assert "NOT PROVEN" in out
        assert "TARGET_UNREACHABLE" in out
        assert "repros/clamp_0.py" in out

    def test_equivalent_bundle_states_the_caveat(self) -> None:
        from dataclasses import replace

        base = _bundle()
        targets = (_target(()),)
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.EQUIVALENT_UNDER_BUDGET),
            targets=targets,
            repro_scripts={},
        )
        out = _render(bundle)
        assert "EQUIVALENT_UNDER_BUDGET" in out
        assert "not" in out.lower() and "correct" in out.lower()

    def test_all_unproven_bundle_blesses_nothing(self) -> None:
        from dataclasses import replace

        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, verdict=Verdict.UNPROVEN),
            targets=(_unproven_target(),),
            repro_scripts={},
        )
        out = _render(bundle)
        assert "Nothing is blessed" in out

    def test_dependency_mismatch_is_surfaced(self) -> None:
        from dataclasses import replace

        base = _bundle()
        bundle = RunBundle(
            manifest=replace(base.manifest, head_deps="uv.lock:deadbeef"),
            targets=base.targets,
            repro_scripts=base.repro_scripts,
        )
        assert "dependencies changed" in _render(bundle)


def _micro_repo(tmp_path: Path, *, marker: bool) -> Path:
    """One behavior change + one impure change + one method change."""
    repo = tmp_path / "micro"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": "/usr/bin:/bin",
                "HOME": str(repo),
            },
        )

    git("init", "-b", "main")
    if marker:
        (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    (repo / "clock.py").write_text(
        "import time\n\n\ndef stamp() -> float:\n    return time.time()\n"
    )
    (repo / "obj.py").write_text("class Box:\n    def get(self) -> int:\n        return 1\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    (repo / "clock.py").write_text(
        "import time\n\n\ndef stamp() -> float:\n    return time.time() + 1\n"
    )
    (repo / "obj.py").write_text("class Box:\n    def get(self) -> int:\n        return 2\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


class TestCliProve:
    def test_prove_exits_1_on_divergence_with_full_honesty_report(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path, marker=True)
        os.environ["TEMPEST_DEV"] = "1"
        result = runner.invoke(
            app,
            ["prove", "--base", "base", "--head", "head", "--repo", str(repo), "--max-inputs", "6"],
        )
        assert result.exit_code == 1, result.output
        assert "DIVERGENT" in result.output
        assert "first-party fixture mode" in result.output
        # Phase 2: the impure clock.stamp target is now PROVEN via record/replay — the +1 shift
        # shows up as a genuine divergence rather than an unproven stub.
        assert "clock.stamp" in result.output
        assert "TARGET_UNREACHABLE" in result.output  # instance method, honestly unproven
        assert "NOT PROVEN" in result.output

    def test_prove_without_sandbox_is_unproven_never_unsandboxed(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path, marker=False)
        os.environ.pop("TEMPEST_DEV", None)
        os.environ["TEMPEST_DOCKER"] = "/nonexistent/docker"  # deterministic on Docker-equipped CI
        os.environ["TEMPEST_NO_SEATBELT"] = "1"  # force past T2 to reach the genuine no-tier path
        try:
            result = runner.invoke(
                app,
                [
                    "prove",
                    "--base",
                    "base",
                    "--head",
                    "head",
                    "--repo",
                    str(repo),
                    "--max-inputs",
                    "6",
                ],
            )
        finally:
            os.environ["TEMPEST_DEV"] = "1"
            del os.environ["TEMPEST_DOCKER"]
            del os.environ["TEMPEST_NO_SEATBELT"]
        assert result.exit_code == 0, result.output
        assert "UNPROVEN" in result.output
        assert "SANDBOX_UNAVAILABLE" in result.output
        assert "Nothing is blessed" in result.output

    def test_user_repo_runs_under_t2_seatbelt_on_macos(self, tmp_path: Path) -> None:
        """The Phase 10 product win: a user repo (no first-party marker) is contained by the
        macOS T2 Seatbelt backend with no Docker — real execution, real evidence, tier recorded."""
        if sys.platform != "darwin":
            pytest.skip("Seatbelt is macOS-only; other OS tiers are CI-gated")
        repo = _micro_repo(tmp_path, marker=False)  # NOT a first-party fixture
        os.environ.pop("TEMPEST_DEV", None)
        os.environ["TEMPEST_DOCKER"] = "/nonexistent/docker"
        try:
            result = runner.invoke(
                app,
                [
                    "prove",
                    "--base",
                    "base",
                    "--head",
                    "head",
                    "--repo",
                    str(repo),
                    "--max-inputs",
                    "8",
                ],
            )
        finally:
            os.environ["TEMPEST_DEV"] = "1"
            del os.environ["TEMPEST_DOCKER"]
        assert result.exit_code == 1, result.output  # DIVERGENT (core.double changed)
        assert "DIVERGENT" in result.output
        assert "T2" in result.output and "Seatbelt" in result.output
        assert "SANDBOX_UNAVAILABLE" not in result.output

    def test_version_flag_still_works(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0


class TestCliEnvReproduction:
    def test_unknown_ref_is_env_reproduction_failed_not_a_traceback(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path, marker=True)
        os.environ["TEMPEST_DEV"] = "1"
        result = runner.invoke(
            app,
            ["prove", "--base", "no-such-ref", "--head", "head", "--repo", str(repo)],
        )
        assert result.exit_code == 2, result.output
        assert "ENV_REPRODUCTION_FAILED" in result.output
        assert "no-such-ref" in result.output  # names the ref so the fix is obvious
