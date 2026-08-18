"""`POST /v1/local/demo` — onboarding's first divergence (Phase 18, HANDOFF-WORLD-CLASS 2.6).

One click, zero setup: the engine writes its own tiny demo repository (first-party marker,
one seeded behavior change) into the data dir and proves it through the ORDINARY local-prove
machinery — the run that appears is a real run with real evidence and a real repro, not a
canned tour. The activation bar is <90 s to a visible divergence; here the whole round trip
runs under the suite's timeout with a real process sandbox.
"""

import time
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _dev_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))


def _poll_complete(api: Any, run_id: int, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        run = api.get_json(f"/v1/runs/{run_id}")
        if run["status"] == "COMPLETE":
            return run
        time.sleep(0.2)
    raise AssertionError(f"demo run {run_id} still {run.get('status')} after {timeout}s")


class TestTheDemo:
    def test_one_post_reaches_a_divergent_run_with_a_repro(self, api: Any, tmp_path: Path) -> None:
        started = time.monotonic()
        resp = api.client.post("/v1/local/demo")
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]

        run = _poll_complete(api, run_id)
        elapsed = time.monotonic() - started
        assert elapsed < 90.0, f"first divergence took {elapsed:.1f}s — the activation bar is 90"
        assert run["verdict"] == "DIVERGENT"
        assert run["divergence_count"] >= 1

        # Real evidence chain: target → divergence → downloadable repro (L1/L7).
        # The demo teaches the vocabulary: the rounding "cleanup" diverges, the honest
        # label refactor is EQUIVALENT_UNDER_BUDGET — both verdicts on one screen.
        by_verdict = {t["qualname"]: t["verdict"] for t in run["targets"]}
        assert by_verdict["final_price"] == "DIVERGENT"
        assert by_verdict["shelf_label"] == "EQUIVALENT_UNDER_BUDGET"
        divergent = [t for t in run["targets"] if t["verdict"] == "DIVERGENT"]
        target = api.get_json(f"/v1/targets/{divergent[0]['id']}")
        d_id = target["divergences"][0]["id"]
        repro = api.client.get(f"/v1/divergences/{d_id}/repro.py")
        assert repro.status_code == 200
        assert "Tempest minimized reproduction" in repro.text
        assert "final_price" in repro.text  # the seeded rounding change is the divergence

        # The demo repo is REAL and inspectable, inside the data dir — named in the ledger.
        events = api.get_json(f"/v1/runs/{run_id}/events")
        assert any("demo" in e["message"].lower() for e in events)
        demo_repos = list((tmp_path / "appdata" / "demo").glob("*/tempest-demo"))
        assert len(demo_repos) == 1
        assert (demo_repos[0] / ".tempest-first-party").exists()

    def test_running_the_demo_twice_gives_two_independent_runs(self, api: Any) -> None:
        first = api.client.post("/v1/local/demo").json()["run_id"]
        _poll_complete(api, first)
        second = api.client.post("/v1/local/demo").json()["run_id"]
        assert second != first
        _poll_complete(api, second)
        listed = api.get_json("/v1/runs")["items"]
        assert {r["id"] for r in listed} == {first, second}
