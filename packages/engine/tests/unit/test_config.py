"""tempest.toml: precedence is CLI flag > file > built-in default; unknown keys are a hard,
fully listed error (error messages are the product); `[ignore].globs` remove files from the
diff walk with case-sensitive fnmatch semantics. The wiring test runs the real `tempest prove`
pipeline on a micro repo — no mocks (Law L4)."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tempest.cli.main import app
from tempest.config import (
    DEFAULT_MAX_INPUTS,
    TempestConfig,
    TempestConfigError,
    is_ignored,
)
from tempest.model import Verdict

runner = CliRunner()


class TestDefaults:
    def test_absent_file_means_pure_defaults(self, tmp_path: Path) -> None:
        cfg = TempestConfig.load(tmp_path)
        assert cfg == TempestConfig()
        assert cfg.max_inputs is None
        assert cfg.max_wall_seconds is None
        assert cfg.float_rel_tol is None
        assert cfg.ignore_globs == ()

    def test_effective_values_fall_back_to_built_ins(self, tmp_path: Path) -> None:
        cfg = TempestConfig.load(tmp_path)
        assert cfg.effective_max_inputs(None) == DEFAULT_MAX_INPUTS
        assert cfg.effective_float_rel_tol(None) is None


class TestLoad:
    def test_full_file_parses_every_section(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text(
            "[budgets]\n"
            "max_inputs = 50\n"
            "max_wall_seconds = 12.5\n"
            "[compare]\n"
            "float_rel_tol = 1e-9\n"
            "[ignore]\n"
            'globs = ["generated/*", "*_pb2.py"]\n',
            encoding="utf-8",
        )
        cfg = TempestConfig.load(tmp_path)
        assert cfg.max_inputs == 50
        assert cfg.max_wall_seconds == 12.5
        assert cfg.float_rel_tol == 1e-9
        assert cfg.ignore_globs == ("generated/*", "*_pb2.py")

    def test_partial_file_leaves_the_rest_unset(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets]\nmax_inputs = 7\n", encoding="utf-8")
        cfg = TempestConfig.load(tmp_path)
        assert cfg.max_inputs == 7
        assert cfg.max_wall_seconds is None
        assert cfg.float_rel_tol is None
        assert cfg.ignore_globs == ()

    def test_integer_wall_seconds_becomes_float(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text(
            "[budgets]\nmax_wall_seconds = 30\n", encoding="utf-8"
        )
        assert TempestConfig.load(tmp_path).max_wall_seconds == 30.0


class TestPrecedence:
    def test_cli_flag_beats_file_beats_default(self) -> None:
        cfg = TempestConfig(max_inputs=50, float_rel_tol=1e-9)
        assert cfg.effective_max_inputs(5) == 5  # CLI wins
        assert cfg.effective_max_inputs(None) == 50  # file wins over default
        assert TempestConfig().effective_max_inputs(None) == DEFAULT_MAX_INPUTS
        assert cfg.effective_float_rel_tol(1e-3) == 1e-3  # CLI wins
        assert cfg.effective_float_rel_tol(None) == 1e-9  # file wins
        assert TempestConfig().effective_float_rel_tol(None) is None


class TestUnknownKeys:
    def test_unknown_table_is_listed_with_the_valid_vocabulary(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[comparison]\nx = 1\n", encoding="utf-8")
        with pytest.raises(TempestConfigError) as exc:
            TempestConfig.load(tmp_path)
        message = str(exc.value)
        assert "[comparison]" in message
        assert "[budgets] max_inputs, max_wall_seconds" in message
        assert "[compare] float_rel_tol" in message
        assert "[ignore] globs" in message

    def test_unknown_key_inside_a_known_table_is_named_precisely(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets]\nmax_input = 10\n", encoding="utf-8")
        with pytest.raises(TempestConfigError, match=r"\[budgets\]\.max_input"):
            TempestConfig.load(tmp_path)

    def test_every_unknown_key_is_listed_at_once(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text(
            "[budgets]\nmax_input = 10\n[compare]\ntolerance = 0.1\n", encoding="utf-8"
        )
        with pytest.raises(TempestConfigError) as exc:
            TempestConfig.load(tmp_path)
        assert "[budgets].max_input" in str(exc.value)
        assert "[compare].tolerance" in str(exc.value)


class TestBadValues:
    def test_invalid_toml_syntax_is_reported_with_the_path(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets\n", encoding="utf-8")
        with pytest.raises(TempestConfigError, match="not valid TOML"):
            TempestConfig.load(tmp_path)

    def test_non_table_section_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text('budgets = "yes"\n', encoding="utf-8")
        with pytest.raises(TempestConfigError, match=r"\[budgets\] must be a TOML table"):
            TempestConfig.load(tmp_path)

    def test_string_max_inputs_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text('[budgets]\nmax_inputs = "lots"\n', encoding="utf-8")
        with pytest.raises(TempestConfigError, match="must be an integer"):
            TempestConfig.load(tmp_path)

    def test_bool_max_inputs_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets]\nmax_inputs = true\n", encoding="utf-8")
        with pytest.raises(TempestConfigError, match="must be an integer"):
            TempestConfig.load(tmp_path)

    def test_zero_max_inputs_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text("[budgets]\nmax_inputs = 0\n", encoding="utf-8")
        with pytest.raises(TempestConfigError, match="must be >= 1"):
            TempestConfig.load(tmp_path)

    def test_negative_float_tolerance_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text(
            "[compare]\nfloat_rel_tol = -0.5\n", encoding="utf-8"
        )
        with pytest.raises(TempestConfigError, match="must be >= 0"):
            TempestConfig.load(tmp_path)

    def test_zero_wall_seconds_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text(
            "[budgets]\nmax_wall_seconds = 0\n", encoding="utf-8"
        )
        with pytest.raises(TempestConfigError, match="must be > 0"):
            TempestConfig.load(tmp_path)

    def test_globs_must_be_an_array(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text('[ignore]\nglobs = "gen/*"\n', encoding="utf-8")
        with pytest.raises(TempestConfigError, match="must be an array of glob strings"):
            TempestConfig.load(tmp_path)

    def test_glob_entries_must_be_non_empty_strings(self, tmp_path: Path) -> None:
        (tmp_path / "tempest.toml").write_text('[ignore]\nglobs = ["ok", ""]\n', encoding="utf-8")
        with pytest.raises(TempestConfigError, match="non-empty strings"):
            TempestConfig.load(tmp_path)


class TestIgnoreGlobs:
    def test_fnmatch_semantics(self) -> None:
        globs = ("generated/*", "*_pb2.py", "vendor/lib.py")
        assert is_ignored("generated/schema.py", globs)
        assert is_ignored("generated/deep/nested.py", globs)  # `*` crosses `/`
        assert is_ignored("api_pb2.py", globs)
        assert is_ignored("proto/api_pb2.py", globs)
        assert is_ignored("vendor/lib.py", globs)
        assert not is_ignored("src/core.py", globs)
        assert not is_ignored("vendor/other.py", globs)

    def test_matching_is_case_sensitive_on_every_platform(self) -> None:
        assert not is_ignored("Generated/schema.py", ("generated/*",))

    def test_empty_globs_ignore_nothing(self) -> None:
        assert not is_ignored("anything.py", ())


def _micro_repo(tmp_path: Path) -> Path:
    """Two seeded behavior changes: one in core.py, one under generated/ (to be ignored)."""
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
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "generated").mkdir()
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    (repo / "generated" / "tables.py").write_text("def lookup(x: int) -> int:\n    return x\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    (repo / "generated" / "tables.py").write_text("def lookup(x: int) -> int:\n    return x + 1\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


class TestProveWiring:
    def test_tempest_toml_budget_and_ignore_globs_shape_the_run(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path)
        (repo / "tempest.toml").write_text(
            '[budgets]\nmax_inputs = 4\n[ignore]\nglobs = ["generated/*"]\n', encoding="utf-8"
        )
        os.environ["TEMPEST_DEV"] = "1"
        out_dir = tmp_path / "bundle-from-file"
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
                "--out",
                str(out_dir),
            ],
        )
        assert result.exit_code == 1, result.output  # core.double diverges
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["budget_max_inputs"] == 4  # file value applied, not the built-in 300
        targets = json.loads((out_dir / "targets.json").read_text(encoding="utf-8"))
        modules = {t["module"] for t in targets}
        assert "core" in modules
        assert "generated.tables" not in modules  # filtered by [ignore].globs
        assert any(t["module"] == "core" and t["verdict"] == Verdict.DIVERGENT for t in targets)

    def test_cli_flag_overrides_the_file_budget(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path)
        (repo / "tempest.toml").write_text(
            '[budgets]\nmax_inputs = 4\n[ignore]\nglobs = ["generated/*"]\n', encoding="utf-8"
        )
        os.environ["TEMPEST_DEV"] = "1"
        out_dir = tmp_path / "bundle-from-flag"
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
                "3",
                "--out",
                str(out_dir),
            ],
        )
        assert result.exit_code == 1, result.output
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["budget_max_inputs"] == 3

    def test_unknown_key_fails_the_run_before_any_execution(self, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path)
        (repo / "tempest.toml").write_text("[budgets]\nmax_input = 4\n", encoding="utf-8")
        result = runner.invoke(
            app, ["prove", "--base", "base", "--head", "head", "--repo", str(repo)]
        )
        assert result.exit_code == 2
        assert "max_input" in result.output
        assert "Valid keys" in result.output
