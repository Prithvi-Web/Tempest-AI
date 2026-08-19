"""Phase 19.7 gate: `python -m tempest.dev.perf_suite --enforce-budgets` (L22).

The master prompt's §5 table is thirteen budgets with a p50 and a p95 each, and L22 makes them
**gates, not aspirations**: a feature that misses its budget does not ship. The table is encoded
here in full — including the ten budgets whose surfaces do not exist yet — because a budget that
is not written down is a budget nobody will be held to.

**The honesty problem this gate exists to avoid.** Ten of the thirteen measure surfaces that
arrive in Phases 20-27 (the editor, the agent, the index, the debugger, the fleet). The tempting
shape is to enforce the three we can and print "perf: PASS", which reads as *thirteen budgets
met*. This gate instead reports every budget in one of three states and says how many are which:

* `MET` / `OVER` — measured against real data.
* `NOT-YET-MEASURABLE` — the surface does not exist; the row names the phase that will build it.
  **Never counted as passing.**
* `NOT-YET-MEASURED` — the surface exists but the run did not collect what the budget needs.

**Why p95 is usually the second kind.** `tempest.dev.bench` stores aggregates, and for cold
launch it stores `min(samples)` — the most flattering statistic available. A p95 cannot be
derived from a minimum, so p95 is only enforced when the bench emits raw `samples`; otherwise it
is reported as not-yet-measured rather than quietly compared against the wrong number. Enforcing
a p95 against a best-case sample would be worse than not enforcing it, because it would look
like coverage.

**Regression bar: 10%**, per §5 ("CI fails on >10% regression"), against the committed
per-platform baseline — the same mechanism `bench_guard` uses for the v1 five.
"""

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCH_DIR = Path("bench")
#: §5: "CI fails on >10% regression."
DEFAULT_MAX_REGRESSION_PCT = 10.0

MET = "MET"
OVER = "OVER"
NOT_MEASURABLE = "NOT-YET-MEASURABLE"
NOT_MEASURED = "NOT-YET-MEASURED"


@dataclass(frozen=True)
class PerfBudget:
    """One row of the §5 table, verbatim, plus where its number comes from."""

    key: str
    label: str
    p50: float
    p95: float
    unit: str
    #: Metric name in `bench.json`. None means no surface measures this yet.
    metric: str | None = None
    #: The phase that will make it measurable — stated so the gap has an owner, not just a gap.
    phase: str = ""


#: The §5 table in full. Lower is better for every row.
BUDGETS: tuple[PerfBudget, ...] = (
    PerfBudget(
        "cold_launch",
        "Cold launch → interactive",
        0.8,
        1.5,
        "s",
        metric="cold_launch_s",
        phase="partially: bench measures spawn → healthy stdio, not webview first paint",
    ),
    # Phase 20.1b armed these: the editor surface exists, so "no surface measures this yet" is
    # no longer true. Absent numbers now read as NOT-YET-MEASURED (nobody ran `make bench-editor`)
    # rather than NOT-YET-MEASURABLE (nothing to run) — a smaller excuse, which is the point.
    PerfBudget(
        "open_file",
        "Open file (10k lines)",
        40,
        100,
        "ms",
        metric="open_file_ms",
        phase="measured by the desktop E2E leg: `make bench-editor`",
    ),
    PerfBudget(
        "keystroke",
        "Keystroke → render",
        8,
        16,
        "ms",
        metric="keystroke_ms",
        phase="measured by the desktop E2E leg: `make bench-editor`",
    ),
    # Phase 20.3c armed this: F11 exists, so "no surface measures this yet" stopped being true.
    PerfBudget(
        "completion",
        "Inline completion (F11)",
        120,
        300,
        "ms",
        metric="completion_ms",
        phase="measured by the desktop E2E leg: `make bench-editor`",
    ),
    PerfBudget("search", "Codebase search (F13)", 150, 400, "ms", phase="Phase 22 (F13)"),
    PerfBudget(
        "agent_first_token", "Agent first token", 400, 1000, "ms", phase="Phase 21 (orchestrator)"
    ),
    PerfBudget(
        "incremental_proof",
        "Incremental proof, 1 function (F18)",
        5,
        15,
        "s",
        phase="Phase 26 (F18)",
    ),
    PerfBudget(
        "full_proof_10_files",
        "Full proof, 10-file PR",
        25,
        60,
        "s",
        phase="Phase 19+ (needs a 10-file fixture PR harness)",
    ),
    PerfBudget(
        "diff_render_500", "Diff render, 500 files (F12)", 150, 300, "ms", phase="Phase 23 (F12)"
    ),
    PerfBudget(
        "debugger_scrub", "Debugger scrub step (F19)", 100, 500, "ms", phase="Phase 27 (F19)"
    ),
    PerfBudget("idle_ram", "Idle RAM", 300, 450, "MB", metric="idle_rss_mb"),
    PerfBudget("ram_8_agents", "RAM, 8 agents (F17)", 2048, 3072, "MB", phase="Phase 26 (F17)"),
    PerfBudget("idle_cpu", "Idle CPU", 0.5, 1.0, "%", metric="idle_cpu_pct"),
)


@dataclass
class Row:
    budget: PerfBudget
    p50_state: str
    p95_state: str
    measured_p50: float | None = None
    measured_p95: float | None = None
    detail: str = ""


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def measured(self) -> int:
        return sum(1 for r in self.rows if r.p50_state in (MET, OVER))


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile. Explicit because 'p95' must mean one thing across the repo."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), round(pct / 100.0 * len(ordered) + 0.5)))
    return ordered[rank - 1]


def evaluate(
    metrics: dict[str, float],
    samples: dict[str, list[float]] | None,
    baseline: dict[str, float] | None,
    *,
    max_regression_pct: float = DEFAULT_MAX_REGRESSION_PCT,
) -> Report:
    report = Report()
    samples = samples or {}
    for budget in BUDGETS:
        if budget.metric is None:
            report.rows.append(Row(budget, NOT_MEASURABLE, NOT_MEASURABLE, detail=budget.phase))
            continue
        value = metrics.get(budget.metric)
        if value is None:
            report.rows.append(
                Row(
                    budget,
                    NOT_MEASURED,
                    NOT_MEASURED,
                    detail=f"{budget.metric} absent from the run",
                )
            )
            continue

        p50_state = MET if value <= budget.p50 else OVER
        if p50_state is OVER or value > budget.p50:
            report.failures.append(
                f"{budget.key}: p50 {value:g}{budget.unit} exceeds the budget "
                f"{budget.p50:g}{budget.unit}"
            )

        raw = samples.get(budget.metric) or []
        if len(raw) >= 2:
            measured_p95 = percentile([float(x) for x in raw], 95)
            p95_state = MET if measured_p95 <= budget.p95 else OVER
            if measured_p95 > budget.p95:
                report.failures.append(
                    f"{budget.key}: p95 {measured_p95:g}{budget.unit} exceeds the budget "
                    f"{budget.p95:g}{budget.unit}"
                )
            report.rows.append(Row(budget, p50_state, p95_state, value, measured_p95))
        else:
            report.rows.append(
                Row(
                    budget,
                    p50_state,
                    NOT_MEASURED,
                    value,
                    detail="no sample distribution in the bench output; a p95 cannot be "
                    "derived from an aggregate (bench stores min for cold launch)",
                )
            )

        if baseline is not None:
            base = baseline.get(budget.metric)
            if base is not None and base > 0:
                regression = (value - base) / base * 100.0
                if regression > max_regression_pct:
                    report.failures.append(
                        f"{budget.key}: {value:g}{budget.unit} regressed {regression:.1f}% over "
                        f"baseline {base:g}{budget.unit} (bar {max_regression_pct:g}%)"
                    )

    if baseline is None:
        report.notes.append(
            "PENDING(baseline): no committed baseline for this platform — budgets enforced, "
            "regression bar not armed"
        )
    return report


def render(report: Report) -> str:
    lines = [
        f"{'budget':<34} {'p50':>10} {'target':>9}  {'p95':>10} {'target':>9}  state",
    ]
    for row in report.rows:
        b = row.budget
        p50 = f"{row.measured_p50:g}" if row.measured_p50 is not None else "-"
        p95 = f"{row.measured_p95:g}" if row.measured_p95 is not None else "-"
        # When nothing was measured the two states are identical, so print one word; when the
        # p50 was measured the two can differ and both are named. Never collapse a
        # not-measured p95 into the p50's verdict — that is the whole point of the gate.
        if row.p50_state == row.p95_state:
            state = row.p50_state
        else:
            state = f"p50 {row.p50_state} / p95 {row.p95_state}"
        measured = f"{p50:>10} {b.p50:>8g}{b.unit:<1}  {p95:>10} {b.p95:>8g}{b.unit:<1}"
        detail = f"  ({row.detail})" if row.detail else ""
        lines.append(f"{b.label:<34} {measured}  {state}{detail}")
    measurable = report.measured
    lines.append("")
    lines.append(
        f"perf_suite: {measurable} of {len(BUDGETS)} §5 budgets are measurable today; the rest "
        f"are NOT-YET-MEASURABLE and are never counted as met."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enforce-budgets", action="store_true", required=True)
    parser.add_argument("--bench", type=Path, default=BENCH_DIR / "bench.json")
    parser.add_argument("--max-regression", type=float, default=DEFAULT_MAX_REGRESSION_PCT)
    args = parser.parse_args(argv)

    if not args.bench.exists():
        print(
            f"perf_suite: {args.bench} not found — run `make bench` first (the budgets are real "
            f"measurements or nothing at all)",
            file=sys.stderr,
        )
        return 2

    payload: Any = json.loads(args.bench.read_text(encoding="utf-8"))
    metrics: dict[str, float] = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    raw_samples = payload.get("samples") if isinstance(payload, dict) else None
    samples = raw_samples if isinstance(raw_samples, dict) else None

    platform_name = str(payload.get("platform", "")) if isinstance(payload, dict) else ""
    baseline_path = args.bench.parent / f"baseline-{platform_name}.json"
    baseline: dict[str, float] | None = None
    if baseline_path.exists():
        base_doc: Any = json.loads(baseline_path.read_text(encoding="utf-8"))
        if isinstance(base_doc, dict):
            baseline = base_doc.get("metrics")

    report = evaluate(metrics, samples, baseline, max_regression_pct=args.max_regression)
    print(render(report))
    for note in report.notes:
        print(note)
    if report.failures:
        print(f"perf_suite: {len(report.failures)} budget failure(s) — FAIL")
        for failure in report.failures:
            print(f"PERF-GATE {failure}", file=sys.stderr)
        return 1
    print("perf_suite: every measurable budget met (L22)")
    return 0


def _median(values: list[float]) -> float:  # pragma: no cover - convenience for callers
    return statistics.median(values)


if __name__ == "__main__":
    raise SystemExit(main())
