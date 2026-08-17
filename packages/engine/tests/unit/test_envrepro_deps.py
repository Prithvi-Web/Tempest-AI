"""envrepro/deps.py — stage-2 environment reproduction, the security-first slice.

The laws this layer must never bend: repo code is NEVER executed during materialization
(metadata comes from static pyproject.toml parsing; dependencies install as WHEELS only),
and the default run is OFFLINE (fetch is an explicit opt-in; the cache makes later runs
offline again). Every test here is hermetic — a local wheel + --no-index, zero PyPI.
"""

import zipfile
from pathlib import Path

import pytest

from tempest.envrepro.deps import DepsResult, materialize_deps, project_metadata


def _pyproject(worktree: Path, body: str) -> None:
    worktree.mkdir(parents=True, exist_ok=True)
    (worktree / "pyproject.toml").write_text(body, encoding="utf-8")


def _local_wheel(directory: Path, name: str = "tinydep", version: str = "1.0.0") -> Path:
    """A REAL importable wheel built by hand — no network, no build backends."""
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    dist_info = f"{name}-{version}.dist-info"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(f"{name}/__init__.py", "ANSWER = 41\n")
        zf.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        zf.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr(f"{dist_info}/RECORD", "")
    return wheel


class TestProjectMetadata:
    def test_static_name_version_and_deps(self, tmp_path: Path) -> None:
        _pyproject(
            tmp_path,
            '[project]\nname = "mypkg"\nversion = "2.5.0"\ndependencies = ["tinydep>=1"]\n',
        )
        meta = project_metadata(tmp_path)
        assert meta is not None
        assert (meta.name, meta.version) == ("mypkg", "2.5.0")
        assert meta.dependencies == ("tinydep>=1",)

    def test_no_pyproject_is_none(self, tmp_path: Path) -> None:
        assert project_metadata(tmp_path) is None

    def test_dynamic_version_still_yields_a_shim_version(self, tmp_path: Path) -> None:
        _pyproject(
            tmp_path,
            '[project]\nname = "mypkg"\ndynamic = ["version"]\n',
        )
        meta = project_metadata(tmp_path)
        assert meta is not None
        assert meta.name == "mypkg"
        assert meta.version  # a placeholder version is still a valid metadata answer

    def test_broken_toml_is_none_never_a_crash(self, tmp_path: Path) -> None:
        _pyproject(tmp_path, "not [ valid")
        assert project_metadata(tmp_path) is None


class TestMaterializeDeps:
    def test_shim_makes_importlib_metadata_answer(self, tmp_path: Path) -> None:
        """The target package's dist-info shim exists with the STATIC version — code keeps
        importing from the worktree; only metadata lookups are satisfied."""
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "mypkg"\nversion = "2.5.0"\n')
        result = materialize_deps(wt, tmp_path / "cache", fetch=False)
        assert isinstance(result, DepsResult)
        assert result.site_dir is not None
        meta = result.site_dir / "mypkg-2.5.0.dist-info" / "METADATA"
        assert meta.exists()
        assert "Name: mypkg" in meta.read_text()
        assert result.detail is None

    def test_no_pyproject_means_nothing_to_do(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        result = materialize_deps(wt, tmp_path / "cache", fetch=False)
        assert result.site_dir is None
        assert result.detail is None

    def test_wheel_deps_install_from_a_local_index_offline(self, tmp_path: Path) -> None:
        """Real `uv pip install --target` against --find-links + --no-index: the wheel
        lands importable in the site dir with zero network."""
        wheels = tmp_path / "wheelhouse"
        _local_wheel(wheels)
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "mypkg"\nversion = "1.0"\ndependencies = ["tinydep"]\n')
        result = materialize_deps(wt, tmp_path / "cache", fetch=False, find_links=wheels)
        assert result.site_dir is not None, result.detail
        assert (result.site_dir / "tinydep" / "__init__.py").exists()
        assert result.detail is None

    def test_missing_wheels_offline_yield_the_fetch_remediation(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        _pyproject(
            wt,
            '[project]\nname = "mypkg"\nversion = "1.0"\n'
            'dependencies = ["definitely-not-cached-anywhere-xyz"]\n',
        )
        result = materialize_deps(wt, tmp_path / "cache", fetch=False)
        # The shim still exists (it can only help); the failure is stated with the fix.
        assert result.site_dir is not None
        assert result.detail is not None
        assert "TEMPEST_FETCH_DEPS" in result.detail or "--fetch-deps" in result.detail

    def test_second_call_reuses_the_cache_dir(self, tmp_path: Path) -> None:
        wheels = tmp_path / "wheelhouse"
        _local_wheel(wheels)
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "mypkg"\nversion = "1.0"\ndependencies = ["tinydep"]\n')
        first = materialize_deps(wt, tmp_path / "cache", fetch=False, find_links=wheels)
        marker = first.site_dir / "reuse-canary"  # type: ignore[union-attr]  # asserted non-None below
        assert first.site_dir is not None
        marker.write_text("x")
        second = materialize_deps(wt, tmp_path / "cache", fetch=False, find_links=wheels)
        assert second.site_dir == first.site_dir
        assert marker.exists()  # not rebuilt — the cache IS the offline story


@pytest.fixture(autouse=True)
def _no_ambient_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_FETCH_DEPS", raising=False)


def _git_repo(worktree: Path, tag: str | None = None) -> None:
    import subprocess

    env = {
        "PATH": "/usr/bin:/bin",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(worktree), *args], check=True, capture_output=True, env=env
        )

    git("init", "-b", "main")
    git("add", "-A")
    git("commit", "-m", "x", "--no-gpg-sign")
    if tag:
        git("tag", tag)


class TestVersionFileShim:
    """The humanize failure mode: `from ._version import __version__` where _version.py is
    generated at BUILD time (hatch-vcs / setuptools-scm) and absent from the git tree."""

    def _pkg(self, tmp_path: Path, init_body: str) -> Path:
        wt = tmp_path / "wt"
        pkg = wt / "src" / "mypkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(init_body, encoding="utf-8")
        _pyproject(wt, '[project]\nname = "mypkg"\ndynamic = ["version"]\n')
        return wt

    def test_missing_generated_version_module_gets_a_shim_from_git_describe(
        self, tmp_path: Path
    ) -> None:
        wt = self._pkg(tmp_path, "from ._version import __version__\n")
        _git_repo(wt, tag="v4.16.0")
        materialize_deps(wt, tmp_path / "cache", fetch=False)
        shim = wt / "src" / "mypkg" / "_version.py"
        assert shim.exists()
        text = shim.read_text()
        assert "4.16.0" in text  # the tag IS the honest version source (what vcs tools use)
        assert "__version__" in text and "version_tuple" in text

    def test_existing_version_module_is_never_touched(self, tmp_path: Path) -> None:
        wt = self._pkg(tmp_path, "from ._version import __version__\n")
        (wt / "src" / "mypkg" / "_version.py").write_text("__version__ = 'real'\n")
        _git_repo(wt)
        materialize_deps(wt, tmp_path / "cache", fetch=False)
        assert (wt / "src" / "mypkg" / "_version.py").read_text() == "__version__ = 'real'\n"

    def test_package_without_version_import_is_untouched(self, tmp_path: Path) -> None:
        wt = self._pkg(tmp_path, "X = 1\n")
        _git_repo(wt)
        materialize_deps(wt, tmp_path / "cache", fetch=False)
        assert not (wt / "src" / "mypkg" / "_version.py").exists()


class TestSetupPyFallback:
    """The slugify failure mode: no pyproject at all — setup.py holds the metadata. Parsed
    by AST ONLY (literal kwargs); anything dynamic is skipped, never executed."""

    def test_literal_kwargs_parse(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "from setuptools import setup\n"
            "setup(\n"
            "    name='python-slugify',\n"
            "    version='8.0.4',\n"
            "    install_requires=['text-unidecode>=1.3'],\n"
            ")\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None
        assert meta.name == "python-slugify"
        assert meta.version == "8.0.4"
        assert meta.dependencies == ("text-unidecode>=1.3",)

    def test_dynamic_values_are_skipped_never_executed(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "import os\nfrom setuptools import setup\n"
            "setup(name='pkg', version=os.environ['V'], install_requires=compute())\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None
        assert meta.name == "pkg"
        assert meta.dependencies == ()  # dynamic list: skipped, not guessed

    def test_pyproject_wins_over_setup_py(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "frompy"\nversion = "1.0"\n')
        (wt / "setup.py").write_text("setup(name='fromsetup')\n", encoding="utf-8")
        meta = project_metadata(wt)
        assert meta is not None and meta.name == "frompy"


class TestSetupPyConstantFolding:
    """slugify's real shape: install_requires = ['literal'] assigned at module level and
    referenced by name in setup(); name= comes from an exec'd file (never resolvable
    statically — and we never execute). Deps must still materialize; only the dist-info
    shim (which needs the name) is skipped."""

    def test_variable_referenced_literal_list_resolves(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "install_requires = ['text-unidecode>=1.3']\n"
            "about = {}\n"
            "setup(name=about['__title__'], version=about['__version__'], "
            "install_requires=install_requires)\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None
        assert meta.name is None  # honestly unknown — never guessed, never executed
        assert meta.dependencies == ("text-unidecode>=1.3",)

    def test_nameless_metadata_still_materializes_deps(self, tmp_path: Path) -> None:
        wheels = tmp_path / "wheelhouse"
        _local_wheel(wheels)
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "deps = ['tinydep']\nsetup(name=dynamic(), install_requires=deps)\n",
            encoding="utf-8",
        )
        result = materialize_deps(wt, tmp_path / "cache", fetch=False, find_links=wheels)
        assert result.site_dir is not None, result.detail
        assert (result.site_dir / "tinydep" / "__init__.py").exists()
        shims = [
            p
            for p in result.site_dir.glob("*.dist-info/INSTALLER")
            if "tempest-shim" in p.read_text()
        ]
        assert not shims  # the wheel's own dist-info is real; OUR shim needs a name


class TestEdgeArms:
    """The give-up and failure arms the 100% gate named — each one is an honesty surface."""

    def test_pyproject_without_a_name_is_none(self, tmp_path: Path) -> None:
        _pyproject(tmp_path, '[project]\nversion = "1.0"\n')
        assert project_metadata(tmp_path) is None

    def test_non_string_version_gets_the_placeholder(self, tmp_path: Path) -> None:
        _pyproject(tmp_path, '[project]\nname = "p"\nversion = 2\n')
        meta = project_metadata(tmp_path)
        assert meta is not None and meta.version.startswith("0.0.0+")

    def test_missing_uv_binary_is_a_stated_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempest.envrepro.deps as deps_mod

        monkeypatch.setattr(deps_mod.shutil, "which", lambda _: None)
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "p"\nversion = "1"\ndependencies = ["x"]\n')
        result = materialize_deps(wt, tmp_path / "cache", fetch=False)
        assert result.detail is not None and "uv" in result.detail

    def test_fetch_mode_failure_names_the_fetch_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("UV_NO_INDEX", "1")  # fetch=True but no index reachable — hermetic
        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "p"\nversion = "1"\ndependencies = ["no-such-dep-xyz"]\n')
        result = materialize_deps(wt, tmp_path / "cache", fetch=True)
        assert result.detail is not None and "with fetching" in result.detail

    def test_reattach_is_idempotent_and_clears_stale_notes(self, tmp_path: Path) -> None:
        from tempest.envrepro.deps import attach_deps

        wt = tmp_path / "wt"
        _pyproject(wt, '[project]\nname = "p"\nversion = "1"\ndependencies = ["nope-xyz"]\n')
        first = attach_deps(wt, tmp_path / "cache", fetch=False)
        assert first.detail is not None and (wt / ".tempest-deps-note").exists()
        _pyproject(wt, '[project]\nname = "p"\nversion = "1"\n')  # deps dropped upstream
        second = attach_deps(wt, tmp_path / "cache", fetch=False)
        assert second.detail is None
        assert not (wt / ".tempest-deps-note").exists()  # stale note gone
        assert (wt / ".tempest-deps").is_dir()  # re-linked, not duplicated

    def test_git_describe_failure_arms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tempest.envrepro.deps import _git_describe_version

        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        assert _git_describe_version(not_a_repo) is None  # git exits non-zero
        monkeypatch.setenv("PATH", "/nonexistent")
        assert _git_describe_version(not_a_repo) is None  # git unfindable → OSError arm

    def test_undecodable_init_and_stray_dirs_are_skipped(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        pkg = wt / "src" / "binpkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_bytes(b"\xff\xfe broken \xff")
        (wt / "src" / "not-a-package").mkdir()  # no __init__.py — skipped
        _pyproject(wt, '[project]\nname = "binpkg"\ndynamic = ["version"]\n')
        result = materialize_deps(wt, tmp_path / "cache", fetch=False)  # must not raise
        assert result.site_dir is not None
        assert not (pkg / "_version.py").exists()

    def test_unparseable_setup_py_is_none(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text("def broken(:", encoding="utf-8")
        assert project_metadata(wt) is None

    def test_attribute_form_setup_call_counts(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "import setuptools\nsetuptools.setup(name='attrpkg', version='1.0')\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None and meta.name == "attrpkg"

    def test_setup_with_nothing_static_is_none(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text("setup(name=dyn(), install_requires=dyn2())\n")
        assert project_metadata(wt) is None

    def test_odd_assignments_and_mixed_lists_fold_to_nothing(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "a, b = 1, 2\nx = [1, 'mixed']\nsetup(name='oddpkg', install_requires=x)\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None
        assert meta.name == "oddpkg"
        assert meta.dependencies == ()  # the mixed list folds to nothing, never guessed


class TestFinalArms:
    def test_project_key_not_a_table_falls_to_setup_py(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "pyproject.toml").write_text('project = "not-a-table"\n', encoding="utf-8")
        (wt / "setup.py").write_text("setup(name='fallback', version='1')\n", encoding="utf-8")
        meta = project_metadata(wt)
        assert meta is not None and meta.name == "fallback"

    def test_attach_on_a_repo_with_no_metadata_leaves_nothing(self, tmp_path: Path) -> None:
        from tempest.envrepro.deps import attach_deps

        wt = tmp_path / "wt"
        wt.mkdir()
        result = attach_deps(wt, tmp_path / "cache", fetch=False)
        assert result.site_dir is None
        assert not (wt / ".tempest-deps").exists()
        assert not (wt / ".tempest-deps-note").exists()

    def test_deps_note_reads_and_empty_arms(self, tmp_path: Path) -> None:
        from tempest.envrepro.deps import deps_note

        assert deps_note(tmp_path) is None
        (tmp_path / ".tempest-deps-note").write_text("  \n", encoding="utf-8")
        assert deps_note(tmp_path) is None  # whitespace-only note is no note
        (tmp_path / ".tempest-deps-note").write_text("fetch it\n", encoding="utf-8")
        assert deps_note(tmp_path) == "fetch it"

    def test_non_setup_calls_are_skipped(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text(
            "print('hello')\nconfigure()\nsetup(name='afterothers', version='1')\n",
            encoding="utf-8",
        )
        meta = project_metadata(wt)
        assert meta is not None and meta.name == "afterothers"

    def test_module_without_any_setup_call_is_none(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "setup.py").write_text("X = 1\nprint(X)\n", encoding="utf-8")
        assert project_metadata(wt) is None
