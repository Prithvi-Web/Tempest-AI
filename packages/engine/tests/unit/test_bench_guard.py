"""bench_guard decision logic (Phase 11): absolute targets always bind; the 15% regression bar
binds when a platform baseline exists; a missing baseline is REPORTED, never silently skipped
(§14.1 — silent suite-narrowing is the failure mode this repo hunts)."""

from tempest.dev.bench_guard import ABSOLUTE_TARGETS, evaluate

GOOD = {
    "cold_launch_s": 0.8,
    "list10k_ms": 90.0,
    "observation_5mb_ms": 200.0,
    "idle_rss_mb": 120.0,
    "idle_cpu_pct": 0.2,
}


def test_all_targets_pass_with_matching_baseline() -> None:
    report = evaluate(GOOD, dict(GOOD), max_regression_pct=15.0)
    assert report.ok
    assert report.failures == []
    assert report.notes == []


def test_absolute_target_violation_fails() -> None:
    slow = dict(GOOD, cold_launch_s=1.6)
    report = evaluate(slow, dict(GOOD, cold_launch_s=1.55), max_regression_pct=15.0)
    assert not report.ok
    assert any("cold_launch_s" in f and "1.5" in f for f in report.failures)


def test_regression_over_bar_fails() -> None:
    regressed = dict(GOOD, list10k_ms=GOOD["list10k_ms"] * 1.2)  # +20% > 15%
    report = evaluate(regressed, dict(GOOD), max_regression_pct=15.0)
    assert not report.ok
    assert any("list10k_ms" in f and "regress" in f.lower() for f in report.failures)


def test_regression_under_bar_passes() -> None:
    wobble = dict(GOOD, list10k_ms=GOOD["list10k_ms"] * 1.1)  # +10% < 15%
    report = evaluate(wobble, dict(GOOD), max_regression_pct=15.0)
    assert report.ok


def test_improvement_passes() -> None:
    faster = {key: value * 0.5 for key, value in GOOD.items()}
    report = evaluate(faster, dict(GOOD), max_regression_pct=15.0)
    assert report.ok


def test_missing_baseline_enforces_absolutes_and_says_so() -> None:
    report = evaluate(GOOD, None, max_regression_pct=15.0)
    assert report.ok
    assert any("PENDING(baseline)" in note for note in report.notes)

    report_slow = evaluate(dict(GOOD, idle_rss_mb=300.0), None, max_regression_pct=15.0)
    assert not report_slow.ok


def test_missing_metric_in_current_run_fails() -> None:
    incomplete = {k: v for k, v in GOOD.items() if k != "idle_cpu_pct"}
    report = evaluate(incomplete, dict(GOOD), max_regression_pct=15.0)
    assert not report.ok
    assert any("idle_cpu_pct" in f and "missing" in f.lower() for f in report.failures)


def test_every_absolute_target_matches_the_plan() -> None:
    # The five Phase 11 numbers, verbatim from docs/PLAN-DESKTOP.md.
    assert ABSOLUTE_TARGETS == {
        "cold_launch_s": 1.5,
        "list10k_ms": 200.0,
        "observation_5mb_ms": 400.0,
        "idle_rss_mb": 250.0,
        "idle_cpu_pct": 1.0,
    }
