"""`POST /v1/local/prove` end to end — REAL execution, no mocks (Law L4): a real git repo,
the real engine prove pipeline on a background thread, ingested through the real upload path.

The happy path uses the first-party fixture marker + TEMPEST_DEV=1 (ADR-0008) so ProcessSandbox
may run it. The no-marker path pins TEMPEST_DOCKER at a nonexistent binary so the run lands on
the honest all-UNPROVEN(SANDBOX_UNAVAILABLE) outcome everywhere — Docker-equipped CI included.
"""

import asyncio
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import tempest_api.localprove as localprove


def _micro_repo(tmp_path: Path, *, marker: bool) -> Path:
    """A tiny two-commit repo (branches `base` and `head`) with one pure behavior change."""
    repo = tmp_path / "micro"
    repo.mkdir()

    def git(*args: str) -> None:
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

    git("init", "-b", "main")
    if marker:
        (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


def _start_prove(api: Any, repo: Path, *, base: str = "base", head: str = "head") -> int:
    resp = api.client.post(
        "/v1/local/prove",
        json={"repo_path": str(repo), "base": base, "head": head, "max_inputs": 6},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    assert isinstance(run_id, int)
    return run_id


def _poll_until_complete(api: Any, run_id: int, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    run: dict[str, Any] = {}
    while time.monotonic() < deadline:
        run = api.get_json(f"/v1/runs/{run_id}")
        if run["status"] == "COMPLETE":
            return run
        time.sleep(0.2)
    events = api.get_json(f"/v1/runs/{run_id}/events")
    raise AssertionError(
        f"run {run_id} still {run.get('status')} after {timeout}s — events so far: {events}"
    )


def _stages(api: Any, run_id: int) -> list[str]:
    events = api.get_json(f"/v1/runs/{run_id}/events")
    for event in events:
        assert event["ts"], event
        assert event["message"], event
        assert event["level"] in {"info", "error"}, event
    return [event["stage"] for event in events]


class TestLocalProveHappyPath:
    def test_divergent_run_end_to_end(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _micro_repo(tmp_path, marker=True)
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))

        run_id = _start_prove(api, repo)
        assert api.get_json(f"/v1/runs/{run_id}")["repo"] == "micro"

        run = _poll_until_complete(api, run_id)
        assert run["verdict"] == "DIVERGENT"
        assert len(run["base_sha"]) == len(run["head_sha"]) == 40
        assert run["base_sha"] != run["head_sha"]
        assert run["engine_version"] is not None  # manifest ingested verbatim

        # The target and its evidence are served, not just counted (Law L1).
        assert [t["qualname"] for t in run["targets"]] == ["double"]
        target_summary = run["targets"][0]
        assert target_summary["verdict"] == "DIVERGENT"
        assert target_summary["divergence_count"] >= 1
        assert run["divergence_count"] >= 1
        target = api.get_json(f"/v1/targets/{target_summary['id']}")
        assert target["divergences"]
        assert target["divergences"][0]["minimized_args"]

        # The bundle artifact landed under the app data dir (Law L7).
        out_root = tmp_path / "appdata" / "local-runs"
        assert (out_root / f"run-{run_id}" / "manifest.json").is_file()
        assert list(out_root.glob("*.tempest.zip"))

        # The polled ledger shows the whole lifecycle, in order, with no error stage.
        stages = _stages(api, run_id)
        assert stages[0] == "started"
        assert stages[-1] == "complete"
        assert (
            stages.index("started")
            < stages.index("proving")
            < stages.index("ingesting")
            < stages.index("ingested")
            < stages.index("complete")
        )
        assert "error" not in stages


class TestLocalProveValidation:
    def test_nonexistent_path_is_repo_not_found(self, api: Any) -> None:
        resp = api.client.post(
            "/v1/local/prove",
            json={"repo_path": "/definitely/not/a/repo/anywhere", "base": "a", "head": "b"},
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"
        assert api.get_json("/v1/runs")["items"] == []  # rejected before any row was written

    def test_non_git_directory_is_repo_not_found(self, api: Any, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        resp = api.client.post(
            "/v1/local/prove", json={"repo_path": str(plain), "base": "a", "head": "b"}
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "REPO_NOT_FOUND"

    def test_unresolvable_ref_is_ref_not_found(self, api: Any, tmp_path: Path) -> None:
        repo = _micro_repo(tmp_path, marker=True)
        resp = api.client.post(
            "/v1/local/prove",
            json={"repo_path": str(repo), "base": "no-such-branch", "head": "head"},
        )
        assert resp.status_code == 400, resp.text
        error = resp.json()["error"]
        assert error["code"] == "REF_NOT_FOUND"
        assert error["details"]["which"] == "base"
        assert api.get_json("/v1/runs")["items"] == []


class TestLocalProveHonestPath:
    def test_unsandboxable_repo_is_all_unproven_not_an_error(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No marker file + no sandbox tier at all → the engine refuses to execute (Law L6) and
        reports UNPROVEN(SANDBOX_UNAVAILABLE) per target. That is the CORRECT outcome — the run
        completes, blesses nothing, and the ledger ends in `complete`, not `error`. Both tiers
        are disabled so this exercises the genuine no-tier path on every OS (on macOS T2 Seatbelt
        would otherwise contain it — see test_user_repo_runs_under_t2_seatbelt)."""
        repo = _micro_repo(tmp_path, marker=False)
        monkeypatch.setenv("TEMPEST_DOCKER", "/nonexistent/docker")
        monkeypatch.setenv("TEMPEST_NO_SEATBELT", "1")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))

        run_id = _start_prove(api, repo)
        run = _poll_until_complete(api, run_id)

        assert run["verdict"] == "UNPROVEN"
        assert run["targets"]
        for target in run["targets"]:
            assert target["verdict"] == "UNPROVEN"
            assert target["reason_code"] == "SANDBOX_UNAVAILABLE"
        assert run["divergence_count"] == 0

        stages = _stages(api, run_id)
        assert stages[-1] == "complete"
        assert "error" not in stages

    def test_status_complete_implies_terminal_ledger(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The moment `/v1/runs/{id}` reads COMPLETE, the events ledger already ends terminal.

        CI run 32610670936 caught the window this pins: ingestion committed `status=COMPLETE`
        plus the `ingested` row, then blob GC and telemetry ran, and only a LATER transaction
        appended `complete` — so a poller that saw COMPLETE could read a timeline that still
        ended mid-ingestion. The prove coroutine is parked at the exact post-ingest point (the
        GC call) so the ex-window is held open deterministically rather than raced for
        (trap 61): with the split commits this fails every time, never one time in forty.
        """
        real_collect_garbage = localprove.collect_garbage
        reached = threading.Event()
        release = threading.Event()

        async def parked_collect_garbage(*args: Any, **kwargs: Any) -> None:
            reached.set()
            while not release.is_set():  # held open until the test thread has looked
                await asyncio.sleep(0.01)
            await real_collect_garbage(*args, **kwargs)

        monkeypatch.setattr(localprove, "collect_garbage", parked_collect_garbage)

        repo = _micro_repo(tmp_path, marker=False)
        monkeypatch.setenv("TEMPEST_DOCKER", "/nonexistent/docker")
        monkeypatch.setenv("TEMPEST_NO_SEATBELT", "1")
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))

        run_id = _start_prove(api, repo)
        try:
            assert reached.wait(timeout=120.0), "prove never reached the post-ingest point"
            assert api.get_json(f"/v1/runs/{run_id}")["status"] == "COMPLETE"
            stages = _stages(api, run_id)
            assert stages[-1] == "complete", stages
        finally:
            release.set()

        run = _poll_until_complete(api, run_id)
        assert run["verdict"] == "UNPROVEN"
        stages = _stages(api, run_id)
        assert stages.count("complete") == 1
        assert stages[-1] == "complete"
        assert "error" not in stages
