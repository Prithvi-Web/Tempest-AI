"""The platform document store (ADR-0068 fallback, C5 slice) — JSON docs in their own SQLite
file, upsert-by-id, ordered reads, and the one multi-collection transaction the streamed-turn
terminal commit rides. Platform data only: this file never holds proof data (L33)."""

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tempest_api.platformstore import PlatformStore


@pytest.fixture
def store(tmp_path: Path) -> PlatformStore:
    return PlatformStore(tmp_path / "platform" / "store.sqlite3")


class TestRoundtrip:
    def test_put_get_roundtrip(self, store: PlatformStore) -> None:
        store.put("conversations", "c1", {"conversationId": "c1", "title": "hello"})
        assert store.get("conversations", "c1") == {"conversationId": "c1", "title": "hello"}

    def test_get_absent_is_none(self, store: PlatformStore) -> None:
        assert store.get("conversations", "nope") is None

    def test_put_is_upsert_by_id(self, store: PlatformStore) -> None:
        store.put("messages", "m1", {"text": "first"})
        store.put("messages", "m1", {"text": "second"})
        doc = store.get("messages", "m1")
        assert doc is not None and doc["text"] == "second"

    def test_collections_do_not_collide(self, store: PlatformStore) -> None:
        store.put("conversations", "x", {"kind": "convo"})
        store.put("messages", "x", {"kind": "message"})
        convo = store.get("conversations", "x")
        message = store.get("messages", "x")
        assert convo is not None and convo["kind"] == "convo"
        assert message is not None and message["kind"] == "message"

    def test_delete_reports_whether_anything_went(self, store: PlatformStore) -> None:
        store.put("messages", "m1", {"text": "bye"})
        assert store.delete("messages", "m1") is True
        assert store.delete("messages", "m1") is False
        assert store.get("messages", "m1") is None


class TestOrderedReads:
    def test_find_equal_orders_by_the_named_field(self, store: PlatformStore) -> None:
        store.put("messages", "m2", {"conversationId": "c1", "createdAt": "2026-01-02"})
        store.put("messages", "m1", {"conversationId": "c1", "createdAt": "2026-01-01"})
        store.put("messages", "m9", {"conversationId": "OTHER", "createdAt": "2026-01-03"})
        docs = store.find_equal("messages", "conversationId", "c1", order_by="createdAt")
        assert [d["createdAt"] for d in docs] == ["2026-01-01", "2026-01-02"]

    def test_find_equal_descending_and_limited(self, store: PlatformStore) -> None:
        for index in range(5):
            store.put(
                "turn_events",
                f"s1:{index}",
                {"streamId": "s1", "seq": index, "createdAt": f"2026-01-0{index + 1}"},
            )
        docs = store.find_equal(
            "turn_events", "streamId", "s1", order_by="seq", descending=True, limit=2
        )
        assert [d["seq"] for d in docs] == [4, 3]

    def test_numeric_order_is_numeric_not_lexicographic(self, store: PlatformStore) -> None:
        for seq in (2, 10, 1):
            store.put("turn_events", f"s:{seq}", {"streamId": "s", "seq": seq})
        docs = store.find_equal("turn_events", "streamId", "s", order_by="seq")
        assert [d["seq"] for d in docs] == [1, 2, 10]

    def test_list_ordered_serves_the_conversation_rail(self, store: PlatformStore) -> None:
        store.put("conversations", "old", {"updatedAt": "2026-01-01"})
        store.put("conversations", "new", {"updatedAt": "2026-02-01"})
        docs = store.list_ordered("conversations", order_by="updatedAt", descending=True)
        assert [d["updatedAt"] for d in docs] == ["2026-02-01", "2026-01-01"]


class TestMultiCollectionCommit:
    def test_put_many_multi_lands_every_row(self, store: PlatformStore) -> None:
        store.put_many_multi(
            [
                ("conversations", "c1", {"conversationId": "c1"}),
                ("messages", "m1", {"messageId": "m1"}),
                ("turns", "c1", {"status": "complete"}),
            ]
        )
        assert store.get("conversations", "c1") is not None
        assert store.get("messages", "m1") is not None
        turn = store.get("turns", "c1")
        assert turn is not None and turn["status"] == "complete"

    def test_put_many_multi_with_nothing_is_a_no_op(self, store: PlatformStore) -> None:
        store.put_many_multi([])
        assert store.list_ordered("turns", order_by="status") == []

    def test_deletes_alone_are_a_real_transaction(self, store: PlatformStore) -> None:
        store.put("turn_events", "s:1", {"streamId": "s", "seq": 1})
        store.put_many_multi([], delete_equal=[("turn_events", "streamId", "s")])
        assert store.find_equal("turn_events", "streamId", "s", order_by="seq") == []

    def test_put_many_multi_is_one_transaction(self, store: PlatformStore) -> None:
        """A duplicate primary key mid-batch aborts the WHOLE batch — the terminal commit is
        all-or-nothing, which is the property fix 52e18fd exists to teach."""
        store.put("messages", "dup", {"v": 0})
        rows = [
            ("conversations", "c1", {"conversationId": "c1"}),
            ("messages", "dup", {"v": 1}),
        ]
        # Force the second row to violate a constraint by making the doc unserializable is
        # not possible (json handles dicts), so drive the failure through sqlite itself:
        # a doc that json.dumps refuses.
        rows.append(("turns", "t1", {"bad": object()}))  # type: ignore[dict-item]
        with pytest.raises(TypeError):
            store.put_many_multi(rows)  # type: ignore[arg-type]
        # Nothing from the failed batch landed — the first row's insert never committed.
        assert store.get("conversations", "c1") is None

    def test_concurrent_writers_all_land(self, store: PlatformStore) -> None:
        """A write that vanishes under concurrency is L15.5 failing quietly, and the worker
        that vanishes with it is L15.3.

        This caught a real one: `_connect` set `PRAGMA journal_mode=WAL` on EVERY connection,
        changing the journal mode needs a brief EXCLUSIVE lock, and SQLite answers
        SQLITE_BUSY for it rather than parking on the busy handler — so one of several
        writers opening at once died with `database is locked` and its document never landed.
        In a turn thread that is not a missing row, it is a turn that stops.

        The original raced only under load, which is why it survived: a writer count and a
        hope are not a concurrency test. A BARRIER makes every thread contend on `_connect`
        at the same moment (trap 61), and thread exceptions are collected so a lost write
        fails as ITSELF rather than as a mystery row count.
        """
        writers = 24
        ready = threading.Barrier(writers)
        failures: list[BaseException] = []
        failures_lock = threading.Lock()

        def write(index: int) -> None:
            try:
                ready.wait(timeout=10)  # everyone opens a connection at once, deliberately
                store.put_many_multi(
                    [("turn_events", f"s:{index}", {"streamId": "s", "seq": index})]
                )
            except BaseException as exc:  # recorded, never swallowed — see the docstring
                with failures_lock:
                    failures.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not failures, f"writers died instead of writing: {failures[:3]}"
        docs = store.find_equal("turn_events", "streamId", "s", order_by="seq")
        assert [d["seq"] for d in docs] == list(range(writers))

    def test_a_write_survives_a_journal_mode_change_it_cannot_make(self, tmp_path: Path) -> None:
        """The deterministic form of the bug that made this file go red, reproduced by its
        actual mechanism instead of by load.

        A `PRAGMA journal_mode=` change needs an EXCLUSIVE lock and SQLite answers
        SQLITE_BUSY for it IMMEDIATELY — it does not park on the busy handler, deliberately,
        to avoid deadlock. So a store opening a not-yet-WAL file while ANY other connection
        holds a write transaction used to die on the pragma, losing the write and the worker
        with it. Measured at 5/5 trials against raw sqlite3; a WAL→WAL no-op never fails,
        which is why the bug needed a fresh file to show itself.

        Here the file is placed in rollback mode and a write transaction is held open
        throughout. The store must still take the write: WAL is a durability and concurrency
        optimisation, not a precondition for storing a document.
        """
        db = tmp_path / "platform" / "store.sqlite3"
        db.parent.mkdir(parents=True, exist_ok=True)
        seed = sqlite3.connect(db)
        seed.execute("PRAGMA journal_mode=delete")
        seed.commit()
        seed.close()

        holder = sqlite3.connect(db, timeout=30.0)
        holder.execute("CREATE TABLE IF NOT EXISTS keepalive (x)")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO keepalive VALUES (1)")
        try:
            store = PlatformStore(db)
            landed: list[str] = []
            failed: list[BaseException] = []

            def write() -> None:
                try:
                    store.put("conversations", "c1", {"conversationId": "c1", "title": "t"})
                    landed.append("ok")
                except BaseException as exc:
                    failed.append(exc)

            worker = threading.Thread(target=write)
            worker.start()
            # The write itself waits on the held transaction — that part is correct and is
            # what `busy_timeout` is for. Release once it has certainly reached the pragma.
            worker.join(timeout=2)
            holder.commit()
            worker.join(timeout=30)
        finally:
            holder.close()

        assert not failed, f"the write died on a journal-mode change: {failed}"
        assert landed == ["ok"]
        assert store.get("conversations", "c1") is not None, (
            "the document never landed — a write lost to an optimisation is still a lost write"
        )

    def test_the_journal_mode_is_set_on_the_file_not_per_connection(
        self, store: PlatformStore
    ) -> None:
        """WAL lives in the database header and survives every connection, so setting it once
        is not an optimisation — it is what keeps a hot path off an exclusive lock. A fresh
        connection must FIND the file already in WAL without asking for it."""
        store.put("conversations", "c1", {"conversationId": "c1"})
        import sqlite3

        conn = sqlite3.connect(store.path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert str(mode).lower() == "wal", (
            f"the file is in {mode!r}: durability and concurrent readers both depend on WAL"
        )


class TestHonestEdges:
    def test_two_instances_share_one_file(self, store: PlatformStore) -> None:
        twin = PlatformStore(store.path)
        store.put("conversations", "c1", {"title": "from the first"})
        doc = twin.get("conversations", "c1")
        assert doc is not None and doc["title"] == "from the first"

    def test_a_non_object_row_is_skipped_not_fatal(self, store: PlatformStore) -> None:
        store.put("messages", "ok", {"conversationId": "c", "createdAt": "a"})
        conn = sqlite3.connect(store.path)
        conn.execute(
            "INSERT INTO documents (collection, id, doc) VALUES ('messages', 'bad', '[1,2]')"
        )
        conn.commit()
        conn.close()
        store.put("messages", "ok2", {"conversationId": "c", "createdAt": "z"})
        docs = store.find_equal("messages", "conversationId", "c", order_by="createdAt")
        assert len(docs) == 2  # the corrupt row sits between the good ones and is skipped
        assert store.get("messages", "bad") is None

    def test_field_names_must_be_bare_identifiers(self, store: PlatformStore) -> None:
        with pytest.raises(ValueError):
            store.find_equal("messages", "a') OR 1=1 --", "x", order_by="createdAt")
        with pytest.raises(ValueError):
            store.list_ordered("messages", order_by="")

    def test_a_non_object_row_mid_list_is_skipped_in_an_unfiltered_scan(
        self, store: PlatformStore
    ) -> None:
        """`find_equal` never sees corrupt rows (json_extract of a non-object is NULL and
        fails the equality), so the skip-and-continue arm lives in `list_ordered`."""
        store.put("conversations", "a", {"updatedAt": "2026-01-01"})
        conn = sqlite3.connect(store.path)
        conn.execute(
            "INSERT INTO documents (collection, id, doc) VALUES ('conversations', 'bad', '5')"
        )
        conn.commit()
        conn.close()
        store.put("conversations", "z", {"updatedAt": "2026-02-01"})
        docs = store.list_ordered("conversations", order_by="updatedAt", descending=False)
        assert [d["updatedAt"] for d in docs] == ["2026-01-01", "2026-02-01"]

    def test_the_second_thread_through_schema_init_stands_down(self, store: PlatformStore) -> None:
        """The double-checked init: a thread that loses the race finds the schema ready
        inside the lock and must not re-run the script. Driven deterministically: the flag
        flips while the loser is parked on the lock."""
        store.put("conversations", "warm", {"updatedAt": "x"})  # schema now exists on disk
        store._schema_ready = False  # the loser's view: outer check will say "not ready"
        released = threading.Event()
        arrived = threading.Event()

        def loser() -> None:
            arrived.set()
            store.put("conversations", "second", {"updatedAt": "y"})
            released.set()

        with store._lock:
            thread = threading.Thread(target=loser)
            thread.start()
            assert arrived.wait(timeout=5)
            time.sleep(0.05)  # the loser is now parked on the lock at the inner check
            store._schema_ready = True
        assert released.wait(timeout=5)
        thread.join(timeout=5)
        assert store.get("conversations", "second") is not None
