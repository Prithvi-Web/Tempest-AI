"""Phase 19.7 pins: the §5 performance budgets as a gate (L22).

The property that matters is **honest coverage**: ten of the thirteen budgets measure surfaces
that do not exist yet, and the gate must never let those read as met. A perf gate that prints
PASS while enforcing 3 of 13 budgets is worse than no gate, because it manufactures confidence.
"""

import json
import re
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
        """Which budgets have no surface — named, not counted.

        This asserted `== 10` until Phase 20.1b built the editor surface and armed two of them.
        A bare count answers "did the number change" and makes the fix "edit the number"; the
        set answers "which surface arrived", and arriving is the only reason it may shrink.
        Every remaining entry names the phase that will build it.
        """
        report = ps.evaluate(_metrics(), None, None)
        unmeasurable = [r for r in report.rows if r.p50_state == ps.NOT_MEASURABLE]
        assert {r.budget.key for r in unmeasurable} == {
            "search",  # Phase 22 (F13) — the next one to arrive
            "agent_first_token",  # Phase 21 (orchestrator)
            "incremental_proof",  # Phase 26 (F18)
            "full_proof_10_files",  # needs a 10-file fixture PR harness
            "diff_render_500",  # Phase 23 (F12)
            "debugger_scrub",  # Phase 27 (F19)
            "ram_8_agents",  # Phase 26 (F17)
        }
        assert all(r.measured_p50 is None for r in unmeasurable)
        assert all(r.budget.phase for r in unmeasurable), "a gap with no owner is just a gap"

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

    def test_the_vector_where_this_used_to_disagree_with_the_webview(self) -> None:
        """`completionPolicy.percentile` computes the SAME number, and did not.

        This side used ``round(pct/100*n + 0.5)`` and the webview used ``ceil``; Python's
        banker's rounding made them differ whenever ``pct/100 * n`` lands on an integer. The
        webview's own test for this vector was titled "matching perf_suite" and asserted 10,
        while this function answered 20. Both are ``ceil`` now, and the same vector is asserted
        in `completionPolicy.test.ts` so neither can drift alone.
        """
        assert ps.percentile([40.0, 10.0, 30.0, 20.0], 25) == 10.0
        assert ps.percentile([float(n) for n in range(1, 21)], 95) == 19.0
        assert ps.percentile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 50) == 3.0

    def test_a_percentile_outside_the_range_is_refused_not_clamped(self) -> None:
        # Clamping would answer with the smallest sample, which is a fabricated number in the
        # one module whose job is feeding a gate.
        for bad in (-5.0, -0.1, 100.1, 1000.0):
            with pytest.raises(ValueError, match=r"outside 0\.\.100"):
                ps.percentile([10.0, 20.0], bad)
        # 0 and 100 are inside the range and mean the extremes, which is not an invention.
        assert ps.percentile([10.0, 20.0], 0) == 10.0
        assert ps.percentile([10.0, 20.0], 100) == 20.0


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
        # The exact counts, not just the phrase: `"of 13 §5 budgets" in out` reads the SAME when
        # the gate evaluates nothing at all — `ps.evaluate({}, None, None)` renders "0 of 13 §5
        # budgets" and returns 0. The loose form passed while the gate read nothing, which is the
        # failure this case exists to catch. `measured` counts MET and OVER alike, so 3 is pinned
        # to the metric KEY SET, not to any measured value.
        #
        # ALL THREE counts are pinned, and they must sum to 13. The summary used to call every
        # unmeasured row NOT-YET-MEASURABLE, which is false for the three editor budgets: they
        # are ARMED and simply have no numbers in this artifact, because `make bench-editor`
        # writes them and nobody ran it. "The surface does not exist" and "nobody measured it"
        # are the two states this module exists to keep apart, and its own summary collapsed them.
        assert "3 of 13 §5 budgets MEASURED and judged" in out
        assert "3 armed but NOT-YET-MEASURED" in out
        assert "7 NOT-YET-MEASURABLE" in out
        # Parsed BACK OUT of the rendered line. `assert 3 + 3 + 7 == 13` is a constant the
        # interpreter folds before the test runs: it asserts arithmetic, not perf_suite, and
        # would pass with the module deleted.
        counts = [int(n) for n in re.findall(r"(\d+) (?:of 13|armed|NOT-YET-MEASURABLE)", out)]
        assert len(counts) == 3, f"all three counts must be rendered: {out}"
        assert sum(counts) == len(ps.BUDGETS), (
            f"the three states must account for every budget, none double-counted: {counts}"
        )
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

    def test_the_editor_budgets_are_armed_but_unmeasured_without_the_e2e_leg(self) -> None:
        """20.1b changed what silence MEANS for the two editor rows.

        Before, `open_file` and `keystroke` carried no metric at all, so the gate called them
        NOT-YET-MEASURABLE: there was no surface to measure. The surface exists now, so an absent
        number is a different statement — nobody ran `make bench-editor` — and it must read as
        NOT-YET-MEASURED. Neither may ever read as MET, which is the only outcome that would
        matter to someone trusting the table.
        """
        report = ps.evaluate(_metrics(), None, None)
        rows = {row.budget.key: row for row in report.rows}
        for key in ("open_file", "keystroke"):
            assert rows[key].p50_state == ps.NOT_MEASURED, key
            assert rows[key].p50_state != ps.MET, key
            assert "bench-editor" in rows[key].budget.phase, key

    def test_the_editor_budgets_bind_once_the_numbers_arrive(self) -> None:
        measured = _metrics(open_file_ms=39.0, keystroke_ms=7.0)
        assert ps.evaluate(measured, None, None).measured == 5
        over = _metrics(open_file_ms=41.0, keystroke_ms=7.0)
        report = ps.evaluate(over, None, None)
        assert any("open_file" in f for f in report.failures), report.failures

    def test_all_three_editor_budgets_arm_together(self) -> None:
        """20.3c armed the third. With all three measured the count is 6 of 13.

        The number is the honest definition of Phase 20's progress, which is why it is asserted
        rather than described: it cannot move because someone edited a comment.
        """
        full = _metrics(open_file_ms=15.6, keystroke_ms=1.3, completion_ms=40.0)
        report = ps.evaluate(full, None, None)
        assert report.measured == 6
        assert "6 of 13" in ps.render(report)
        assert report.failures == [], report.failures

    def test_a_completion_over_budget_fails_like_any_other(self) -> None:
        over = _metrics(open_file_ms=15.6, keystroke_ms=1.3, completion_ms=121.0)
        report = ps.evaluate(over, None, None)
        assert any("completion" in f for f in report.failures), report.failures


#: What `tempest.dev.bench` measures in its OWN process, and therefore the only metrics its load
#: sample can speak for. Mirrors `bench.MEASURED_IN_PROCESS`; asserted equal to it below, so the
#: two cannot drift apart silently.
_ENGINE_METRICS = [
    "cold_launch_s",
    "list10k_ms",
    "observation_5mb_ms",
    "idle_rss_mb",
    "idle_cpu_pct",
]
#: A quiet machine: 0.4 runnable threads across 8 CPUs — 0.05/cpu, well under the bar.
_QUIET: dict[str, object] = {
    "source": "os.getloadavg",
    "load_avg_1m_background": 0.4,
    "cpu_count": 8,
    "covers": _ENGINE_METRICS,
}
#: The owner's Mac as actually observed on 2026-08-20 while TreeMap and Chrome were running:
#: load 3.96 on 8 CPUs — 0.495/cpu, nearly 2.5x the bar. Not a hypothetical.
_LOADED: dict[str, object] = {
    "source": "os.getloadavg",
    "load_avg_1m_background": 3.96,
    "cpu_count": 8,
    "covers": _ENGINE_METRICS,
}
#: The same load, written by a `bench` that predates the `covers` key. Qualification must NOT
#: engage: a sample that does not say what it measured speaks for nothing.
_LOADED_NO_COVERS: dict[str, object] = {
    "source": "os.getloadavg",
    "load_avg_1m_background": 3.96,
    "cpu_count": 8,
}


class TestLoadQualification:
    """A measurement taken on a busy machine is an UPPER BOUND, and the gate says so.

    The asymmetry is the whole idea and it is not a softening: background load can only make a
    latency measurement *slower*, never faster. So

    * a latency number that is **within** budget under load is a definitive PASS — the true
      quiet-machine number can only be lower;
    * a latency number that is **over** budget under load proves nothing, and calling it a
      regression invites the one repair this project forbids: re-baselining to make it green.

    States enumerated before the tests (trap 43): conditions absent · conditions present but the
    source was unavailable · quiet · loaded · loaded-and-passing · loaded-and-failing-p50 ·
    loaded-and-failing-p95 · loaded-and-regressed · cpu_count missing · cpu_count zero ·
    load missing · a non-latency budget under load · a baseline with no recorded conditions.
    """

    def test_the_bar_is_provisional_and_the_code_says_so(self) -> None:
        """The bar is a GUESS, and the constant's comment must keep saying that out loud.

        An earlier version of this docstring read: *"25-30% background load was observed
        producing +11.7% on cold_launch (ADR-0044) — the quiet bar sits below the lowest level at
        which distortion has been OBSERVED here."* Every clause of that was wrong. ADR-0044 is
        about a test asserting a false fact about the repo and contains no load measurement at
        all (its only "load" is the word "loaders"); the +11.7% figure lives in
        `docs/HANDOFF-NEXT.md`; "25-30% background load" is a CPU-utilisation estimate while this
        constant is a run-queue depth per CPU, which is a different quantity; and no
        (load-per-cpu, latency) pair has ever been recorded in this repository, because
        `os.getloadavg` appeared nowhere in it until this module.

        So this test pins the honesty of the label, not a number someone can nudge. The bar may
        change when there is a curve to derive it from — but it may not quietly become
        "empirical" without one.
        """
        assert ps.QUIET_LOAD_PER_CPU == 0.20
        doc = ps.__doc__ or ""
        import inspect

        source = inspect.getsource(ps)
        marker = source[
            source.index("#: The 1-minute run-queue") : source.index("QUIET_LOAD_PER_CPU = ")
        ]
        assert "PROVISIONAL" in marker, "the bar must not be presented as measured"
        assert "0.495" in marker, "it must name the one load figure this project has recorded"
        # The refuted claim IS quoted in the comment — deliberately, so the history survives — so
        # the test cannot simply forbid the phrase. What must never disappear is the refutation
        # that follows it; without that, the quote reads as the claim.
        assert "The citation was false" in marker
        assert "no (load-per-cpu, latency) pair" in marker or "No such measurement exists" in marker
        assert doc, "the module docstring is part of the same contract"

    def test_the_one_load_figure_this_repo_has_recorded_is_over_the_bar(self) -> None:
        """3.96 on 8 CPUs, sampled on the author's Mac with two heavy apps running, in the same
        session where cold_launch read 0.3309s and 0.3762s against a 0.2968s baseline. That case
        — the only one this project has ever written down — must classify as loaded, or the bar
        is not doing the single job it was chosen for."""
        assert ps.is_quiet(_LOADED) is False
        assert ps.load_per_cpu(_LOADED) == pytest.approx(0.495)

    def test_load_per_cpu_divides_by_the_cores_that_exist(self) -> None:
        assert ps.load_per_cpu(_LOADED) == pytest.approx(3.96 / 8)

    def test_quiet_and_loaded_are_told_apart(self) -> None:
        assert ps.is_quiet(_QUIET) is True
        assert ps.is_quiet(_LOADED) is False

    def test_conditions_that_cannot_answer_say_unknown_rather_than_quiet(self) -> None:
        """Unknown must never collapse into "quiet" — that is how a gate starts flattering
        itself. Every degenerate shape answers None, and None disables qualification entirely
        rather than enabling it."""
        assert ps.is_quiet(None) is None
        assert ps.is_quiet({"source": "unavailable", "load_avg_1m_background": None}) is None
        assert ps.is_quiet({"source": "os.getloadavg", "cpu_count": 8}) is None
        assert ps.is_quiet({"source": "os.getloadavg", "load_avg_1m_background": 1.0}) is None
        assert (
            ps.is_quiet({"source": "os.getloadavg", "load_avg_1m_background": 1.0, "cpu_count": 0})
            is None
        )
        assert ps.load_per_cpu(None) is None

    def test_a_value_within_budget_under_load_is_still_a_pass(self) -> None:
        """Load can only inflate it, so an in-budget reading taken under load is a valid upper
        bound — the quiet number can only be better. Refusing to pass here would be superstition,
        not rigour."""
        report = ps.evaluate(_metrics(), None, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.MET
        assert report.ok

    def test_a_latency_budget_over_its_p50_under_load_is_inconclusive_not_over(self) -> None:
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.INCONCLUSIVE
        assert not report.failures, "an unusable measurement is not a proved failure"
        assert any("cold_launch" in i for i in report.inconclusive)

    def test_inconclusive_is_not_ok_so_the_gate_still_goes_red(self) -> None:
        """The exit code does NOT soften. Today a loaded cold_launch fails; after this change it
        still fails — with a message naming the real problem (re-measure) instead of one that
        invites re-baselining. Anything else would be v2 failure mode 2."""
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED)
        assert not report.ok

    def test_the_same_number_on_a_quiet_machine_is_a_plain_failure(self) -> None:
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_QUIET)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.OVER
        assert any("cold_launch" in f and "exceeds" in f for f in report.failures)
        assert not report.inconclusive

    def test_a_p95_over_budget_under_load_is_inconclusive_too(self) -> None:
        samples = {"cold_launch_s": [0.3, 0.35, 0.4, 0.45, 9.0]}
        report = ps.evaluate(_metrics(), samples, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p95_state == ps.INCONCLUSIVE
        assert not report.failures

    def test_a_regression_measured_under_load_is_inconclusive(self) -> None:
        """This is the live one: cold_launch 0.3309 against a 0.2968 baseline, +11.5%, taken
        while the machine was busy. It has been carried for three sessions as "probably load"."""
        report = ps.evaluate(
            _metrics(cold_launch_s=0.3309),
            None,
            {"cold_launch_s": 0.2968},
            conditions=_LOADED,
        )
        assert not report.failures
        assert any("regress" in i and "cold_launch" in i for i in report.inconclusive)
        assert not report.ok

    def test_the_same_regression_on_a_quiet_machine_is_a_real_failure(self) -> None:
        report = ps.evaluate(
            _metrics(cold_launch_s=0.3309),
            None,
            {"cold_launch_s": 0.2968},
            conditions=_QUIET,
        )
        assert any("regressed" in f for f in report.failures)

    def test_a_number_inside_the_regression_bar_under_load_is_not_flagged_at_all(self) -> None:
        """Under load the reading is an upper bound; an upper bound inside the bar proves there
        is no regression. Nothing to report."""
        report = ps.evaluate(
            _metrics(cold_launch_s=0.30),
            None,
            {"cold_launch_s": 0.2968},
            conditions=_LOADED,
        )
        assert report.ok
        assert not report.inconclusive

    def test_a_non_latency_budget_is_not_qualified_and_the_report_says_why(self) -> None:
        """Load does not simply inflate a memory figure, and it can FLATTER the sidecar's own
        idle CPU share by starving it. Neither direction is established here, so those two rows
        keep their plain verdict and the report states that they were not qualified — rather
        than silently extending an argument that only holds for latency."""
        report = ps.evaluate(_metrics(idle_rss_mb=999.0), None, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "idle_ram")
        assert row.p50_state == ps.OVER
        assert any("idle_ram" in f for f in report.failures)
        assert any("NOT qualified by the load argument" in n for n in report.notes)
        assert any("idle_ram" in n and "idle_cpu" in n for n in report.notes), (
            "the note must NAME the rows it is about, so it cannot go stale silently"
        )

    def test_exactly_which_budgets_carry_the_one_sided_argument(self) -> None:
        """Named, not counted — the set is the claim, and it may only grow when a row's metric
        is genuinely a latency."""
        assert {b.key for b in ps.BUDGETS if b.load_inflated} == {
            "cold_launch",
            "open_file",
            "keystroke",
            "completion",
            "search",
            "agent_first_token",
            "incremental_proof",
            "full_proof_10_files",
            "diff_render_500",
            "debugger_scrub",
        }

    def test_a_run_with_no_conditions_behaves_exactly_as_before_and_says_so(self) -> None:
        """No silent behaviour change for a bench.json written before this existed — but the
        report must not stay quiet about the fact that it cannot qualify anything."""
        before = ps.evaluate(_metrics(cold_launch_s=1.2), None, None)
        after = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=None)
        assert [r.p50_state for r in before.rows] == [r.p50_state for r in after.rows]
        assert before.failures == after.failures
        assert any("no machine conditions" in n for n in after.notes)

    def test_a_quiet_run_states_the_load_it_was_taken_under(self) -> None:
        report = ps.evaluate(_metrics(), None, None, conditions=_QUIET)
        assert any("0.05" in n and "quiet" in n for n in report.notes)

    def test_a_baseline_with_no_recorded_conditions_is_announced(self) -> None:
        """The committed baseline was taken before any of this existed. Comparing against a
        reference of unknown provenance is still worth doing — it is the project's recorded
        number — but the gate must not present it as a like-for-like comparison."""
        report = ps.evaluate(
            _metrics(), None, {"cold_launch_s": 0.2968}, baseline_meta={"cpu_count": 8}
        )
        assert any("unknown provenance" in n for n in report.notes)

    def test_a_baseline_from_a_different_machine_is_announced(self) -> None:
        """Eight cores against sixteen is not a regression, it is a different computer."""
        report = ps.evaluate(
            _metrics(),
            None,
            {"cold_launch_s": 0.2968},
            conditions=_QUIET,
            baseline_meta={"cpu_count": 16},
        )
        # Not `"16" in n and "8" in n` — that passes for the sentence with the two numbers
        # SWAPPED, which is the one thing this note exists to get right.
        assert any("measured on 16 CPUs, this run on 8" in n for n in report.notes)

    def test_an_inconclusive_row_is_never_counted_as_measured(self) -> None:
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED)
        assert report.measured == 2  # idle_ram and idle_cpu; cold_launch is inconclusive
        assert ps.INCONCLUSIVE in ps.render(report)

    def test_the_rendered_summary_counts_inconclusive_rows_separately(self) -> None:
        """Asserted against the ROWS line specifically.

        The first version of this test asserted `"1 INCONCLUSIVE" in rendered`, which the
        FINDINGS line satisfies on its own — so setting `inconclusive_rows = 0` left it green
        while the summary printed "0 INCONCLUSIVE rows". A guard written for a counting bug that
        cannot see the counting bug is worse than no guard, because it reads as coverage.
        """
        rendered = ps.render(
            ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED)
        )
        rows_line = next(ln for ln in rendered.splitlines() if "INCONCLUSIVE rows" in ln)
        assert "1 INCONCLUSIVE rows" in rows_line
        # and the other line is a different number's home, not a second copy of this one
        findings_line = next(ln for ln in rendered.splitlines() if "INCONCLUSIVE finding" in ln)
        assert findings_line != rows_line


class TestLoadQualificationThroughTheCli:
    def test_conditions_in_the_bench_file_are_read_and_applied(self, tmp_path: Path) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(
            json.dumps(
                {
                    "platform": "darwin",
                    "conditions": {
                        "source": "os.getloadavg",
                        "load_avg_1m_background": 3.96,
                        "cpu_count": 8,
                        "covers": _ENGINE_METRICS,
                    },
                    "metrics": _metrics(cold_launch_s=1.2),
                }
            )
        )
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 1

    def test_the_inconclusive_exit_names_the_measurement_not_the_code(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The operator-facing difference: "re-measure on a quiet machine", never "regressed"."""
        bench = tmp_path / "bench.json"
        bench.write_text(
            json.dumps(
                {
                    "platform": "darwin",
                    "conditions": {
                        "source": "os.getloadavg",
                        "load_avg_1m_background": 3.96,
                        "cpu_count": 8,
                        "covers": _ENGINE_METRICS,
                    },
                    "metrics": _metrics(cold_launch_s=1.2),
                }
            )
        )
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 1
        err = capsys.readouterr().err
        assert "INCONCLUSIVE" in err
        assert "re-measure on a quiet machine" in err
        # The point of the whole message: it must NOT say "regressed". That word is what makes
        # re-baselining look like the repair, and re-baselining is forbidden. Asserting only the
        # presence of "quiet" left the forbidden wording free to come back.
        assert "regressed" not in err

    def test_a_malformed_conditions_block_is_ignored_rather_than_fatal(
        self, tmp_path: Path
    ) -> None:
        bench = tmp_path / "bench.json"
        bench.write_text(
            json.dumps({"platform": "darwin", "metrics": _metrics(), "conditions": "not a dict"})
        )
        assert ps.main(["--enforce-budgets", "--bench", str(bench)]) == 0

    def test_the_baseline_document_is_passed_through_for_provenance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "bench.json").write_text(
            json.dumps({"platform": "darwin", "metrics": _metrics()})
        )
        # The baseline matches, so nothing trips the bar — this test is about the NOTE, and a
        # regression failure here would let it pass for the wrong reason.
        (tmp_path / "baseline-darwin.json").write_text(
            json.dumps({"cpu_count": 8, "metrics": {"cold_launch_s": 0.34}})
        )
        assert ps.main(["--enforce-budgets", "--bench", str(tmp_path / "bench.json")]) == 0
        assert "unknown provenance" in capsys.readouterr().out


class TestTheSummaryCountsWhatTheGateIsActuallyHolding:
    """Found by breaking the gate on purpose (trap 47), not by reading it.

    `cold_launch` at 0.3309s is comfortably inside its 0.8s p50 budget, so its ROW is MET. The
    same number is 11.5% over the committed baseline, and under load that comparison is unusable.
    The first version of this summary counted only rows whose STATE was inconclusive, and so
    printed `0 INCONCLUSIVE` in the very run it was failing for — a gate reporting green about
    something it never looked at, which is the exact shape it exists to prevent.
    """

    def test_a_met_row_can_still_carry_an_unusable_regression(self) -> None:
        report = ps.evaluate(
            _metrics(cold_launch_s=0.3309),
            None,
            {"cold_launch_s": 0.2968},
            conditions=_LOADED,
        )
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.MET, "0.3309s is inside the 0.8s budget"
        assert len(report.inconclusive) == 1, "and yet the run is not usable"
        assert not report.ok

    def test_the_summary_does_not_print_zero_while_holding_a_finding(self) -> None:
        rendered = ps.render(
            ps.evaluate(
                _metrics(cold_launch_s=0.3309),
                None,
                {"cold_launch_s": 0.2968},
                conditions=_LOADED,
            )
        )
        assert "0 INCONCLUSIVE finding" not in rendered
        assert "1 INCONCLUSIVE finding" in rendered

    def test_the_printed_row_counts_partition_the_table(self) -> None:
        """Parsed out of `render()`, in the one input shape where they used to sum to 14.

        The first version of this test tallied `p50_state` itself and never called `render()` —
        structurally true for any implementation, including the one that printed 14 of 13. The
        state that exposes it needs a row whose p50 is MET while its p95 is INCONCLUSIVE, which
        needs raw samples; `cold_launch_s=1.2` with no samples can never reach it.
        """
        # p50 0.34 is inside the 0.8 budget; the p95 of these samples is 9.0, which is not.
        report = ps.evaluate(
            _metrics(),
            {"cold_launch_s": [0.30, 0.31, 0.32, 0.33, 9.0]},
            None,
            conditions=_LOADED,
        )
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert (row.p50_state, row.p95_state) == (ps.MET, ps.INCONCLUSIVE), "the shape under test"

        rows_line = next(ln for ln in ps.render(report).splitlines() if "INCONCLUSIVE rows" in ln)
        counts = [
            int(n)
            for n in re.findall(
                r"(\d+) (?:of 13|armed|NOT-YET-MEA|INCONCLUSIVE r)",
                rows_line.replace("NOT-YET-MEASURABLE", "NOT-YET-MEA"),
            )
        ]
        assert sum(counts) == len(ps.BUDGETS) == 13, f"printed counts {counts} do not partition"

    def test_a_p95_made_unusable_by_load_is_still_reported_somewhere(self) -> None:
        """Counting rows on p50 alone must not make a p95 disappear — it moves to the findings
        line and the table, and the gate still fails."""
        report = ps.evaluate(
            _metrics(),
            {"cold_launch_s": [0.30, 0.31, 0.32, 0.33, 9.0]},
            None,
            conditions=_LOADED,
        )
        assert not report.ok
        assert any("p95" in i for i in report.inconclusive)
        assert "1 INCONCLUSIVE finding" in ps.render(report)

    def test_a_clean_quiet_run_reports_zero_findings_honestly(self) -> None:
        rendered = ps.render(ps.evaluate(_metrics(), None, None, conditions=_QUIET))
        assert "0 INCONCLUSIVE finding" in rendered


class TestTheStatesTheFirstReviewFoundUnpinned:
    """Every test here exists because a review named a one-line mutation nothing would catch.

    The lesson is trap 43's: line coverage said these lines ran. It could not say which STATES
    were considered, and each of these was a state nobody had.
    """

    def test_the_quiet_bar_is_inclusive_and_the_note_says_so(self) -> None:
        """`<=` vs `<` at exactly the bar. Changing it flips a run's verdict while the printed
        note goes on claiming "at or under the bar" — a threshold whose inclusiveness is the one
        thing about a threshold worth pinning, and the one thing that was not pinned."""
        exactly = {
            "source": "os.getloadavg",
            "load_avg_1m_background": ps.QUIET_LOAD_PER_CPU * 8,
            "cpu_count": 8,
        }
        assert ps.load_per_cpu(exactly) == pytest.approx(ps.QUIET_LOAD_PER_CPU)
        assert ps.is_quiet(exactly) is True, "a run exactly ON the bar is quiet"
        report = ps.evaluate(_metrics(), None, None, conditions=exactly)
        assert any("at or under" in n for n in report.notes)
        # and one hair over is not
        over = dict(exactly, load_avg_1m_background=ps.QUIET_LOAD_PER_CPU * 8 + 0.001)
        assert ps.is_quiet(over) is False

    def test_a_boolean_is_not_a_load_average(self) -> None:
        """`True` is an `int` in Python. Without the explicit bool guard a bench.json carrying
        `"load_avg_1m_background": true` computes 1/8 = 0.125/cpu and is judged QUIET — the exact
        direction `load_per_cpu`'s own docstring forbids. The guard shares a line with the numeric
        check, so line coverage cannot see its absence."""
        assert (
            ps.load_per_cpu(
                {"source": "os.getloadavg", "load_avg_1m_background": True, "cpu_count": 8}
            )
            is None
        )
        assert (
            ps.load_per_cpu(
                {"source": "os.getloadavg", "load_avg_1m_background": 1.0, "cpu_count": True}
            )
            is None
        )
        assert (
            ps.is_quiet({"source": "os.getloadavg", "load_avg_1m_background": True, "cpu_count": 8})
            is None
        )

    def test_a_baseline_that_DOES_record_conditions_is_not_warned_about(self) -> None:
        """The suppression side of the provenance branch — the behaviour that is supposed to
        change the day someone re-baselines on a quiet machine. Nothing pinned it, so replacing
        the guard with `if True:` left every test green and the warning permanent."""
        with_conditions = {
            "cpu_count": 8,
            "conditions": {
                "source": "os.getloadavg",
                "load_avg_1m_background": 0.4,
                "cpu_count": 8,
            },
        }
        report = ps.evaluate(
            _metrics(), None, {"cold_launch_s": 0.34}, baseline_meta=with_conditions
        )
        assert not any("unknown provenance" in n for n in report.notes)
        # and the negative control: the same call without them still warns
        without = ps.evaluate(_metrics(), None, {"cold_launch_s": 0.34}, baseline_meta={})
        assert any("unknown provenance" in n for n in without.notes)


class TestTheLoadSampleOnlySpeaksForWhatItMeasured:
    """`covers` — the fix for a real defect: the editor budgets were being qualified by a load
    average sampled in a different process, minutes to days before their Playwright run.
    """

    def test_the_fixture_matches_what_bench_actually_records(self) -> None:
        """If `bench.MEASURED_IN_PROCESS` gains or loses a metric, these tests must not keep
        asserting against a list that no longer describes the producer."""
        from tempest.dev.bench import MEASURED_IN_PROCESS

        assert set(_ENGINE_METRICS) == set(MEASURED_IN_PROCESS)

    def test_a_covered_duration_is_qualified(self) -> None:
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.INCONCLUSIVE

    def test_an_UNCOVERED_duration_keeps_its_plain_verdict(self) -> None:
        """`open_file_ms` comes from `make bench-editor`, which this sample never watched. A miss
        there is a real miss until someone measures the conditions of THAT run."""
        report = ps.evaluate(_metrics(open_file_ms=999.0), None, None, conditions=_LOADED)
        row = next(r for r in report.rows if r.budget.key == "open_file")
        assert row.p50_state == ps.OVER, "not excused by a load sample that never saw it"
        assert any("open_file" in f and "exceeds" in f for f in report.failures)
        assert any("does not COVER" in n for n in report.notes)

    def test_a_block_with_no_covers_key_qualifies_nothing(self) -> None:
        """Conservative by construction: a conditions block written before `covers` existed
        covers nothing, so qualification simply does not engage — the same direction as
        `is_quiet`'s unknown."""
        assert ps.covered_metrics(_LOADED_NO_COVERS) == frozenset()
        report = ps.evaluate(_metrics(cold_launch_s=1.2), None, None, conditions=_LOADED_NO_COVERS)
        row = next(r for r in report.rows if r.budget.key == "cold_launch")
        assert row.p50_state == ps.OVER

    def test_a_malformed_covers_value_is_not_trusted(self) -> None:
        for bad in ("cold_launch_s", 7, {"cold_launch_s": True}, None):
            assert ps.covered_metrics(dict(_LOADED_NO_COVERS, covers=bad)) == frozenset()
        # non-string entries are dropped, the rest survive
        assert ps.covered_metrics(dict(_LOADED, covers=["cold_launch_s", 3, None])) == frozenset(
            {"cold_launch_s"}
        )

    def test_the_note_naming_uncovered_rows_is_derived_not_hand_listed(self) -> None:
        """A note that hard-codes row names goes stale the day a flag changes, and a stale note
        in a gate's own output is the failure this module refuses. Cover everything and the note
        must disappear."""
        everything = dict(
            _LOADED, covers=[b.metric for b in ps.BUDGETS if b.metric and b.load_inflated]
        )
        report = ps.evaluate(_metrics(), None, None, conditions=everything)
        assert not any("does not COVER" in n for n in report.notes)
