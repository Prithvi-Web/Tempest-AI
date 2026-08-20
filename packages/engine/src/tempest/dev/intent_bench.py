"""Phase 21's exit gate, part 2 of 4 — F2's classification accuracy.

    python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0

**Two thresholds, and only one of them is a quality bar.** Accuracy may be 90%; false INTENDEDs
must be **zero**. They are different kinds of requirement because they have different
consequences: a divergence wrongly called UNCLASSIFIED is shown to the user, who then reads it —
annoying, and safe. A divergence wrongly called INTENDED is *hidden behind a reassurance*, which
is the one outcome that turns evidence into false comfort. F2 says so directly: "a false
'intended' is worse than no feature".

So a run with 100% accuracy and one false INTENDED fails, and a run at 92% with none passes.

**And a third bar, which is the one that actually binds on a keyless run.** The model here is a
script, so the corpus is deterministic: every row has exactly one correct answer and the product
either gets it or has regressed. The accuracy floor is a bar for a REAL model, where 90% is a
quality judgement; against the scripted corpus it is nearly unfallible, because 54 rows and a 90%
bar tolerate five wrong answers. So a keyless run additionally fails on ANY mismatch, and says
which. Growing the corpus made this necessary and a review made it visible: adding tasks had
quietly diluted the denominator until a real classification regression could not turn the gate
red (trap 47).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from tempest.agent import contracts as contracts_mod
from tempest.dev._agent_corpus import TASKS, TaskCase, run_case


@dataclass(frozen=True)
class Row:
    task: str
    symbol: str
    expected: str
    actual: str

    @property
    def correct(self) -> bool:
        return self.expected == self.actual

    @property
    def false_intended(self) -> bool:
        """Called INTENDED when it was not. The safety-critical error, counted separately."""
        return self.actual == contracts_mod.INTENDED and self.expected != contracts_mod.INTENDED


def evaluate(cases: tuple[TaskCase, ...]) -> list[Row]:
    rows: list[Row] = []
    for case in cases:
        if not case.expect_classification:
            continue
        run = run_case(case)
        seen = {d.qualname: d.classification for d in run.divergences}
        for symbol, expected in case.expect_classification.items():
            rows.append(
                Row(
                    task=case.name,
                    symbol=symbol,
                    expected=expected,
                    # A symbol the run never diverged on is reported as such rather than skipped:
                    # "it did not happen" is a different answer from "it was classified", and a
                    # gate that silently dropped it would measure a smaller, easier set.
                    actual=seen.get(symbol, "NO-DIVERGENCE"),
                )
            )
    return rows


def render(rows: list[Row], *, min_accuracy: float) -> str:
    correct = sum(1 for r in rows if r.correct)
    accuracy = correct / len(rows) if rows else 0.0
    false_intended = sum(1 for r in rows if r.false_intended)
    lines = [
        f"{'task':<38} {'symbol':<12} {'expected':<14} actual",
        *[f"{r.task:<38} {r.symbol:<12} {r.expected:<14} {r.actual}" for r in rows],
        "",
        f"intent_bench: {correct}/{len(rows)} correct ({accuracy:.0%}; required "
        f"{min_accuracy:.0%}) · false INTENDED: {false_intended} (required 0)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A FLOOR, not a slice: `--tasks 50` asserts the corpus holds at least fifty tasks and
    # then runs ALL of them. Slicing to exactly N would silently exclude every task added
    # after the Nth, so growing the corpus would quietly stop testing the new work while
    # the gate went on printing the number it was asked for (trap 44).
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    parser.add_argument("--min-accuracy", type=float, default=0.90)
    parser.add_argument("--max-false-intended", type=int, default=0)
    args = parser.parse_args(argv)

    if args.tasks > len(TASKS):
        print(
            f"intent_bench: {args.tasks} tasks requested, corpus holds {len(TASKS)} — refusing "
            f"to report a rate over a smaller set than was asked for",
            file=sys.stderr,
        )
        return 2

    rows = evaluate(TASKS)
    print(render(rows, min_accuracy=args.min_accuracy))
    correct = sum(1 for r in rows if r.correct)
    accuracy = correct / len(rows) if rows else 0.0
    false_intended = sum(1 for r in rows if r.false_intended)

    failed = False
    for row in rows:
        if row.false_intended:
            print(
                f"INTENT-BENCH {row.task}/{row.symbol}: called INTENDED, expected "
                f"{row.expected} — a false INTENDED hides a divergence behind a reassurance",
                file=sys.stderr,
            )
    if false_intended > args.max_false_intended:
        failed = True
    if accuracy < args.min_accuracy:
        failed = True
    # Every mismatch is named and every mismatch fails, independently of the floor above. The
    # corpus is deterministic; a wrong row is a regression, not a rounding error.
    for row in rows:
        if not row.correct and not row.false_intended:
            print(
                f"INTENT-BENCH {row.task}/{row.symbol}: {row.actual}, expected {row.expected} — "
                f"the scripted corpus has one correct answer per row, so this is a regression",
                file=sys.stderr,
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
