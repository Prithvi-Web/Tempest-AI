"""C1 gate: `store_check --no-sspl-binaries --no-proof-data-in-document-store`.

L33 — the document store is never SSPL, and never a second datastore for proofs. MongoDB
Community Server is SSPL-licensed, which the OSI declared not open source in 2021 and which is
encumbered for redistribution inside a product; and proof data (bundles, cassettes,
observations, journals, indices) stays in engine SQLite no matter what answers the platform's
Mongoose wire. Both halves are testable properties, and each check below is proven to fail on a
violating tree.

`--no-sspl-binaries`:

1. **No mongod/mongos/mongosh anywhere in the tree** — the SSPL binary must not ship, and the
   cheapest way to guarantee that is for it never to enter the repository at all.
2. **No SSPL licence text** in any LICENSE/COPYING file — a vendored component under the
   Server Side Public License is the same problem wearing a different filename.
3. **No runtime dependency that downloads the SSPL server** — `mongodb-memory-server` in a
   `dependencies` block would fetch `mongod` onto every user's machine at install time.
   (In `devDependencies` it is a test-only tool that never ships; that is allowed and the
   distinction is the point.)

`--no-proof-data-in-document-store`:

4. **The engine never speaks to a document store** — no `pymongo`/`motor`/`mongoengine` import
   under `packages/engine/src`. Proof data lives in engine SQLite; an engine that could reach
   the document store is an engine one refactor away from putting proof data in it.
5. **Cross-store references are declared** — `docs/MERGE-CONTRACT.md` carries the
   "Declared cross-store references" table with at least one real row. Opaque ids, never joins;
   the declaration is the contract this gate holds the tree to (it grows teeth against the
   live store in C6).
"""

import argparse
import re
import sys
from pathlib import Path

_SSPL_NAMES = {"mongod", "mongos", "mongosh"}
_SSPL_TEXT = "Server Side Public License"
_DOWNLOADER = "mongodb-memory-server"
_ENGINE_IMPORT = re.compile(r"^\s*(?:import|from)\s+(pymongo|motor|mongoengine)\b", re.MULTILINE)
_CROSS_STORE_HEADING = "## Declared cross-store references"
#: Untracked build/tooling output is not repository content: the claim this gate makes is about
#: what the repo carries and ships, and walking a cargo `target/` tree would cost minutes to
#: scan artifacts that no release process reads from.
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


def _walk(root: Path) -> list[Path]:
    out: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir(), key=lambda p: p.name):
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    stack.append(entry)
            else:
                out.append(entry)
    return out


def _check_sspl(root: Path, fail: list[str]) -> None:
    for path in _walk(root):
        rel = path.relative_to(root)
        stem = path.name.split(".")[0].lower()
        if stem in _SSPL_NAMES:
            fail.append(f"{rel}: a MongoDB server binary name in the tree — SSPL never ships")
            continue
        name_upper = path.name.upper()
        if name_upper.startswith(("LICENSE", "COPYING")) and _SSPL_TEXT in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            fail.append(f"{rel}: carries the Server Side Public License text — SSPL never ships")
        if path.name == "package.json":
            body = path.read_text(encoding="utf-8", errors="replace")
            deps = _runtime_dependencies_block(body)
            if deps is not None and _DOWNLOADER in deps:
                fail.append(
                    f"{rel}: runtime dependency on {_DOWNLOADER} — it downloads mongod onto "
                    "every user's machine at install time (devDependencies is where test "
                    "tooling belongs)"
                )


def _runtime_dependencies_block(body: str) -> str | None:
    """The raw text of the top-level `"dependencies"` object, or None.

    A structural slice rather than json.loads: vendored manifests are third-party input and a
    gate must not crash on one that is malformed — a paranoid reader beats a fragile parser.
    """
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


def _check_engine_imports(root: Path, fail: list[str]) -> None:
    engine_src = root / "packages" / "engine" / "src"
    if not engine_src.is_dir():
        return
    for path in sorted(engine_src.rglob("*.py")):
        match = _ENGINE_IMPORT.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            fail.append(
                f"{path.relative_to(root)}: imports {match.group(1)} — the engine never "
                "speaks to a document store; proof data stays in engine SQLite (L33)"
            )


def _check_cross_store_declaration(root: Path, fail: list[str]) -> None:
    contract = root / "docs" / "MERGE-CONTRACT.md"
    if not contract.is_file():
        fail.append(
            "docs/MERGE-CONTRACT.md: missing — cross-store references must be declared "
            "somewhere a gate can read (L33)"
        )
        return
    body = contract.read_text(encoding="utf-8")
    in_section = False
    rows = 0
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.startswith(_CROSS_STORE_HEADING)
            continue
        if not in_section or not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = [c.strip().strip("`") for c in stripped.strip("|").split("|")]
        if len(cells) >= 3 and cells[0].lower() != "from" and all(cells[:3]):
            rows += 1
    if rows == 0:
        fail.append(
            'docs/MERGE-CONTRACT.md: no "Declared cross-store references" table with at '
            "least one row — the L33 contract is undeclared"
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
        "store_check: no SSPL binary, licence, or runtime downloader in the tree; the engine "
        "imports no document-store client; cross-store references declared — L33 holds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
