"""F12's engine half — a change split into hunks, each with the behaviour it is responsible for.

The composer's whole idea is one column a diff viewer has never had. Not "these lines changed" —
every tool shows that — but **what this hunk DOES**: the verdict over the symbols it touches, the
divergences it caused, and how much of what it changed was actually exercised.

Three operations, and they are deliberately separate:

* `hunks_for` splits a real `git diff` into applyable pieces. Each carries its own patch text, so
  a subset can be handed to `git apply` — the same mechanism `git add -p` uses, rather than a
  line-splicing scheme of our own that would disagree with git about what a change is.
* `impact` maps a proved bundle back onto those hunks by asking which SYMBOLS each hunk's changed
  lines fall inside. A hunk that touches no executable symbol gets `UNPROVEN` with a reason, never
  a blank — "no evidence" and "no divergence" are different facts and the column must not blur
  them.
* `prove_selection` applies a chosen subset to the baseline and proves THAT. Accepting three of
  ten hunks is a different change from the whole diff, and the only honest verdict about it comes
  from executing it.

**Why a subset is proved rather than filtered.** The tempting shortcut is to prove the whole diff
once and then report the subset's verdict by dropping the targets the user rejected. That is
wrong in the direction that matters: hunks interact. Rejecting the hunk that adds a guard while
accepting the one that relies on it produces a tree neither proof ever executed, and reporting the
full run's verdict for it would be a claim about code that was never run (L16). So a selection is
materialized and proved on its own.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tempest.bundle.bundle import TargetRecord
from tempest.model import Verdict
from tempest.prove import ProveConfig, ProveResult
from tempest.targets.symbols import enclosing_symbols

#: `git diff` hunk header: @@ -base,count +head,count @@
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
#: How much context each hunk carries. Three is git's default and what `git apply` expects to be
#: able to re-anchor with when earlier hunks have shifted the file.
_CONTEXT = 3


class ComposeError(Exception):
    """A change that cannot be split, applied, or attributed honestly."""


@dataclass(frozen=True)
class Hunk:
    """One applyable piece of a change, and the lines it is responsible for."""

    #: Stable across runs and across machines: the same bytes always produce the same id, so a
    #: UI can remember an accept/reject decision without holding an index into a list that a
    #: re-diff would renumber.
    id: str
    path: str
    #: The file header plus this hunk, ready for `git apply`.
    patch: str
    head_lines: frozenset[int]
    base_lines: frozenset[int]

    @property
    def summary(self) -> str:
        lines = sorted(self.head_lines)
        if not lines:
            return f"{self.path}: deletion only"
        return f"{self.path}:{lines[0]}-{lines[-1]}"


@dataclass(frozen=True)
class HunkImpact:
    """What one hunk did, in the vocabulary the engine is allowed to use (L2).

    `verdict` is the STRONGEST claim the hunk's own targets support, and `UNPROVEN` is not a
    fallback for "we did not look" — it is the answer when the hunk touched nothing executable, or
    when everything it touched came back unproven. A composer column that showed a blank there
    would let a reader supply their own optimism.
    """

    hunk: Hunk
    verdict: Verdict
    qualnames: tuple[str, ...]
    divergence_count: int
    changed_line_coverage: float
    reason: str = ""


@dataclass(frozen=True)
class Selection:
    """A subset of a change, materialized and proved on its own."""

    accepted: tuple[Hunk, ...]
    head: str
    #: Hunks that could not be applied on top of the accepted ones. Reported, never dropped: a
    #: selection that silently lost a piece is a selection the user did not make.
    rejected_by_git: tuple[Hunk, ...] = field(default_factory=tuple)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-compose",
            "GIT_AUTHOR_EMAIL": "compose@tempest",
            "GIT_COMMITTER_NAME": "tempest-compose",
            "GIT_COMMITTER_EMAIL": "compose@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )
    if check and done.returncode != 0:
        raise ComposeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def _digest(path: str, patch: str) -> str:
    return hashlib.sha256(f"{path}\n{patch}".encode()).hexdigest()[:16]


def hunks_for(
    repo: Path, base: str, head: str, patterns: tuple[str, ...] = ("*.py", "*.ts", "*.tsx")
) -> tuple[Hunk, ...]:
    """Split the change between two revisions into individually applyable hunks."""
    done = _git(
        repo,
        "diff",
        "--no-renames",
        "--no-color",
        f"--unified={_CONTEXT}",
        f"{base}..{head}",
        "--",
        *patterns,
    )
    return _split(done.stdout)


def _split(diff_text: str) -> tuple[Hunk, ...]:
    """Cut a unified diff into one patch per hunk, each with its own file header.

    Written against the text rather than a library because the patch a hunk carries must be
    byte-identical to what git produced — a re-rendered patch is a patch git may decline to apply.
    """
    hunks: list[Hunk] = []
    header: list[str] = []
    current: list[str] | None = None
    path = ""
    head_start = base_start = 0

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        patch = "".join(header) + "".join(current)
        head_lines, base_lines = _lines_of(current, head_start, base_start)
        hunks.append(
            Hunk(
                id=_digest(path, patch),
                path=path,
                patch=patch,
                head_lines=frozenset(head_lines),
                base_lines=frozenset(base_lines),
            )
        )
        current = None

    for raw in diff_text.splitlines(keepends=True):
        if raw.startswith("diff --git "):
            flush()
            header = [raw]
            path = raw.split(" b/", 1)[-1].strip() if " b/" in raw else ""
            continue
        if current is None and (
            raw.startswith(
                ("index ", "--- ", "+++ ", "old mode", "new mode", "new file", "deleted file")
            )
        ):
            header.append(raw)
            continue
        match = _HUNK_RE.match(raw)
        if match:
            flush()
            base_start = int(match.group(1))
            head_start = int(match.group(3))
            current = [raw]
            continue
        if current is not None:
            current.append(raw)
    flush()
    return tuple(hunks)


def _lines_of(body: list[str], head_start: int, base_start: int) -> tuple[set[int], set[int]]:
    """Which head and base line numbers this hunk actually changes (context excluded)."""
    head_lines: set[int] = set()
    base_lines: set[int] = set()
    head_no, base_no = head_start, base_start
    for line in body[1:]:  # body[0] is the @@ header
        if line.startswith("+"):
            head_lines.add(head_no)
            head_no += 1
        elif line.startswith("-"):
            base_lines.add(base_no)
            base_no += 1
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            head_no += 1
            base_no += 1
    return head_lines, base_lines


def symbols_touched(head_source: str, hunk: Hunk) -> tuple[str, ...]:
    """The symbols whose bodies contain this hunk's changed head lines."""
    if not hunk.head_lines:
        return ()
    return tuple(sorted({s.symbol for s in enclosing_symbols(head_source, set(hunk.head_lines))}))


def _strongest(records: list[TargetRecord]) -> Verdict:
    """The honest summary of several targets: any DIVERGENT wins, then any UNPROVEN.

    Ordering matters and is not arbitrary. A hunk with one divergent target and four equivalent
    ones is DIVERGENT — averaging would be a way to dilute evidence. A hunk with one unproven
    target and four equivalent ones is UNPROVEN, because "some of this could not be run" is the
    fact a reader needs before they accept it, not a footnote under a reassuring word.
    """
    verdicts = {r.verdict for r in records}
    if Verdict.DIVERGENT in verdicts:
        return Verdict.DIVERGENT
    if Verdict.UNPROVEN in verdicts or not records:
        return Verdict.UNPROVEN
    if Verdict.ERROR in verdicts:
        return Verdict.ERROR
    return Verdict.EQUIVALENT_UNDER_BUDGET


def impact(
    hunks: tuple[Hunk, ...], targets: tuple[TargetRecord, ...], sources: dict[str, str]
) -> tuple[HunkImpact, ...]:
    """Attribute a proved bundle's targets back to the hunks that caused them.

    `sources` maps a path to its HEAD text — the tree the bundle was proved over. A hunk whose
    file is missing from it is reported as unproven with that reason rather than skipped, because
    a row missing from the composer is a change the user cannot see they are accepting.
    """
    by_path: dict[str, list[TargetRecord]] = {}
    for record in targets:
        by_path.setdefault(record.file_path, []).append(record)

    out: list[HunkImpact] = []
    for hunk in hunks:
        source = sources.get(hunk.path)
        if source is None:
            out.append(
                HunkImpact(
                    hunk=hunk,
                    verdict=Verdict.UNPROVEN,
                    qualnames=(),
                    divergence_count=0,
                    changed_line_coverage=0.0,
                    reason=f"no head source for {hunk.path}; nothing could be attributed to it",
                )
            )
            continue
        names = symbols_touched(source, hunk)
        mine = [r for r in by_path.get(hunk.path, []) if r.qualname in names]
        if not names:
            reason = "this hunk changes no executable symbol — imports, comments or data only"
        elif not mine:
            reason = f"{', '.join(names)} changed but the proof produced no record for it"
        else:
            reason = ""
        coverage = sum(r.changed_line_coverage for r in mine) / len(mine) if mine else 0.0
        out.append(
            HunkImpact(
                hunk=hunk,
                verdict=_strongest(mine),
                qualnames=names,
                divergence_count=sum(len(r.divergences) for r in mine),
                changed_line_coverage=coverage,
                reason=reason,
            )
        )
    return tuple(out)


def apply_selection(repo: Path, base: str, accepted: tuple[Hunk, ...], branch: str) -> Selection:
    """Build a commit that is `base` plus exactly the accepted hunks.

    Applied in file order and then by position, because `git apply` re-anchors later hunks against
    what earlier ones did; feeding them out of order turns a clean subset into a conflict that is
    an artifact of the ordering rather than of the change.
    """
    worktree = repo / ".tempest" / "compose" / branch
    if worktree.exists():
        _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
    _git(repo, "worktree", "add", "--detach", "--force", str(worktree), base)

    ordered = sorted(accepted, key=lambda h: (h.path, min(h.head_lines or {0})))
    rejected: list[Hunk] = []
    for hunk in ordered:
        done = subprocess.run(
            ["git", "-C", str(worktree), "apply", "--unidiff-zero", "-"],
            input=hunk.patch,
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            rejected.append(hunk)

    _git(worktree, "add", "-A")
    _git(worktree, "commit", "--allow-empty", "-m", f"tempest: composed selection {branch}")
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    return Selection(accepted=tuple(ordered), head=head, rejected_by_git=tuple(rejected))


# --------------------------------------------------------------------------------------------
# Incremental re-proof (F12's "proof re-runs incrementally on partial acceptance")
# --------------------------------------------------------------------------------------------
#
# Toggling one row must not cost a full re-proof. The saving is real and the reasoning behind it
# is the part that has to be right: a target may be carried forward from the previous selection
# ONLY IF its module's bytes are identical AND nothing it can reach has changed. Same bytes is not
# enough on its own — a function whose source did not move still behaves differently when a module
# it imports did, which is exactly why F12 says *call-graph-affected* targets and not
# *changed files*.
#
# The closure below is deliberately CONSERVATIVE: it walks module-level imports with `ast`, and
# anything it cannot resolve keeps its module dirty. Re-proving more than strictly necessary costs
# time; re-proving less would carry a verdict that is no longer about the code in the tree.


@dataclass(frozen=True)
class Incremental:
    """The records for a new selection, and where each of them came from.

    `carried` is not a footnote. A carried record is real evidence — the same bytes, the same
    inputs, the same execution — but it was produced by a proof of a DIFFERENT head, and a reader
    deciding whether to accept a change is entitled to know which rows were re-executed just now
    and which are being reused. L1 says a claim carries its artifact; this says which artifact.
    """

    records: tuple[TargetRecord, ...]
    reproved: tuple[str, ...]
    carried: tuple[str, ...]
    #: The bundle the re-proved records came from, or "" when nothing needed re-proving.
    bundle_id: str = ""


def _module_name(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".")


def import_graph(sources: dict[str, str]) -> dict[str, set[str]]:
    """path -> the paths it imports, for the files we have. Unparseable files import EVERYTHING.

    A file we cannot read the imports of is a file whose dependencies are unknown, and an unknown
    dependency has to be treated as a dependency on everything — the alternative is carrying a
    verdict past a change we could not see.
    """
    by_module = {_module_name(p): p for p in sources}
    graph: dict[str, set[str]] = {}
    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            graph[path] = set(sources) - {path}
            continue
        edges: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                for module, target in by_module.items():
                    if name == module or name.startswith(f"{module}."):
                        edges.add(target)
        graph[path] = edges
    return graph


def affected(dirty: set[str], graph: dict[str, set[str]]) -> set[str]:
    """`dirty` plus everything that can transitively reach it. Fixed point, not one hop.

    One hop is the bug this shape invites: A imports B imports C, C changed, and a single pass
    marks B and leaves A carrying a stale verdict.
    """
    out = set(dirty)
    changed = True
    while changed:
        changed = False
        for path, edges in graph.items():
            if path not in out and edges & out:
                out.add(path)
                changed = True
    return out


def changed_between(repo: Path, previous_head: str, new_head: str) -> set[str]:
    """Paths whose BYTES differ between two selections."""
    done = _git(repo, "diff", "--no-renames", "--name-only", f"{previous_head}..{new_head}")
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def reprove(
    repo: Path,
    base: str,
    previous_head: str,
    new_head: str,
    previous_records: tuple[TargetRecord, ...],
    *,
    prove: Callable[[ProveConfig], ProveResult],
    max_inputs: int = 50,
    seed: int = 0,
    all_paths: tuple[str, ...] = (),
) -> Incremental:
    """Prove only what the toggle can have changed; carry the rest, and say which is which.

    `prove` is a parameter rather than a hard call so a caller can supply a configured or
    instrumented prover — the bench passes `run_prove` and times it. It is not a seam for faking
    one: every record in the result came out of a real execution, here or in the previous
    selection's run (L4).
    """
    sources = {
        path: (repo / path).read_text(encoding="utf-8", errors="replace")
        for path in all_paths
        if (repo / path).exists() and path.endswith(".py")
    }
    dirty = affected(changed_between(repo, previous_head, new_head), import_graph(sources))
    carried = tuple(sorted(set(sources) - dirty))
    reproved = tuple(sorted(dirty))
    if not dirty:
        return Incremental(records=previous_records, reproved=(), carried=carried)

    result = prove(
        ProveConfig(
            repo=repo,
            base=base,
            head=new_head,
            max_inputs=max_inputs,
            seed=seed,
            # Everything NOT dirty is out of scope for this run. Expressed as ignore globs because
            # a path is its own glob, and `is_ignored` is the one place the engine already asks
            # "should I skip this file".
            ignore_globs=carried,
        )
    )
    kept = tuple(r for r in previous_records if r.file_path in set(carried))
    return Incremental(
        records=(*result.bundle.targets, *kept),
        reproved=reproved,
        carried=carried,
        bundle_id=result.bundle.manifest.base_sha[:12]
        + ".."
        + result.bundle.manifest.head_sha[:12],
    )
