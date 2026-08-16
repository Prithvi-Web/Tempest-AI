"""`[roots] source` — monorepo modules become provable (HANDOFF-WORLD-CLASS 2.2).

A file at `packages/engine/src/tempest/model.py` is unimportable as
`packages.engine.src.tempest.model`, so every monorepo change used to land UNPROVEN on an
import failure. Configured source roots fix the whole chain: module derivation, worker
sys.path in both worktrees, coverage target-file resolution, and the standalone repro.

These tests also pin the config-resolution law the feature introduces: `run_prove` loads
`tempest.toml` ITSELF when the caller does not override — so the CLI, the desktop app, and
CI honor the same repo config instead of only the CLI (the pre-existing gap).
"""

import subprocess
from pathlib import Path

import pytest

from tempest.config import TempestConfig, TempestConfigError
from tempest.model import Verdict
from tempest.prove import ProveConfig, _module_name, run_prove


class TestRootsConfig:
    def _load(self, tmp_path: Path, body: str) -> TempestConfig:
        (tmp_path / "tempest.toml").write_text(body, encoding="utf-8")
        return TempestConfig.load(tmp_path)

    def test_source_roots_parse(self, tmp_path: Path) -> None:
        cfg = self._load(tmp_path, '[roots]\nsource = ["packages/engine/src"]\n')
        assert cfg.source_roots == ("packages/engine/src",)

    def test_trailing_slash_is_normalized(self, tmp_path: Path) -> None:
        cfg = self._load(tmp_path, '[roots]\nsource = ["libs/core/src/"]\n')
        assert cfg.source_roots == ("libs/core/src",)

    def test_absolute_path_is_rejected_with_the_fix_named(self, tmp_path: Path) -> None:
        with pytest.raises(TempestConfigError, match=r"\[roots\].source.*repo-relative"):
            self._load(tmp_path, '[roots]\nsource = ["/abs/path"]\n')

    def test_parent_escapes_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TempestConfigError, match=r"\[roots\].source"):
            self._load(tmp_path, '[roots]\nsource = ["a/../../b"]\n')

    def test_non_list_is_rejected_with_an_example(self, tmp_path: Path) -> None:
        with pytest.raises(TempestConfigError, match=r"list of .*strings"):
            self._load(tmp_path, '[roots]\nsource = "packages/engine/src"\n')

    def test_empty_string_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(TempestConfigError, match=r"\[roots\].source"):
            self._load(tmp_path, '[roots]\nsource = [""]\n')

    def test_unknown_key_error_names_the_roots_vocabulary(self, tmp_path: Path) -> None:
        with pytest.raises(TempestConfigError, match=r"\[roots\] source"):
            self._load(tmp_path, '[roots]\nsrc = ["x"]\n')


class TestModuleNameWithRoots:
    def test_configured_root_is_stripped(self) -> None:
        got = _module_name(
            "packages/engine/src/tempest/model.py", source_roots=("packages/engine/src",)
        )
        assert got == "tempest.model"

    def test_non_matching_path_keeps_the_bare_src_fallback(self) -> None:
        assert _module_name("src/foo.py", source_roots=("packages/engine/src",)) == "foo"

    def test_longest_root_wins(self) -> None:
        got = _module_name("a/b/src/m.py", source_roots=("a", "a/b/src"))
        assert got == "m"

    def test_root_matches_whole_path_segments_only(self) -> None:
        # "pack" must not swallow the "packages/" prefix.
        assert _module_name("packages/x.py", source_roots=("pack",)) == "packages.x"

    def test_a_file_exactly_at_a_root_path_is_not_swallowed(self) -> None:
        # `a/b.py` with root `a/b`: stripping would leave an empty module name.
        assert _module_name("a/b.py", source_roots=("a/b",)) == "a.b"


class TestWorktreeSelfDescription:
    def test_a_broken_historical_config_never_crashes_job_building(self, tmp_path: Path) -> None:
        """A revision whose tempest.toml is unparseable gets no extra roots — the honest
        UNPROVEN surfaces at import time; job building must not raise."""
        from tempest.execute.runner import _source_roots_of, _sys_path_for

        (tmp_path / "tempest.toml").write_text("not [ valid toml", encoding="utf-8")
        _source_roots_of.cache_clear()
        assert _sys_path_for(tmp_path) == [str(tmp_path)]
        _source_roots_of.cache_clear()

    def test_a_configured_root_missing_in_this_revision_is_skipped(self, tmp_path: Path) -> None:
        """The config names `libs/core/src` but this revision has no such directory (it
        predates the layout): sys.path gets only what exists — never a phantom entry."""
        from tempest.execute.runner import _source_roots_of, _sys_path_for

        (tmp_path / "tempest.toml").write_text(
            '[roots]\nsource = ["libs/core/src"]\n', encoding="utf-8"
        )
        _source_roots_of.cache_clear()
        assert _sys_path_for(tmp_path) == [str(tmp_path)]
        _source_roots_of.cache_clear()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


@pytest.fixture()
def monorepo(tmp_path: Path) -> Path:
    """A first-party micro-MONOREPO: the changed module lives under libs/core/src/."""
    repo = tmp_path / "mono"
    pkg = repo / "libs" / "core" / "src" / "calclib"
    pkg.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "tempest.toml").write_text('[roots]\nsource = ["libs/core/src"]\n', encoding="utf-8")
    (pkg / "__init__.py").write_text("")
    (pkg / "ops.py").write_text("def scale(x: int) -> int:\n    return x * 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    (pkg / "ops.py").write_text("def scale(x: int) -> int:\n    return x * 3 + 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")
    return repo


class TestMonorepoProve:
    def test_configured_root_makes_the_module_provable(
        self, monorepo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole chain: tempest.toml is honored by run_prove ITSELF (no CLI wiring),
        the module resolves as calclib.ops, the worker imports it in both worktrees, and
        the seeded change lands DIVERGENT with a self-contained repro."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        result = run_prove(
            ProveConfig(repo=monorepo, base="base", head="head", max_inputs=12, seed=0)
        )
        targets = {t.module: t for t in result.bundle.targets}
        assert "calclib.ops" in targets, sorted(targets)
        t = targets["calclib.ops"]
        assert t.verdict is Verdict.DIVERGENT
        # The repro must run from the repo root: the configured root rides inside it (L7).
        repro = result.bundle.repro_scripts[t.divergences[0].repro_filename]
        assert "libs/core/src" in repro
        compile(repro, "repro.py", "exec")

    def test_explicit_tuples_override_the_file_entirely(
        self, monorepo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller passing BOTH tuples (the CLI precedence contract) skips the file load —
        the run behaves exactly as configured, not as tempest.toml says."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        result = run_prove(
            ProveConfig(
                repo=monorepo,
                base="base",
                head="head",
                max_inputs=6,
                seed=0,
                ignore_globs=("libs/*",),
                source_roots=("libs/core/src",),
            )
        )
        # The explicit ignore wins even though the file's [ignore] has no such glob.
        assert result.bundle.targets == ()

    def test_ignore_globs_are_honored_without_the_cli(
        self, monorepo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unification pin: tempest.toml [ignore].globs now shapes DIRECT run_prove
        calls (the desktop/API path), not just CLI runs."""
        (monorepo / "tempest.toml").write_text(
            '[roots]\nsource = ["libs/core/src"]\n[ignore]\nglobs = ["libs/*"]\n',
            encoding="utf-8",
        )
        _git(monorepo, "add", "-A")
        _git(monorepo, "commit", "-m", "cfg", "--no-gpg-sign")
        _git(monorepo, "branch", "-f", "head")
        monkeypatch.setenv("TEMPEST_DEV", "1")
        result = run_prove(
            ProveConfig(repo=monorepo, base="base", head="head", max_inputs=12, seed=0)
        )
        assert all(not t.module.startswith("calclib") for t in result.bundle.targets)
