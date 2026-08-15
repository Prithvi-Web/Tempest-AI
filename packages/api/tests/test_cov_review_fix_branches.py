"""Branch closure for the review-fix code itself (100% gate): every guard arm the regression
pins didn't reach — the true commit-race 409, non-duplicate ALTER failures during adoption,
shared-digest dedup in sync, and the protected-run prune break."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.bundlestore import BundleStore, prune_over_budget
from tempest_api.db.session import create_engine_and_factory
from tempest_api.sync import push_all


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine, factory = create_engine_and_factory()
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def test_true_double_submit_race_maps_integrity_error_to_409(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The COMMIT-time loser (review m3): both requests pass the PENDING check before either
    commits; the loser's IntegrityError must become 409, never 500. Staged with two real
    sessions racing over the same run row."""
    from fastapi import UploadFile

    from tempest_api.routers.runs import upload_run_bundle

    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    bundle = api.make_bundle()
    run_id = api.create_run_for(bundle)
    data = api.zip_bytes(bundle)

    async def race() -> int:
        import io

        from tempest_api.errors import ApiError

        async with _session() as loser:
            # The loser loads the run (PENDING) and ingests, but before its commit the winner
            # lands the full ingest through the ordinary endpoint path.
            from tempest_api.db.models import Run

            run = await loser.get(Run, run_id)
            assert run is not None and run.status.value == "PENDING"
            resp = api.upload_zip(run_id, data)  # the winner commits first
            assert resp.status_code == 200
            upload = UploadFile(io.BytesIO(data), filename="race.tempest.zip")
            try:
                await upload_run_bundle(run_id, upload, loser)
            except ApiError as exc:
                return exc.status_code
            return 0

    assert asyncio.run(race()) == 409, "the race loser gets 409 RUN_NOT_PENDING, never a 500"


def test_adoption_reraises_non_duplicate_alter_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3 guard's other arm: an ALTER that fails for any reason OTHER than duplicate-column
    must surface, never be swallowed. A view named `runs` cannot be altered."""
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError

    from tempest_api.app import create_app

    weird = tmp_path / "weird.db"
    with sqlite3.connect(weird) as conn:
        conn.execute("CREATE VIEW runs AS SELECT 1 AS id")
        conn.commit()

    monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{weird}")
    with pytest.raises(OperationalError), TestClient(create_app()):
        pass  # startup must fail loudly — a view named runs is not a legacy store


def test_sync_dedups_runs_sharing_one_digest(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two runs referencing the same blob are ONE sync candidate (content addressing)."""
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")
    bundle = api.make_bundle(repo="shared", head_sha="7" * 40)
    data = api.zip_bytes(bundle)
    first = api.create_run_id(repo="shared", base_sha="a" * 40, head_sha="7" * 40)
    assert api.upload_zip(first, data).status_code == 200
    second = api.client.post(
        "/v1/runs/import", files={"file": ("dup.tempest.zip", data, "application/zip")}
    )
    assert second.status_code == 200

    async def push_against_nowhere() -> int:
        async with _session() as session:
            report = await push_all(session, "http://127.0.0.1:9", timeout_s=2)
            return report.candidates

    assert asyncio.run(push_against_nowhere()) == 1, "one digest, one candidate — never two"


def test_prune_breaks_when_every_older_run_is_the_protected_one(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1's break arm: over budget, but the only prunable (older) row IS the protected run —
    prune must stop, not loop or delete it."""
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    protected = api.create_run_id(repo="mine", base_sha="a" * 40, head_sha="c" * 40)
    assert (
        api.upload_zip(
            protected, api.zip_bytes(api.make_bundle(repo="mine", head_sha="c" * 40))
        ).status_code
        == 200
    )
    newer = api.ingest(api.make_bundle(repo="other", head_sha="d" * 40))
    assert newer is not None

    async def prune() -> list[str]:
        async with _session() as session:
            store = BundleStore(tmp_path / "data" / "bundles", budget_bytes=1)
            pruned = await prune_over_budget(session, store, protect_run_id=protected)
            await session.commit()
            return pruned

    assert asyncio.run(prune()) == [], "nothing prunable when the only older run is protected"
    assert api.get_json(f"/v1/runs/{protected}")["status"] == "COMPLETE"


def test_prove_thread_returns_cleanly_when_run_vanishes_before_ingest(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The locked-ingest early return: the run row vanishes while the prove is pinned at a
    pause; the thread must end without error and without resurrecting the run."""
    import subprocess
    import time as time_mod

    from tempest_api import localprove

    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "pinned for vanish test")

    repo = tmp_path / "vanish-repo"
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
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def f(x: int) -> int:\n    return x * 2\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def f(x: int) -> int:\n    return x + 2\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")

    resp = api.client.post(
        "/v1/local/prove",
        json={"repo_path": str(repo), "base": "base", "head": "head", "max_inputs": 3},
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    deadline = time_mod.monotonic() + 60
    while time_mod.monotonic() < deadline:
        events = api.get_json(f"/v1/runs/{run_id}/events")
        if any(e["stage"] == "paused" for e in events):
            break
        time_mod.sleep(0.05)
    else:
        raise AssertionError("prove never reached the pinned pause")

    with sqlite3.connect(api.db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()

    monkeypatch.delenv("TEMPEST_FORCE_POWER_PAUSE")  # unpin; the prove proceeds to ingest
    deadline = time_mod.monotonic() + 60
    while time_mod.monotonic() < deadline and localprove.is_prove_active(run_id):
        time_mod.sleep(0.05)
    assert not localprove.is_prove_active(run_id), "the thread must end after the vanish"
    assert api.client.get(f"/v1/runs/{run_id}").status_code == 404, "nothing resurrected"


def test_shared_digest_prune_candidate_survives_gc_when_still_referenced(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """collect_garbage's candidate skip arm: a pruned run's digest that another COMMITTED run
    still references must not lose its blob."""
    from tempest_api.bundlestore import collect_garbage

    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    bundle = api.make_bundle(repo="shared-gc", head_sha="e" * 40)
    data = api.zip_bytes(bundle)
    keeper = api.create_run_id(repo="shared-gc", base_sha="a" * 40, head_sha="e" * 40)
    assert api.upload_zip(keeper, data).status_code == 200
    import hashlib

    digest = hashlib.sha256(data).hexdigest()

    async def sweep() -> None:
        async with _session() as session:
            store = BundleStore(tmp_path / "data" / "bundles")
            removed = await collect_garbage(session, store, candidates=[digest, "f" * 64])
            assert removed == [], "a still-referenced candidate is never unlinked"
            assert digest in store.digests()

    asyncio.run(sweep())


def test_adoption_guard_reraises_a_genuinely_failing_alter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local_store adoption: only duplicate-column failures are skips; any other ALTER
    failure surfaces. The failing statement is REAL SQL really executed (config patched,
    execution genuine)."""
    from sqlalchemy import create_engine

    from tempest_api.db import local_store

    db = tmp_path / "adopt-fail.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY)")
        conn.commit()

    monkeypatch.setitem(
        local_store._FORWARD_STEPS,
        "0001",
        ("ALTER TABLE no_such_table ADD COLUMN x TEXT",),  # missing table → real failure
    )
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn2, pytest.raises(Exception, match=r"(?i)no such table"):
            local_store._prepare(conn2)
    finally:
        engine.dispose()


def test_presence_endpoint_direct_call_records_both_arms(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct-call presence (portal-traced lines): present requires row AND blob."""
    from tempest_api.routers.sync import check_bundle_presence
    from tempest_api.schemas.sync import BundlePresenceRequest

    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    bundle = api.make_bundle(repo="direct-presence", head_sha="b" * 40)
    data = api.zip_bytes(bundle)
    run_id = api.create_run_id(repo="direct-presence", base_sha="a" * 40, head_sha="b" * 40)
    assert api.upload_zip(run_id, data).status_code == 200
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    orphan = BundleStore(tmp_path / "data" / "bundles").put(b"row-less orphan")

    async def probe() -> None:
        async with _session() as session:
            result = await check_bundle_presence(
                BundlePresenceRequest(digests=[digest, orphan, "0" * 64]), session
            )
            assert result.present == [digest]
            assert result.missing == [orphan, "0" * 64]

    asyncio.run(probe())


def test_prove_coroutine_returns_when_run_vanished(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct-call variant of the vanish arm (thread-loop line attribution): the full prove
    coroutine, run from this thread, must end silently when the run row is already gone."""
    import subprocess

    from tempest.prove import ProveConfig
    from tempest_api.db.session import database_url
    from tempest_api.localprove import _prove_and_ingest, local_run_out_dir

    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))

    repo = tmp_path / "gone-repo"
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
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def f(x: int) -> int:\n    return x * 2\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def f(x: int) -> int:\n    return x + 2\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")

    run_id = api.create_run_id(repo="gone", base_sha="a" * 40, head_sha="b" * 40)

    # Pin the prove at its first checkpoint; a helper thread waits for the pinned 'paused'
    # ledger row, deletes the run, then releases the pin — the coroutine (running on THIS
    # thread's loop, where line attribution is exact) resumes into ingest and must return.
    import os as os_mod
    import threading
    import time as time_mod

    monkeypatch.setenv("TEMPEST_FORCE_POWER_PAUSE", "pinned for direct vanish test")

    def delete_when_paused() -> None:
        deadline = time_mod.monotonic() + 60
        while time_mod.monotonic() < deadline:
            with sqlite3.connect(api.db_path, timeout=10) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM run_events WHERE run_id = ? AND event_type = ?",
                    (run_id, "local.paused"),
                ).fetchone()
            if row and row[0] > 0:
                break
            time_mod.sleep(0.05)
        with sqlite3.connect(api.db_path, timeout=10) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            conn.commit()
        os_mod.environ.pop("TEMPEST_FORCE_POWER_PAUSE", None)  # release the pin

    helper = threading.Thread(target=delete_when_paused, daemon=True)
    helper.start()
    cfg = ProveConfig(
        repo=repo, base="base", head="head", max_inputs=2, out=local_run_out_dir(run_id)
    )
    asyncio.run(_prove_and_ingest(run_id, cfg, database_url()))  # must simply return
    helper.join(timeout=10)
    assert api.client.get(f"/v1/runs/{run_id}").status_code == 404
