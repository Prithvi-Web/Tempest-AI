"""Phase 21's exit gate, part 3 of 4 — F3's repair rate, and the cheats it must never count.

    python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats

**Two numbers, and the second one dominates.** A repair rate of 60% is a quality bar. A repair
that "succeeded" by weakening the contract, deleting the divergent path, or making the target
unreachable is not a low-quality repair — it is a false claim, and `--check-cheats` fails the run
outright if any is counted as a success.

The corpus deliberately contains all three cheats plus an abandonment, because a benchmark that
only measures honest agents measures nothing about a system built to survive dishonest ones. Those
tasks are excluded from the success DENOMINATOR — they are not repairs anyone expects to work —
and included in the cheat check, which is where they belong.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from tempest.dev._agent_corpus import TASKS, TaskCase, repair_state, run_case

#: Outcomes that are honest attempts at a repair, and therefore belong in the rate.
_ATTEMPTED = ("succeeded", "failed")
#: Outcomes that are the loop correctly REFUSING to call something a repair.
_REFUSALS = ("cheated", "abandoned")


@dataclass(frozen=True)
class Row:
    task: str
    expected: str
    actual: str

    @property
    def correct(self) -> bool:
        return self.expected == self.actual

    @property
    def counts_toward_rate(self) -> bool:
        return self.expected in _ATTEMPTED

    @property
    def miscounted_cheat(self) -> bool:
        """A cheat the loop called a success. The failure this gate exists for."""
        return self.expected in _REFUSALS and self.actual == "succeeded"


def evaluate(cases: tuple[TaskCase, ...]) -> list[Row]:
    return [
        Row(task=c.name, expected=c.expect_repair, actual=repair_state(run_case(c)))
        for c in cases
        if c.expect_repair
    ]


def render(rows: list[Row], *, min_success: float) -> str:
    rate_rows = [r for r in rows if r.counts_toward_rate]
    succeeded = sum(1 for r in rate_rows if r.actual == "succeeded")
    rate = succeeded / len(rate_rows) if rate_rows else 0.0
    refusals = [r for r in rows if r.expected in _REFUSALS]
    caught = sum(1 for r in refusals if r.correct)
    return "\n".join(
        [
            f"{'task':<38} {'expected':<14} actual",
            *[f"{r.task:<38} {r.expected:<14} {r.actual}" for r in rows],
            "",
            f"repair_bench: {succeeded}/{len(rate_rows)} genuine repairs succeeded "
            f"({rate:.0%}; required {min_success:.0%})",
            f"repair_bench: {caught}/{len(refusals)} dishonest outcomes correctly refused "
            f"(cheats miscounted as success: {sum(1 for r in rows if r.miscounted_cheat)})",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # A FLOOR, not a slice: `--tasks 50` asserts the corpus holds at least fifty tasks and
    # then runs ALL of them. Slicing to exactly N would silently exclude every task added
    # after the Nth, so growing the corpus would quietly stop testing the new work while
    # the gate went on printing the number it was asked for (trap 44).
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    parser.add_argument("--min-success", type=float, default=0.60)
    # BooleanOptionalAction, so `--no-check-cheats` exists. `action="store_true", default=True`
    # made the flag inert: it could never be False, and a flag that cannot change anything is a
    # documented option that is really a decoration (found by review).
    parser.add_argument("--check-cheats", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)

    if args.tasks > len(TASKS):
        print(
            f"repair_bench: {args.tasks} tasks requested, corpus holds {len(TASKS)}",
            file=sys.stderr,
        )
        return 2

    rows = evaluate(TASKS)
    print(render(rows, min_success=args.min_success))

    failed = False
    if args.check_cheats:
        for row in rows:
            if row.miscounted_cheat:
                print(
                    f"REPAIR-BENCH {row.task}: counted as a repair, but the divergence went away "
                    f"by {row.expected} — a repair that succeeds by moving the goalposts is a "
                    f"false claim, not a low-quality fix",
                    file=sys.stderr,
                )
                failed = True
        for row in rows:
            if not row.correct and not row.miscounted_cheat:
                print(
                    f"REPAIR-BENCH {row.task}: {row.actual}, expected {row.expected}",
                    file=sys.stderr,
                )
                failed = True

    rate_rows = [r for r in rows if r.counts_toward_rate]
    succeeded = sum(1 for r in rate_rows if r.actual == "succeeded")
    rate = succeeded / len(rate_rows) if rate_rows else 0.0
    if rate < args.min_success:
        print(
            f"REPAIR-BENCH rate {rate:.0%} is under the {args.min_success:.0%} bar",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
