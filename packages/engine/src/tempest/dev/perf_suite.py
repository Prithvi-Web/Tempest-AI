"""Phase 19.7 gate: `python -m tempest.dev.perf_suite --enforce-budgets` (L22).

The master prompt's §5 table is thirteen budgets with a p50 and a p95 each, and L22 makes them
**gates, not aspirations**: a feature that misses its budget does not ship. The table is encoded
here in full — including the ten budgets whose surfaces do not exist yet — because a budget that
is not written down is a budget nobody will be held to.

**The honesty problem this gate exists to avoid.** Ten of the thirteen measure surfaces that
arrive in Phases 20-27 (the editor, the agent, the index, the debugger, the fleet). The tempting
shape is to enforce the three we can and print "perf: PASS", which reads as *thirteen budgets
met*. This gate instead reports every budget in one of four states and says how many are which:

* `MET` / `OVER` — measured against real data.
* `NOT-YET-MEASURABLE` — the surface does not exist; the row names the phase that will build it.
  **Never counted as passing.**
* `NOT-YET-MEASURED` — the surface exists but the run did not collect what the budget needs.
* `INCONCLUSIVE(load)` — a duration that MISSED its budget while the machine was measurably busy.
  Load can only have made it slower, so the miss proves nothing; it is emphatically **not** a
  pass, and the gate stays red. A duration that MET its budget under load keeps `MET`, because an
  in-budget upper bound is a real result. See `QUIET_LOAD_PER_CPU`.

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
import math
import statistics
import sys
from collections.abc import Mapping
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
#: A number taken while the machine was busy, which MISSED its budget. Load can only have made it
#: worse, so the miss proves nothing — but it is emphatically not a pass, and the gate stays red.
INCONCLUSIVE = "INCONCLUSIVE(load)"

#: The 1-minute run-queue average per CPU at or below which a measurement counts as quiet.
#:
#: **PROVISIONAL, and deliberately labelled as such.** An earlier version of this comment called
#: it "empirical, not aesthetic" and cited ADR-0044 for "~25-30% background load producing +11.7%
#: on cold_launch". A review refuted that on three counts and it was right on all three:
#:
#: 1. **The citation was false.** ADR-0044 is "a test asserted a false fact about the repo"; the
#:    only match for "load" inside it is the phrase "fixture loaders". The +11.7% observation
#:    lives in `docs/HANDOFF-NEXT.md` §4/2a, nowhere else.
#: 2. **The two quantities are not the same.** The handoff records "~25-30% background load", a
#:    tilde-estimate of CPU *utilisation*. This constant is a *run-queue depth* divided by CPU
#:    count. Reading 25-30% as 0.25-0.30/cpu is a unit conversion nothing justifies.
#: 3. **No such measurement exists.** Before this module, `os.getloadavg` appeared nowhere in this
#:    repository, so no (load-per-cpu, latency) pair has ever been recorded here. "The lowest
#:    level at which distortion has actually been seen" described data that did not exist.
#:
#: What IS known, and all this bar is chosen against: the one load figure this project has ever
#: written down is **3.96 on 8 CPUs = 0.495/cpu**, sampled on the author's Mac with two heavy
#: apps running, in the same session in which `cold_launch` measured 0.3309 s and 0.3762 s against
#: a 0.2968 s baseline. The bar sits well under that so the case the project has actually seen is
#: classified as loaded. It is **not** derived from a measured load-versus-latency curve, because
#: there is not one.
#:
#: That is the point of recording the raw load with every run: this constant is the feature's
#: weakest part today, and the feature's own output is what will let a future session replace the
#: guess with a curve. Until then it says "provisional" rather than "empirical" (trap 49 — a
#: number you did not measure is a guess, and a guess presented as evidence is a false claim).
QUIET_LOAD_PER_CPU = 0.20


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
    #: True when this row measures a DURATION, so background load can only push it UP.
    #:
    #: That one-sidedness is what lets a busy-machine reading still be trusted when it PASSES
    #: (the quiet number can only be lower) while a miss is unusable. It is deliberately false
    #: for the memory and CPU-share rows: load does not simply inflate an RSS figure, and it can
    #: FLATTER the sidecar's own idle CPU share by starving it — the opposite direction. Extending
    #: the argument to them would be reasoning past the evidence.
    load_inflated: bool = False


#: The §5 table in full. Lower is better for every row.
BUDGETS: tuple[PerfBudget, ...] = (
    PerfBudget(
        "cold_launch",
        "Cold launch → interactive",
        0.8,
        1.5,
        "s",
        metric="cold_launch_s",
        load_inflated=True,
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
        load_inflated=True,
        phase="measured by the desktop E2E leg: `make bench-editor`",
    ),
    PerfBudget(
        "keystroke",
        "Keystroke → render",
        8,
        16,
        "ms",
        metric="keystroke_ms",
        load_inflated=True,
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
        load_inflated=True,
        phase="measured by the desktop E2E leg: `make bench-editor`",
    ),
    PerfBudget(
        "search",
        "Codebase search (F13)",
        150,
        400,
        "ms",
        load_inflated=True,
        phase="Phase 22 (F13)",
    ),
    PerfBudget(
        "agent_first_token",
        "Agent first token",
        400,
        1000,
        "ms",
        load_inflated=True,
        phase="Phase 21 (orchestrator)",
    ),
    PerfBudget(
        "incremental_proof",
        "Incremental proof, 1 function (F18)",
        5,
        15,
        "s",
        load_inflated=True,
        phase="Phase 26 (F18)",
    ),
    PerfBudget(
        "full_proof_10_files",
        "Full proof, 10-file PR",
        25,
        60,
        "s",
        load_inflated=True,
        phase="Phase 19+ (needs a 10-file fixture PR harness)",
    ),
    PerfBudget(
        "diff_render_500",
        "Diff render, 500 files (F12)",
        150,
        300,
        "ms",
        load_inflated=True,
        phase="Phase 23 (F12)",
    ),
    PerfBudget(
        "debugger_scrub",
        "Debugger scrub step (F19)",
        100,
        500,
        "ms",
        load_inflated=True,
        phase="Phase 27 (F19)",
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
    #: Budgets that MISSED while the machine was busy. Separate from `failures` because the two
    #: call for different repairs — a failure means fix the code, an inconclusive means re-take
    #: the measurement — and because collapsing them is how "probably load" became a hypothesis
    #: this project carried for three sessions instead of a number it could check.
    inconclusive: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # An unusable measurement is NOT a pass. The exit code is exactly as red as before this
        # distinction existed; only the message changed (v2 failure mode 2 forbids the other way).
        return not self.failures and not self.inconclusive

    @property
    def measured(self) -> int:
        return sum(1 for r in self.rows if r.p50_state in (MET, OVER))


def load_per_cpu(conditions: Mapping[str, Any] | None) -> float | None:
    """Background run-queue depth per CPU, or None when the run did not record enough to say.

    Every degenerate shape answers None, and None means *unknown* — which switches qualification
    OFF rather than on. Unknown must never collapse into "quiet": that is the direction in which
    a gate starts flattering itself, and the whole module exists to refuse it.
    """
    if not isinstance(conditions, Mapping):
        return None
    load = conditions.get("load_avg_1m_background")
    cpus = conditions.get("cpu_count")
    if not isinstance(load, (int, float)) or isinstance(load, bool):
        return None
    if not isinstance(cpus, int) or isinstance(cpus, bool) or cpus <= 0:
        return None
    return float(load) / cpus


def covered_metrics(conditions: Mapping[str, Any] | None) -> frozenset[str]:
    """Which metrics the recorded load sample is actually ABOUT.

    `bench` writes this as `conditions["covers"]`. A block without it — anything written before
    the key existed — covers NOTHING, so qualification simply does not engage: the conservative
    direction, and the same "unknown is not quiet" rule `is_quiet` follows.
    """
    if not isinstance(conditions, Mapping):
        return frozenset()
    covers = conditions.get("covers")
    if not isinstance(covers, list):
        return frozenset()
    return frozenset(c for c in covers if isinstance(c, str))


def is_quiet(conditions: Mapping[str, Any] | None) -> bool | None:
    """True/False when the conditions are known, None when they are not."""
    per_cpu = load_per_cpu(conditions)
    if per_cpu is None:
        return None
    return per_cpu <= QUIET_LOAD_PER_CPU


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile: ``ceil(pct/100 * n)``, clamped into ``[1, n]``.

    "Explicit because 'p95' must mean one thing across the repo" was the intent, and it was not
    met: `completionPolicy.percentile` in the webview used `ceil`, this used
    `round(x + 0.5)`, and those two disagree whenever ``pct/100 * n`` lands exactly on an integer
    (Python's banker's rounding then pushes the rank up by one). `percentile([40,10,30,20], 25)`
    answered 10 there and 20 here, under a TS test whose name said "matching perf_suite".

    `ceil` is the textbook nearest-rank definition and is now what both compute. Every existing
    assertion in this repo is unchanged by the switch — the vectors it pins never hit the
    disagreeing case, which is exactly why nobody noticed.
    """
    if not samples:
        raise ValueError("no samples")
    if not 0.0 <= pct <= 100.0:
        raise ValueError(f"percentile {pct} is outside 0..100")
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), math.ceil(pct / 100.0 * len(ordered))))
    return ordered[rank - 1]


def evaluate(
    metrics: dict[str, float],
    samples: dict[str, list[float]] | None,
    baseline: dict[str, float] | None,
    *,
    max_regression_pct: float = DEFAULT_MAX_REGRESSION_PCT,
    conditions: Mapping[str, Any] | None = None,
    baseline_meta: Mapping[str, Any] | None = None,
) -> Report:
    report = Report()
    samples = samples or {}
    quiet = is_quiet(conditions)
    # `qualify` is True only when we KNOW the machine was busy. Unknown conditions leave every
    # verdict exactly as it was before this feature existed — no silent behaviour change for a
    # bench.json written earlier — and say so in a note further down.
    qualify = quiet is False
    covered = covered_metrics(conditions)
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

        # The one-sided argument, applied in exactly one place: load can only push a DURATION
        # up, so an in-budget reading taken on a busy machine is a valid upper bound and stays
        # MET, while a miss is unusable rather than proved.
        #
        # `covered` is the third condition and it is not a formality. The editor rows
        # (`open_file_ms`, `keystroke_ms`, `completion_ms`) are durations, and they are NOT
        # measured by the process that sampled the load: `make bench-editor` writes them in a
        # separate Playwright run whose only staleness guard is a matching HEAD, so it may have
        # run hours earlier under different load. Qualifying them with this sample would answer
        # about the wrong process — in both directions, hiding a real editor miss and excusing
        # a fake one. They keep their plain verdict and the report says why.
        unusable = qualify and budget.load_inflated and budget.metric in covered

        if value <= budget.p50:
            p50_state = MET
        elif unusable:
            p50_state = INCONCLUSIVE
            report.inconclusive.append(
                f"{budget.key}: p50 {value:g}{budget.unit} missed the budget "
                f"{budget.p50:g}{budget.unit}, but the machine was busy "
                f"({_load_phrase(conditions)}) — re-measure on a quiet machine"
            )
        else:
            p50_state = OVER
            report.failures.append(
                f"{budget.key}: p50 {value:g}{budget.unit} exceeds the budget "
                f"{budget.p50:g}{budget.unit}"
            )

        raw = samples.get(budget.metric) or []
        if len(raw) >= 2:
            measured_p95 = percentile([float(x) for x in raw], 95)
            if measured_p95 <= budget.p95:
                p95_state = MET
            elif unusable:
                p95_state = INCONCLUSIVE
                report.inconclusive.append(
                    f"{budget.key}: p95 {measured_p95:g}{budget.unit} missed the budget "
                    f"{budget.p95:g}{budget.unit}, but the machine was busy "
                    f"({_load_phrase(conditions)}) — re-measure on a quiet machine"
                )
            else:
                p95_state = OVER
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
                if regression <= max_regression_pct:
                    pass  # an upper bound inside the bar PROVES there is no regression
                elif unusable:
                    report.inconclusive.append(
                        f"{budget.key}: {value:g}{budget.unit} is {regression:.1f}% over "
                        f"baseline {base:g}{budget.unit} (bar {max_regression_pct:g}%), but the "
                        f"machine was busy ({_load_phrase(conditions)}) — this is not a proved "
                        f"regression; re-measure on a quiet machine. Re-baselining to clear it "
                        f"is forbidden."
                    )
                else:
                    report.failures.append(
                        f"{budget.key}: {value:g}{budget.unit} regressed {regression:.1f}% over "
                        f"baseline {base:g}{budget.unit} (bar {max_regression_pct:g}%)"
                    )

    report.notes.extend(_condition_notes(conditions, baseline, baseline_meta))
    if baseline is None:
        report.notes.append(
            "PENDING(baseline): no committed baseline for this platform — budgets enforced, "
            "regression bar not armed"
        )
    return report


def _load_phrase(conditions: Mapping[str, Any] | None) -> str:
    per_cpu = load_per_cpu(conditions)
    return "load unknown" if per_cpu is None else f"background load {per_cpu:.2f}/cpu"


def _condition_notes(
    conditions: Mapping[str, Any] | None,
    baseline: dict[str, float] | None,
    baseline_meta: Mapping[str, Any] | None,
) -> list[str]:
    """Say what the conditions were, and — louder — what they do NOT license.

    Every branch here exists because the alternative is silence, and silence about a measurement's
    conditions is what made "is cold_launch drift or load?" unanswerable for three sessions.
    """
    notes: list[str] = []
    quiet = is_quiet(conditions)
    if quiet is None:
        notes.append(
            "PENDING(conditions): this run recorded no machine conditions it could be judged on "
            "— every verdict below is unqualified. Re-run `make bench` to record them."
        )
    elif quiet:
        notes.append(
            f"conditions: {_load_phrase(conditions)}, at or under the "
            f"{QUIET_LOAD_PER_CPU:g}/cpu bar — the machine was quiet and every verdict binds."
        )
    else:
        notes.append(
            f"conditions: {_load_phrase(conditions)}, OVER the {QUIET_LOAD_PER_CPU:g}/cpu bar. "
            f"Latency budgets that PASSED still bind (load can only have made them slower); "
            f"latency budgets that MISSED are reported {INCONCLUSIVE} and the gate stays red."
        )
        # DERIVED, never hand-listed: a note naming a fixed set of rows becomes false the day a
        # budget's `load_inflated` flag or the `covers` list changes, and a stale note in a gate's
        # own output is the failure this module exists to refuse.
        covered = covered_metrics(conditions)
        not_a_duration = sorted(
            b.key for b in BUDGETS if b.metric is not None and not b.load_inflated
        )
        not_covered = sorted(
            b.key
            for b in BUDGETS
            if b.metric is not None and b.load_inflated and b.metric not in covered
        )
        if not_a_duration:
            notes.append(
                f"conditions: {', '.join(not_a_duration)} are NOT qualified by the load argument. "
                f"Load does not simply inflate an RSS figure, and it can FLATTER the sidecar's own "
                f"idle CPU share by starving it — the opposite direction. Their verdicts stand as "
                f"measured; extending a one-sided argument to them would reason past the evidence."
            )
        if not_covered:
            notes.append(
                f"conditions: {', '.join(not_covered)} are durations, but the load sample does not "
                f"COVER them — they are merged from `bench/editor-metrics.json`, which "
                f"`make bench-editor` writes in a separate run that this sample never observed. "
                f"Qualifying them here would answer about the wrong process, so their verdicts "
                f"stand as measured. Closing that gap means recording conditions in the editor "
                f"leg too."
            )

    if baseline is not None:
        base_conditions = (
            baseline_meta.get("conditions") if isinstance(baseline_meta, Mapping) else None
        )
        if not isinstance(base_conditions, Mapping):
            notes.append(
                "baseline: the committed baseline records no conditions of its own, so a "
                "regression is measured against a reference of unknown provenance. It is still "
                "this project's recorded number and still binds — but it is not a like-for-like "
                "comparison, and it becomes one the next time a baseline is taken and committed."
            )
        here = conditions.get("cpu_count") if isinstance(conditions, Mapping) else None
        there = baseline_meta.get("cpu_count") if isinstance(baseline_meta, Mapping) else None
        if isinstance(here, int) and isinstance(there, int) and here != there:
            notes.append(
                f"baseline: measured on {there} CPUs, this run on {here}. A difference across "
                f"that is a different computer, not a regression."
            )
    return notes


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
    lines.append("")
    # Three states, counted separately, because collapsing them is how a gate starts flattering
    # itself. MEASURED means a number exists and was judged. NOT-YET-MEASURED means the surface
    # exists and nobody ran the measurement — `make bench-editor` for the editor rows. NOT-YET-
    # MEASURABLE means the feature does not exist yet. The old sentence said "N of 13 budgets are
    # measurable" while counting MEASURED rows, and then called every other row NOT-YET-
    # MEASURABLE — which is false the moment an armed budget simply has not been run, and that is
    # exactly the state of the three editor rows on a machine that has not run bench-editor.
    # `measured_count`, not `measured`: the loop above binds `measured` to a formatted row
    # string, and mypy --strict caught the shadow immediately.
    measured_count = report.measured
    not_measured = sum(1 for r in report.rows if r.p50_state == NOT_MEASURED)
    not_measurable = sum(1 for r in report.rows if r.p50_state == NOT_MEASURABLE)
    # A FOURTH row state, counted apart for the same reason as the other three: a number taken on
    # a busy machine that missed its budget is neither a pass nor a proved failure, and folding it
    # into either one loses the only information that says what to do about it.
    # Counted on `p50_state` ALONE, exactly like the three counts above it, so the four numbers
    # PARTITION the thirteen budgets. Counting "INCONCLUSIVE in either state" double-counted a row
    # whose p50 was MET and whose p95 was inconclusive: the printed numbers summed to 14 of 13,
    # and that row read as both "MEASURED and judged" and "INCONCLUSIVE" in the same sentence.
    # A p95 that load made unusable is not lost — it is in the table and in the findings line.
    inconclusive_rows = sum(1 for r in report.rows if r.p50_state == INCONCLUSIVE)
    lines.append(
        f"perf_suite: {measured_count} of {len(BUDGETS)} §5 budgets MEASURED and judged; "
        f"{not_measured} armed but NOT-YET-MEASURED (run the measurement); "
        f"{not_measurable} NOT-YET-MEASURABLE (the feature does not exist yet); "
        f"{inconclusive_rows} INCONCLUSIVE rows (a duration that missed while the machine was "
        f"busy). The four counts partition the table; none of the last three is ever met."
    )
    # ROWS and FINDINGS are different units and the second is what the gate actually holds. A row
    # can be MET on its budget and still carry an unusable REGRESSION comparison — `cold_launch`
    # at 0.3309s is inside its 0.8s budget and 11.5% over the baseline at the same time. Counting
    # only rows printed "0 INCONCLUSIVE" in the very run the gate was failing for (trap 47, found
    # by running the probe rather than by reading the code).
    lines.append(
        f"perf_suite: {len(report.inconclusive)} INCONCLUSIVE finding(s) — a budget can be MET on "
        f"its own row and still have a comparison that load made unusable. Re-measure on a quiet "
        f"machine; re-baselining to clear one is forbidden."
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
    raw_conditions = payload.get("conditions") if isinstance(payload, dict) else None
    # A malformed block is treated as ABSENT, not as quiet: `is_quiet(None)` answers unknown,
    # which switches qualification off rather than on.
    conditions = raw_conditions if isinstance(raw_conditions, dict) else None

    platform_name = str(payload.get("platform", "")) if isinstance(payload, dict) else ""
    baseline_path = args.bench.parent / f"baseline-{platform_name}.json"
    baseline: dict[str, float] | None = None
    baseline_meta: dict[str, Any] | None = None
    if baseline_path.exists():
        base_doc: Any = json.loads(baseline_path.read_text(encoding="utf-8"))
        if isinstance(base_doc, dict):
            baseline = base_doc.get("metrics")
            baseline_meta = base_doc

    report = evaluate(
        metrics,
        samples,
        baseline,
        max_regression_pct=args.max_regression,
        conditions=conditions,
        baseline_meta=baseline_meta,
    )
    print(render(report))
    for note in report.notes:
        print(note)
    if report.failures:
        print(f"perf_suite: {len(report.failures)} budget failure(s) — FAIL")
        for failure in report.failures:
            print(f"PERF-GATE {failure}", file=sys.stderr)
    if report.inconclusive:
        # Deliberately NOT printed as "PERF-GATE <budget> regressed": the operator-facing repair
        # is to re-take the measurement, and a message that says "regressed" is what makes
        # re-baselining look like the fix.
        print(f"perf_suite: {len(report.inconclusive)} budget(s) INCONCLUSIVE — FAIL")
        for item in report.inconclusive:
            print(f"PERF-GATE {INCONCLUSIVE} {item}", file=sys.stderr)
    if not report.ok:
        return 1
    print("perf_suite: every measurable budget met (L22)")
    return 0


def _median(values: list[float]) -> float:  # pragma: no cover - convenience for callers
    return statistics.median(values)


if __name__ == "__main__":
    raise SystemExit(main())
