"""The index database — one SQLite file holding all three indices (Phase 22, ADR-0054).

**Three indices, one store, one query planner.** F13 names them: vector, structural, execution.
They live in one file because every interesting question crosses them — *"which functions that
call `charge()` have never been exercised?"* is structural and execution in one breath — and a
join across three databases is a query planner nobody can debug.

**SQLite, WAL, stdlib.** Same reasoning as the turn log (ADR-0050): the engine ships frozen and
takes no new runtime dependency. `sqlite-vec` and LanceDB are both native extensions that would
have to be built for three platforms and loaded into a frozen binary; the vector index here is
computed in Python and stored as an inverted index, which is what makes it work in a PyInstaller
build with no extension loading at all.

**The store never decides anything.** It holds rows and answers queries. Which rows are worth
holding is `execution.py`'s judgement, what a term is worth is `lexical.py`'s, and what an answer
means is `query.py`'s. A store that scored things would be a fourth opinion nobody asked for.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

#: One file per repository, beside the agent's state and the turn log.
INDEX_PATH = Path(".tempest") / "index" / "index.sqlite3"

#: Bumped when the schema changes shape. An index built by an older engine is DISCARDED and
#: rebuilt rather than migrated: it is a derived artifact — every row can be recomputed from the
#: repository — so a migration path would be code that exists to preserve something already free.
#: That is the opposite of the bundle store, where the rows ARE the evidence (trap 37).
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- STRUCTURAL ---------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS files (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT    NOT NULL UNIQUE,
    digest    TEXT    NOT NULL,
    lines     INTEGER NOT NULL,
    indexed   REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module     TEXT    NOT NULL,
    qualname   TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    line_start INTEGER NOT NULL,
    line_end   INTEGER NOT NULL,
    signature  TEXT    NOT NULL,
    doc        TEXT    NOT NULL,
    UNIQUE(module, qualname)
);
CREATE INDEX IF NOT EXISTS symbols_by_file ON symbols (file_id);

CREATE TABLE IF NOT EXISTS calls (
    caller_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    callee    TEXT    NOT NULL,
    callee_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    line      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_by_caller ON calls (caller_id);
CREATE INDEX IF NOT EXISTS calls_by_callee ON calls (callee);

-- LEXICAL / VECTOR ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS terms (
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    term      TEXT    NOT NULL,
    count     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS terms_by_term ON terms (term);
CREATE INDEX IF NOT EXISTS terms_by_symbol ON terms (symbol_id);

CREATE TABLE IF NOT EXISTS lengths (
    symbol_id INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    tokens    INTEGER NOT NULL,
    norm      REAL    NOT NULL
);

-- EXECUTION ----------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    revision TEXT    NOT NULL,
    started  REAL    NOT NULL,
    source   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS behaviours (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    symbol_id   INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    outcome     TEXT    NOT NULL,
    return_kind TEXT    NOT NULL,
    raised_type TEXT    NOT NULL,
    effects     TEXT    NOT NULL,
    inputs      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS behaviours_by_symbol ON behaviours (symbol_id);

CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    behaviour_id   INTEGER NOT NULL REFERENCES behaviours(id) ON DELETE CASCADE,
    args_literal   TEXT    NOT NULL,
    kwargs_literal TEXT    NOT NULL,
    return_repr    TEXT    NOT NULL,
    raised_message TEXT    NOT NULL,
    stdout         TEXT    NOT NULL,
    wall_ns        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_by_behaviour ON observations (behaviour_id);
"""


class IndexError_(Exception):
    """The index could not be opened, built, or queried. Never used for an empty result."""


@dataclass(frozen=True)
class SymbolRow:
    id: int
    path: str
    module: str
    qualname: str
    kind: str
    line_start: int
    line_end: int
    signature: str
    doc: str

    @property
    def span(self) -> str:
        """The citation form. Every answer that names a symbol prints this, so a reader can go
        and look — a claim about code with no way to find the code is a claim, not evidence."""
        return f"{self.path}:{self.line_start}-{self.line_end}"


def open_index(repo: Path) -> sqlite3.Connection:
    """Open (creating if needed) the index for `repo`, at the current schema version.

    An index written by a different schema version is dropped and recreated. That is safe here
    and would not be for a bundle: an index is derived, so the worst case is the cost of
    rebuilding it, while a bundle is the evidence itself and may never be regenerated silently.
    """
    path = Path(repo) / INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    found = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if found is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
    elif found[0] != str(SCHEMA_VERSION):
        conn.close()
        path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        return open_index(repo)
    return conn


@contextmanager
def index_for(repo: Path) -> Iterator[sqlite3.Connection]:
    conn = open_index(repo)
    try:
        yield conn
    finally:
        conn.close()


def symbol_rows(
    conn: sqlite3.Connection, where: str = "", params: tuple[object, ...] = ()
) -> list[SymbolRow]:
    """Every symbol matching `where`, as value objects. `where` is composed only from literals in
    this package — no caller-supplied SQL reaches it, and every value is a bound parameter."""
    sql = (
        "SELECT s.id, f.path, s.module, s.qualname, s.kind, s.line_start, s.line_end, "
        "s.signature, s.doc FROM symbols s JOIN files f ON f.id = s.file_id"
    )
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY f.path, s.line_start"
    return [
        SymbolRow(
            id=int(r[0]),
            path=str(r[1]),
            module=str(r[2]),
            qualname=str(r[3]),
            kind=str(r[4]),
            line_start=int(r[5]),
            line_end=int(r[6]),
            signature=str(r[7]),
            doc=str(r[8]),
        )
        for r in conn.execute(sql, params).fetchall()
    ]
