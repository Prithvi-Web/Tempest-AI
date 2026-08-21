"""THE ENV-REPRODUCTION GATE (ADR-0027): the two real-world import killers, fixed and
proven through full `run_prove` — keyless, offline, hermetic (local wheelhouse, no PyPI).

(a) humanize's failure mode: module-level `importlib.metadata.version(<own package>)` —
    the static dist-info shim satisfies it while code imports from the worktree → DIVERGENT.
(b) slugify's failure mode: a third-party import — absent wheels land honest UNPROVEN with
    the exact fetch remediation; with wheels reachable (local find-links standing in for
    the uv cache), the same repo proves DIVERGENT.
"""

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from tempest.model import Verdict
from tempest.prove import ProveConfig, run_prove


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


def _repo(tmp_path: Path, files: dict[str, str], head_files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    for rel, content in head_files.items():
        (repo / rel).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")
    return repo


def _wheelhouse(tmp_path: Path) -> Path:
    wheels = tmp_path / "wheelhouse"
    wheels.mkdir()
    with zipfile.ZipFile(wheels / "tinydep-1.0.0-py3-none-any.whl", "w") as zf:
        zf.writestr("tinydep/__init__.py", "ANSWER = 41\n")
        zf.writestr(
            "tinydep-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: tinydep\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "tinydep-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr("tinydep-1.0.0.dist-info/RECORD", "")
    return wheels


class TestMetadataShim:
    def test_module_level_version_lookup_proves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The humanize pattern: `version(__package__)` at import time. Keyless, offline —
        the shim makes the module importable and the seeded change lands DIVERGENT."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        base_src = (
            "from importlib.metadata import version\n"
            "\n"
            "VERSION = version('shimpkg')\n"
            "\n"
            "\n"
            "def banner(name: str) -> str:\n"
            "    return f'{name} {VERSION}'\n"
        )
        repo = _repo(
            tmp_path,
            {
                "pyproject.toml": '[project]\nname = "shimpkg"\nversion = "9.9.9"\n',
                "src/shimpkg/__init__.py": "",
                "src/shimpkg/hello.py": base_src,
            },
            {"src/shimpkg/hello.py": base_src.replace("{name} {VERSION}", "{name}={VERSION}")},
        )
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=8, seed=0))
        targets = {t.module: t for t in result.bundle.targets}
        t = targets["shimpkg.hello"]
        assert t.verdict is Verdict.DIVERGENT, (t.reason_code, t.reason_detail)
        # The shim's synthetic version is part of the observed evidence.
        assert "9.9.9" in t.divergences[0].base_summary


class TestThirdPartyDeps:
    BASE = "import tinydep\n\n\ndef lucky(x: int) -> int:\n    return tinydep.ANSWER + x\n"

    def _files(self) -> dict[str, str]:
        return {
            "pyproject.toml": (
                '[project]\nname = "deppkg"\nversion = "1.0"\ndependencies = ["tinydep"]\n'
            ),
            "core.py": self.BASE,
        }

    def test_missing_wheels_offline_land_unproven_with_the_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("UV_NO_INDEX", "1")  # hermetic: even a leaky env finds no PyPI
        repo = _repo(tmp_path, self._files(), {"core.py": self.BASE.replace("+ x", "+ x + 1")})
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=8, seed=0))
        t = {r.module: r for r in result.bundle.targets}["core"]
        assert t.verdict is Verdict.UNPROVEN
        assert t.reason_detail is not None
        assert "--fetch-deps" in t.reason_detail or "TEMPEST_FETCH_DEPS" in t.reason_detail

    def test_reachable_wheels_prove_the_same_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """UV_FIND_LINKS stands in for the uv wheel cache: same offline code path the
        production run takes after a one-time fetch — and the target proves."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("UV_NO_INDEX", "1")
        monkeypatch.setenv("UV_FIND_LINKS", str(_wheelhouse(tmp_path)))
        repo = _repo(tmp_path, self._files(), {"core.py": self.BASE.replace("+ x", "+ x + 1")})
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=8, seed=0))
        t = {r.module: r for r in result.bundle.targets}["core"]
        assert t.verdict is Verdict.DIVERGENT, (t.reason_code, t.reason_detail)
        assert t.inputs_run > 0


class TestUnderTheRealSandbox:
    def test_wheels_prove_under_t2_seatbelt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug ProcessSandbox could never catch: the deps symlink resolves OUTSIDE the
        Seatbelt repo carve, so T2 must explicitly allow the resolved site dir. A user repo
        (no first-party marker) exercises the REAL tier ladder on macOS."""
        import shutil
        import sys as _sys

        if _sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
            pytest.skip("Seatbelt is macOS-only; the Linux T1 leg is CI's")
        if os.environ.get("TEMPEST_NO_SEATBELT") == "1":
            # `make verify-linux-denominator` forces the ladder past T2 so a macOS run cannot
            # hide a fixture that quietly needs a tier Linux does not have (ADR-0058). This test
            # is ABOUT T2, so a T2-less run has nothing to say about it.
            pytest.skip("TEMPEST_NO_SEATBELT=1 forces past the tier this test exists to check")
        monkeypatch.delenv("TEMPEST_DEV", raising=False)
        monkeypatch.setenv("TEMPEST_DOCKER", "/nonexistent/docker")  # force past T1 to T2
        monkeypatch.setenv("UV_NO_INDEX", "1")
        monkeypatch.setenv("UV_FIND_LINKS", str(_wheelhouse(tmp_path)))
        repo = _repo(
            tmp_path,
            {
                "pyproject.toml": (
                    '[project]\nname = "deppkg"\nversion = "1.0"\ndependencies = ["tinydep"]\n'
                ),
                "core.py": TestThirdPartyDeps.BASE,
            },
            {"core.py": TestThirdPartyDeps.BASE.replace("+ x", "+ x + 1")},
        )
        (repo / ".tempest-first-party").unlink()  # a USER repo — the honest tier ladder
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=6, seed=0))
        assert result.sandbox_tier == "T2"
        t = {r.module: r for r in result.bundle.targets}["core"]
        assert t.verdict is Verdict.DIVERGENT, (t.reason_code, t.reason_detail)
