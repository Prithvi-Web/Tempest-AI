"""P2 — a durable turn log, so an interrupted task loses nothing (L15.5).

A turn is expensive: model calls cost money, and a differential proof costs minutes. If the app
is killed — a crash, a battery, a user quitting — none of that may have to happen twice, and
nothing already established may be forgotten. This module is the record that makes that true.

**SQLite, in the engine, with the standard library.** The API package has a SQLAlchemy store, but
it wraps the engine rather than the other way round, and importing it here would invert the
dependency. `sqlite3` is in the standard library, the file is per-repository, and every write is
committed before the function returns — a checkpoint that is still in a buffer when the process
dies is not a checkpoint.

**Stages are the unit, not turns.** What matters for resumption is not "how many turns happened"
but "what had definitely finished". `PROVING` and `PROVED` are separate stages precisely because
the gap between them is the expensive one: a process killed in that gap has done the model work
and not the proof, and resuming must redo exactly the second.

**A checkpoint records what HAPPENED, never what is expected to happen.** Every row is written
after the thing it describes, which is what makes the log safe to trust after a crash.

One row needs the distinction spelled out, because a review read it as a counter-example and was
right to look: `RESUMED` carries `redo_turns`, which is about the future. What has happened at
that point is the DECISION — the plan was computed from the log and this is what it said — and the
row is written after computing it, not after acting on it. That matters for reading the log back:
a `RESUMED` row means "a restart decided this", not "a restart did this", and a task that died
immediately afterwards will show the decision and none of its consequences. Which is correct, and
is why the flag is recorded rather than inferred later from what did or did not follow.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: One file per repository, beside the agent's other state.
TURNLOG_PATH = Path(".tempest") / "agent" / "turns.sqlite3"

STARTED = "started"
TURNS_DONE = "turns_done"
PROVING = "proving"
PROVED = "proved"
REPAIR_ATTEMPT = "repair_attempt"
RESUMED = "resumed"
FINISHED = "finished"
#: C5 HITL: the turn is PARKED on a human — written durably BEFORE the question is asked, so
#: a kill mid-park finds the question in the log. Resumption treats it like any other
#: mid-converse kill (redo the turns): the pending question is VOID on restart — the tool
#: never ran, nothing user-visible is lost, and re-deriving the ask is the model's job.
PENDING_APPROVAL = "pending_approval"

#: The closed set. A stage outside it is a bug in a caller, and is refused rather than stored —
#: an unrecognised stage in the log would make resumption guess.
STAGES = (STARTED, TURNS_DONE, PROVING, PROVED, REPAIR_ATTEMPT, RESUMED, FINISHED, PENDING_APPROVAL)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id   TEXT    NOT NULL,
    stage     TEXT    NOT NULL,
    payload   TEXT    NOT NULL,
    recorded  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS turn_log_task ON turn_log (task_id, id);
"""


class TurnLogError(Exception):
    """The log could not be written or read. Never used for an ordinary absence."""


@dataclass(frozen=True)
class Checkpoint:
    seq: int
    task_id: str
    stage: str
    payload: dict[str, Any]
    recorded: float


def _shield_state_dir(repo: Path) -> None:
    """Make `.tempest/` un-committable in the user's repository.

    The log holds the agent's whole conversation — prompts, model text, and the CONTENT of every
    file it read, because that is what a tool result is. All of that is ordinary local state, in
    the same category as the bundle store, and nothing sends it anywhere. But a user running
    `git add -A` in their own project would commit it, and a transcript in a repository's history
    is a different thing from a transcript in a working directory.

    So the directory ships its own `.gitignore`, written once and never overwritten: a user who
    deliberately edits it has said something, and this should not argue.
    """
    marker = repo / ".tempest" / ".gitignore"
    if marker.exists():
        return
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        "# Tempest's local state: bundles, shadow worktrees, agent turn logs, caches.\n"
        "# None of it belongs in a repository's history.\n"
        "*\n",
        encoding="utf-8",
    )


class TurnLog:
    """Append-only, durable, per-repository.

    Deliberately not a context manager and deliberately not holding a connection open: a long
    agent task spends most of its time in a proof or a model call, and a connection held across
    that is a lock held across it too. Each call opens, writes, commits, closes.
    """

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)
        self.path = self.repo / TURNLOG_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _shield_state_dir(self.repo)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        # WAL survives a kill -9 mid-write; a synchronous commit is what makes "durable" true
        # rather than "durable once the OS gets round to it".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def checkpoint(self, task_id: str, stage: str, **payload: Any) -> Checkpoint:
        """Record that `stage` has HAPPENED. Committed before this returns."""
        if stage not in STAGES:
            raise TurnLogError(f"unknown stage {stage!r}; the log's vocabulary is {STAGES}")
        recorded = time.time()
        body = json.dumps(payload, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO turn_log (task_id, stage, payload, recorded) VALUES (?, ?, ?, ?)",
                (task_id, stage, body, recorded),
            )
            seq = int(cursor.lastrowid or 0)
        return Checkpoint(seq=seq, task_id=task_id, stage=stage, payload=payload, recorded=recorded)

    def history(self, task_id: str) -> list[Checkpoint]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, stage, payload, recorded FROM turn_log WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [
            Checkpoint(
                seq=int(r[0]),
                task_id=task_id,
                stage=str(r[1]),
                payload=json.loads(r[2]),
                recorded=float(r[3]),
            )
            for r in rows
        ]

    def last(self, task_id: str) -> Checkpoint | None:
        """The most recent checkpoint, or None for a task nobody has started.

        None is an ordinary answer, not an error: "this task has no history" is exactly what a
        fresh run looks like.
        """
        entries = self.history(task_id)
        return entries[-1] if entries else None


@dataclass(frozen=True)
class ResumePlan:
    """What a restarted process should do about a task it finds in the log."""

    #: True when the task ran to completion and its answer is already recorded.
    finished: bool
    #: True when the process died between starting a proof and recording its result, so the proof
    #: must be run again. It is the only expensive step that is safe to redo blindly: a proof is
    #: a pure function of (baseline, head, budget, seed), so redoing it cannot change the answer.
    reprove: bool
    reason: str
    #: True when the model conversation has to happen again. This is the expensive-and-UNSAFE
    #: one: model turns cost money, they are not a pure function of anything, and the edits they
    #: produced are already on disk in the shadow worktree. It is False for every interruption
    #: after `TURNS_DONE` was recorded, which is the whole point of recording it.
    redo_turns: bool = True
    #: The baseline the task started from, as recorded at `STARTED`. A resumed task must prove
    #: against THIS commit; deriving a fresh one from the user's tree would re-point the proof at
    #: a different starting state.
    baseline: str = ""
    #: True when there is history at all. Distinguishes "resume decided to redo everything" from
    #: "there was nothing to resume", which look identical in the flags and are not the same fact.
    resuming: bool = False
    #: Repair attempts already recorded for this task, across every restart. The attempt budget
    #: is a bound on MONEY (L15.4), and a bound that resets when the process dies is not a bound:
    #: a task killed four times would spend four full budgets and the record would show one.
    repair_attempts_spent: int = 0
    #: True when the log was actually read. False only for a caller that asked for a fresh run
    #: without consulting it — which is a different state from "the log was read and was empty",
    #: and the difference decides whether an existing shadow is an orphan to adopt or a tree the
    #: caller is deliberately declining to reuse.
    consulted_the_log: bool = True


def plan_resume(log: TurnLog, task_id: str) -> ResumePlan:
    """Read the log and say what is left to do.

    The three cases that matter, and why each is what it is:

    * **No history** — nothing was started, so there is nothing to resume. Run normally.
    * **Last stage is PROVING** — the process died inside the expensive step. The model work
      before it is done and recorded; the proof is not. Re-prove, and only re-prove.
    * **Last stage is FINISHED** — the answer exists. Re-running would spend money and minutes to
      recompute a result already on disk, and (worse) would create a second shadow worktree for a
      task that already has one.
    """
    history = log.history(task_id)
    if not history:
        return ResumePlan(finished=False, reprove=False, reason="no history: this is a fresh task")
    last = history[-1]
    baseline = _recorded_baseline(history)
    if last.stage == FINISHED:
        return ResumePlan(
            finished=True,
            reprove=False,
            reason="the task already finished; its verdict is recorded",
            redo_turns=False,
            baseline=baseline,
            resuming=True,
        )
    # The model work is done exactly when TURNS_DONE was written. Everything after it — PROVING,
    # PROVED, REPAIR_ATTEMPT, RESUMED — implies it, so the question is asked of the WHOLE history
    # rather than of the last row: a task interrupted twice has a RESUMED row on top and its
    # turns are no less finished for that.
    turns_done = any(c.stage == TURNS_DONE for c in history)
    # Distinct attempt NUMBERS, not rows. One attempt writes two rows — one before the model is
    # asked, so an attempt that died mid-conversation still counts against the budget, and one
    # after, carrying the transcript. Counting rows charged every attempt twice and a task with a
    # budget of two was refused before its second attempt. And `phase="baseline"` is neither: it
    # records what the loop is judging AGAINST, so it is excluded outright.
    spent = len(
        {
            c.payload.get("number")
            for c in history
            if c.stage == REPAIR_ATTEMPT and c.payload.get("phase") != "baseline"
        }
    )
    if last.stage == PROVING:
        return ResumePlan(
            finished=False,
            reprove=True,
            reason=(
                "interrupted inside the proof — the model work is recorded, the verdict is not, "
                "and a proof is a pure function of its inputs so re-running it is safe"
            ),
            redo_turns=not turns_done,
            baseline=baseline,
            resuming=True,
            repair_attempts_spent=spent,
        )
    return ResumePlan(
        finished=False,
        reprove=False,
        reason=(
            f"interrupted after {last.stage}; the remaining stages have not run"
            + ("" if turns_done else " and the model turns never completed")
        ),
        redo_turns=not turns_done,
        baseline=baseline,
        resuming=True,
        repair_attempts_spent=spent,
    )


def _recorded_baseline(history: list[Checkpoint]) -> str:
    """The baseline from the FIRST `STARTED` row.

    The first, not the last: a task resumed twice has one baseline and several attempts at it,
    and reading the newest row would let the answer drift with each restart.
    """
    for entry in history:
        if entry.stage == STARTED and entry.payload.get("baseline"):
            return str(entry.payload["baseline"])
    return ""
