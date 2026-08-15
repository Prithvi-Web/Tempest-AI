"""Content-addressed bundle store (Phase 11, ADR-0017).

Every ingested `.tempest.zip` is kept as a blob under `<data_dir>/bundles/<aa>/<digest>.tempest.zip`
where `digest` is the sha256 of the zip bytes: identical bundles share one blob, and a blob can
be handed back byte-identical for export/replay (L7). Runs reference blobs via
`runs.bundle_digest`; GC removes only blobs no run references.

A user-controlled budget (`TEMPEST_BUNDLE_BUDGET_BYTES`; unset or 0 = unlimited) bounds the
store: when an ingest pushes it over, the OLDEST bundle-bearing runs are pruned — row and blob
together, so every surviving run keeps its evidence — and the newest run is never pruned, so
the run the user just proved always survives.
"""

import hashlib
import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.db.models import Run

_SUFFIX = ".tempest.zip"


class BundleStore:
    def __init__(self, root: Path, budget_bytes: int | None = None) -> None:
        self.root = root
        self.budget_bytes = budget_bytes

    def _blob_path(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}{_SUFFIX}"

    def put(self, data: bytes) -> str:
        """Store bytes under their sha256; atomic (tmp + rename), idempotent for same content."""
        digest = hashlib.sha256(data).hexdigest()
        blob = self._blob_path(digest)
        if blob.exists():
            return digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        tmp = blob.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(blob)
        return digest

    def get(self, digest: str) -> bytes:
        blob = self._blob_path(digest)
        if not blob.exists():
            raise KeyError(f"no bundle blob for digest {digest!r} in {self.root}")
        return blob.read_bytes()

    def size(self, digest: str) -> int:
        blob = self._blob_path(digest)
        return blob.stat().st_size if blob.exists() else 0

    def digests(self) -> set[str]:
        return {p.name[: -len(_SUFFIX)] for p in self.root.glob(f"??/*{_SUFFIX}")}

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob(f"??/*{_SUFFIX}"))

    def gc(self, referenced: set[str], *, min_age_s: float = 0.0) -> list[str]:
        """Remove every blob whose digest is not referenced; returns what was removed.
        `min_age_s` shields young blobs — a concurrent ingest's put that has not committed
        its run row yet must not be collected (review C1)."""
        import time

        removed = []
        now = time.time()
        for digest in sorted(self.digests() - referenced):
            blob = self._blob_path(digest)
            if min_age_s > 0.0:
                try:
                    if now - blob.stat().st_mtime < min_age_s:
                        continue
                except OSError:  # pragma: no cover — raced by a concurrent unlink; nothing to do
                    continue
            blob.unlink()
            removed.append(digest)
        return removed


def bundle_store() -> BundleStore:
    """The store for this process's data dir + the user's current budget (env-read per call so
    the desktop can adjust the budget without a restart)."""
    from tempest_api.localprove import data_dir  # local import: localprove imports ingest

    raw = os.environ.get("TEMPEST_BUNDLE_BUDGET_BYTES", "0")
    try:
        budget = int(raw)
    except ValueError:
        budget = 0
    return BundleStore(data_dir() / "bundles", budget if budget > 0 else None)


# A blob younger than this is presumed to belong to an in-flight (flushed, uncommitted)
# ingest and is never garbage-collected by the background sweep (review C1).
_GC_GRACE_S = 15 * 60.0


async def prune_over_budget(
    session: AsyncSession, store: BundleStore, *, protect_run_id: int | None = None
) -> list[str]:
    """Prune oldest bundle-bearing runs (rows only, in the caller's transaction) until the
    store fits the budget. Never the newest run, and never `protect_run_id` — an ingest must
    not prune the very run it is completing (review M1). Returns the pruned runs' digests as
    GC candidates for AFTER the caller commits; no filesystem mutation happens here (C1)."""
    if store.budget_bytes is None:
        return []
    rows = list(
        (
            await session.execute(
                sa.select(Run.id, Run.bundle_digest)
                .where(Run.bundle_digest.is_not(None))
                .order_by(Run.created_at.asc(), Run.id.asc())
            )
        ).all()
    )
    if not rows:
        return []

    def referenced(remaining: list[sa.Row[tuple[int, str | None]]]) -> set[str]:
        return {digest for _, digest in remaining if digest is not None}

    pruned: list[str] = []
    while len(rows) > 1 and sum(store.size(d) for d in referenced(rows)) > store.budget_bytes:
        prunable = next(
            (row for row in rows[:-1] if row.id != protect_run_id),
            None,
        )
        if prunable is None:
            break  # everything older is the protected run itself — nothing prunable
        oldest = await session.get(Run, prunable.id)
        if oldest is not None:
            await session.delete(oldest)
        # The SELECT filters bundle_digest IS NOT NULL, so this narrowing never sees None.
        if prunable.bundle_digest is not None:  # pragma: no branch — query-guaranteed
            pruned.append(prunable.bundle_digest)
        rows = [row for row in rows if row.id != prunable.id]
    await session.flush()
    return pruned


async def collect_garbage(
    session: AsyncSession, store: BundleStore, *, candidates: list[str] | None = None
) -> list[str]:
    """Blob GC against COMMITTED truth — call only after the ingest transaction committed
    (review C1). With explicit `candidates` (a prune's digests), exactly those are removed
    when no committed run references them; the general sweep additionally shields young
    blobs so a concurrent in-flight ingest's put is never collected."""
    referenced = {
        digest
        for digest in (
            await session.execute(
                sa.select(Run.bundle_digest).where(Run.bundle_digest.is_not(None))
            )
        )
        .scalars()
        .all()
        if digest is not None
    }
    if candidates is not None:
        removed = []
        for digest in candidates:
            if digest not in referenced and digest in store.digests():
                store._blob_path(digest).unlink()
                removed.append(digest)
        return removed
    return store.gc(referenced, min_age_s=_GC_GRACE_S)
