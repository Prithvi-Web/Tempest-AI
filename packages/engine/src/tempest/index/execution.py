"""The execution index — what the code ACTUALLY did, recorded so questions can cite it.

This is F13's sleeper and F4's whole substrate: *"what happens when `user_id` is null?"* answered
from an observation rather than inferred from source, and *"which functions have never been
exercised?"* answered at all.

**Where the observations come from.** The proof pipeline computes observations and throws them
away — a bundle keeps counts and the divergences, which is right for a bundle and useless as an
index. So this module runs the generator with **no head revision** (exactly what F4 specifies):
introspect the symbol, generate inputs, execute them in the sandbox, and record what came back.
It does not touch `prove.py`. That is deliberate: the proof pipeline is the product's hot path and
the thing 30 corpus fixtures pin, and an index is not a good enough reason to reach into it.

**Behaviour CLASSES, not invocations.** Storing every input of every symbol of every run is
unbounded and mostly repetition: two hundred integers that all return an integer are one fact,
observed two hundred times. So observations are clustered by (outcome, returned type, raised type,
effect signature) and the store keeps the class, its count, and a bounded number of
REPRESENTATIVES — the smallest input in the class and the largest, because the interesting ones
live at the edges. Every claim F4 makes cites a representative, so every claim is backed by an
input somebody can re-run.

**Nothing here is a verdict.** An observation is what happened once, on one revision. It is
evidence, and the vocabulary keeps it that way: this module never writes the word EQUIVALENT.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from tempest.execute.runner import introspect_target, run_batch
from tempest.execute.sandbox import Sandbox
from tempest.generate.inputs import Budget, generate_inputs
from tempest.generate.mining import mine_literals
from tempest.model import Observation

#: Representatives kept per behaviour class. Two — the shortest input literal and the longest —
#: because a claim needs an example and the edges are where the interesting ones are. More would
#: be repetition; one would make every claim about the same corner.
REPRESENTATIVES = 2


@dataclass(frozen=True)
class SymbolTarget:
    symbol_id: int
    module: str
    qualname: str


@dataclass(frozen=True)
class ExecutionStats:
    symbols_attempted: int
    symbols_observed: int
    inputs_run: int
    behaviours: int
    unreachable: tuple[tuple[str, str], ...] = ()


def behaviour_key(obs: Observation) -> tuple[str, str, str, str]:
    """The class an observation belongs to.

    Type of the returned value, not the value: `total([1,2])` and `total([3,4])` are the same
    behaviour observed twice. The exception TYPE, not its message, for the same reason. And the
    effect signature — the ordered surfaces touched — because a function that opened a file this
    time and did not last time is doing two different things, whatever it returned.
    """
    return (
        str(obs.outcome.value),
        "" if not obs.return_present else type(obs.return_canon).__name__,
        obs.raised.type_name if obs.raised is not None else "",
        ",".join(f"{e.surface}:{e.call}" for e in obs.effects),
    )


def _return_repr(obs: Observation) -> str:
    if not obs.return_present:
        return ""
    text = repr(obs.return_canon)
    return text if len(text) <= 400 else text[:397] + "..."


def record_run(conn: sqlite3.Connection, revision: str, source: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (revision, started, source) VALUES (?, ?, ?)",
        (revision, time.time(), source),
    )
    return int(cursor.lastrowid or 0)


def store_observations(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    symbol_id: int,
    inputs: list[tuple[str, str]],
    observations: list[Observation],
) -> int:
    """Cluster and persist. Returns the number of behaviour classes written."""
    classes: dict[tuple[str, str, str, str], list[int]] = {}
    for i, obs in enumerate(observations):
        classes.setdefault(behaviour_key(obs), []).append(i)

    for key, indices in sorted(classes.items()):
        outcome, return_kind, raised_type, effects = key
        cursor = conn.execute(
            "INSERT INTO behaviours "
            "(run_id, symbol_id, outcome, return_kind, raised_type, effects, inputs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, symbol_id, outcome, return_kind, raised_type, effects, len(indices)),
        )
        behaviour_id = int(cursor.lastrowid or 0)
        ordered = sorted(indices, key=lambda i: (len(inputs[i][0]) + len(inputs[i][1]), i))
        chosen = ordered[:1] + ordered[-1:] if len(ordered) > 1 else ordered
        for i in chosen[:REPRESENTATIVES]:
            obs = observations[i]
            conn.execute(
                "INSERT INTO observations "
                "(behaviour_id, args_literal, kwargs_literal, return_repr, raised_message, "
                " stdout, wall_ns) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    behaviour_id,
                    inputs[i][0],
                    inputs[i][1],
                    _return_repr(obs),
                    obs.raised.message if obs.raised is not None else "",
                    obs.stdout[:400],
                    obs.timing.wall_ns,
                ),
            )
    return len(classes)


def observe(
    conn: sqlite3.Connection,
    repo: Path,
    targets: list[SymbolTarget],
    sandbox: Sandbox,
    *,
    revision: str,
    max_inputs: int = 24,
    seed: int = 0,
    per_input_timeout: float = 5.0,
) -> ExecutionStats:
    """Run every target on generated inputs and record what happened.

    A symbol that cannot be introspected — it is not importable, it is a class, its module raises
    at import — is recorded as UNREACHABLE with the reason, never skipped in silence. "Nothing was
    observed" and "nothing could be observed" are different answers, and the second one is the
    honest half of *"which functions have never been exercised?"*.
    """
    run_id = record_run(conn, revision, source="index")
    mined = mine_literals(repo)
    attempted = 0
    observed = 0
    inputs_run = 0
    behaviours = 0
    unreachable: list[tuple[str, str]] = []

    for target in targets:
        attempted += 1
        introspection = introspect_target(repo, target.module, target.qualname, sandbox)
        if introspection is None:
            unreachable.append((target.qualname, "the symbol could not be introspected"))
            continue
        candidates = generate_inputs(
            introspection, mined=list(mined), budget=Budget(max_inputs=max_inputs, seed=seed)
        )
        if not candidates:
            unreachable.append((target.qualname, "no inputs could be generated for it"))
            continue
        literals = [(c.args_literal, c.kwargs_literal) for c in candidates]
        results = run_batch(
            repo,
            target.module,
            target.qualname,
            literals,
            sandbox,
            per_input_timeout=per_input_timeout,
        )
        # A CRASH and a HANG are observations, not failures — the engine says so explicitly — so
        # they are kept and become behaviour classes of their own. What is dropped is an input
        # whose RESULT could not be canonicalised at all: there is nothing to record about a
        # value the comparison layer cannot represent, and a claim built on one would cite an
        # example nobody can read.
        usable = [
            (literal, obs)
            for literal, obs in zip(literals, results, strict=False)
            if obs.unrepresentable is None
        ]
        if not usable:
            unreachable.append(
                (target.qualname, "every generated input produced an unrepresentable result")
            )
            continue
        observed += 1
        inputs_run += len(usable)
        behaviours += store_observations(
            conn,
            run_id=run_id,
            symbol_id=target.symbol_id,
            inputs=[literal for literal, _ in usable],
            observations=[obs for _, obs in usable],
        )

    return ExecutionStats(
        symbols_attempted=attempted,
        symbols_observed=observed,
        inputs_run=inputs_run,
        behaviours=behaviours,
        unreachable=tuple(unreachable),
    )


def latest_run(conn: sqlite3.Connection) -> int | None:
    """The most recent execution run, or None when nothing has ever been observed.

    It is the evidence behind an ABSENCE claim. "This function has never been exercised" is a
    statement about a run that exercised everything else, and citing that run is what stops the
    claim being an unfalsifiable "I did not find any".
    """
    row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return int(row[0]) if row else None


def never_exercised(conn: sqlite3.Connection) -> list[int]:
    """Symbol ids with no recorded behaviour. F13's second example question, answered exactly."""
    rows = conn.execute(
        "SELECT s.id FROM symbols s LEFT JOIN behaviours b ON b.symbol_id = s.id "
        "WHERE b.id IS NULL ORDER BY s.id"
    ).fetchall()
    return [int(r[0]) for r in rows]


def behaviours_of(conn: sqlite3.Connection, symbol_id: int) -> list[dict[str, object]]:
    """Every recorded behaviour class for one symbol, newest run first, with representatives."""
    rows = conn.execute(
        "SELECT id, outcome, return_kind, raised_type, effects, inputs FROM behaviours "
        "WHERE symbol_id = ? ORDER BY id DESC",
        (symbol_id,),
    ).fetchall()
    out: list[dict[str, object]] = []
    for row in rows:
        examples = conn.execute(
            "SELECT id, args_literal, kwargs_literal, return_repr, raised_message, stdout "
            "FROM observations WHERE behaviour_id = ? ORDER BY id",
            (int(row[0]),),
        ).fetchall()
        out.append(
            {
                "behaviour_id": int(row[0]),
                "outcome": str(row[1]),
                "return_kind": str(row[2]),
                "raised_type": str(row[3]),
                "effects": str(row[4]),
                "inputs": int(row[5]),
                "examples": [
                    {
                        "observation_id": int(e[0]),
                        "args": str(e[1]),
                        "kwargs": str(e[2]),
                        "returned": str(e[3]),
                        "raised": str(e[4]),
                        "stdout": str(e[5]),
                    }
                    for e in examples
                ],
            }
        )
    return out


def as_json(value: object) -> str:
    return json.dumps(value, sort_keys=True)
