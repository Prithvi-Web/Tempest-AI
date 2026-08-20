"""F4 — behavioural spec synthesis: what a function DOES, from execution, with the evidence.

**The claim this feature makes, and the reason it is different.** Every other tool summarises code
by reading it, which reproduces the intent the author wrote down — including the bugs, which are
by definition the places where intent and behaviour disagree. This reads the OBSERVATIONS. If a
function named `round_up` rounds down, the spec says it rounds down and points at the input that
proves it.

**Every sentence is generated FROM a stored observation, never about one.** There is no model in
this path. A claim is a template filled from a behaviour class, and it carries the observation ids
of the representatives that support it. The gate is exactly that: every generated claim resolves
to at least one stored observation. A model may later rewrite these sentences into nicer prose —
and when it does, the claims it is allowed to say are these, and the citations travel with them.

**What is NOT written.** Anything the observations do not support. No "handles empty input
gracefully" unless an empty input was run. No "returns an integer" unless one was returned. The
absence of a claim is information too, and the spec says how many inputs it is speaking for so a
reader can weigh it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from tempest.index import execution
from tempest.index.store import SymbolRow, symbol_rows


@dataclass(frozen=True)
class Claim:
    text: str
    #: Observation ids. NEVER empty — a claim with no evidence is not constructed.
    observations: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError(
                "a behavioural claim with no observation behind it is a summary of the source, "
                "which is the thing F4 exists not to be"
            )


@dataclass(frozen=True)
class BehaviouralSpec:
    qualname: str
    span: str
    signature: str
    inputs_observed: int
    claims: tuple[Claim, ...]
    #: Set when there is nothing to synthesise. A spec with no claims and no reason would read as
    #: "this function does nothing", which is a different and much stronger statement.
    unobserved: str = ""

    def render(self) -> str:
        header = f"## {self.qualname}{self.signature}\n\n`{self.span}`\n"
        if self.unobserved:
            return f"{header}\n_No behaviour recorded: {self.unobserved}._\n"
        body = "\n".join(
            f"- {claim.text}  \n  _evidence: observation "
            f"{', '.join(str(o) for o in claim.observations)}_"
            for claim in self.claims
        )
        return (
            f"{header}\nDerived from {self.inputs_observed} observed input(s). Every claim below "
            f"is a description of what ran, not of what the source says.\n\n{body}\n"
        )


def _find(conn: sqlite3.Connection, qualname: str) -> SymbolRow | None:
    rows = symbol_rows(conn, "s.qualname = ?", (qualname,))
    return rows[0] if rows else None


def synthesize(conn: sqlite3.Connection, qualname: str) -> BehaviouralSpec:
    """The spec for one symbol, built entirely from its recorded behaviour classes."""
    row = _find(conn, qualname)
    if row is None:
        return BehaviouralSpec(
            qualname=qualname,
            span="",
            signature="",
            inputs_observed=0,
            claims=(),
            unobserved="the symbol is not in the index",
        )
    behaviours = execution.behaviours_of(conn, row.id)
    if not behaviours:
        return BehaviouralSpec(
            qualname=row.qualname,
            span=row.span,
            signature=row.signature,
            inputs_observed=0,
            claims=(),
            unobserved="nothing has executed it in this index",
        )

    claims: list[Claim] = []
    total = 0
    for behaviour in behaviours:
        examples = behaviour["examples"]
        if not isinstance(examples, list) or not examples:
            # A behaviour class whose representatives were lost cannot support a claim, and a
            # claim it cannot support is not written. Counting its inputs would inflate the
            # denominator behind claims that do not cover them.
            continue
        ids = tuple(int(cast("int", e["observation_id"])) for e in examples)
        count = int(cast("int", behaviour["inputs"]))
        total += count
        first = examples[0]
        plural = "input" if count == 1 else "inputs"
        if behaviour["raised_type"]:
            claims.append(
                Claim(
                    text=(
                        f"raises `{behaviour['raised_type']}` on {count} observed {plural} — "
                        f"for example `args={first['args']}, kwargs={first['kwargs']}`"
                        + (f", with the message {first['raised']!r}" if first["raised"] else "")
                    ),
                    observations=ids,
                )
            )
        elif behaviour["outcome"] != "COMPLETED":
            claims.append(
                Claim(
                    text=(
                        f"ended as {behaviour['outcome']} on {count} observed {plural} — "
                        f"for example `args={first['args']}, kwargs={first['kwargs']}`"
                    ),
                    observations=ids,
                )
            )
        else:
            returned = first["returned"] or "None"
            kind = behaviour["return_kind"] or "NoneType"
            claims.append(
                Claim(
                    text=(
                        f"returns a `{kind}` on {count} observed {plural} — "
                        f"`args={first['args']}` returned `{returned}`"
                    ),
                    observations=ids,
                )
            )
        if behaviour["effects"]:
            claims.append(
                Claim(
                    text=f"touched these surfaces while running: {behaviour['effects']}",
                    observations=ids,
                )
            )
        if first["stdout"]:
            claims.append(
                Claim(
                    text=f"wrote to standard output: {first['stdout']!r}",
                    observations=(int(first["observation_id"]),),
                )
            )

    if not claims:
        return BehaviouralSpec(
            qualname=row.qualname,
            span=row.span,
            signature=row.signature,
            inputs_observed=0,
            claims=(),
            unobserved="its recorded behaviour classes kept no example inputs",
        )
    return BehaviouralSpec(
        qualname=row.qualname,
        span=row.span,
        signature=row.signature,
        inputs_observed=total,
        claims=tuple(claims),
    )


def every_claim_is_backed(conn: sqlite3.Connection, spec: BehaviouralSpec) -> tuple[bool, str]:
    """F4's gate, executed rather than asserted: does every claim's citation resolve to a row?

    A citation that names an observation the store does not have is worse than no citation — it
    reads as evidence and is not. So the check is a lookup, not a non-empty test.
    """
    for claim in spec.claims:
        for observation_id in claim.observations:
            found = conn.execute(
                "SELECT 1 FROM observations WHERE id = ?", (observation_id,)
            ).fetchone()
            if found is None:
                return (
                    False,
                    f"claim {claim.text!r} cites observation {observation_id}, which is not stored",
                )
    return True, f"{len(spec.claims)} claim(s), every citation resolves"
