"""The query planner: routing, and the rule that every statement carries evidence (Phase 22).

The bar these tests hold is not "an answer comes back". It is: **an answer that is not evidenced
is not written**, and a question the planner cannot route says so instead of inventing prose.

States enumerated before the tests (trap 43): an empty index · a question matching nothing · a
question matching a symbol with no execution · each of the six routes · an absence question with
no run behind it · an answer whose statements exist but carry no citation (must be impossible).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tempest.execute.sandbox import ProcessSandbox, SandboxSelection
from tempest.index import query
from tempest.index.build import build_index
from tempest.index.store import index_for, open_index

SANDBOX = ProcessSandbox()

_APP = (
    '"""Money."""\n\n\n'
    "def parse_amount(text):\n"
    '    """Parse a money string into cents."""\n'
    "    if not isinstance(text, str):\n"
    "        raise ValueError('amount must be a string')\n"
    "    return len(text)\n\n\n"
    "def quote(text):\n"
    '    """Render a price."""\n'
    "    return parse_amount(text)\n\n\n"
    "def never_touched(reason):\n"
    '    """Nothing calls this."""\n'
    "    return str(reason)\n\n\n"
    "def constant():\n"
    '    """Calls nothing, and nothing calls it."""\n'
    "    return 1\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(_APP, encoding="utf-8")
    return root


def _fixture_selection(_repo: Path) -> SandboxSelection:
    return SandboxSelection(SANDBOX, tier="fixture", kind="process-first-party")


@pytest.fixture
def built(repo: Path) -> Iterator[sqlite3.Connection]:
    """An index over the fixture app, with only the charging path executed.

    `never_touched` is deliberately NOT run, so "which functions have never been exercised?" has
    a real answer instead of the empty set.
    """
    conn = open_index(repo)
    try:
        build_index(
            conn,
            repo,
            observe=True,
            only=frozenset({"parse_amount", "quote"}),
            max_inputs=24,
            select=_fixture_selection,
        )
        yield conn
    finally:
        conn.close()


class TestEveryStatementCarriesEvidence:
    def test_no_answer_ever_has_an_uncited_statement(self, built: sqlite3.Connection) -> None:
        """The one invariant. If this ever fails, the feature has become a chatbot."""
        questions = [
            "where is parse_amount defined?",
            "who calls parse_amount?",
            "what does quote call?",
            "what exceptions does parse_amount actually raise?",
            "what does parse_amount actually return?",
            "which functions have never been exercised?",
            "parse_amount",
        ]
        for text in questions:
            answer = query.answer(built, text)
            for statement in answer.statements:
                assert statement.citations, f"{text!r} produced an uncited statement"

    def test_an_empty_answer_is_not_counted_as_cited(self, tmp_path: Path) -> None:
        """ "Nothing to show" must never pass a citation gate by being empty — that is how a gate
        goes green about something it never looked at (trap 47)."""
        with index_for(tmp_path) as conn:
            answer = query.answer(conn, "where is anything defined?")
            assert not answer.statements and not answer.cited and answer.unanswered


class TestRouting:
    def test_absence_is_answered_from_execution_and_cites_the_run(
        self, built: sqlite3.Connection
    ) -> None:
        answer = query.answer(built, "which functions have never been exercised?")
        assert answer.route == "execution"
        assert any("never_touched" in s.text for s in answer.statements)
        assert answer.grounded_in_execution
        assert "run" in {c.kind for s in answer.statements for c in s.citations}

    def test_absence_with_nothing_ever_run_says_so_rather_than_claiming_everything(
        self, repo: Path
    ) -> None:
        """With no run behind it, "never exercised" would be true of every symbol and would mean
        nothing. The planner refuses instead."""
        with index_for(repo) as conn:
            build_index(conn, repo, observe=False)
            answer = query.answer(conn, "which functions have never been exercised?")
            assert not answer.statements
            assert "absence proves nothing" in answer.unanswered

    def test_callers_come_from_the_call_graph(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "who calls parse_amount?")
        assert answer.route == "structural"
        assert any("quote calls parse_amount" in s.text for s in answer.statements)

    def test_callees_come_from_the_call_graph(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "what does quote call?")
        assert answer.route == "structural"
        assert any("parse_amount" in s.text for s in answer.statements)

    def test_raised_exceptions_are_the_OBSERVED_ones(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "what exceptions does parse_amount actually raise?")
        assert answer.route == "execution"
        assert any("ValueError" in s.text for s in answer.statements)
        assert answer.observation_citations

    def test_a_symbol_with_no_execution_says_so_instead_of_reading_its_source(
        self, built: sqlite3.Connection
    ) -> None:
        """The refusal that makes the feature trustworthy: it will not describe behaviour it has
        not seen, even when the source is right there and obvious."""
        answer = query.answer(built, "what does never_touched actually return?")
        assert not answer.statements
        assert "no recorded execution" in answer.unanswered

    def test_a_question_matching_no_symbol_names_what_it_looked_for(
        self, built: sqlite3.Connection
    ) -> None:
        answer = query.answer(built, "where is zzzqqq defined?")
        assert not answer.statements and "zzzqqq" in answer.unanswered

    def test_a_bare_symbol_name_falls_back_to_finding_it(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "never_touched")
        assert any("never_touched" in s.text for s in answer.statements)


class TestWhatCountsAsExecUTIONGrounding:
    """The distinction the fifteen source-impossible questions rest on.

    A source span says where code IS. An observation says what it DID, and a run says what was
    exercised. Only the second two can settle a question that reading the code cannot, so a
    source citation must not qualify — otherwise every answer is "grounded" and the fifteen
    prove nothing.
    """

    def test_a_source_only_answer_is_not_grounded_in_execution(
        self, built: sqlite3.Connection
    ) -> None:
        answer = query.answer(built, "where is never_touched defined?")
        assert answer.statements and answer.cited
        assert {c.kind for s in answer.statements for c in s.citations} == {"source"}
        assert not answer.grounded_in_execution

    def test_an_observation_citation_grounds_it(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "what does parse_amount actually return?")
        assert answer.grounded_in_execution
        assert answer.observation_citations

    def test_an_empty_answer_is_not_grounded_either(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            assert not query.answer(
                conn, "what does anything actually return?"
            ).grounded_in_execution


class TestSubjectExtraction:
    def test_routing_words_are_not_part_of_the_subject(self) -> None:
        """ "who calls charge" must not retrieve every function whose docstring says "calls"."""
        assert query._subject("who calls charge?") == "charge"
        assert query._subject("what exceptions does parse_amount actually raise?") == "parse amount"


class TestTheAnswersThatAreRefusals:
    """Every route has a state where it has nothing to say, and each says so differently. A
    planner that fell through to prose here would be inventing an answer, which is the failure
    the citation rule exists to make impossible."""

    def test_a_citation_prints_as_kind_and_reference(self) -> None:
        assert str(query.Citation(kind="observation", reference="7")) == "observation:7"

    def test_when_everything_has_run_the_absence_question_says_so(self, repo: Path) -> None:
        with index_for(repo) as conn:
            build_index(conn, repo, observe=True, max_inputs=8, select=_fixture_selection)
            answer = query.answer(conn, "which functions have never been exercised?")
            assert not answer.statements
            assert "every indexed symbol has at least one recorded behaviour" in answer.unanswered

    def test_callers_of_something_that_is_not_indexed(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "who calls zzzqqq?")
        assert not answer.statements and "zzzqqq" in answer.unanswered

    def test_a_symbol_nothing_calls_says_nothing_calls_it(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "who calls never_touched?")
        assert not answer.statements
        assert "no indexed symbol calls never_touched" in answer.unanswered

    def test_callees_of_something_that_is_not_indexed(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "what does zzzqqq call?")
        assert not answer.statements and "zzzqqq" in answer.unanswered

    def test_a_symbol_that_calls_nothing_says_so(self, built: sqlite3.Connection) -> None:
        answer = query.answer(built, "what does constant call?")
        assert not answer.statements
        assert "calls nothing the index can see" in answer.unanswered

    def test_asking_what_raised_when_nothing_did(self, repo: Path) -> None:
        with index_for(repo) as conn:
            build_index(conn, repo, observe=False)
            answer = query.answer(conn, "what exceptions does parse_amount actually raise?")
            assert not answer.statements
            assert "no recorded execution of a matching symbol raised anything" in answer.unanswered

    def test_a_behaviour_class_whose_examples_are_gone_supports_nothing(
        self, built: sqlite3.Connection
    ) -> None:
        """Defensive, and reachable: the representatives are what a citation points at, so a
        class without them can carry no statement. Deleting them is the only way to construct
        the state, and it is worth constructing — the alternative is a claim with a dangling
        citation, which reads as evidence and is not."""
        built.execute("DELETE FROM observations")
        for question in (
            "what exceptions does parse_amount actually raise?",
            "what does parse_amount actually return?",
        ):
            answer = query.answer(built, question)
            assert not answer.statements, question
            assert answer.unanswered
