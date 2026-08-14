"""`POST /v1/runs/{id}/cancel` (L11): a running local prove stops — thread unwound, children
dead — in under two seconds, the run lands in the honest CANCELLED state, and a run with no
active prove refuses with RUN_NOT_ACTIVE. Real repo, real engine, no mocks (L4)."""

import subprocess
import time
from pathlib import Path
from typing import Any

from tempest_api import localprove


def _slow_repo(tmp_path: Path) -> Path:
    """First-party-marked repo whose target sleeps per input — cancellable mid-prove."""
    repo = tmp_path / "slowrepo"
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

    source = (
        "import time\n\n\ndef crawl(x: int) -> int:\n    time.sleep(0.4)\n    return x {op} 2\n"
    )
    git("init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text(source.format(op="*"))
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text(source.format(op="+"))
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


def _wait_for_stage(api: Any, run_id: int, stage: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = api.get_json(f"/v1/runs/{run_id}/events")
        if any(e["stage"] == stage for e in events):
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} never reached stage {stage!r}")


def test_cancel_stops_a_running_prove_within_two_seconds(
    api: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_DEV", "1")
    repo = _slow_repo(tmp_path)
    resp = api.client.post(
        "/v1/local/prove",
        json={"repo_path": str(repo), "base": "base", "head": "head", "max_inputs": 200},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    _wait_for_stage(api, run_id, "proving")
    time.sleep(0.5)  # let workers actually spawn and start crawling

    cancel_resp = api.client.post(f"/v1/runs/{run_id}/cancel")
    assert cancel_resp.status_code == 202, cancel_resp.text

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and localprove.is_prove_active(run_id):
        time.sleep(0.05)
    elapsed = 2.0 - max(0.0, deadline - time.monotonic())
    assert not localprove.is_prove_active(run_id), (
        f"prove thread still alive {elapsed:.2f}s after cancel"
    )

    run = api.get_json(f"/v1/runs/{run_id}")
    assert run["status"] == "CANCELLED"
    assert run["verdict"] is None, "a cancelled run must not claim any verdict (L2)"
    events = api.get_json(f"/v1/runs/{run_id}/events")
    assert any(e["stage"] == "cancelled" for e in events)


def test_cancel_without_an_active_prove_is_409(api: Any) -> None:
    run_id = api.create_run_id(repo="idle", base_sha="a" * 40, head_sha="b" * 40)
    resp = api.client.post(f"/v1/runs/{run_id}/cancel")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RUN_NOT_ACTIVE"


def test_cancel_a_missing_run_is_404(api: Any) -> None:
    resp = api.client.post("/v1/runs/999999/cancel")
    assert resp.status_code == 404
