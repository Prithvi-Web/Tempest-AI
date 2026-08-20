"""Phase 21's exit gate, part 1 of 4 — F1's verdict coverage.

    python -m tempest.dev.agent_bench --tasks 50 --require-verdict-coverage 1.0

**What it measures.** For every task in the corpus, did the run end on a verdict traceable to a
stored bundle? That is F1's whole claim, and the threshold is 1.0 because anything less means
some agent output reached a user without evidence, which L16 makes a critical bug rather than a
quality metric.

**It is not a quality benchmark and does not pretend to be.** It does not ask whether the agent
wrote *good* code — that would need a real model and the owner's money (QV2), and a keyless CI
run must never report a real-model number. It asks whether the machinery around the model holds:
every task proved, every claim carries a bundle id, nothing was presented unproved.

**The model is a scripted loopback peer.** Deterministic, offline, free, and — the point — able
to be scripted into behaving badly. A benchmark that only ever sees a cooperative model measures
the happy path of a system whose entire job is the unhappy one.

**`--tasks N` is a REQUIREMENT, not a target.** Asking for more tasks than the corpus holds fails
with the shortfall named. A benchmark that quietly ran 12 of a requested 50 and printed a rate
would be the most flattering possible lie, and the exact shape of trap 44.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from tempest.dev._agent_corpus import TASKS, TaskCase, run_case


@dataclass(frozen=True)
class Row:
    name: str
    verdict: str
    has_bundle: bool
    note: str

    @property
    def covered(self) -> bool:
        """A task is covered when it ended on a verdict AND that verdict has evidence behind it.

        Both halves matter: a verdict with no bundle is exactly the forgery L16 forbids, and a
        bundle with no verdict is a run that never reached a conclusion.
        """
        return bool(self.verdict) and self.has_bundle


def evaluate(cases: tuple[TaskCase, ...]) -> list[Row]:
    rows: list[Row] = []
    for case in cases:
        run = run_case(case)
        rows.append(
            Row(
                name=case.name,
                verdict=run.change.verdict.value,
                has_bundle=bool(run.change.bundle_id),
                note=run.stopped_because,
            )
        )
    return rows


def render(rows: list[Row], *, required: float) -> str:
    covered = sum(1 for r in rows if r.covered)
    rate = covered / len(rows) if rows else 0.0
    lines = [
        f"{'task':<28} {'verdict':<24} bundle  note",
        *[
            f"{r.name:<28} {r.verdict:<24} {'yes' if r.has_bundle else 'NO':<6}  {r.note}"
            for r in rows
        ],
    ]
    lines.append("")
    lines.append(
        f"agent_bench: {covered}/{len(rows)} tasks ended on a verdict backed by a bundle "
        f"({rate:.0%}; required {required:.0%})"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=len(TASKS))
    parser.add_argument("--require-verdict-coverage", type=float, default=1.0)
    args = parser.parse_args(argv)

    if args.tasks > len(TASKS):
        print(
            f"agent_bench: {args.tasks} tasks requested, corpus holds {len(TASKS)} — refusing to "
            f"report a rate over a smaller set than was asked for (trap 44: a benchmark that "
            f"quietly runs fewer tasks than requested reports the most flattering number it can)",
            file=sys.stderr,
        )
        return 2

    rows = evaluate(TASKS[: args.tasks])
    print(render(rows, required=args.require_verdict_coverage))
    covered = sum(1 for r in rows if r.covered)
    rate = covered / len(rows) if rows else 0.0
    if rate < args.require_verdict_coverage:
        for row in rows:
            if not row.covered:
                print(
                    f"AGENT-BENCH {row.name}: verdict={row.verdict or 'NONE'} "
                    f"bundle={'yes' if row.has_bundle else 'NO'} — a change reached the caller "
                    f"without evidence (L16)",
                    file=sys.stderr,
                )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
