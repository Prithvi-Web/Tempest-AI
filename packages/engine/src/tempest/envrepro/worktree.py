"""Materialize base/head working trees via `git worktree` under identical, normalized conditions.

Both revisions always execute with the same interpreter build, locale, TZ, and hash seed
(Law L3: determinism before comparison). Dependency fingerprints are recorded so that
dependency-induced divergence is reported as a finding, never hidden.
"""

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_LOCKFILE_NAMES = ("uv.lock", "poetry.lock", "requirements.txt", "requirements.lock")


@dataclass(frozen=True)
class MaterializedEnv:
    revision: str
    worktree: Path
    python: Path
    env: dict[str, str]
    deps_fingerprint: str


class EnvReproError(Exception):
    pass


def normalized_env(tmpdir: Path | None = None) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
    }
    if tmpdir is not None:
        env["TMPDIR"] = str(tmpdir)
        env["HOME"] = str(tmpdir)
    return env


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise EnvReproError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def materialize(repo: Path, ref: str, cache: Path) -> MaterializedEnv:
    sha = _git(repo, "rev-parse", f"{ref}^{{commit}}")
    worktree = cache / "worktrees" / sha[:12]
    if not worktree.exists():
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "--detach", "--force", str(worktree), sha)
    return MaterializedEnv(
        revision=sha,
        worktree=worktree,
        # v1 pins to the engine's own 3.12 interpreter; per-repo interpreter resolution
        # (.python-version / pyproject requires-python via uv) extends here.
        python=Path(sys.executable),
        env=normalized_env(),
        deps_fingerprint=_deps_fingerprint(worktree),
    )


def remove(repo: Path, env: MaterializedEnv) -> None:
    _git(repo, "worktree", "remove", "--force", str(env.worktree))


def _deps_fingerprint(worktree: Path) -> str:
    for name in _LOCKFILE_NAMES:
        lock = worktree / name
        if lock.exists():
            digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:16]
            return f"{name}:{digest}"
    return "no-lockfile"
