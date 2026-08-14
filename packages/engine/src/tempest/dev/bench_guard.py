"""Phase 11 perf gate: `python -m tempest.dev.bench_guard --max-regression 15`.

Reads `bench/bench.json` (written by `make bench` → `tempest.dev.bench`) and enforces, in order:

1. **Absolute targets** — the five Phase 11 numbers from docs/PLAN-DESKTOP.md, always binding.
2. **Regression bar** — each metric may not regress more than `--max-regression`% against the
   committed per-platform baseline (`bench/baseline-<platform>.json`). A missing baseline is
   reported as PENDING(baseline) and the absolutes still bind — never a silent skip (§14.1).

Exit 0 only when every check passes; the report is printed either way.
"""

import argparse
import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Lower is better for every metric. Values are the PLAN-DESKTOP.md Phase 11 targets, verbatim.
ABSOLUTE_TARGETS: dict[str, float] = {
    "cold_launch_s": 1.5,
    "list10k_ms": 200.0,
    "observation_5mb_ms": 400.0,
    "idle_rss_mb": 250.0,
    "idle_cpu_pct": 1.0,
}

BENCH_DIR = Path("bench")


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def evaluate(
    current: dict[str, float], baseline: dict[str, float] | None, *, max_regression_pct: float
) -> Report:
    report = Report()
    for metric, target in ABSOLUTE_TARGETS.items():
        value = current.get(metric)
        if value is None:
            report.failures.append(f"{metric}: missing from the bench run — nothing to assert")
            continue
        if value > target:
            report.failures.append(f"{metric}: {value:g} exceeds the absolute target {target:g}")
    if baseline is None:
        report.notes.append(
            "PENDING(baseline): no committed baseline for this platform — absolute targets "
            "enforced; commit bench/bench.json as the baseline to arm the regression bar"
        )
        return report
    for metric in ABSOLUTE_TARGETS:
        value, base = current.get(metric), baseline.get(metric)
        if value is None or base is None or base <= 0:
            continue  # the missing-metric failure above already covers absent current values
        regression_pct = (value - base) / base * 100.0
        if regression_pct > max_regression_pct:
            report.failures.append(
                f"{metric}: {value:g} regressed {regression_pct:.1f}% over baseline {base:g} "
                f"(bar {max_regression_pct:g}%)"
            )
    return report


def platform_key() -> str:
    return platform.system().lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-regression", type=float, default=15.0, metavar="PCT")
    parser.add_argument("--bench", type=Path, default=BENCH_DIR / "bench.json")
    args = parser.parse_args(argv)

    if not args.bench.exists():
        print(f"bench_guard: {args.bench} not found — run `make bench` first", file=sys.stderr)
        return 2
    payload = json.loads(args.bench.read_text())
    current: dict[str, float] = payload["metrics"]

    baseline_path = args.bench.parent / f"baseline-{platform_key()}.json"
    baseline: dict[str, float] | None = None
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())["metrics"]

    report = evaluate(current, baseline, max_regression_pct=args.max_regression)
    for metric, target in ABSOLUTE_TARGETS.items():
        value = current.get(metric)
        shown = "MISSING" if value is None else f"{value:g}"
        base = "" if baseline is None else f"  (baseline {baseline.get(metric, 'n/a')})"
        print(f"  {metric:<20} {shown:>10}  target {target:g}{base}")
    for note in report.notes:
        print(f"note: {note}")
    for failure in report.failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    print(f"bench_guard: {'PASS' if report.ok else 'FAIL'} ({args.bench}, {platform_key()})")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
