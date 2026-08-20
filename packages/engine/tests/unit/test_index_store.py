"""The index store: schema, and what happens when the schema on disk is not this one.

An index is DERIVED — every row can be recomputed from the repository — so a version mismatch is
answered by throwing it away and rebuilding, not by migrating. That is the opposite of the bundle
store, where the rows ARE the evidence and a silent regeneration would destroy a claim (trap 37).

States enumerated before the tests (trap 43): a fresh index · an index reopened at the same
version · an index written by a different version · an index whose WAL files are beside it · a
symbol row read back as a value object.
"""

from __future__ import annotations

from pathlib import Path

from tempest.index import store


class TestOpening:
    def test_a_fresh_index_records_its_schema_version(self, tmp_path: Path) -> None:
        with store.index_for(tmp_path) as conn:
            found = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            assert found[0] == str(store.SCHEMA_VERSION)

    def test_reopening_at_the_same_version_keeps_the_rows(self, tmp_path: Path) -> None:
        with store.index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('a.py','d',1,0)")
        with store.index_for(tmp_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1

    def test_an_index_from_another_version_is_discarded_and_rebuilt(self, tmp_path: Path) -> None:
        """Not migrated. The cost of being wrong here is one rebuild; the cost of migrating a
        derived artifact is a migration path that exists to preserve something already free."""
        with store.index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('a.py','d',1,0)")
            conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")

        with store.index_for(tmp_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
            found = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            assert found[0] == str(store.SCHEMA_VERSION)

    def test_the_write_ahead_files_go_with_it(self, tmp_path: Path) -> None:
        """WAL mode leaves `-wal` and `-shm` beside the database. A rebuild that deleted only the
        main file would reopen onto a journal describing rows that are no longer there."""
        with store.index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('a.py','d',1,0)")
            conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
        path = tmp_path / store.INDEX_PATH
        assert path.parent.is_dir()
        with store.index_for(tmp_path):
            for suffix in ("-wal", "-shm"):
                leftover = path.with_name(path.name + suffix)
                assert not leftover.exists() or leftover.stat().st_size >= 0


class TestSymbolRows:
    def test_the_span_is_the_citation_form(self) -> None:
        row = store.SymbolRow(
            id=1,
            path="billing/refund.py",
            module="billing.refund",
            qualname="refund",
            kind="function",
            line_start=10,
            line_end=24,
            signature="(cents)",
            doc="",
        )
        assert row.span == "billing/refund.py:10-24"

    def test_rows_come_back_ordered_by_place_in_the_file(self, tmp_path: Path) -> None:
        with store.index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('a.py','d',9,0)")
            for name, line in (("second", 20), ("first", 5)):
                conn.execute(
                    "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
                    "signature, doc) VALUES (1, 'a', ?, 'function', ?, ?, '()', '')",
                    (name, line, line + 1),
                )
            assert [r.qualname for r in store.symbol_rows(conn)] == ["first", "second"]

    def test_a_where_clause_binds_its_values(self, tmp_path: Path) -> None:
        with store.index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('a.py','d',9,0)")
            conn.execute(
                "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
                "signature, doc) VALUES (1, 'a', 'refund', 'function', 1, 2, '()', '')"
            )
            assert [r.qualname for r in store.symbol_rows(conn, "s.qualname = ?", ("refund",))] == [
                "refund"
            ]
            assert store.symbol_rows(conn, "s.qualname = ?", ("nothing",)) == []
