"""The platform document store — ADR-0068's engaged fallback, in its C5 slice.

Platform data (conversations, messages, turn ledgers) lives HERE, in its own SQLite file,
never in the engine's proof store and never in the API's runs database (L33: two stores, a
third is forbidden — this IS the second store, the document one). The shape is deliberately
the fallback's: one `documents` table of JSON rows with expression indices on the hot fields,
so C6's Mongoose-methods adapter lands on this exact schema rather than migrating it.

stdlib `sqlite3` only, WAL, `synchronous=FULL` — the turnlog's durability discipline. Every
public method opens, commits and closes; there is no long-lived connection to leak across the
prove threads and the FastAPI event loop. Writers serialize on SQLite's own file lock; the
one hot path that needs batching (streamed turn deltas) batches ABOVE this module and flushes
terminal frames synchronously, because a lost mid-stream delta is replayable noise while a
lost terminal frame is a lie about whether the turn finished.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    collection TEXT NOT NULL,
    id         TEXT NOT NULL,
    doc        TEXT NOT NULL,
    PRIMARY KEY (collection, id)
) WITHOUT ROWID;
-- Plain expression indexes, deliberately NOT partial: a partial index whose WHERE names a
-- literal collection is unusable when the query passes the collection as a bound parameter
-- (the planner cannot prove the predicate at plan time), which is exactly how every query
-- here binds it. The expression columns cover all collections; the write overhead is noise
-- at this store's scale.
CREATE INDEX IF NOT EXISTS idx_doc_updated
    ON documents (collection, json_extract(doc, '$.updatedAt'));
CREATE INDEX IF NOT EXISTS idx_doc_convo
    ON documents (collection, json_extract(doc, '$.conversationId'),
                  json_extract(doc, '$.createdAt'));
CREATE INDEX IF NOT EXISTS idx_doc_stream
    ON documents (collection, json_extract(doc, '$.streamId'),
                  json_extract(doc, '$.seq'));
"""


def _ensure_wal(conn: sqlite3.Connection) -> None:
    """Put the FILE in WAL, once, and never at the cost of the write that asked.

    WAL is a property of the database header, not of a connection: it survives every open,
    so it only ever needs setting once. It used to run on every `_connect`, and that was a
    data-loss bug. Changing the journal mode needs an EXCLUSIVE lock, and SQLite answers
    SQLITE_BUSY for it IMMEDIATELY rather than parking on the busy handler — deliberately,
    to avoid deadlock. So while one thread held the write transaction that creates the
    schema, every other thread opening a connection died on the pragma with `database is
    locked`. Measured, deterministically, at 5/5 trials: a journal-mode change against a
    held write transaction always fails, while a WAL→WAL no-op never does.

    In a test that looked like a missing row. In a turn thread it is worse: the exception
    kills a worker nobody is reading, the document never lands, and the turn simply stops —
    L15.5 (zero data loss) failing quietly, with L15.3 on top.

    Two things follow, and both are here. The mode is READ first, so a file already in WAL —
    every file after the first open — never attempts a conversion at all. And a conversion
    that cannot get its lock right now is not fatal: WAL is a durability and concurrency
    optimisation, and a store that cannot convert this instant must still take the write.
    The catch recovers rather than swallows (L15.3): the file stays in rollback mode, every
    write still lands, and the next open tries again.
    """
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        return


class PlatformStore:
    """One file, one table, JSON documents — opened lazily, schema ensured once per path."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._schema_ready = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30.0)
        # Set BEFORE anything that can contend, and explicitly rather than relying on the
        # connect timeout alone: a statement that meets a held lock waits here instead of
        # failing, which is the difference between a slow write and a lost one.
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    _ensure_wal(conn)
                    conn.executescript(_SCHEMA)
                    conn.commit()
                    self._schema_ready = True
        return conn

    # ------------------------------------------------------------------ writes

    def put(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None:
        """Insert or replace one document (upsert-by-id — saveMessage's idempotence)."""
        payload = json.dumps(doc, sort_keys=True, separators=(",", ":"))
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO documents (collection, id, doc) VALUES (?, ?, ?) "
                "ON CONFLICT (collection, id) DO UPDATE SET doc = excluded.doc",
                (collection, doc_id, payload),
            )
            conn.commit()
        finally:
            conn.close()

    def put_many_multi(
        self,
        rows: list[tuple[str, str, dict[str, Any]]],
        *,
        delete_equal: list[tuple[str, str, str]] | None = None,
    ) -> None:
        """One transaction across collections — the terminal-commit path: a turn's messages,
        its ledger tail and its status row land together, so no reader can catch a state
        where one exists without the others (the run-events lesson, fix 52e18fd).

        `delete_equal` rows — (collection, field, value) — are removed in the SAME
        transaction, before the inserts: a new turn's opening commit atomically retires the
        previous turn's ledger so no reader ever sees two generations interleaved."""
        if not rows and not delete_equal:
            return
        encoded = [
            (collection, doc_id, json.dumps(doc, sort_keys=True, separators=(",", ":")))
            for collection, doc_id, doc in rows
        ]
        conn = self._connect()
        try:
            for collection, field, value in delete_equal or []:
                _check_field(field)
                conn.execute(
                    "DELETE FROM documents WHERE collection = ? "
                    f"AND json_extract(doc, '$.{field}') = ?",
                    (collection, value),
                )
            if encoded:
                conn.executemany(
                    "INSERT INTO documents (collection, id, doc) VALUES (?, ?, ?) "
                    "ON CONFLICT (collection, id) DO UPDATE SET doc = excluded.doc",
                    encoded,
                )
            conn.commit()
        finally:
            conn.close()

    def delete(self, collection: str, doc_id: str) -> bool:
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM documents WHERE collection = ? AND id = ?", (collection, doc_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------- reads

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT doc FROM documents WHERE collection = ? AND id = ?",
                (collection, doc_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        parsed: Any = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else None

    def find_equal(
        self,
        collection: str,
        field: str,
        value: str,
        *,
        order_by: str,
        descending: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Equality on one JSON field, ordered by another — the two hot queries this slice
        serves (messages of a conversation; events of a stream). `field`/`order_by` are code
        literals, never user input; the guard makes that a property rather than a habit."""
        _check_field(field)
        _check_field(order_by)
        sql = (
            "SELECT doc FROM documents WHERE collection = ? "
            f"AND json_extract(doc, '$.{field}') = ? "
            f"ORDER BY json_extract(doc, '$.{order_by}') {'DESC' if descending else 'ASC'}"
        )
        params: list[Any] = [collection, value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._docs(sql, params)

    def list_ordered(
        self,
        collection: str,
        *,
        order_by: str,
        descending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        _check_field(order_by)
        sql = (
            "SELECT doc FROM documents WHERE collection = ? "
            f"ORDER BY json_extract(doc, '$.{order_by}') {'DESC' if descending else 'ASC'}"
        )
        params: list[Any] = [collection]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._docs(sql, params)

    def _docs(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        docs: list[dict[str, Any]] = []
        for (payload,) in rows:
            parsed: Any = json.loads(payload)
            if isinstance(parsed, dict):
                docs.append(parsed)
        return docs


def _check_field(name: str) -> None:
    """Field names are interpolated into json_extract paths; refuse anything that is not a
    bare identifier so the interpolation cannot become injection even by a future mistake."""
    if not name.replace("_", "").isalnum() or not name:
        raise ValueError(f"not a bare document field name: {name!r}")
