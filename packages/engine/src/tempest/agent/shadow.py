"""The shadow worktree — **the agent never writes the user's working tree** (L19, ADR-0036).

Agent edits are staged in a git worktree under `.tempest/agent/worktrees/<task-id>/`. The user's
checkout is not touched until they accept, and every acceptance is journalled so it can be undone
exactly (L20). Three properties make this more than a scratch directory:

**1. The baseline is what the user can actually see.** A worktree created from bare `HEAD` would
hand the agent a tree that differs from the user's screen whenever anything is uncommitted — and
then every uncommitted edit of theirs would read as an agent change in the diff. Instead the
baseline is built with `git stash create`, which writes a commit object capturing the working
state **without mutating the tree or the stash list**, plus a carry-over of untracked files. The
user's tree is observably unchanged by creating a shadow; a test asserts exactly that.

**2. A snapshot is a real commit, so the v1 engine proves it unchanged.** `snapshot()` commits the
shadow's state onto its own branch and returns a sha resolvable from the user's repository. That
means F1's proof step is `prove(baseline_sha, shadow_sha)` against the existing nine stages —
no new engine concept, no special "prove a dirty directory" path.

**3. Acceptance is all-or-nothing and reversible.** Preconditions are checked for the whole
changeset before a single byte is written; a conflict aborts with nothing applied. Pre-images are
journalled to `.tempest/agent/journal/`, so undo restores the user's bytes even when their
baseline was never committed — which is the case `git checkout` cannot serve and is exactly why
L20 says "journalled, not 'hopefully git has it'".

Scope: this is the staging substrate. The orchestrator that decides *what* to write arrives in
Phase 21.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tempest.agent import journal

_AGENT_DIR = Path(".tempest") / "agent"
_WORKTREES = _AGENT_DIR / "worktrees"
_BRANCH_PREFIX = "tempest/agent/"
#: Per-shadow metadata, kept OUTSIDE the worktree — a file inside it would be picked up by
#: `changed_files()` as agent work, which is the very confusion this record exists to end.
_META_DIR = _AGENT_DIR / "meta"
#: git refuses to operate through these; a staged write must never reach repository internals.
_FORBIDDEN_TOP = {".git"}


class ShadowError(Exception):
    """A shadow-worktree operation could not be completed. The message names the reason."""


class PathEscape(ShadowError):
    """A staged write tried to leave the shadow worktree (L19's hard edge)."""


class AcceptConflict(ShadowError):
    """The user edited a file since staging. Their work wins; nothing is applied."""


@dataclass(frozen=True)
class Shadow:
    """One task's staging area. Stateless by design — the filesystem is the source of truth."""

    task_id: str
    repo: Path
    path: Path
    branch: str
    baseline: str


@dataclass(frozen=True)
class Acceptance:
    """The record that makes an acceptance undoable (L20)."""

    id: str
    repo: Path
    files: list[str]
    journal_dir: Path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ShadowError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    """Exactly what git wrote, unmodified — for content comparisons where bytes matter."""
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise ShadowError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def _require_repo(repo: Path) -> None:
    if not (repo / ".git").exists():
        raise ShadowError(f"{repo} is not a git repository")


def _slug(task_id: str) -> str:
    """Task ids reach the filesystem and a git ref, so keep them to a safe alphabet."""
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in task_id).strip("-")
    if not safe:
        raise ShadowError(f"task id {task_id!r} has no usable characters")
    return safe


def _baseline_commit(repo: Path) -> str:
    """A commit capturing what the user can see right now, without disturbing anything.

    `git stash create` builds the commit object and prints its sha but does **not** touch the
    working tree, the index, or the stash list. On a clean tree it prints nothing, and HEAD is
    already the answer.
    """
    created = _git(repo, "stash", "create")
    return created or _git(repo, "rev-parse", "HEAD^{commit}")


def _untracked(repo: Path) -> list[str]:
    listing = _git(repo, "ls-files", "--others", "--exclude-standard")
    return [line for line in listing.splitlines() if line]


def create(repo: Path, task_id: str, *, baseline: str | None = None) -> Shadow:
    """Stage a fresh shadow worktree for `task_id`, seeded from the user's visible state."""
    repo = Path(repo)
    _require_repo(repo)
    slug = _slug(task_id)
    path = repo / _WORKTREES / slug
    if path.exists():
        if _meta_path(repo, slug).is_file():
            raise ShadowError(f"a shadow for task {task_id!r} already exists at {path}")
        # A worktree under our own directory with no metadata beside it is the wreckage of a
        # process killed between `git worktree add` and `_write_meta` — a window one line wide
        # that closed the task id permanently, because `attach` will not adopt a shadow it cannot
        # read a baseline from and `create` refused to overwrite one. Nothing else writes here,
        # and without metadata there is nothing in it worth keeping: the baseline it was built
        # from is exactly the fact that was never recorded.
        _git_quiet(repo, "worktree", "remove", "--force", str(path))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        _git_quiet(repo, "worktree", "prune")

    sha = _git(repo, "rev-parse", f"{baseline}^{{commit}}") if baseline else _baseline_commit(repo)
    branch = f"{_BRANCH_PREFIX}{slug}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--force", "-B", branch, str(path), sha)

    # `git stash create` captures tracked changes only; untracked files are part of what the
    # user sees, so carry them across or the agent edits a tree the user does not recognise.
    carried = False
    for rel in _untracked(repo):
        if rel.startswith(str(_AGENT_DIR)) or rel.startswith(".tempest"):
            continue
        src, dst = repo / rel, path / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            carried = True

    if carried:
        # The carried files must be IN the baseline commit, not merely in the worktree. When
        # they were only in the worktree, `changed_files()` reported the user's untracked files
        # as agent work, `accept()` raised a false conflict naming a file the agent never
        # touched, and — acceptance being all-or-nothing — one ordinary untracked file made
        # every acceptance impossible. It also corrupted the proof pair, attributing the user's
        # files to the agent. The baseline is a claim about what the agent started from; it has
        # to be true.
        _git(path, "add", "-A")
        _commit(path, "tempest: baseline (untracked carry-over)")
        sha = _git(path, "rev-parse", "HEAD^{commit}")

    _write_meta(repo, slug, task_id=task_id, baseline=sha)
    return Shadow(task_id=task_id, repo=repo, path=path, branch=branch, baseline=sha)


def _commit(worktree: Path, message: str) -> None:
    """Commit whatever is staged in `worktree` with a fixed identity (no user config needed)."""
    _git(
        worktree,
        "-c",
        "user.name=Tempest",
        "-c",
        "user.email=agent@tempest.local",
        "commit",
        "-m",
        message,
        "--no-gpg-sign",
    )


def _meta_path(repo: Path, slug: str) -> Path:
    return repo / _META_DIR / f"{slug}.json"


def _write_meta(repo: Path, slug: str, *, task_id: str, baseline: str) -> None:
    """Record the baseline on disk.

    `list_shadows()` used to recover it from the branch tip, but `snapshot()` moves that branch
    forward — so after a restart a shadow diffed against itself, reported nothing staged, and
    `accept()` silently applied nothing. The baseline is a fact about when the shadow was
    created; it is written down once and never derived from mutable state.
    """
    target = _meta_path(repo, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"task_id": task_id, "baseline": baseline}, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_inside(shadow: Shadow, relpath: str) -> Path:
    """Resolve `relpath` inside the shadow, refusing anything that leaves it.

    Checked against the *resolved* path, so a symlink planted inside the shadow cannot be used
    as a tunnel to somewhere else on disk.
    """
    if not relpath or relpath.strip() == "":
        raise PathEscape("empty path")
    candidate = Path(relpath)
    if candidate.is_absolute():
        raise PathEscape(f"absolute paths are not writable: {relpath}")
    if candidate.parts and candidate.parts[0] in _FORBIDDEN_TOP:
        raise PathEscape(f"repository internals are not writable: {relpath}")

    root = shadow.path.resolve()
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise PathEscape(f"path escapes the shadow worktree: {relpath}")
    if any(part in _FORBIDDEN_TOP for part in target.relative_to(root).parts):
        raise PathEscape(f"repository internals are not writable: {relpath}")
    return target


def write(shadow: Shadow, relpath: str, contents: str) -> Path:
    """Stage one file write inside the shadow. Never reaches the user's tree."""
    target = _resolve_inside(shadow, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")
    return target


def changed_files(shadow: Shadow) -> list[str]:
    """Repository-relative paths the agent has changed, relative to the baseline."""
    _git(shadow.path, "add", "-A")
    listing = _git(shadow.path, "diff", "--cached", "--name-only", shadow.baseline)
    return [line for line in listing.splitlines() if line]


def snapshot(shadow: Shadow, message: str = "tempest: agent staged change") -> str:
    """Commit the shadow's state and return a sha the engine can prove against.

    **Idempotent.** Calling it twice with nothing new in between returns the same sha rather than
    failing. `changed_files` answers "does this differ from the BASELINE", which stays true after
    the first commit — so a second call used to reach `git commit` with an empty index and die
    with an empty stderr. F3's repair loop proves after every attempt, so that second call is the
    normal case, not an edge one.

    The two questions are genuinely different and both are asked here: *anything since the
    baseline?* decides whether there is a change at all, and *anything staged that HEAD does not
    already have?* decides whether a new commit is warranted.
    """
    if not changed_files(shadow):
        return shadow.baseline
    if _git(shadow.path, "diff", "--cached", "--name-only", "HEAD"):
        _commit(shadow.path, message)
    return _git(shadow.path, "rev-parse", "HEAD^{commit}")


def accept(shadow: Shadow, *, files: list[str] | None = None) -> Acceptance:
    """Apply staged changes into the user's tree — all of them, or none.

    Refuses if the user modified any target since the shadow was created: their work wins.
    """
    changed = changed_files(shadow)
    selected = list(changed) if files is None else list(files)
    unknown = [f for f in selected if f not in changed]
    if unknown:
        raise ShadowError(f"not changed in this shadow: {', '.join(sorted(unknown))}")

    # Phase 1 — validate the WHOLE changeset before touching anything.
    conflicts = [rel for rel in selected if _user_moved_since_baseline(shadow, rel)]
    if conflicts:
        raise AcceptConflict(
            "the user edited these since staging, so nothing was applied: "
            + ", ".join(sorted(conflicts))
        )

    # Phase 2 — write through the agent journal (L20). There is exactly ONE journal: the same
    # record every other agent action lands in, so `undo_last()` reverses an acceptance as
    # naturally as it reverses an edit. The context manager captures pre-images before the first
    # byte moves and rolls the whole changeset back if any copy fails.
    entries = journal.Journal(shadow.repo)
    with entries.record(
        journal.KIND_ACCEPTANCE,
        f"accepted {len(selected)} file(s) from shadow {shadow.task_id}",
        selected,
    ) as entry:
        for rel in selected:
            src, dst = shadow.path / rel, shadow.repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    return Acceptance(id=entry.id, repo=shadow.repo, files=selected, journal_dir=entry.dir)


def _user_moved_since_baseline(shadow: Shadow, rel: str) -> bool:
    """True when the user's copy differs from the baseline the agent started from."""
    user_file = shadow.repo / rel
    try:
        # NOT `_git()`: that strips leading and trailing whitespace, which made this comparison
        # wrong in both directions — inventing conflicts on content beginning with a blank line
        # (ordinary in YAML and markdown), and missing real user edits that only changed
        # surrounding whitespace, silently overwriting their work. Bytes are compared as bytes.
        baseline_blob = _git_bytes(shadow.repo, "show", f"{shadow.baseline}:{rel}")
    except ShadowError:
        # Not in the baseline: a new file. It conflicts only if the user has since made one.
        return user_file.exists()
    if not user_file.is_file():
        return True  # the user deleted it; re-creating it silently would be a surprise
    return user_file.read_bytes() != baseline_blob


def revert(acceptance: Acceptance) -> None:
    """Undo an acceptance exactly (L20). Idempotent.

    A thin alias for the journal's undo: an acceptance is an ordinary journal entry, so it is
    also reachable from `undo_last()` alongside every other agent action. Keeping one reversal
    path means there is one place for undo to be correct.
    """
    journal.Journal(acceptance.repo).undo(acceptance.id)


def discard(shadow: Shadow) -> None:
    """Throw the shadow away. Idempotent, and it never touches the user's tree."""
    if shadow.path.exists():
        _git(shadow.repo, "worktree", "remove", "--force", str(shadow.path))
    _git_quiet(shadow.repo, "branch", "-D", shadow.branch)
    _git_quiet(shadow.repo, "worktree", "prune")
    meta = _meta_path(shadow.repo, _slug(shadow.task_id))
    if meta.exists():
        meta.unlink()


def _git_quiet(repo: Path, *args: str) -> None:
    """Best-effort cleanup: a branch that is already gone is success, not an error."""
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def list_shadows(repo: Path) -> list[Shadow]:
    """Every live shadow, rebuilt from disk — the manager survives a restart with no state."""
    repo = Path(repo)
    root = repo / _WORKTREES
    if not root.is_dir():
        return []
    out: list[Shadow] = []
    for path in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path = _meta_path(repo, path.name)
        if not meta_path.is_file():
            continue  # not a shadow this version created; nothing trustworthy to rebuild from
        meta: Any = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not meta.get("baseline"):
            continue
        out.append(
            Shadow(
                task_id=str(meta.get("task_id", path.name)),
                repo=repo,
                path=path,
                branch=f"{_BRANCH_PREFIX}{path.name}",
                baseline=str(meta["baseline"]),
            )
        )
    return out


def attach(repo: Path, task_id: str) -> Shadow | None:
    """The existing shadow for `task_id`, or None when there is not one.

    P2's way back in after a restart. `create` deliberately refuses to overwrite a live shadow,
    and a resumed task must not get a NEW baseline: the baseline is a claim about what the agent
    started from, and re-deriving it from the user's tree hours later would silently re-point the
    proof at a different starting state — the agent's own edits would vanish from the diff and
    the user's later edits would appear in it.

    Both halves are required. A meta file whose worktree is gone describes a shadow that no
    longer exists, and answering with it would hand the caller a path nothing lives at.
    """
    repo = Path(repo)
    slug = _slug(task_id)
    meta_path = _meta_path(repo, slug)
    path = repo / _WORKTREES / slug
    if not meta_path.is_file() or not path.is_dir():
        return None
    meta: Any = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or not meta.get("baseline"):
        return None
    return Shadow(
        task_id=str(meta.get("task_id", task_id)),
        repo=repo,
        path=path,
        branch=f"{_BRANCH_PREFIX}{slug}",
        baseline=str(meta["baseline"]),
    )


def read_at(shadow: Shadow, sha: str, relpath: str) -> str | None:
    """A file's text at a revision of the shadow, or None when it is not there.

    Used by F3 to tell a symbol that was PUT BACK from one that was deleted: both vanish from a
    bundle that only carries changed symbols, and only the source can say which happened.
    """
    result = subprocess.run(
        ["git", "-C", str(shadow.path), "show", f"{sha}:{relpath}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None
