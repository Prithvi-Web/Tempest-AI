"""Phase 19.7 pins: the §5 performance budgets as a gate (L22).

The property that matters is **honest coverage**: ten of the thirteen budgets measure surfaces
that do not exist yet, and the gate must never let those read as met. A perf gate that prints
PASS while enforcing 3 of 13 budgets is worse than no gate, because it manufactures confidence.
"""

import json
import subprocess
from pathlib import Path

import pytest

from tempest.dev import perf_suite as ps


def _metrics(**kw: float) -> dict[str, float]:
    base = {"cold_launch_s": 0.34, "idle_rss_mb": 115.2, "idle_cpu_pct": 0.0}
    base.update(kw)
    return base


_REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_committed(path: Path) -> bool:
    """True when `path` is in the committed tree — i.e. a fresh checkout would contain it.

    Deliberately **not** `git ls-files`, which reports the INDEX: a file that has been `git add`ed
    but never committed answers "tracked" there, while a fresh checkout would still lack it —
    trap 44 again, one step later. `HEAD` is the question actually being asked. The `rev:path`
    form also takes a literal path rather than a pathspec, so glob metacharacters in a filename
    cannot be reinterpreted. Checked against a depth-1 shallow clone in detached HEAD, which is
    what `actions/checkout` produces.
    """
    rel = path.relative_to(_REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "cat-file", "-e", f"HEAD:{rel}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


class TestTheTableIsTheMasterPromptsTable:
    def test_all_thirteen_budgets_are_encoded(self) -> None:
        assert len(ps.BUDGETS) == 13

    def test_keys_are_unique(self) -> None:
        keys = [b.key for b in ps.BUDGETS]
        assert len(set(keys)) == len(keys)

    def test_every_budget_has_a_p95_no_tighter_than_its_p50(self) -> None:
        for b in ps.BUDGETS:
            assert b.p95 >= b.p50, f"{b.key}: p95 {b.p95} tighter than p50 {b.p50}"

    def test_a_budget_with_no_metric_names_the_phase_that_will_provide_it(self) -> None:
        """An unmeasurable budget with no owner is just a gap nobody is accountable for."""
        for b in ps.BUDGETS:
            if b.metric is None:
                assert b.phase, f"{b.key} is unmeasurable and names no phase"

    def test_the_spot_values_match_the_master_prompt(self) -> None:
        by_key = {b.key: b for b in ps.BUDGETS}
        assert (by_key["cold_launch"].p50, by_key["cold_launch"].p95) == (0.8, 1.5)
        assert (by_key["keystroke"].p50, by_key["keystroke"].p95) == (8, 16)
        assert (by_key["idle_ram"].p50, by_key["idle_ram"].p95) == (300, 450)
        assert (by_key["idle_cpu"].p50, by_key["idle_cpu"].p95) == (0.5, 1.0)


class TestUnmeasurableIsNeverPassing:
    def test_budgets_without_a_surface_report_not_yet_measurable(self) -> None:
        report = ps.evaluate(_metrics(), None, None)
        unmeasurable = [r for r in report.rows if r.p50_state == ps.NOT_MEASURABLE]
        assert len(unmeasurable) == 10
        assert all(r.measured_p50 is None for r in unmeasurable)

    def test_the_report_states_how_many_budgets_are_actually_covered(self) -> None:
        report = ps.evaluate(_metrics(), None, None)
        assert report.measured == 3
        assert "3 of 13" in ps.render(report)

    def test_an_unmeasurable_budget_never_appears_as_met(self) -> None:
        rendered = ps.render(ps.evaluate(_metrics(), None, None))
        for budget in ps.BUDGETS:
            if budget.metric is None:
                line = next(ln for ln in rendered.splitlines() if ln.startswith(budget.label))
                assert ps.NOT_MEASURABLE in line
                assert " MET" not in line

    def test_a_metric_missing_from_the_run_is_reported_not_skipped(self) -> None:
        metrics = _metrics()
        del metrics["idle_cpu_pct"]
        report = ps.evaluate(metrics, None, None)
        row = next(r for r in report.rows if r.budget.key == "idle_cpu")
        assert row.p50_state == ps.NOT_MEASURED
        assert "absent" in row.detail


class TestEnforcement:
    def test_a_measured_budget_within_target_passes(self) -> None:
        assert ps.evaluate(_metrics(), None, None).ok

    def test_a_measured_budget_over_target_fails_and_names_itself(self) -> None:
        report = ps.evaluate(_metrics(idle_rss_mb=999.0), None, None)
        assert not report.ok
        assert any("idle_ram" in f and "exceeds" in f for f in report.failures)

    def test_cold_launch_over_its_p50_fails(self) -> None:
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None)
        assert not report.ok
        assert any("cold_launch" in f for f in report.failures)

    def test_a_value_exactly_on_the_budget_is_met(self) -> None:
        """A budget is a ceiling, not a strict inequality — 300MB is within a 300MB budget."""
        assert ps.evaluate(_metrics(idle_rss_mb=300.0), None, None).ok


class TestP95NeedsADistribution:
    def test_without_samples_p95_is_reported_not_yet_measured(self) -> None:
        """A p95 cannot be derived from an aggregate; bench even stores MIN for cold launch."""
        report = ps.evaluate(_metrics(), None, None)
        row = next(r for r in report.rows if r.budget.key == "idle_ram")
        assert row.p95_state == ps.NOT_MEASURED
        assert "cannot be derived" in row.detail

    def test_with_samples_the_p95_is_enforced(self) -> None:
        samples = {"cold_launch_s": [0.3, 0.35, 0.4, 0.45, 2.0]}
        report = ps.evaluate(_metrics(), samples, None)
        assert not report.ok
        assert any("p95" in f and "cold_launch" in f for f in report.failures)

    def test_a_healthy_distribution_passes_both_percentiles(self) -> None:
        samples = {"cold_launch_s": [0.30, 0.32, 0.34, 0.36, 0.38]}
        report = ps.evaluate(_metrics(), samples, None)
        assert report.ok
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p95_state == ps.MET

    def test_a_single_sample_is_not_a_distribution(self) -> None:
        report = ps.evaluate(_metrics(), {"cold_launch_s": [0.34]}, None)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p95_state == ps.NOT_MEASURED


class TestPercentile:
    def test_nearest_rank_is_explicit_and_stable(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert ps.percentile(values, 95) == 5.0
        assert ps.percentile(values, 50) == 3.0

    def test_order_does_not_matter(self) -> None:
        assert ps.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 95) == 5.0

    def test_no_samples_is_an_error_not_a_zero(self) -> None:
        with pytest.raises(ValueError, match="no samples"):
            ps.percentile([], 95)


class TestRegressionBar:
    def test_a_regression_beyond_ten_percent_fails(self) -> None:
        """§5: CI fails on >10% regression."""
        report = ps.evaluate(_metrics(idle_rss_mb=140.0), None, {"idle_rss_mb": 115.2})
        assert not report.ok
        assert any("regressed" in f for f in report.failures)

    def test_a_small_regression_within_the_bar_passes(self) -> None:
        report = ps.evaluate(_metrics(idle_rss_mb=120.0), None, {"idle_rss_mb": 115.2})
        assert report.ok

    def test_the_default_bar_is_ten_percent(self) -> None:
        assert ps.DEFAULT_MAX_REGRESSION_PCT == 10.0

    def test_a_missing_baseline_is_announced_not_silently_skipped(self) -> None:
        report = ps.evaluate(_metrics(), None, None)
        assert any("PENDING(baseline)" in n for n in report.notes)

    def test_a_zero_baseline_is_not_divided_by(self) -> None:
        report = ps.evaluate(_metrics(idle_cpu_pct=0.0), None, {"idle_cpu_pct": 0.0})
        assert report.ok


class TestCli:
    def test_the_flag_is_required(self) -> None:
        with pytest.raises(SystemExit):
            ps.main([])

    def test_a_missing_bench_file_says_to_run_bench(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert ps.main(["--enforce-budgets", "--bench", str(tmp_path / "nope.json")]) == 2
        assert "run `make bench` first" in capsys.readouterr().err

    def test_a_passing_bench_file_exits_zero(self, tmp_path: Path) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(json.dumps({"platform": "darwin", "metrics": _metrics()}))
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 0

    def test_a_failing_bench_file_exits_one_and_names_the_budget(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(json.dumps({"platform": "darwin", "metrics": _metrics(idle_rss_mb=999)}))
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 1
        assert "PERF-GATE" in capsys.readouterr().err

    def test_a_committed_baseline_arms_the_regression_bar(self, tmp_path: Path) -> None:
        (tmp_path / "bench.json").write_text(
            json.dumps({"platform": "darwin", "metrics": _metrics(idle_rss_mb=140.0)})
        )
        (tmp_path / "baseline-darwin.json").write_text(
            json.dumps({"metrics": {"idle_rss_mb": 115.2}})
        )
        assert ps.main(["--enforce-budgets", "--bench", str(tmp_path / "bench.json")]) == 1

    def test_samples_in_the_bench_file_are_used(self, tmp_path: Path) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(
            json.dumps(
                {
                    "platform": "darwin",
                    "metrics": _metrics(),
                    "samples": {"cold_launch_s": [0.3, 0.31, 0.32, 0.33, 9.0]},
                }
            )
        )
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 1

    def test_a_malformed_samples_block_is_ignored_rather_than_fatal(self, tmp_path: Path) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(
            json.dumps({"platform": "darwin", "metrics": _metrics(), "samples": "not a dict"})
        )
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 0

    def test_the_committed_baseline_artifact_is_evaluated(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The gate must parse and evaluate a REAL committed artifact, not only synthetic input.

        The file is `bench/baseline-darwin.json` — the committed *baseline*, deliberately not
        called "the committed bench file". In this repo `bench.json` and `baseline-<platform>.json`
        are two different roles (`--bench` defaults to the former, the baseline is resolved
        separately from the latter), and blurring them is what produced trap 44 in the first place.

        It names `baseline-darwin.json` and not `bench.json` because `bench.json` is **this
        machine's** latest measurement and is gitignored. The first version of this test asserted
        that "the repo ships a committed bench.json" — a false statement that passed anyway,
        because a locally generated copy happened to be sitting on disk. On CI's fresh checkout
        there was no such file and the suite went red (trap 44). Presence on disk is therefore
        not the property this test needs; being IN the repo is, so that is asserted directly and
        the test can no longer be green for a reason that does not travel.

        It deliberately does **not** assert the exit code. The gate's pass/fail logic is pinned
        exactly by the synthetic cases above, where the inputs are known; what this case adds is
        that the gate reaches a verdict on a real shipped artifact instead of crashing on it, and
        that it actually reads something out of it.

        One honest limit: `_is_committed` asks HEAD, while the evaluation below reads the working
        copy from disk. In a clean tree those are the same bytes; if someone edits the baseline
        without committing, the guard still passes and the gate reads the edit. Determinism here
        rests on a clean tree, which `verify-contract` assumes too.

        Note that `perf_suite` derives the baseline from the payload's own `platform` field, so
        feeding it `baseline-darwin.json` makes the file its own baseline and the regression arm
        is identically 0%. That arm is covered by the synthetic cases; this one is about parsing
        and evaluating real committed data, and it stays deterministic on Linux CI precisely
        because the platform comes from the payload rather than from the running machine.
        """
        bench = _REPO_ROOT / "bench" / "baseline-darwin.json"
        assert bench.is_file(), f"{bench} is missing"
        assert _is_committed(bench), (
            f"{bench} is not in the committed tree — a test that reads a repo file must name one "
            "the repo actually ships, or it passes on the author's machine and fails on a fresh "
            "checkout"
        )
        exit_code = ps.main(["--enforce-budgets", "--bench", str(bench)])
        assert exit_code in (0, 1), "the gate must reach a verdict, not crash"
        out = capsys.readouterr().out
        # The exact count, not just the phrase: `"of 13 §5 budgets" in out` reads the SAME when
        # the gate evaluates nothing at all — `ps.evaluate({}, None, None)` renders "0 of 13 §5
        # budgets" and returns 0. The loose form passed while the gate read nothing, which is the
        # failure this case exists to catch. `measured` counts MET and OVER alike, so 3 is pinned
        # to the metric KEY SET, not to any measured value. Phase 20 turns three editor budgets on
        # and this becomes 6 — deliberately, visibly, here.
        assert "3 of 13 §5 budgets are measurable today" in out
        assert "every measurable budget met" in out

    def test_the_committed_check_tells_a_shipped_file_from_a_local_measurement(self) -> None:
        """The guard in the test above is only worth having if it can tell the two apart.

        `bench/baseline-darwin.json` is committed; `bench/bench.json` is what `make bench` writes
        on **this** machine, is gitignored, and a fresh checkout has none. Trap 44 was one being
        mistaken for the other. Without this case the guard's discriminating power is incidental,
        and repointing the test above at the gitignored file would go quietly green again on the
        author's machine. Neither assertion depends on what happens to be on disk, which is the
        whole point.

        Scope, stated honestly: this pins the predicate and *this file*. It is **not** a repo-wide
        gate — `_is_committed` is module-private and nothing stops a new test elsewhere from using
        bare `Path.is_file()` on a repo path. That gate is queued, not built.
        """
        assert _is_committed(_REPO_ROOT / "bench" / "baseline-darwin.json")
        assert not _is_committed(_REPO_ROOT / "bench" / "bench.json")
