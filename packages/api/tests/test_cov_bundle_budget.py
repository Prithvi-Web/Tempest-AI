"""Bundle store internals (ADR-0017, reworked per review C1/M1) pinned directly: env-driven
budget parsing, blob sizing, and every arm of prune_over_budget + collect_garbage — no pruning
without a budget, no pruning under budget, the
oldest-first prune loop, the newest-run guarantee, and a run vanishing concurrently mid-prune
(deleted through a separate connection while the enforcer walks — the enforcer must treat the
disappearance as already-done work, never crash)."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState

from tempest_api.bundlestore import (
    BundleStore,
    bundle_store,
    collect_garbage,
    prune_over_budget,
)
from tempest_api.db.local_store import install_sqlite_pragmas
from tempest_api.db.session import create_engine_and_factory


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine, factory = create_engine_and_factory()
    install_sqlite_pragmas(engine)  # FK ON: pruning must cascade exactly as in the app
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


class TestBundleStoreEnv:
    def test_budget_env_parsing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))

        monkeypatch.delenv("TEMPEST_BUNDLE_BUDGET_BYTES", raising=False)
        store = bundle_store()
        assert store.root == tmp_path / "data" / "bundles"
        assert store.budget_bytes is None, "unset = unlimited"

        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "0")
        assert bundle_store().budget_bytes is None, "0 = unlimited"

        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "-1024")
        assert bundle_store().budget_bytes is None, "a negative budget cannot bound anything"

        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "not-a-number")
        assert bundle_store().budget_bytes is None, "garbage degrades to unlimited, never raises"

        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "4096")
        assert bundle_store().budget_bytes == 4096

    def test_size_reports_zero_for_a_missing_blob(self, tmp_path: Path) -> None:
        store = BundleStore(tmp_path / "bundles")
        digest = store.put(b"present bytes")
        assert store.size(digest) == len(b"present bytes")
        assert store.size("f" * 64) == 0, "a missing blob weighs nothing, never raises"


def _digest_by_repo(db_path: Path, repo: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bundle_digest FROM runs WHERE repo_id = (SELECT id FROM repos WHERE name = ?)",
            (repo,),
        ).fetchone()
    assert row is not None and row[0] is not None
    return str(row[0])


def _run_ids(db_path: Path) -> set[int]:
    with sqlite3.connect(db_path) as conn:
        return {int(r[0]) for r in conn.execute("SELECT id FROM runs")}


def _enforce(store: BundleStore) -> None:
    """The app's full sequence: prune rows in-transaction, commit, then GC committed truth."""

    async def scenario() -> None:
        async with _session() as session:
            pruned = await prune_over_budget(session, store)
            await session.commit()
            await collect_garbage(session, store, candidates=pruned)
            await collect_garbage(session, store)  # the general aged-orphan sweep

    asyncio.run(scenario())


class TestEnforceBudget:
    def test_no_bundle_bearing_runs_is_a_no_op(self, api: Any) -> None:
        api.create_run_id(repo="pending-only", base_sha="a" * 40, head_sha="b" * 40)
        _enforce(BundleStore(Path("/nonexistent-bundle-root"), budget_bytes=1))
        assert len(_run_ids(api.db_path)) == 1, "runs without bundles are never prune material"

    def test_without_a_budget_young_orphans_survive_and_aged_ones_are_collected(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review C1: a fresh orphan may be a concurrent ingest's uncommitted put — the grace
        period shields it; only provably abandoned (aged) orphans are swept."""
        import os

        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        api.ingest(api.make_bundle(repo="keep-a", head_sha="1" * 40))
        api.ingest(api.make_bundle(repo="keep-b", head_sha="2" * 40))
        store = bundle_store()
        orphan = store.put(b"referenced by no run at all")

        _enforce(BundleStore(store.root, budget_bytes=None))
        assert orphan in store.digests(), "a YOUNG orphan is shielded (in-flight ingest, C1)"

        blob = store.root / orphan[:2] / f"{orphan}.tempest.zip"
        os.utime(blob, (1, 1))  # provably abandoned
        _enforce(BundleStore(store.root, budget_bytes=None))
        assert len(_run_ids(api.db_path)) == 2
        assert orphan not in store.digests(), "aged orphans are collected"
        assert len(store.digests()) == 2

    def test_under_budget_keeps_everything(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        api.ingest(api.make_bundle(repo="fits-a", head_sha="3" * 40))
        api.ingest(api.make_bundle(repo="fits-b", head_sha="4" * 40))
        store = bundle_store()
        _enforce(BundleStore(store.root, budget_bytes=store.total_bytes()))
        assert len(_run_ids(api.db_path)) == 2
        assert len(store.digests()) == 2

    def test_prunes_oldest_runs_until_the_budget_fits(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        for i, repo in enumerate(("old", "mid", "new")):
            api.ingest(api.make_bundle(repo=repo, head_sha=f"{i + 5}" * 40))
        store = bundle_store()
        newest_digest = _digest_by_repo(api.db_path, "new")

        # A budget only the newest bundle fits: BOTH older runs must go, oldest first.
        _enforce(BundleStore(store.root, budget_bytes=store.size(newest_digest)))
        with sqlite3.connect(api.db_path) as conn:
            survivors = [
                r[0]
                for r in conn.execute(
                    "SELECT repos.name FROM runs JOIN repos ON repos.id = runs.repo_id"
                )
            ]
            orphans = conn.execute(
                "SELECT COUNT(*) FROM targets WHERE run_id NOT IN (SELECT id FROM runs)"
            ).fetchone()[0]
        assert survivors == ["new"], "oldest-first pruning, newest always survives"
        assert orphans == 0, "pruning a run must cascade to its evidence rows"
        assert store.digests() == {newest_digest}, "pruned runs take their blobs with them"

    def test_a_lone_over_budget_run_is_never_pruned(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        api.ingest(api.make_bundle(repo="only", head_sha="9" * 40))
        store = bundle_store()
        _enforce(BundleStore(store.root, budget_bytes=1))
        assert len(_run_ids(api.db_path)) == 1, "the run the user just proved always survives"
        assert len(store.digests()) == 1

    def test_a_run_deleted_concurrently_mid_prune_is_skipped(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Between the enforcer's row listing and its per-run load, another actor deletes the
        oldest run (real DELETE on a separate connection). The enforcer must count that as
        already-pruned and finish; the vanished run's blob is still collected."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        api.ingest(api.make_bundle(repo="vanishing", head_sha="a1" * 20))
        api.ingest(api.make_bundle(repo="surviving", head_sha="b2" * 20))
        store = bundle_store()
        surviving_digest = _digest_by_repo(api.db_path, "surviving")
        oldest_id = min(_run_ids(api.db_path))

        async def scenario() -> None:
            async with _session() as session:
                selects = {"n": 0}

                def vanish(state: ORMExecuteState) -> None:
                    if state.is_select:
                        selects["n"] += 1
                        if selects["n"] == 2:  # the enforcer's load of the oldest run
                            with sqlite3.connect(api.db_path, timeout=10) as conn:
                                conn.execute("PRAGMA foreign_keys=ON")
                                conn.execute("DELETE FROM runs WHERE id = ?", (oldest_id,))
                                conn.commit()

                event.listen(session.sync_session, "do_orm_execute", vanish)
                target_store = BundleStore(store.root, budget_bytes=store.size(surviving_digest))
                pruned = await prune_over_budget(session, target_store)
                await session.commit()
                await collect_garbage(session, target_store, candidates=pruned)
                event.remove(session.sync_session, "do_orm_execute", vanish)

        asyncio.run(scenario())
        assert _run_ids(api.db_path) == {max(_run_ids(api.db_path))}
        assert store.digests() == {surviving_digest}

    def test_gc_removes_exactly_the_unreferenced(self, tmp_path: Path) -> None:
        store = BundleStore(tmp_path / "bundles")
        keep = store.put(b"still referenced")
        drop_a = store.put(b"orphan one")
        drop_b = store.put(b"orphan two")
        removed = store.gc(referenced={keep})
        assert sorted(removed) == sorted([drop_a, drop_b])
        assert store.digests() == {keep}


def test_put_get_round_trip_and_dedup(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "bundles")
    digest = store.put(b"the bytes")
    assert store.put(b"the bytes") == digest
    assert store.get(digest) == b"the bytes"
    with pytest.raises(KeyError, match="no bundle blob"):
        store.get("0" * 64)
