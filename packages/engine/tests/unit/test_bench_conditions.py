"""The conditions a benchmark was taken under, recorded as facts rather than assumed.

**Why this exists.** `bench.json` and `bench/baseline-darwin.json` are two numbers compared by
`perf_suite` as though they were taken under the same conditions, and nothing anywhere recorded
what those conditions were. That is why "is cold_launch drift or is it load?" has been carried
across three sessions as an unresolvable question: the data needed to settle it was never
captured. A ruler that cannot see its own error bars is trap 47's shape.

**The split, deliberately.** `bench` records FACTS (how many CPUs, what the load average was);
`perf_suite` owns the JUDGEMENT (what counts as quiet). A gate owns its ruler — otherwise
changing the bar means re-taking every measurement, and a measurement file would carry a verdict
that its own author chose.

States enumerated before the tests (trap 43): load average available · **absent** (Windows:
CPython defines `getloadavg` only under `HAVE_GETLOADAVG`, so the attribute does not exist and the
lookup raises `AttributeError`) · **present but failing** (`OSError`) · `os.cpu_count()` answering
`None` · the background sample (before any bench work) vs the final sample (which necessarily
includes the bench's OWN seeding and is therefore recorded but never judged on).

The first two of those were one state in an earlier draft — this file's own enumeration said
"raises `OSError` where it is not implemented", which is false, and the code caught only `OSError`
to match. A missing attribute raises `AttributeError`, which is not an `OSError` subclass, so the
one platform the branch existed for would have crashed `make bench` at its first statement. A
mutation run found it: reverting the fix left every test green until the test below was written.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.dev import bench

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _is_committed(path: Path) -> bool:
    """True when `path` is in the committed tree — a fresh checkout would contain it (trap 44)."""
    rel = path.relative_to(_REPO_ROOT).as_posix()
    return (
        subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "cat-file", "-e", f"HEAD:{rel}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


class TestTheFactsAreRecorded:
    def test_a_working_load_average_is_recorded_with_its_source(self) -> None:
        conditions = bench.machine_conditions()
        assert conditions["source"] == "os.getloadavg"
        assert isinstance(conditions["load_avg_1m"], float)
        assert conditions["load_avg_1m"] >= 0.0

    def test_the_cpu_count_rides_along_because_load_alone_means_nothing(self) -> None:
        """A load average of 4 is idle on 32 cores and saturated on 2 — the count is half
        the fact, and a number recorded without it cannot be judged later."""
        conditions = bench.machine_conditions()
        assert conditions["cpu_count"] == os.cpu_count()

    def test_an_unavailable_load_average_records_why_rather_than_a_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fabricated 0.0 would read as a perfectly idle machine — the most flattering lie
        available, and exactly the failure mode this module exists to prevent."""

        def _boom() -> tuple[float, float, float]:
            raise OSError("not implemented on this platform")

        monkeypatch.setattr(bench.os, "getloadavg", _boom)
        conditions = bench.machine_conditions()
        assert conditions["source"] == "unavailable"
        assert "not implemented" in conditions["reason"]
        assert conditions["load_avg_1m"] is None

    def test_an_ABSENT_load_average_is_caught_too_not_only_a_failing_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Windows shape: the symbol does not exist at all.

        `AttributeError` is not a subclass of `OSError`, so this state and the one above are two
        different exceptions and a handler for one does not cover the other. Deleting the
        attribute is the honest reproduction — the earlier test replaced it with a function that
        raised `OSError`, which tests a platform that does not exist.
        """
        monkeypatch.delattr(bench.os, "getloadavg", raising=False)
        conditions = bench.machine_conditions()
        assert conditions["source"] == "unavailable"
        assert conditions["load_avg_1m"] is None
        assert "AttributeError" in conditions["reason"], "the reason names WHICH failure it was"
        assert conditions["cpu_count"] == os.cpu_count(), "still records what it does know"

    def test_the_two_failure_modes_are_told_apart_in_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both degrade to `unavailable`, and a reader must be able to tell which happened —
        an absent symbol is a platform fact, a raising one is a machine fault."""

        def _boom() -> tuple[float, float, float]:
            raise OSError("temporarily unavailable")

        monkeypatch.setattr(bench.os, "getloadavg", _boom)
        assert "OSError" in bench.machine_conditions()["reason"]
        monkeypatch.delattr(bench.os, "getloadavg", raising=False)
        assert "AttributeError" in bench.machine_conditions()["reason"]

    def test_an_unknown_cpu_count_is_null_not_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`os.cpu_count()` may answer None. Defaulting to 1 would divide load by 1 and call a
        quiet 32-core machine saturated."""
        monkeypatch.setattr(bench.os, "cpu_count", lambda: None)
        assert bench.machine_conditions()["cpu_count"] is None


class TestTheBackgroundSampleIsTheOnlyHonestOne:
    def test_both_samples_are_carried_and_only_one_is_named_background(self) -> None:
        """The final sample includes the bench's own 10,000-run seeding, so it cannot tell
        foreign load from our own work. It is recorded for the reader and never judged on."""
        payload = bench.conditions_block(
            background={"source": "os.getloadavg", "load_avg_1m": 0.4, "cpu_count": 8},
            final={"source": "os.getloadavg", "load_avg_1m": 6.2, "cpu_count": 8},
        )
        assert payload["load_avg_1m_background"] == 0.4
        assert payload["load_avg_1m_final"] == 6.2
        assert payload["cpu_count"] == 8
        assert payload["source"] == "os.getloadavg"

    def test_the_block_says_out_loud_which_sample_the_gate_may_use(self) -> None:
        payload = bench.conditions_block(
            background={"source": "os.getloadavg", "load_avg_1m": 0.4, "cpu_count": 8},
            final={"source": "os.getloadavg", "load_avg_1m": 6.2, "cpu_count": 8},
        )
        assert "background" in payload["judged_on"]
        assert "seed" in payload["note"] or "own" in payload["note"]

    def test_an_unavailable_background_sample_propagates_its_reason(self) -> None:
        payload = bench.conditions_block(
            background={"source": "unavailable", "reason": "no getloadavg", "load_avg_1m": None},
            final={"source": "unavailable", "reason": "no getloadavg", "load_avg_1m": None},
        )
        assert payload["source"] == "unavailable"
        assert payload["reason"] == "no getloadavg"
        assert payload["load_avg_1m_background"] is None

    def test_a_background_sample_that_worked_wins_over_a_final_one_that_did_not(self) -> None:
        """Whatever the final sample did, the judgement is about the background one."""
        payload = bench.conditions_block(
            background={"source": "os.getloadavg", "load_avg_1m": 0.4, "cpu_count": 8},
            final={"source": "unavailable", "reason": "vanished", "load_avg_1m": None},
        )
        assert payload["source"] == "os.getloadavg"
        assert payload["load_avg_1m_background"] == 0.4
        assert payload["load_avg_1m_final"] is None


class TestTheBlockIsJsonSerialisable:
    def test_it_round_trips_through_json_unchanged(self) -> None:
        """It is written into `bench.json`; a value json cannot encode would kill `make bench`
        after the measurement had already been taken."""
        payload = bench.conditions_block(
            background=bench.machine_conditions(), final=bench.machine_conditions()
        )
        assert json.loads(json.dumps(payload)) == payload


class TestTheCommittedBaselinePredatesThis:
    def test_the_shipped_baseline_has_no_conditions_and_that_is_stated_not_hidden(self) -> None:
        """`bench/baseline-darwin.json` was measured before conditions were recorded at all.

        This is asserted rather than assumed because the whole point of the feature is that a
        comparison against a reference of unknown provenance must SAY so. The day someone
        re-baselines on a quiet machine this test changes to assert the opposite, and the change
        is the record that the provenance gap closed.
        """
        baseline = _REPO_ROOT / "bench" / "baseline-darwin.json"
        assert _is_committed(baseline), "the baseline must be in HEAD, not merely on disk"
        doc: Any = json.loads(baseline.read_text(encoding="utf-8"))
        assert "conditions" not in doc
