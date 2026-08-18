"""Watch mode in the app (ADR-0029) — a REAL repo, REAL commits, the REAL prove pipeline.

The claim under test is the design claim: a watched commit becomes an ORDINARY run. So the
assertions here are deliberately about the run rows, the ledger, and the run list — if watch
ever grew a private notion of a verdict, these would still pass while the product lied, so
they check the shared evidence instead.

L11 is pinned too: Stop is immediate (an in-flight prove is cancelled, not awaited), and a
repo that disappears stops the session with the reason recorded rather than spinning.
"""

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from tempest_api.watchsession import stop_watch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def _repo(tmp_path: Path, name: str = "watched") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "one", "--no-gpg-sign")
    return repo


def _commit_change(repo: Path, body: str) -> None:
    (repo / "core.py").write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "change", "--no-gpg-sign")


@pytest.fixture(autouse=True)
def _always_stop(api: Any) -> Any:
    """No test may leave a loop running — a stray watch thread would prove other tests' repos."""
    yield
    from tempest_api.db.session import database_url

    stop_watch(database_url())


def _status(api: Any) -> dict[str, Any]:
    return api.get_json("/v1/local/watch")


def _wait_for(api: Any, predicate: Any, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = _status(api)
        if predicate(status):
            return status
        time.sleep(0.2)
    raise AssertionError(f"watch status never satisfied the predicate — last: {status}")


class TestTheFeedIsTheLedger:
    """The proven-commit feed is a QUERY over the runs a watch session marked, not a list the
    session holds — so it survives a restart and can never disagree with the run list."""

    def test_a_marked_run_appears_in_the_feed_with_its_real_evidence(
        self, api: Any, tmp_path: Path
    ) -> None:
        from tempest_api.db.session import database_url
        from tempest_api.watchsession import create_watch_run

        # A run created exactly the way the loop creates one — same function, no mocks.
        repo = _repo(tmp_path)
        run_id = create_watch_run(repo, "a" * 40, "b" * 40, 4, database_url())

        feed = _status(api)["runs"]
        assert [entry["run_id"] for entry in feed] == [run_id]
        assert feed[0]["head_sha"] == "b" * 40
        assert feed[0]["status"] == "PENDING"
        assert feed[0]["verdict"] is None
        assert feed[0]["divergence_count"] == 0

    def test_runs_that_watch_did_not_produce_stay_out_of_the_feed(
        self, api: Any, tmp_path: Path
    ) -> None:
        api.ingest(api.make_bundle())  # an ordinary uploaded run
        assert _status(api)["runs"] == []

    def test_the_feed_counts_divergences_and_is_newest_first(
        self, api: Any, tmp_path: Path
    ) -> None:
        from tempest_api.db.session import database_url
        from tempest_api.watchsession import create_watch_run

        repo = _repo(tmp_path)
        older = create_watch_run(repo, "a" * 40, "b" * 40, 4, database_url())
        newer = create_watch_run(repo, "b" * 40, "c" * 40, 4, database_url())
        assert [e["run_id"] for e in _status(api)["runs"]] == [newer, older]


class TestIdle:
    def test_nothing_is_watched_until_asked(self, api: Any) -> None:
        assert _status(api) == {
            "watching": False,
            "repo_path": None,
            "repo_name": None,
            "interval_seconds": 0.0,
            "last_sha": None,
            "active_run_id": None,
            "runs": [],
            "problem": None,
        }

    def test_stopping_an_idle_session_is_a_no_op(self, api: Any) -> None:
        resp = api.client.delete("/v1/local/watch")
        assert resp.status_code == 200
        assert resp.json()["watching"] is False


class TestValidation:
    def test_a_path_that_is_not_a_repo_is_refused_before_anything_starts(self, api: Any) -> None:
        resp = api.client.post("/v1/local/watch", json={"repo_path": "/definitely/not/a/repo"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"
        assert _status(api)["watching"] is False

    def test_watching_twice_is_refused_with_the_running_repo_named(
        self, api: Any, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path)
        assert api.client.post("/v1/local/watch", json={"repo_path": str(repo)}).status_code == 200
        second = api.client.post("/v1/local/watch", json={"repo_path": str(repo)})
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "WATCH_ALREADY_ACTIVE"
        assert str(repo) in second.json()["error"]["message"]

    def test_an_absurdly_fast_interval_is_refused(self, api: Any, tmp_path: Path) -> None:
        resp = api.client.post(
            "/v1/local/watch", json={"repo_path": str(_repo(tmp_path)), "interval_seconds": 0.01}
        )
        assert resp.status_code == 422
        assert _status(api)["watching"] is False


class TestArming:
    def test_arming_records_the_repo_and_the_commit_it_starts_from(
        self, api: Any, tmp_path: Path
    ) -> None:
        repo = _repo(tmp_path)
        resp = api.client.post(
            "/v1/local/watch",
            json={"repo_path": str(repo), "interval_seconds": 1.0, "max_inputs": 4},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["watching"] is True
        assert body["repo_path"] == str(repo)
        assert body["repo_name"] == "watched"
        assert body["interval_seconds"] == 1.0
        assert len(body["last_sha"]) == 40
        assert body["runs"] == []  # watch proves what happens NEXT

    def test_stopping_disarms_and_the_state_says_so(self, api: Any, tmp_path: Path) -> None:
        api.client.post("/v1/local/watch", json={"repo_path": str(_repo(tmp_path))})
        assert api.client.delete("/v1/local/watch").json()["watching"] is False
        assert _status(api)["watching"] is False
        # …and re-arming (on a different repo) is allowed — stop really released the session.
        again = api.client.post(
            "/v1/local/watch", json={"repo_path": str(_repo(tmp_path, "second"))}
        )
        assert again.status_code == 200, again.text
        assert again.json()["repo_name"] == "second"


class TestTheContinuousAgent:
    def test_a_new_commit_becomes_an_ordinary_proven_run(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
        repo = _repo(tmp_path)
        started = api.client.post(
            "/v1/local/watch",
            json={"repo_path": str(repo), "interval_seconds": 1.0, "max_inputs": 4},
        ).json()

        _commit_change(repo, "def double(x: int) -> int:\n    return x * 2 + 1\n")

        status = _wait_for(
            api,
            lambda s: s["runs"] and s["runs"][0]["status"] == "COMPLETE",
        )
        entry = status["runs"][0]
        assert entry["verdict"] == "DIVERGENT"
        assert entry["divergence_count"] >= 1
        assert entry["head_sha"] != started["last_sha"]
        assert status["last_sha"] == entry["head_sha"]  # the next commit proves from here

        # The design claim: it is an ORDINARY run — same list, same detail, same evidence.
        listed = api.get_json("/v1/runs")["items"]
        assert [r["id"] for r in listed] == [entry["run_id"]]
        detail = api.get_json(f"/v1/runs/{entry['run_id']}")
        assert detail["verdict"] == "DIVERGENT"
        assert [t["qualname"] for t in detail["targets"]] == ["double"]
        stages = [e["stage"] for e in api.get_json(f"/v1/runs/{entry['run_id']}/events")]
        assert stages[0] == "started" and stages[-1] == "complete"

    def test_a_repo_that_disappears_stops_the_session_with_the_reason(
        self, api: Any, tmp_path: Path
    ) -> None:
        import shutil

        repo = _repo(tmp_path)
        api.client.post("/v1/local/watch", json={"repo_path": str(repo), "interval_seconds": 1.0})
        shutil.rmtree(repo)
        status = _wait_for(api, lambda s: s["problem"] is not None, timeout=30.0)
        assert status["watching"] is False
        assert "cannot read HEAD" in status["problem"]


class TestTheLoopSurvivesRealFailures:
    """No mocks (L4): the failure is made real by handing the session a store it genuinely
    cannot write to, so the run row creation fails for the same reason a broken disk would."""

    def test_a_store_that_cannot_be_written_stops_the_session_with_the_reason(
        self, api: Any, tmp_path: Path
    ) -> None:
        from tempest_api.watchsession import start_watch, stop_watch, watch_state

        repo = _repo(tmp_path, "unwritable")
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory\n")
        broken_url = f"sqlite+aiosqlite:///{blocker}/nowhere.db"
        try:
            start_watch(
                repo_path=str(repo),
                interval_seconds=1.0,
                max_inputs=4,
                database_url=broken_url,
            )
            _commit_change(repo, "def double(x: int) -> int:\n    return x * 3\n")
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                state = watch_state(broken_url)
                if state.problem is not None:
                    break
                time.sleep(0.2)
            assert state.problem is not None, "a store that cannot be written must be reported"
            assert "could not start a run" in state.problem
            assert state.watching is False
        finally:
            stop_watch(broken_url)


class TestL11:
    def test_stop_is_immediate_even_while_the_machine_is_paused(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real forced pause (the same switch the engine's own pause tests use): the loop is
        blocked inside the hold, and Stop must still return it — never "stop when unplugged"."""
        monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "on battery power")
        repo = _repo(tmp_path, "paused")
        assert (
            api.client.post(
                "/v1/local/watch", json={"repo_path": str(repo), "interval_seconds": 1.0}
            ).status_code
            == 200
        )
        time.sleep(0.3)  # let the loop reach the hold
        assert api.client.delete("/v1/local/watch").json()["watching"] is False

        from tempest_api.db.session import database_url
        from tempest_api.watchsession import _session

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            thread = _session(database_url())._thread
            if thread is not None and not thread.is_alive():
                return
            time.sleep(0.05)
        raise AssertionError("the watch thread did not leave the pause hold after Stop")

    def test_an_interval_below_the_floor_is_refused_at_the_source(self, tmp_path: Path) -> None:
        """The HTTP layer bounds it too, but the engine-side floor is the real one — a caller
        that reaches `start_watch` directly must not be able to busy-poll a repository."""
        from tempest_api.watchsession import WatchError, start_watch

        with pytest.raises(WatchError) as err:
            start_watch(
                repo_path=str(_repo(tmp_path, "toofast")),
                interval_seconds=0.05,
                max_inputs=4,
                database_url="sqlite+aiosqlite:///unused-because-it-never-arms.db",
            )
        assert "at least 1s" in str(err.value)

    def test_stop_cancels_the_prove_that_is_in_flight(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop must not mean "after this commit finishes" — the running prove is cancelled and
        lands in the honest terminal state CANCELLED (never a verdict, L2/L11)."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
        repo = _repo(tmp_path, "cancelme")
        api.client.post(
            "/v1/local/watch",
            json={"repo_path": str(repo), "interval_seconds": 1.0, "max_inputs": 300},
        )
        _commit_change(repo, "def double(x: int) -> int:\n    return x * 2 + 1\n")
        live = _wait_for(api, lambda s: s["active_run_id"] is not None, timeout=60.0)
        run_id = live["active_run_id"]

        assert api.client.delete("/v1/local/watch").json()["watching"] is False

        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            status = api.get_json(f"/v1/runs/{run_id}")["status"]
            if status != "PENDING":
                assert status == "CANCELLED", "a stopped prove is CANCELLED, never a verdict"
                return
            time.sleep(0.2)
        raise AssertionError(f"run {run_id} never left PENDING after Stop")
