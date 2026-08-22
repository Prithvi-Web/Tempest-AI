"""C1 gate: `store_check --no-sspl-binaries --no-proof-data-in-document-store`.

L33 — the document store is never SSPL, and never a second datastore for proofs. MongoDB
Community Server is SSPL-licensed, which the OSI declared not open source in 2021 and which is
encumbered for redistribution inside a product; and proof data (bundles, cassettes,
observations, journals, indices) stays in engine SQLite no matter what answers the platform's
Mongoose wire. Both halves are testable properties, and each check below is proven to fail on a
violating tree.

`--no-sspl-binaries`:

1. **No file carrying a MongoDB server's canonical name** (`mongod`/`mongos`/`mongosh` stem)
   anywhere in the scanned set — which is the working tree (build/tooling directories skipped
   by name) UNIONED with every git-tracked file, so tracked content inside a directory named
   `dist/` or `build/` is still scanned. Scope stated exactly: matching is by canonical name;
   a server binary renamed to something else is out of this check's reach — the licence-text
   and downloader checks below are the layers behind it.
2. **No SSPL licence text** in any LICENSE/LICENCE/COPYING file — a vendored component under
   the Server Side Public License is the same problem wearing a different filename.
3. **No runtime dependency that downloads the SSPL server** — `mongodb-memory-server` in a
   `dependencies` block would fetch `mongod` onto every user's machine at install time.
   (In `devDependencies` it is a test-only tool that never ships; that is allowed and the
   distinction is the point.) Manifests are parsed as JSON; only a manifest too malformed to
   parse falls back to a paranoid textual scan, so a decoy string cannot mask the real block.

`--no-proof-data-in-document-store`:

4. **The engine has no static import of a document-store client** — no `pymongo` / `motor` /
   `mongoengine` / `bson` import under `packages/engine/src`, found by AST (comma-form
   `import os, pymongo` included), with a textual fallback only for files Python cannot parse.
   Dynamic `importlib` indirection is out of scope and said so. Proof data lives in engine
   SQLite; an engine that could reach the document store is one refactor away from putting
   proof data in it.
5. **Cross-store references are declared** — `docs/MERGE-CONTRACT.md` carries the
   "Declared cross-store references" table with at least one real (non-placeholder) row.
   Opaque ids, never joins; the declaration is the contract this gate holds the tree to (it
   grows teeth against the live store in C6).
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

_SSPL_NAMES = {"mongod", "mongos", "mongosh"}
_SSPL_TEXT = "Server Side Public License"
_DOWNLOADER = "mongodb-memory-server"
_CLIENT_MODULES = {"pymongo", "motor", "mongoengine", "bson"}
_ENGINE_IMPORT_FALLBACK = re.compile(
    r"^\s*(?:import|from)\s+(pymongo|motor|mongoengine|bson)\b", re.MULTILINE
)
_CROSS_STORE_HEADING = "## Declared cross-store references"
_PLACEHOLDER_CELLS = {"", "—", "-", "*(none)*", "(none)", "n/a"}
#: Build/tooling output is skipped BY NAME in the walk — but the walk is unioned with
#: `git ls-files`, so anything TRACKED inside a directory with one of these names is still
#: scanned. The skip only spares the scan from cargo `target/` trees and virtualenvs.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".tempest",
    ".venv",
    "target",
    "dist",
    "build",
    ".pytest_cache",
    ".turbo",
    "coverage",
}


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/parity.py`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _tracked_rels(root: Path, fail: list[str]) -> list[str]:
    """Relative paths of every git-tracked file. When the root looks like a git checkout but
    `git ls-files` fails (dubious ownership, locked index, missing git), that is recorded as a
    FAILURE — a silently vanished union would reopen the exact tracked-content-in-`dist/`
    bypass this function exists to close. Fail closed, never fail open."""
    tracked = subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotePath=false", "ls-files", "-z"],
        capture_output=True,
        text=True,
    )
    if tracked.returncode != 0:
        if (root / ".git").exists():
            reason = (tracked.stderr or "no stderr").strip().splitlines()[0]
            fail.append(
                f"{root}: looks like a git checkout but `git ls-files` failed ({reason}) — "
                "the tracked-content union cannot be proven, and a gate that cannot see "
                "is a failing gate"
            )
        return []
    return [rel for rel in tracked.stdout.split("\0") if rel]


def _walk_files(root: Path) -> set[Path]:
    """The working-tree walk: skip-named dirs and symlinks excluded. Symlinks are skipped
    entirely — following one invites cycles and out-of-tree scans, and a symlink cannot
    itself BE the SSPL binary."""
    out: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir(), key=lambda p: p.name):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            else:
                out.add(entry)
    return out


def _check_sspl(root: Path, fail: list[str]) -> None:
    tracked = _tracked_rels(root, fail)
    tracked_set = set(tracked)
    # The name check needs no bytes, so it runs over every TRACKED name even when the file is
    # locally deleted — `git add mongod; rm mongod` must not turn the gate green on the one
    # machine where the walk cannot see what the repository ships.
    for rel in tracked:
        stem = rel.rsplit("/", 1)[-1].split(".")[0].lower()
        if stem in _SSPL_NAMES:
            fail.append(f"{rel}: a MongoDB server binary name is tracked — SSPL never ships")
    paths = _walk_files(root)
    for rel in tracked:
        path = root / rel
        if path.is_file() and not path.is_symlink():
            paths.add(path)
    for path in sorted(paths):
        rel_path = path.relative_to(root)
        if str(rel_path) not in tracked_set:
            stem = path.name.split(".")[0].lower()
            if stem in _SSPL_NAMES:
                fail.append(
                    f"{rel_path}: a MongoDB server binary name in the tree — SSPL never ships"
                )
                continue
        name_upper = path.name.upper()
        if name_upper.startswith(("LICENSE", "LICENCE", "COPYING")) and _SSPL_TEXT in (
            path.read_text(encoding="utf-8", errors="replace")
        ):
            fail.append(
                f"{rel_path}: carries the Server Side Public License text — SSPL never ships"
            )
        if path.name == "package.json":
            deps = _runtime_dependencies(path.read_text(encoding="utf-8", errors="replace"))
            if deps is not None and _DOWNLOADER in deps:
                fail.append(
                    f"{rel_path}: runtime dependency on {_DOWNLOADER} — it downloads mongod "
                    "onto every user's machine at install time (devDependencies is where "
                    "test tooling belongs)"
                )


def _runtime_dependencies(body: str) -> str | None:
    """The top-level `"dependencies"` object as text, or None.

    JSON parse first — a decoy `"dependencies"` inside a string value must not aim the check
    at the wrong braces. Only a manifest too malformed to parse falls back to the paranoid
    textual slice, so an unclosed brace still cannot smuggle the downloader past the gate.
    """
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r'"dependencies"\s*:\s*\{', body)
        if match is None:
            return None
        depth, start = 1, match.end()
        for index in range(start, len(body)):
            char = body[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return body[start:index]
        return body[start:]
    if isinstance(data, dict) and isinstance(data.get("dependencies"), dict):
        return json.dumps(data["dependencies"])
    return None


def _static_client_import(source: str) -> str | None:
    """The first document-store client a file statically imports, by AST — `import os, pymongo`
    included. Files Python cannot parse fall back to the line-anchored regex."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        match = _ENGINE_IMPORT_FALLBACK.search(source)
        return match.group(1) if match else None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _CLIENT_MODULES:
                    return alias.name.split(".")[0]
        elif (
            isinstance(node, ast.ImportFrom)
            # level == 0: `from .bson import x` names an engine-LOCAL module, not the client.
            and node.level == 0
            and node.module
            and node.module.split(".")[0] in _CLIENT_MODULES
        ):
            return node.module.split(".")[0]
    return None


def _check_engine_imports(root: Path, fail: list[str]) -> None:
    engine_src = root / "packages" / "engine" / "src"
    if not engine_src.is_dir():
        return
    for path in sorted(engine_src.rglob("*.py")):
        found = _static_client_import(path.read_text(encoding="utf-8", errors="replace"))
        if found:
            fail.append(
                f"{path.relative_to(root)}: imports {found} — the engine never speaks to a "
                "document store; proof data stays in engine SQLite (L33)"
            )


def _separator_row(cells: list[str]) -> bool:
    """True for `|---|`, `| --- |`, `|:---:|` and friends in any prettifier dialect."""
    return all(not cell or set(cell) <= {"-", ":"} for cell in cells)


def _check_cross_store_declaration(root: Path, fail: list[str]) -> None:
    contract = root / "docs" / "MERGE-CONTRACT.md"
    if not contract.is_file():
        fail.append(
            "docs/MERGE-CONTRACT.md: missing — cross-store references must be declared "
            "somewhere a gate can read (L33)"
        )
        return
    body = contract.read_text(encoding="utf-8", errors="replace")
    in_section = False
    rows = 0
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.startswith(_CROSS_STORE_HEADING)
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in stripped.strip("|").split("|")]
        if _separator_row(cells) or (cells and cells[0].lower() == "from"):
            continue
        if len(cells) >= 3 and all(cell not in _PLACEHOLDER_CELLS for cell in cells[:3]):
            rows += 1
    if rows == 0:
        fail.append(
            'docs/MERGE-CONTRACT.md: no "Declared cross-store references" table with at '
            "least one real row — the L33 contract is undeclared"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-sspl-binaries", action="store_true")
    parser.add_argument("--no-proof-data-in-document-store", action="store_true")
    parser.add_argument(
        "--root", default=None, help="repository root to check (default: this repository)"
    )
    args = parser.parse_args(argv)
    if not (args.no_sspl_binaries or args.no_proof_data_in_document_store):
        parser.error("pass --no-sspl-binaries and/or --no-proof-data-in-document-store")
    root = Path(args.root) if args.root else _repo_root()
    if not root.is_dir():
        print("store_check: 1 problem(s) — FAIL")
        print(
            f"STORE-GATE {root}: not a directory — nothing to check is a failure, not a pass",
            file=sys.stderr,
        )
        return 1

    fail: list[str] = []
    if args.no_sspl_binaries:
        _check_sspl(root, fail)
    if args.no_proof_data_in_document_store:
        _check_engine_imports(root, fail)
        _check_cross_store_declaration(root, fail)

    if fail:
        print(f"store_check: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"STORE-GATE {problem}", file=sys.stderr)
        return 1
    print(
        "store_check: no SSPL binary name, licence, or runtime downloader in the tree; the "
        "engine has no static document-store import; cross-store references declared — L33 holds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
