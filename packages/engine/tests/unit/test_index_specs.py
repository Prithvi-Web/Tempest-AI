"""F4 — a behavioural spec is a description of what RAN, and every sentence cites an input.

The adversarial test is the one that matters and it is first: a function whose name and docstring
say one thing and whose body does another must produce a spec describing the BODY. That is the
test that proves the feature is what it claims rather than a summariser with extra steps.

States enumerated before the tests (trap 43): a symbol that is not indexed · one indexed but never
run · one whose behaviour classes kept no examples · one that returns · one that raises · one that
does both · one that prints · a claim constructed with no evidence (must be impossible).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tempest.execute.sandbox import ProcessSandbox, SandboxSelection
from tempest.index import specs
from tempest.index.build import build_index
from tempest.index.store import open_index

SANDBOX = ProcessSandbox()

_APP = (
    "def round_up(cents):\n"
    '    """Round the amount UP to the next whole unit."""\n'
    "    return int(cents)\n\n\n"
    "def parse(text):\n"
    '    """Parse a value."""\n'
    "    if not isinstance(text, str):\n"
    "        raise ValueError('required')\n"
    "    return text.strip()\n\n\n"
    "def never_run(x):\n"
    '    """Nothing exercises this."""\n'
    "    return x\n"
)


def _fixture_selection(_repo: Path) -> SandboxSelection:
    return SandboxSelection(SANDBOX, tier="fixture", kind="process-first-party")


@pytest.fixture
def built(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(_APP, encoding="utf-8")
    conn = open_index(root)
    try:
        build_index(
            conn,
            root,
            observe=True,
            only=frozenset({"round_up", "parse"}),
            max_inputs=24,
            select=_fixture_selection,
        )
        yield conn
    finally:
        conn.close()


class TestTheSpecDescribesTheBodyNotTheName:
    def test_a_function_that_lies_in_its_docstring_is_described_by_what_it_did(
        self, built: sqlite3.Connection
    ) -> None:
        """`round_up` says it rounds up and truncates. The spec must describe truncation — and
        it can only do that because it never read the docstring."""
        spec = specs.synthesize(built, "round_up")
        assert spec.claims
        text = " ".join(c.text for c in spec.claims)
        assert "round" not in text.lower(), "nothing here comes from the name or the docstring"
        assert "returns" in text
        assert spec.inputs_observed > 0

    def test_every_claim_carries_at_least_one_observation(self, built: sqlite3.Connection) -> None:
        spec = specs.synthesize(built, "parse")
        assert spec.claims
        for claim in spec.claims:
            assert claim.observations

    def test_every_citation_resolves_to_a_stored_row(self, built: sqlite3.Connection) -> None:
        """F4's gate, executed rather than asserted. A citation naming an observation the store
        does not have is worse than no citation: it reads as evidence and is not."""
        spec = specs.synthesize(built, "parse")
        ok, detail = specs.every_claim_is_backed(built, spec)
        assert ok, detail

    def test_a_raised_exception_is_reported_with_the_input_that_caused_it(
        self, built: sqlite3.Connection
    ) -> None:
        spec = specs.synthesize(built, "parse")
        raising = [c for c in spec.claims if "raises" in c.text]
        assert raising and "ValueError" in raising[0].text
        assert "args=" in raising[0].text


class TestWhatIsNotWritten:
    def test_a_symbol_nothing_ran_gets_no_claims_and_says_why(
        self, built: sqlite3.Connection
    ) -> None:
        """The refusal that makes it trustworthy: the source is right there and obvious, and the
        spec still will not describe behaviour it has not seen."""
        spec = specs.synthesize(built, "never_run")
        assert not spec.claims
        assert "nothing has executed it" in spec.unobserved
        assert "No behaviour recorded" in spec.render()

    def test_a_symbol_that_is_not_indexed_at_all_says_that_instead(
        self, built: sqlite3.Connection
    ) -> None:
        spec = specs.synthesize(built, "not_a_symbol")
        assert not spec.claims and "not in the index" in spec.unobserved

    def test_a_claim_cannot_be_constructed_without_evidence(self) -> None:
        """The invariant, enforced by the type rather than by review. F4's whole gate is "every
        generated claim resolves to at least one stored observation"; a Claim with an empty
        citation list would be a sentence about behaviour with nothing behind it."""
        with pytest.raises(ValueError, match="no observation behind it"):
            specs.Claim(text="returns an int", observations=())


class TestRendering:
    def test_the_rendered_spec_carries_the_span_and_the_input_count(
        self, built: sqlite3.Connection
    ) -> None:
        rendered = specs.synthesize(built, "parse").render()
        assert "app.py:" in rendered
        assert "observed input(s)" in rendered
        assert "_evidence: observation" in rendered

    def test_it_says_the_claims_describe_execution_not_source(
        self, built: sqlite3.Connection
    ) -> None:
        rendered = specs.synthesize(built, "parse").render()
        assert "not of what the source says" in rendered


class TestTheOtherKindsOfClaim:
    """A behaviour is more than a return value: what it PRINTED and what it TOUCHED are part of
    what the function does, and a spec that omitted them would describe a smaller function than
    the one that ran."""

    def _one_class(self, conn: sqlite3.Connection, **kw: object) -> None:
        """Insert a single behaviour class by hand. The shapes below — a crash, an effect
        ledger, output on stdout — are real observations that the fixture's own functions do not
        produce, and constructing them directly is more honest than contriving a fixture that
        crashes on purpose to reach a formatting branch."""
        conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('h.py','d',2,0)")
        file_id = conn.execute("SELECT id FROM files WHERE path = 'h.py'").fetchone()[0]
        conn.execute(
            "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
            "signature, doc) VALUES (?, 'h', 'handmade', 'function', 1, 2, '(x)', '')",
            (file_id,),
        )
        symbol_id = conn.execute("SELECT id FROM symbols WHERE qualname = 'handmade'").fetchone()[0]
        run_id = conn.execute(
            "INSERT INTO runs (revision, started, source) VALUES ('r', 0, 'test')"
        ).lastrowid
        conn.execute(
            "INSERT INTO behaviours (run_id, symbol_id, outcome, return_kind, raised_type, "
            "effects, inputs) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (
                run_id,
                symbol_id,
                kw.get("outcome", "COMPLETED"),
                kw.get("return_kind", "int"),
                kw.get("raised_type", ""),
                kw.get("effects", ""),
            ),
        )
        behaviour_id = conn.execute("SELECT MAX(id) FROM behaviours").fetchone()[0]
        if kw.get("with_example", True):
            conn.execute(
                "INSERT INTO observations (behaviour_id, args_literal, kwargs_literal, "
                "return_repr, raised_message, stdout, wall_ns) VALUES (?, '(1,)', '{}', '1', '', "
                "?, 1)",
                (behaviour_id, kw.get("stdout", "")),
            )

    def test_a_crash_is_described_as_what_it_was(self, built: sqlite3.Connection) -> None:
        self._one_class(built, outcome="CRASHED", return_kind="")
        claims = specs.synthesize(built, "handmade").claims
        assert any("ended as CRASHED" in c.text for c in claims)

    def test_the_surfaces_a_function_touched_are_a_claim(self, built: sqlite3.Connection) -> None:
        self._one_class(built, effects="fs:open,net:connect")
        claims = specs.synthesize(built, "handmade").claims
        assert any("touched these surfaces" in c.text and "fs:open" in c.text for c in claims)

    def test_what_it_printed_is_a_claim(self, built: sqlite3.Connection) -> None:
        self._one_class(built, stdout="hello from the function\n")
        claims = specs.synthesize(built, "handmade").claims
        assert any("wrote to standard output" in c.text for c in claims)

    def test_a_class_with_no_example_supports_no_claim_at_all(
        self, built: sqlite3.Connection
    ) -> None:
        """And the spec says why, rather than reading as "this function does nothing"."""
        self._one_class(built, with_example=False)
        spec = specs.synthesize(built, "handmade")
        assert not spec.claims
        assert "kept no example inputs" in spec.unobserved

    def test_a_dangling_citation_fails_the_gate(self, built: sqlite3.Connection) -> None:
        """The check F4's gate names is a LOOKUP, not a non-empty test. A citation naming an
        observation the store does not have is worse than no citation: it reads as evidence."""
        spec = specs.synthesize(built, "parse")
        assert spec.claims
        built.execute("DELETE FROM observations")
        ok, detail = specs.every_claim_is_backed(built, spec)
        assert not ok and "not stored" in detail
