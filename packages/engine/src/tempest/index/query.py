"""The query planner — one question, three indices, and a citation on every claim (F13).

**Every statement carries evidence or is not made.** An answer here is a list of statements, and
each statement carries the source spans and observation ids it came from. A statement with no
citation is not written: the benchmark fails any uncited answer, and the reason that bar exists is
that an uncited answer from a codebase assistant is indistinguishable from a guess.

**Routing is mechanical.** The planner decides which index answers a question by matching the
question's shape, not by asking a model. That is L17 in its retrieval form: a model may summarise
what was retrieved, it may not decide what the evidence is. It also means the planner works
offline, deterministically, and identically on every machine — which is what makes the benchmark
a measurement rather than a sample.

**"I don't know" is an answer.** A question the planner cannot route returns no statements and
says why. That is a miss the benchmark counts, and it is strictly better than the alternative,
which is prose with nothing behind it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from tempest.index import execution, lexical
from tempest.index.store import SymbolRow, symbol_rows


@dataclass(frozen=True)
class Citation:
    """Where a statement came from. Either a place in the source or a recorded observation."""

    kind: str  # "source" | "observation"
    reference: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.reference}"


@dataclass(frozen=True)
class Statement:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Answer:
    question: str
    route: str
    statements: tuple[Statement, ...] = ()
    #: Why there is nothing to say, when there is nothing to say. Empty on a real answer.
    unanswered: str = ""

    @property
    def cited(self) -> bool:
        """True when every statement carries at least one citation. An answer with no statements
        is NOT cited — "nothing to show" must never pass a citation gate by being empty."""
        return bool(self.statements) and all(s.citations for s in self.statements)

    @property
    def observation_citations(self) -> tuple[str, ...]:
        return tuple(
            c.reference for s in self.statements for c in s.citations if c.kind == "observation"
        )

    @property
    def grounded_in_execution(self) -> bool:
        """True when at least one statement is backed by something that RAN.

        Two citation kinds qualify. An `observation` is one recorded invocation. A `run` is the
        execution pass itself, and it is the only evidence an ABSENCE claim can ever have —
        "nothing ever exercised this" is a statement about a run that exercised everything else,
        and there is no observation of a thing that did not happen. Source citations do not
        qualify, which is the whole point: these are the questions source text cannot answer.
        """
        return any(c.kind in {"observation", "run"} for s in self.statements for c in s.citations)


_NEVER_RUN = re.compile(r"never (been )?(exercised|run|executed|called)|which .*never", re.I)
_CALLERS = re.compile(r"who calls|what calls|callers of|which functions call", re.I)
_CALLEES = re.compile(r"what does .* call|callees of|which functions does .* call", re.I)
_RAISES = re.compile(r"raise|throw|exception|error", re.I)
_WHAT_HAPPENS = re.compile(r"what (actually )?happens|what does .* (do|return)|behaviou?r of", re.I)
_RANGE = re.compile(r"range of values|what values|which values|what types", re.I)
_WHERE = re.compile(r"where is|where are|find|defined|definition of", re.I)

#: Words the routing patterns use that are not part of the SUBJECT being asked about. Stripping
#: them stops "who calls charge" retrieving every function whose docstring says "calls".
# fmt: off
_ROUTING_WORDS = frozenset({
    # interrogatives
    "who", "what", "which", "where", "when", "how", "does", "do", "actually",
    # the shapes the router matches on
    "happens", "happen", "call", "calls", "called", "caller", "callers", "callee", "callees",
    "never", "been", "exercised", "run", "executed", "function", "functions",
    "defined", "definition", "definitions", "value", "values", "type", "types", "range",
    "raise", "raises", "raised", "throw", "throws", "exception", "exceptions", "error", "errors",
    "behaviour", "behavior",
    # glue, and the words a question uses to describe an INPUT rather than a symbol
    "of", "the", "a", "an", "is", "are", "and", "or", "to", "for", "in", "on", "with",
    "null", "none", "empty", "zero", "negative",
})
# fmt: on


def _subject(question: str) -> str:
    """The part of the question that names code, with the interrogative scaffolding removed."""
    kept = [w for w in lexical.words(question) if w not in _ROUTING_WORDS]
    return " ".join(kept)


def _by_id(conn: sqlite3.Connection, symbol_ids: list[int]) -> dict[int, SymbolRow]:
    if not symbol_ids:
        return {}
    placeholders = ",".join("?" for _ in symbol_ids)
    rows = symbol_rows(conn, f"s.id IN ({placeholders})", tuple(symbol_ids))
    return {row.id: row for row in rows}


def _top_symbols(conn: sqlite3.Connection, question: str, *, limit: int) -> list[SymbolRow]:
    subject = _subject(question) or question
    scored = lexical.search(conn, subject, limit=limit)
    found = _by_id(conn, [s.symbol_id for s in scored])
    return [found[s.symbol_id] for s in scored if s.symbol_id in found]


def _source(row: SymbolRow) -> Citation:
    return Citation(kind="source", reference=row.span)


def answer(conn: sqlite3.Connection, question: str, *, limit: int = 5) -> Answer:
    """Route, retrieve, and state what the evidence says. Never more than the evidence says."""
    if _NEVER_RUN.search(question):
        return _answer_never_exercised(conn, question, limit=limit)
    if _CALLEES.search(question):
        return _answer_callees(conn, question, limit=limit)
    if _CALLERS.search(question):
        return _answer_callers(conn, question, limit=limit)
    if _RAISES.search(question):
        return _answer_raises(conn, question, limit=limit)
    if _RANGE.search(question) or _WHAT_HAPPENS.search(question):
        return _answer_behaviour(conn, question, limit=limit)
    if _WHERE.search(question):
        return _answer_where(conn, question, limit=limit)
    return _answer_behaviour(conn, question, limit=limit, fall_back_to_source=True)


def _answer_never_exercised(conn: sqlite3.Connection, question: str, *, limit: int) -> Answer:
    """The question source text cannot answer at all: absence of execution."""
    run_id = execution.latest_run(conn)
    if run_id is None:
        return Answer(
            question=question,
            route="execution",
            unanswered="nothing has been executed into this index, so absence proves nothing",
        )
    ids = execution.never_exercised(conn)
    rows = _by_id(conn, ids)
    if not rows:
        return Answer(
            question=question,
            route="execution",
            unanswered="every indexed symbol has at least one recorded behaviour",
        )
    # The citation is the RUN, not an observation: the evidence for an absence is the execution
    # that covered everything else. An answer citing nothing would be an unfalsifiable "I did not
    # find any", which is exactly the shape of answer this feature exists to replace.
    statements = [
        Statement(
            text=f"{row.qualname} has no recorded execution in this index",
            citations=(_source(row), Citation(kind="run", reference=str(run_id))),
        )
        for row in sorted(rows.values(), key=lambda r: (r.path, r.line_start))[:limit]
    ]
    return Answer(question=question, route="execution", statements=tuple(statements))


def _answer_callers(conn: sqlite3.Connection, question: str, *, limit: int) -> Answer:
    targets = _top_symbols(conn, question, limit=1)
    if not targets:
        return Answer(question=question, route="structural", unanswered=_nothing_matched(question))
    target = targets[0]
    rows = conn.execute(
        "SELECT DISTINCT caller_id, line FROM calls WHERE callee = ? OR callee_id = ? "
        "ORDER BY caller_id",
        (target.qualname.split(".")[-1], target.id),
    ).fetchall()
    callers = _by_id(conn, [int(r[0]) for r in rows])
    if not callers:
        return Answer(
            question=question,
            route="structural",
            unanswered=f"no indexed symbol calls {target.qualname}",
        )
    statements = [
        Statement(
            text=f"{row.qualname} calls {target.qualname}",
            citations=(_source(row), _source(target)),
        )
        for row in sorted(callers.values(), key=lambda r: (r.path, r.line_start))[:limit]
    ]
    return Answer(question=question, route="structural", statements=tuple(statements))


def _answer_callees(conn: sqlite3.Connection, question: str, *, limit: int) -> Answer:
    targets = _top_symbols(conn, question, limit=1)
    if not targets:
        return Answer(question=question, route="structural", unanswered=_nothing_matched(question))
    target = targets[0]
    rows = conn.execute(
        "SELECT callee, MIN(line), COUNT(*) FROM calls WHERE caller_id = ? GROUP BY callee "
        "ORDER BY MIN(line)",
        (target.id,),
    ).fetchall()
    if not rows:
        return Answer(
            question=question,
            route="structural",
            unanswered=f"{target.qualname} calls nothing the index can see",
        )
    statements = [
        Statement(
            text=f"{target.qualname} calls {row[0]} (line {int(row[1])})",
            citations=(_source(target),),
        )
        for row in rows[:limit]
    ]
    return Answer(question=question, route="structural", statements=tuple(statements))


def _answer_where(conn: sqlite3.Connection, question: str, *, limit: int) -> Answer:
    rows = _top_symbols(conn, question, limit=limit)
    if not rows:
        return Answer(question=question, route="lexical", unanswered=_nothing_matched(question))
    statements = [
        Statement(
            text=f"{row.qualname} is a {row.kind} defined in {row.path}",
            citations=(_source(row),),
        )
        for row in rows
    ]
    return Answer(question=question, route="lexical", statements=tuple(statements))


def _answer_raises(conn: sqlite3.Connection, question: str, *, limit: int) -> Answer:
    """Which exceptions were actually OBSERVED — not which ones the source mentions.

    This is the difference the execution index exists for: a `raise ValueError` the code can never
    reach does not appear here, and an exception raised from three frames down by a library does.
    """
    targets = _top_symbols(conn, question, limit=3)
    statements: list[Statement] = []
    for target in targets:
        for behaviour in execution.behaviours_of(conn, target.id):
            if not behaviour["raised_type"]:
                continue
            examples = behaviour["examples"]
            if not isinstance(examples, list) or not examples:
                continue
            first = examples[0]
            statements.append(
                Statement(
                    text=(
                        f"{target.qualname} raised {behaviour['raised_type']} on "
                        f"{behaviour['inputs']} observed input(s), for example "
                        f"args={first['args']} kwargs={first['kwargs']}"
                    ),
                    citations=(
                        _source(target),
                        Citation(kind="observation", reference=str(first["observation_id"])),
                    ),
                )
            )
    if not statements:
        return Answer(
            question=question,
            route="execution",
            unanswered="no recorded execution of a matching symbol raised anything",
        )
    return Answer(question=question, route="execution", statements=tuple(statements[:limit]))


def _answer_behaviour(
    conn: sqlite3.Connection, question: str, *, limit: int, fall_back_to_source: bool = False
) -> Answer:
    targets = _top_symbols(conn, question, limit=2)
    if not targets:
        return Answer(question=question, route="execution", unanswered=_nothing_matched(question))
    statements: list[Statement] = []
    for target in targets:
        for behaviour in execution.behaviours_of(conn, target.id):
            examples = behaviour["examples"]
            if not isinstance(examples, list) or not examples:
                continue
            first = examples[0]
            if behaviour["raised_type"]:
                text = (
                    f"{target.qualname} raised {behaviour['raised_type']} on "
                    f"{behaviour['inputs']} observed input(s)"
                )
            else:
                text = (
                    f"{target.qualname} returned a {behaviour['return_kind'] or 'None'} on "
                    f"{behaviour['inputs']} observed input(s); "
                    f"args={first['args']} gave {first['returned'] or 'None'}"
                )
            statements.append(
                Statement(
                    text=text,
                    citations=(
                        _source(target),
                        Citation(kind="observation", reference=str(first["observation_id"])),
                    ),
                )
            )
    if statements:
        return Answer(question=question, route="execution", statements=tuple(statements[:limit]))
    if fall_back_to_source:
        return _answer_where(conn, question, limit=limit)
    return Answer(
        question=question,
        route="execution",
        unanswered=(
            f"{targets[0].qualname} matched the question but has no recorded execution — "
            f"the honest answer is that nothing was observed, not a guess from its source"
        ),
    )


def _nothing_matched(question: str) -> str:
    return f"no indexed symbol matched {_subject(question)!r}"
