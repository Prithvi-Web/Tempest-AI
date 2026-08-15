"""Local prove orchestration edges — REAL repos, REAL prove threads, no mocked execution (L4).

test_local_prove and test_cancel_run pin the happy/validation/cancel paths over HTTP; these
tests drive `startLocalProve`/`cancelRun` and the localprove registry directly to pin the
edges: the forced battery-pause reporting its reason into the ledger mid-prove, the duplicate
spawn guard, cancel through the router against a live prove, the run row vanishing mid-prove
(the worker must finish silently — nothing to record on), an unwritable data dir surfacing as
the honest ERROR verdict with the traceback in the ledger (L2), the `_mark_*` guards for a
run that no longer exists, and registry cleanup when the OS refuses to start the thread (the
one failure that cannot be produced for real deterministically — only `.start()` is made to
raise; every cleanup line under test is the real code)."""

import asyncio
import sqlite3
import subprocess
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tempest.prove import ProveConfig
from tempest_api import localprove
from tempest_api.db.session import create_engine_and_factory, database_url
from tempest_api.localprove import (
    _mark_cancelled,
    _mark_error,
    is_prove_active,
    local_run_out_dir,
    spawn_prove_thread,
)
from tempest_api.routers.local import start_local_prove
from tempest_api.routers.runs import cancel_run
from tempest_api.schemas import LocalProveRequest


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine, factory = create_engine_and_factory()
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _repo(tmp_path: Path, *, sleep_s: float = 0.0) -> Path:
    """A tiny two-commit first-party repo; `sleep_s` slows the target for mid-prove tests."""
    repo = tmp_path / "repo"
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

    prelude = f"import time\n\n\ndef pace() -> None:\n    time.sleep({sleep_s})\n\n\n"
    source = prelude + "def double(x: int) -> int:\n    pace()\n    return x * 2{op}\n"
    git("init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text(source.format(op=""))
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text(source.format(op=" + 1"))
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


def _start(repo: Path, *, max_inputs: int) -> int:
    async def scenario() -> int:
        async with _session() as session:
            body = LocalProveRequest(
                repo_path=str(repo), base="base", head="head", max_inputs=max_inputs
            )
            return (await start_local_prove(body, session)).run_id

    return asyncio.run(scenario())


def _wait(predicate: Any, *, timeout_s: float, what: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out after {timeout_s}s waiting for {what}")


def _events(api: Any, run_id: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = api.get_json(f"/v1/runs/{run_id}/events")
    return events


def _has_stage(api: Any, run_id: int, stage: str) -> bool:
    return any(e["stage"] == stage for e in _events(api, run_id))


def test_forced_pause_reports_its_reason_then_the_prove_resumes(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L11 end to end: with a pause condition forced, the ledger shows WHY the run is holding
    (the on_pause callback threading the reason into the run's events); lifting the condition
    lets the same run finish with a real verdict."""
    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "battery drill: forced by the test suite")
    repo = _repo(tmp_path)

    run_id = _start(repo, max_inputs=4)
    try:
        _wait(
            lambda: _has_stage(api, run_id, "paused"),
            timeout_s=60,
            what="the paused ledger event",
        )
        paused = [e for e in _events(api, run_id) if e["stage"] == "paused"]
        assert any("battery drill: forced by the test suite" in e["message"] for e in paused)
        assert not _has_stage(api, run_id, "complete"), "a paused prove must be holding"
    finally:
        monkeypatch.delenv("TEMPEST_FORCE_POWER_PAUSE")

    _wait(
        lambda: api.get_json(f"/v1/runs/{run_id}")["status"] == "COMPLETE",
        timeout_s=120,
        what="the resumed prove to complete",
    )
    run = api.get_json(f"/v1/runs/{run_id}")
    assert run["verdict"] == "DIVERGENT"
    assert run["repo"] == "repo"
    _wait(lambda: not is_prove_active(run_id), timeout_s=30, what="the prove thread to exit")


def test_duplicate_spawn_is_refused_and_cancel_flows_through_the_router(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    # Forcing the power pause pins the prove at its first checkpoint — a DETERMINISTIC
    # long-lived active state (no sleep-per-input timing lottery under full-suite load).
    # Cancel unblocks a pause immediately, so the cancel leg stays fast.
    monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "pinned by duplicate-spawn test")
    repo = _repo(tmp_path, sleep_s=0.0)

    run_id = _start(repo, max_inputs=5)
    _wait(lambda: _has_stage(api, run_id, "paused"), timeout_s=60, what="the pinned pause")
    assert is_prove_active(run_id), "a paused prove is an active prove"

    duplicate_cfg = ProveConfig(
        repo=repo, base="base", head="head", max_inputs=1, out=local_run_out_dir(run_id)
    )
    assert spawn_prove_thread(run_id, duplicate_cfg, database_url()) is False, (
        "one run, one prove: the registry must refuse a concurrent duplicate"
    )

    async def cancel() -> None:
        async with _session() as session:
            accepted = await cancel_run(run_id, session)
            assert accepted.run_id == run_id and accepted.cancelling is True

    asyncio.run(cancel())
    _wait(lambda: not is_prove_active(run_id), timeout_s=30, what="the cancelled thread")
    _wait(
        lambda: api.get_json(f"/v1/runs/{run_id}")["status"] == "CANCELLED",
        timeout_s=30,
        what="the CANCELLED status",
    )
    assert api.get_json(f"/v1/runs/{run_id}")["verdict"] is None, "no verdict claimed (L2)"


def test_run_row_vanishing_mid_prove_ends_the_worker_silently(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    repo = _repo(tmp_path, sleep_s=0.3)

    run_id = _start(repo, max_inputs=3)
    _wait(lambda: _has_stage(api, run_id, "proving"), timeout_s=60, what="the proving stage")
    with sqlite3.connect(api.db_path, timeout=10) as conn:
        conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()

    _wait(lambda: not is_prove_active(run_id), timeout_s=120, what="the worker to finish")
    with sqlite3.connect(api.db_path, timeout=10) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        stages = {
            str(r[0])
            for r in conn.execute(
                "SELECT json_extract(payload, '$.stage') FROM run_events WHERE run_id = ?",
                (run_id,),
            )
        }
    assert "complete" not in stages and "error" not in stages, (
        "with the run gone there is nothing to record a terminal state on"
    )


def test_unwritable_data_dir_is_an_honest_error_verdict_with_traceback(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tempest itself failing (here: its own data dir made unwritable mid-flight) must land
    on verdict ERROR with the traceback in the ledger (L2) — never a silent hang, never a
    blessed run."""
    monkeypatch.setenv("TEMPEST_DEV", "1")
    data_dir = tmp_path / "readonly-appdata"
    data_dir.mkdir()
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(data_dir))
    repo = _repo(tmp_path)
    data_dir.chmod(0o555)
    try:
        run_id = _start(repo, max_inputs=3)
        _wait(
            lambda: api.get_json(f"/v1/runs/{run_id}")["status"] == "COMPLETE",
            timeout_s=120,
            what="the failed prove to land on ERROR",
        )
        run = api.get_json(f"/v1/runs/{run_id}")
        assert run["verdict"] == "ERROR"
        error_events = [e for e in _events(api, run_id) if e["stage"] == "error"]
        assert error_events, "the ledger must carry the failure"
        assert error_events[-1]["level"] == "error"
        assert "Traceback" in error_events[-1]["message"], "the traceback IS the evidence (L1)"
        _wait(lambda: not is_prove_active(run_id), timeout_s=30, what="the worker to exit")
    finally:
        data_dir.chmod(0o755)


def test_mark_helpers_are_noops_for_a_run_that_no_longer_exists(api: Any) -> None:
    async def scenario() -> None:
        engine, factory = create_engine_and_factory()
        try:
            await _mark_cancelled(factory, 987_654)
            await _mark_error(factory, 987_654, "trace that has nowhere to go")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    with sqlite3.connect(api.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ?", (987_654,)
        ).fetchone()[0]
    assert count == 0, "no phantom ledger rows for a vanished run"


def test_thread_start_failure_cleans_the_registry_and_reraises(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Thread.start` failing (resource exhaustion) cannot be produced for real
    deterministically, so only `.start()` is made to raise; the registry cleanup and the
    re-raise under test are the real code paths."""

    class ExplodingThread(threading.Thread):
        def start(self) -> None:
            raise RuntimeError("can't start new thread (simulated resource exhaustion)")

    monkeypatch.setattr(threading, "Thread", ExplodingThread)
    cfg = ProveConfig(repo=tmp_path, base="a" * 40, head="b" * 40, max_inputs=1)
    with pytest.raises(RuntimeError, match="can't start new thread"):
        spawn_prove_thread(999_001, cfg, database_url())
    monkeypatch.undo()
    assert not is_prove_active(999_001), "a failed spawn must not leave a registry entry"
    assert localprove.request_cancel(999_001) is False, "nothing to cancel after the failure"
