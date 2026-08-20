"""Retrieval over what a symbol is called and what it says (Phase 22).

States enumerated before the tests (trap 43): an empty index · a query with no terms · a query
whose terms appear nowhere · an exact name match · a snake_case name matched by words · a
camelCase name matched by words · a misspelling matched by trigrams · a long function that merely
mentions the word · two symbols where the NAME should win · a symbol re-indexed after an edit.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from tempest.index import lexical
from tempest.index.store import index_for


def _index(conn: object, symbol_id: int, **kw: str) -> None:
    lexical.index_symbol(conn, symbol_id, lexical.document_terms(**kw))  # type: ignore[arg-type]


def _symbols(conn: object, *specs: tuple[str, str]) -> dict[str, int]:
    """Insert bare symbol rows so the foreign keys hold, and return name → id."""
    out: dict[str, int] = {}
    conn.execute(  # type: ignore[attr-defined]
        "INSERT INTO files (path, digest, lines, indexed) VALUES ('m.py', 'd', 1, 0)"
    )
    file_id = conn.execute("SELECT id FROM files").fetchone()[0]  # type: ignore[attr-defined]
    for qualname, doc in specs:
        cursor = conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
            "signature, doc) VALUES (?, 'm', ?, 'function', 1, 2, '()', ?)",
            (file_id, qualname, doc),
        )
        out[qualname] = int(cursor.lastrowid)
    return out


class TestTokenising:
    def test_snake_case_and_camel_case_both_split(self) -> None:
        assert lexical.words("round_refund_amount") == ["round", "refund", "amount"]
        assert lexical.words("roundRefundAmount") == ["round", "refund", "amount"]

    def test_stop_words_and_bare_digits_are_dropped(self) -> None:
        assert lexical.words("the amount is 42 for the refund") == ["amount", "refund"]

    def test_trigrams_are_prefixed_so_one_index_holds_both_families(self) -> None:
        grams = lexical.trigrams("ref")
        assert all(g.startswith("3:") for g in grams)
        assert "3: re" in grams

    def test_the_name_is_weighted_above_the_body(self) -> None:
        """A 200-line function that says `refund` once must not outrank the function named
        `refund`. Weighting is the mechanism, so it is asserted rather than assumed."""
        counts = lexical.document_terms(
            qualname="refund", signature="(cents)", doc="", text="def refund(cents): pass"
        )
        assert counts["refund"] >= 4


class TestSearch:
    def test_an_empty_index_answers_nothing_rather_than_raising(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            assert lexical.search(conn, "anything") == []

    def test_a_query_with_no_usable_terms_answers_nothing(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("refund", ""))
            _index(conn, ids["refund"], qualname="refund", signature="()", doc="", text="")
            assert lexical.search(conn, "the and of") == []

    def test_the_named_symbol_wins_over_one_that_merely_mentions_it(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("round_refund", ""), ("audit_log", ""))
            _index(
                conn,
                ids["round_refund"],
                qualname="round_refund",
                signature="(cents)",
                doc="",
                text="return int(cents)",
            )
            _index(
                conn,
                ids["audit_log"],
                qualname="audit_log",
                signature="(event)",
                doc="Logs a refund event and a refund reason and refund detail.",
                text="refund refund refund refund refund refund",
            )
            top = lexical.search(conn, "refund rounding")
            assert top[0].symbol_id == ids["round_refund"]

    def test_a_misspelling_still_finds_the_symbol(self, tmp_path: Path) -> None:
        """Trigrams are why. Word tokens alone answer nothing for "refnd"."""
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("refund_total", ""))
            _index(
                conn, ids["refund_total"], qualname="refund_total", signature="()", doc="", text=""
            )
            assert [s.symbol_id for s in lexical.search(conn, "refnd")] == [ids["refund_total"]]

    def test_a_term_that_appears_nowhere_scores_nothing(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("refund", ""))
            _index(conn, ids["refund"], qualname="refund", signature="()", doc="", text="")
            assert lexical.search(conn, "zzzzzzzzz") == []

    def test_the_limit_is_respected(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("refund_a", ""), ("refund_b", ""), ("refund_c", ""))
            for name, sid in ids.items():
                _index(conn, sid, qualname=name, signature="()", doc="", text="")
            assert len(lexical.search(conn, "refund", limit=2)) == 2

    def test_reindexing_replaces_terms_rather_than_adding_to_them(self, tmp_path: Path) -> None:
        """A symbol renamed from `refund` to `credit` must stop answering to `refund`, or the
        index accumulates every name a symbol has ever had."""
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("s", ""))
            _index(conn, ids["s"], qualname="refund", signature="()", doc="", text="")
            _index(conn, ids["s"], qualname="credit", signature="()", doc="", text="")
            assert lexical.search(conn, "refund") == []
            assert [s.symbol_id for s in lexical.search(conn, "credit")] == [ids["s"]]

    def test_scores_are_ordered_and_deterministic(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            ids = _symbols(conn, ("refund_total", ""), ("refund", ""))
            for name, sid in ids.items():
                _index(conn, sid, qualname=name, signature="()", doc="", text="")
            first = lexical.search(conn, "refund")
            second = lexical.search(conn, "refund")
            assert [s.symbol_id for s in first] == [s.symbol_id for s in second]
            assert first[0].score >= first[-1].score


class TestDocumentTerms:
    def test_every_source_of_text_contributes(self) -> None:
        counts: Counter[str] = lexical.document_terms(
            qualname="charge",
            signature="(amount)",
            doc="Bills the customer.",
            text="return bill(amount)",
        )
        for term in ("charge", "amount", "bills", "customer", "bill"):
            assert counts[term] >= 1
