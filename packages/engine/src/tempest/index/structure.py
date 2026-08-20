"""The structural index — symbols, their spans, and who calls whom (Phase 22, F13).

**Incremental by content digest.** A file whose bytes have not changed is not re-parsed and its
rows are not rewritten. That is what makes re-indexing a 500k-line repository a few milliseconds
of hashing rather than a full parse, and it is the only reason the ambient re-index in Phase 26
can ever be cheap enough to run on save.

**`ast`, not tree-sitter.** The master prompt names tree-sitter, and for a multi-language index it
is the right answer. Python's own `ast` is in the standard library, is exactly as incremental at
file granularity, and is the parser the ENGINE already uses to choose targets
(`targets/symbols.py`) — so the index and the prover agree about what a symbol is by
construction rather than by two parsers happening to concur. The moment a second language needs
structural indexing, tree-sitter earns its dependency and this module grows a backend seam; until
then it would be a native dependency in a frozen binary, bought with nothing (ADR-0054).

**Call edges are recorded by NAME, and resolved where they can be.** `charge(...)` records the
callee name; if exactly one indexed symbol has that name the edge is resolved to it. Ambiguous and
unknown names stay unresolved rather than being guessed, because a call graph that guesses is a
call graph that answers "who calls this?" with things that do not.
"""

from __future__ import annotations

import ast
import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from tempest.config import TempestConfig, TempestConfigError, is_ignored
from tempest.execute.runner import module_for_path


@dataclass(frozen=True)
class ParsedSymbol:
    module: str
    qualname: str
    kind: str
    line_start: int
    line_end: int
    signature: str
    doc: str
    calls: tuple[tuple[str, int], ...]
    text: str


@dataclass(frozen=True)
class IndexStats:
    files_seen: int
    files_reparsed: int
    symbols: int
    calls: int
    unreadable: tuple[str, ...] = ()


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The parameter list as written. `ast.unparse` on the arguments node, which round-trips
    defaults and annotations without this module inventing a formatting rule of its own."""
    return f"({ast.unparse(node.args)})"


def parse_symbols(source: str, module: str) -> list[ParsedSymbol]:
    """Every top-level function, class, and method in one module.

    Nested functions are deliberately NOT indexed as symbols of their own: they are not
    importable, the engine cannot target them, and an index that offered them as answers would be
    offering something nothing else in the product can act on. Their calls are attributed to the
    enclosing symbol, which is where a reader would look for them.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[ParsedSymbol] = []

    def calls_in(node: ast.AST) -> tuple[tuple[str, int], ...]:
        found: list[tuple[str, int]] = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name):
                found.append((func.id, child.lineno))
            elif isinstance(func, ast.Attribute):
                found.append((func.attr, child.lineno))
        return tuple(found)

    def record(
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, qualname: str, kind: str
    ) -> None:
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        out.append(
            ParsedSymbol(
                module=module,
                qualname=qualname,
                kind=kind,
                line_start=start,
                line_end=node.end_lineno or node.lineno,
                signature="" if isinstance(node, ast.ClassDef) else _signature(node),
                doc=ast.get_docstring(node) or "",
                calls=calls_in(node),
                text=ast.get_source_segment(source, node) or "",
            )
        )

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            record(
                node,
                node.name,
                "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            )
        elif isinstance(node, ast.ClassDef):
            record(node, node.name, "class")
            for member in ast.iter_child_nodes(node):
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    record(member, f"{node.name}.{member.name}", "method")
    return out


def python_files(repo: Path) -> list[Path]:
    """Every Python file the engine would consider, in a stable order.

    Uses the repository's own ignore rules, so the index covers exactly what the prover covers —
    an index over files the engine refuses to touch would answer questions about code the product
    can say nothing else about.
    """
    try:
        config = TempestConfig.load(repo)
    except TempestConfigError:
        config = TempestConfig()
    out: list[Path] = []
    for path in sorted(repo.rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        if is_ignored(rel, config.ignore_globs):
            continue
        if any(
            part in {".git", ".tempest", "__pycache__"} for part in path.relative_to(repo).parts
        ):
            continue
        out.append(path)
    return out


def build(conn: sqlite3.Connection, repo: Path, *, on_symbol: object = None) -> IndexStats:
    """Index every Python file under `repo`, skipping those whose bytes have not changed.

    Returns what it actually did — files seen versus files re-parsed — because "the index is up
    to date" and "the index was rebuilt" are different facts and a caller measuring incremental
    cost needs the second one.
    """
    repo = Path(repo)
    known = {
        str(row[0]): (int(row[1]), str(row[2]))
        for row in conn.execute("SELECT path, id, digest FROM files").fetchall()
    }
    seen: set[str] = set()
    reparsed = 0
    symbols = 0
    calls = 0
    unreadable: list[str] = []

    for path in python_files(repo):
        rel = path.relative_to(repo).as_posix()
        seen.add(rel)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A file the index cannot read is REPORTED, not skipped in silence: a symbol missing
            # from the index makes every "never exercised" answer quietly wrong.
            unreadable.append(rel)
            continue
        digest = digest_of(source)
        existing = known.get(rel)
        if existing is not None and existing[1] == digest:
            continue
        reparsed += 1
        if existing is not None:
            conn.execute("DELETE FROM files WHERE id = ?", (existing[0],))
        cursor = conn.execute(
            "INSERT INTO files (path, digest, lines, indexed) VALUES (?, ?, ?, ?)",
            (rel, digest, source.count("\n") + 1, time.time()),
        )
        file_id = int(cursor.lastrowid or 0)
        module = module_for_path(repo, rel)
        for parsed in parse_symbols(source, module):
            symbol_cursor = conn.execute(
                "INSERT OR REPLACE INTO symbols "
                "(file_id, module, qualname, kind, line_start, line_end, signature, doc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id,
                    parsed.module,
                    parsed.qualname,
                    parsed.kind,
                    parsed.line_start,
                    parsed.line_end,
                    parsed.signature,
                    parsed.doc,
                ),
            )
            symbol_id = int(symbol_cursor.lastrowid or 0)
            symbols += 1
            for callee, line in parsed.calls:
                conn.execute(
                    "INSERT INTO calls (caller_id, callee, callee_id, line) VALUES (?, ?, NULL, ?)",
                    (symbol_id, callee, line),
                )
                calls += 1
            if callable(on_symbol):
                on_symbol(symbol_id, parsed)

    for rel, (file_id, _digest) in known.items():
        if rel not in seen:
            # The file is gone. Its symbols go with it — an index that remembers deleted code
            # answers "where is this defined?" with a path that no longer exists.
            conn.execute("DELETE FROM files WHERE id = ?", (file_id,))

    resolve_calls(conn)
    return IndexStats(
        files_seen=len(seen),
        files_reparsed=reparsed,
        symbols=symbols,
        calls=calls,
        unreadable=tuple(unreadable),
    )


def resolve_calls(conn: sqlite3.Connection) -> int:
    """Point every call edge at a symbol when exactly ONE symbol answers to that name.

    Ambiguity is left unresolved on purpose. Two functions named `run` in different modules make
    `run(...)` genuinely undecidable from the call site alone, and a call graph that picks one is
    a call graph that will one day tell somebody their function has a caller it does not have.
    """
    unique = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT qualname, MIN(id), COUNT(*) FROM symbols GROUP BY qualname HAVING COUNT(*) = 1"
        ).fetchall()
    }
    conn.execute("UPDATE calls SET callee_id = NULL")
    resolved = 0
    for callee, symbol_id in unique.items():
        cursor = conn.execute(
            "UPDATE calls SET callee_id = ? WHERE callee = ?", (symbol_id, callee)
        )
        resolved += cursor.rowcount
    return resolved
