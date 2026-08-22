"""C1 gate: `python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete`.

L27 — upstream mergeability is a shipped feature. LibreChat ships continuously; a fork that
cannot absorb upstream is obsolete within two release cycles. What makes absorption possible is
that the delta between this tree and upstream stays small, declared, and diffable — and that is
a measurable property, not a hope.

The gate reads `packages/platform/UPSTREAM.md` and asks four things, each proven to fail on a
violating tree:

1. **The origin is pinned**: an `- **Adopted commit:** <40-hex>` line names the upstream commit.
   Exactly one — a duplicated field is ambiguous and fails rather than silently picking one.
2. **The baseline is real**: a `- **Vendor baseline:** <40-hex>` line names a commit that
   resolves in THIS repository — the commit that landed (or last merged) the vendored tree.
3. **Every delta is declared** (`--ledger-complete`): every path under `packages/platform/**`
   that differs from the baseline — committed, staged, unstaged, or untracked (enumerated
   per-file, never as a directory) — is either an inline-delta ledger row, a declared seam
   (a path *inside* `packages/platform/<pkg>/tempest/`), or `UPSTREAM.md` itself. Renames are
   counted as a delete plus an add, so moving a vendored file into a seam still surfaces the
   vanished original. And the converse: a ledger row whose path has NOT changed is stale.
   Undeclared drift and stale rows both fail — the ledger is the map, and a map that disagrees
   with the territory in either direction is worse than no map.
4. **The ledger stays small** (`--max-inline-deltas N`): more rows than the cap means seams are
   being skipped and their code edited in place, which is the beginning of fork rot.

Scope, stated so the claim is exact: the baseline field is **self-attested** — this gate proves
the tree matches the ledger against the recorded baseline; that the baseline moves only on a
vendoring or upstream-merge commit is UPSTREAM.md's documented rule, held by review of commits
that touch it, not by this gate. Fenced code blocks in UPSTREAM.md are documentation, never
structure (the license_check lesson, applied here from day one).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

_HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
_ADOPTED_FIELD = "- **Adopted commit:**"
_BASELINE_FIELD = "- **Vendor baseline:**"
_LEDGER_HEADING = "## Inline-delta ledger"
_PLACEHOLDER_CELLS = {"", "—", "-", "*(none)*", "(none)", "n/a"}
_PLATFORM = "packages/platform"


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/parity.py`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _git(root: Path, *args: str) -> str:
    """Git with path quoting off: a `café.js` must round-trip byte-identically between the
    diff output, the status output, and the ledger cell that declares it."""
    return subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _strip_fences(body: str) -> str:
    """Drop fenced code blocks — CommonMark nesting: a fence of N backticks closes only on a
    fence of at least N. A doc example inside a fence must never read as a live field or row."""
    out: list[str] = []
    open_fence = 0
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            ticks = len(stripped) - len(stripped.lstrip("`"))
            if open_fence == 0:
                open_fence = ticks
            elif ticks >= open_fence:
                open_fence = 0
            continue
        if open_fence == 0:
            out.append(line)
    return "\n".join(out)


def _sha_fields(body: str, prefix: str) -> list[str | None]:
    """One entry per line carrying the field: its 40-hex value, or None if malformed."""
    values: list[str | None] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            match = _HEX40.search(stripped)
            values.append(match.group(0) if match else None)
    return values


def _separator_row(cells: list[str]) -> bool:
    """True for `|---|`, `| --- |`, `|:---:|` and friends in any prettifier dialect."""
    return all(not cell or set(cell) <= {"-", ":"} for cell in cells)


def _ledger_rows(body: str) -> list[tuple[str, str]]:
    """(path, reason) per real row of the inline-delta ledger table."""
    rows: list[tuple[str, str]] = []
    in_section = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped == _LEDGER_HEADING
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in stripped.strip("|").split("|")]
        if _separator_row(cells) or not cells or cells[0].lower() == "path":
            continue
        if cells[0] in _PLACEHOLDER_CELLS:
            continue
        rows.append((cells[0], cells[1] if len(cells) > 1 else ""))
    return rows


def _exempt(path: str) -> bool:
    """UPSTREAM.md is ours; paths INSIDE `packages/platform/<pkg>/tempest/` are the declared
    seams (a plain file merely NAMED `tempest` is not a seam); `.DS_Store` is Finder junk that
    appears by opening a folder and must not redden a gate."""
    if path == f"{_PLATFORM}/UPSTREAM.md":
        return True
    parts = path.split("/")
    if parts and parts[-1] == ".DS_Store":
        return True
    return len(parts) > 4 and parts[3] == "tempest"


def _changed_paths(root: Path, baseline: str) -> set[str]:
    """Every platform path differing from the baseline: committed AND working-tree state.

    A gate that reads only HEAD reports green over a dirty tree; verify runs on the working
    tree, so this must too. Rename detection is OFF in both views so a move contributes its
    old path (a deletion) and its new path (an addition) — otherwise `git mv` into a seam
    directory would vanish a vendored file with zero ledger trace. Untracked content is
    enumerated per-file so a directory row cannot declare an unbounded set.
    """
    changed = {
        line
        for line in _git(
            root, "diff", "--name-only", "--no-renames", baseline, "HEAD", "--", _PLATFORM
        )
        .strip()
        .splitlines()
        if line
    }
    for line in _git(
        root,
        "-c",
        "status.renames=false",
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        _PLATFORM,
    ).splitlines():
        if not line.strip():
            continue
        # `XY path` in porcelain v1. With rename detection off no `old -> new` arrows remain,
        # but the split stays as a belt against a future git changing that default.
        changed.add(line[3:].split(" -> ")[-1].strip().strip('"'))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-inline-deltas", type=int, default=40)
    parser.add_argument("--ledger-complete", action="store_true")
    parser.add_argument(
        "--root", default=None, help="repository root to check (default: this repository)"
    )
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else _repo_root()

    fail: list[str] = []
    upstream_md = root / _PLATFORM / "UPSTREAM.md"
    if not upstream_md.is_file():
        fail.append(
            f"{_PLATFORM}/UPSTREAM.md: missing — a vendored tree whose origin and deltas are "
            "unrecorded cannot absorb upstream (L27)"
        )
        return _report(fail, rows=0, cap=args.max_inline_deltas)

    body = _strip_fences(upstream_md.read_text(encoding="utf-8", errors="replace"))

    adopted_values = _sha_fields(body, _ADOPTED_FIELD)
    if not adopted_values:
        fail.append(f"UPSTREAM.md: no `{_ADOPTED_FIELD} <40-hex>` line — the origin is unpinned")
    elif len(adopted_values) > 1:
        fail.append(
            f"UPSTREAM.md: `{_ADOPTED_FIELD}` appears {len(adopted_values)} times — ambiguous"
        )
    elif adopted_values[0] is None:
        fail.append(f"UPSTREAM.md: `{_ADOPTED_FIELD}` line carries no 40-hex commit")

    baseline: str | None = None
    baseline_values = _sha_fields(body, _BASELINE_FIELD)
    if not baseline_values:
        fail.append(
            f"UPSTREAM.md: no `{_BASELINE_FIELD} <40-hex>` line — without a baseline, drift "
            "cannot be measured"
        )
    elif len(baseline_values) > 1:
        fail.append(
            f"UPSTREAM.md: `{_BASELINE_FIELD}` appears {len(baseline_values)} times — ambiguous"
        )
    elif baseline_values[0] is None:
        fail.append(f"UPSTREAM.md: `{_BASELINE_FIELD}` line carries no 40-hex commit")
    else:
        baseline = baseline_values[0]
        resolvable = (
            subprocess.run(
                ["git", "-C", str(root), "cat-file", "-e", f"{baseline}^{{commit}}"],
                capture_output=True,
            ).returncode
            == 0
        )
        if not resolvable:
            fail.append(
                f"UPSTREAM.md: vendor baseline {baseline[:12]} does not resolve to a commit "
                "in this repository — the ledger's reference point is fictional"
            )
            baseline = None

    rows = _ledger_rows(body)
    if len(rows) > args.max_inline_deltas:
        fail.append(
            f"UPSTREAM.md: {len(rows)} inline deltas exceed the cap of "
            f"{args.max_inline_deltas} — seams are being skipped and fork rot has begun"
        )
    for path, reason in rows:
        if not reason or reason in _PLACEHOLDER_CELLS:
            fail.append(f"UPSTREAM.md: ledger row {path} has no reason — a bare path is a claim")

    if args.ledger_complete and baseline is not None:
        changed = {p for p in _changed_paths(root, baseline) if not _exempt(p)}
        declared = {path for path, _ in rows}
        for path in sorted(changed - declared):
            fail.append(
                f"{path}: differs from the vendor baseline but is not in the inline-delta "
                "ledger — undeclared drift is how upstream merges die"
            )
        for path in sorted(declared - changed):
            fail.append(
                f"UPSTREAM.md: ledger row {path} is stale — the path no longer differs from "
                "the baseline (or does not exist), and a map that disagrees with the territory "
                "is worse than no map"
            )

    return _report(fail, rows=len(rows), cap=args.max_inline_deltas)


def _report(fail: list[str], *, rows: int, cap: int) -> int:
    if fail:
        print(f"upstream_check: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"UPSTREAM-GATE {problem}", file=sys.stderr)
        return 1
    print(
        f"upstream_check: {rows} inline delta(s) against a cap of {cap}, every delta declared, "
        "baseline resolves — upstream mergeability intact (L27)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
