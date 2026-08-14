"""Content-addressed bundle store (Phase 11, ADR-0017).

Every ingested `.tempest.zip` is kept as a blob keyed by its sha256; runs reference blobs by
digest; GC removes only unreferenced blobs; a user-controlled size budget prunes the OLDEST
runs first and never the newest — bounded disk, and every surviving run keeps its evidence (L7).
"""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from tempest_api.bundlestore import BundleStore


def test_put_is_content_addressed_and_dedups(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "bundles")
    payload = b"tempest bundle bytes"
    digest = store.put(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert store.put(payload) == digest, "same bytes must map to the same blob"
    assert store.get(digest) == payload
    assert store.total_bytes() == len(payload)
    assert store.digests() == {digest}


def test_get_missing_digest_raises(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "bundles")
    with pytest.raises(KeyError):
        store.get("0" * 64)


def test_gc_removes_only_unreferenced_blobs(tmp_path: Path) -> None:
    store = BundleStore(tmp_path / "bundles")
    keep = store.put(b"referenced by a run")
    drop = store.put(b"orphaned blob")
    assert store.gc(referenced={keep}) == [drop]
    assert store.digests() == {keep}
    assert store.get(keep) == b"referenced by a run"


def _stored_digest(db_path: Path, run_id: int) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT bundle_digest FROM runs WHERE id = ?", (run_id,)).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _run_ids(db_path: Path) -> set[int]:
    with sqlite3.connect(db_path) as conn:
        return {int(r[0]) for r in conn.execute("SELECT id FROM runs")}


def test_ingest_stores_blob_and_records_digest(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    bundle = api.make_bundle()
    data = api.zip_bytes(bundle)
    run_id = api.create_run_for(bundle)
    assert api.upload_zip(run_id, data).status_code == 200

    digest = hashlib.sha256(data).hexdigest()
    assert _stored_digest(api.db_path, run_id) == digest
    assert BundleStore(tmp_path / "data" / "bundles").get(digest) == data


def _distinct_bundles(api, count: int) -> list[bytes]:
    """Zip payloads guaranteed distinct (distinct head shas → distinct manifests)."""
    return [
        api.zip_bytes(api.make_bundle(repo=f"repo-{i}", head_sha=f"{i:x}" * 40))
        for i in range(count)
    ]


def test_budget_prunes_oldest_runs_first(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    zips = _distinct_bundles(api, 3)
    # Holds any two bundles but not all three: the third ingest must evict exactly the oldest.
    monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", str(sum(len(z) for z in zips) - 1))

    run_ids = []
    for i, data in enumerate(zips):
        run_id = api.create_run_id(repo=f"repo-{i}", base_sha="a" * 40, head_sha=f"{i:x}" * 40)
        assert api.upload_zip(run_id, data).status_code == 200
        run_ids.append(run_id)

    assert _run_ids(api.db_path) == {run_ids[1], run_ids[2]}, "oldest run must be pruned"
    store = BundleStore(tmp_path / "data" / "bundles")
    expected = {hashlib.sha256(z).hexdigest() for z in zips[1:]}
    assert store.digests() == expected, "the pruned run's blob must be GC'd with it"
    with sqlite3.connect(api.db_path) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM targets WHERE run_id NOT IN (SELECT id FROM runs)"
        ).fetchone()[0]
    assert orphans == 0, "pruning a run must cascade to its targets"


def test_budget_never_prunes_the_newest_run(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "1")
    zips = _distinct_bundles(api, 2)

    first = api.create_run_id(repo="repo-0", base_sha="a" * 40, head_sha="0" * 40)
    assert api.upload_zip(first, zips[0]).status_code == 200
    assert _run_ids(api.db_path) == {first}, "a lone over-budget run is never pruned"

    second = api.create_run_id(repo="repo-1", base_sha="a" * 40, head_sha="1" * 40)
    assert api.upload_zip(second, zips[1]).status_code == 200
    assert _run_ids(api.db_path) == {second}, "over budget: oldest goes, newest stays"
    store = BundleStore(tmp_path / "data" / "bundles")
    assert store.digests() == {hashlib.sha256(zips[1]).hexdigest()}


def test_pending_runs_without_bundles_are_never_pruned(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "1")
    pending = api.create_run_id(repo="waiting", base_sha="a" * 40, head_sha="b" * 40)

    data = api.zip_bytes(api.make_bundle(repo="repo-x", head_sha="c" * 40))
    ingested = api.create_run_id(repo="repo-x", base_sha="a" * 40, head_sha="c" * 40)
    assert api.upload_zip(ingested, data).status_code == 200

    assert _run_ids(api.db_path) == {pending, ingested}
