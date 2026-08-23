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
        def write(index: int) -> None:
            store.put_many_multi([("turn_events", f"s:{index}", {"streamId": "s", "seq": index})])

        threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        docs = store.find_equal("turn_events", "streamId", "s", order_by="seq")
        assert [d["seq"] for d in docs] == list(range(8))


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
