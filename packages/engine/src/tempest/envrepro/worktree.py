"""Materialize base/head working trees via `git worktree` under identical, normalized conditions.

Both revisions always execute with the same interpreter build, locale, TZ, and hash seed
(Law L3: determinism before comparison). Dependency fingerprints are recorded so that
dependency-induced divergence is reported as a finding, never hidden.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_LOCKFILE_NAMES = ("uv.lock", "poetry.lock", "requirements.txt", "requirements.lock")

#: Written beside a cached worktree AFTER `git worktree add` returns successfully, and never
#: before. Its presence is the only thing that makes a cached tree reusable.
#:
#: The directory existing is not evidence that it is complete. `git worktree add` creates the
#: directory and then checks files out into it, so a process killed part-way through — a crash, a
#: battery, `resume_test --kill-mid-proof` — leaves a real directory holding a partial checkout.
#: The old rule was `if not worktree.exists()`, which then reused the wreck FOREVER: every later
#: run in that repository died on a source file that was simply not there. Found by P2's kill
#: gate on its first run (ADR-0052).
_READY_SUFFIX = ".ready"

#: Held while a cache entry is being rebuilt, so two processes never fight over one path.
#:
#: The marker fixed one race and opened another, which the review caught: with the old rule a
#: second process REUSED a half-written tree (silently wrong); with the marker it would DISCARD
#: the tree the first process was still checking out (loudly wrong, and someone else's work).
#: Neither is acceptable, so a rebuild happens under an exclusive create and everyone else waits
#: for the marker instead of acting.
_LOCK_SUFFIX = ".lock"
#: A lock older than this belonged to a process that died holding it. Generous on purpose: a
#: large checkout is slow, and stealing a live lock is the failure this exists to prevent.
_LOCK_STALE_S = 300.0
#: How long to wait for another process's rebuild before treating its lock as abandoned.
_LOCK_WAIT_S = 120.0


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
    ready = worktree.with_name(worktree.name + _READY_SUFFIX)
    # BOTH halves, always. A marker whose tree has been deleted — a cleaned cache, a `rm -rf`,
    # a half-finished removal — is the same lie in the other direction: it claims a checkout that
    # is not there, and a caller handed that path dies on a file that does not exist. Found by
    # the review of the fix that introduced the marker (trap 48).
    if not _is_complete(worktree, ready):
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _rebuild(repo, worktree, ready, sha)
    return MaterializedEnv(
        revision=sha,
        worktree=worktree,
        # v1 pins to the engine's own 3.12 interpreter; per-repo interpreter resolution
        # (.python-version / pyproject requires-python via uv) extends here.
        python=Path(sys.executable),
        env=normalized_env(),
        deps_fingerprint=_deps_fingerprint(worktree),
    )


def _rebuild(repo: Path, worktree: Path, ready: Path, sha: str) -> None:
    """Check `sha` out at `worktree`, exactly once across processes.

    The lock is an exclusive create, which is atomic on every filesystem this runs on. A process
    that cannot take it does not fall through and rebuild anyway — that would be the race the
    lock exists to close — it waits for the marker the holder will write. A lock that is older
    than any plausible checkout belonged to a process that died holding it and is reclaimed.
    """
    lock = worktree.with_name(worktree.name + _LOCK_SUFFIX)
    deadline = time.monotonic() + _LOCK_WAIT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _is_complete(worktree, ready):
                return  # the holder finished while we waited; its tree is the answer
            if _lock_is_stale(lock) or time.monotonic() > deadline:
                lock.unlink(missing_ok=True)
                continue
            time.sleep(0.05)
            continue
        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        try:
            if _is_complete(worktree, ready):
                return  # somebody finished between our check and our lock
            if worktree.exists() or ready.exists():
                _discard_incomplete(repo, worktree)
            # --force TWICE, deliberately: a kill can land after git registers the worktree
            # (writing its own lock under .git/worktrees/) but before the directory is
            # populated. That leaves a "missing but locked" registration the discard above
            # never sees — it keys on filesystem presence, and there is no filesystem — and
            # a single --force refuses it. Git documents the double force as the override
            # for exactly this state; it cannot stomp a LIVE materialization because the
            # exclusive-create lock above already serializes rebuilds of this path.
            # resume_test caught the window live (kill-mid-proof → resume).
            _git(repo, "worktree", "add", "--detach", "--force", "--force", str(worktree), sha)
            # Only now. The marker is a claim that the checkout finished, so it is written by the
            # line after the one that finishes it.
            ready.write_text(sha, encoding="utf-8")
        finally:
            lock.unlink(missing_ok=True)
        return


def _is_complete(worktree: Path, ready: Path) -> bool:
    """A cache entry is usable only when BOTH halves are there.

    One function rather than three copies of the same conjunction, because it is asked at three
    moments that must agree: before taking the lock, while waiting for someone else's, and again
    after acquiring it. The last is not redundant — the holder may have finished in between, and
    tearing down a tree that is now complete is exactly the race the lock exists to close.
    """
    return ready.is_file() and worktree.is_dir()


def _lock_is_stale(lock: Path) -> bool:
    try:
        return (time.time() - lock.stat().st_mtime) > _LOCK_STALE_S
    except OSError:  # pragma: no cover — the holder released it between the two calls
        return False


def remove(repo: Path, env: MaterializedEnv) -> None:
    _git(repo, "worktree", "remove", "--force", str(env.worktree))
    ready = env.worktree.with_name(env.worktree.name + _READY_SUFFIX)
    ready.unlink(missing_ok=True)


def _discard_incomplete(repo: Path, worktree: Path) -> None:
    """Throw away a cached tree nobody finished writing, and any marker that outlived it.

    Four steps because a half-created worktree can be broken in four ways: git may know about it
    (so ask git to remove it), the path may survive that as a directory OR as a plain file or
    symlink left by something else (so remove it by the right call for what it is), git's own
    registry may still name it (so prune), and a stale marker may still claim it. Every step is
    best-effort: this runs on the wreckage of a crash, and the only outcome that matters is that
    the path is free afterwards.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _remove_path(worktree)
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"], capture_output=True, text=True)
    _remove_path(worktree)
    worktree.with_name(worktree.name + _READY_SUFFIX).unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    """Free `path` whatever it is. `shutil.rmtree` refuses a symlink and refuses a plain file,
    and either of those sitting where a worktree belongs would survive a rmtree-only cleanup and
    then break `git worktree add` with a message about an existing path."""
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _deps_fingerprint(worktree: Path) -> str:
    for name in _LOCKFILE_NAMES:
        lock = worktree / name
        if lock.exists():
            digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:16]
            return f"{name}:{digest}"
    return "no-lockfile"
