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

    def gc(self, referenced: set[str]) -> list[str]:
        """Remove every blob whose digest is not referenced; returns what was removed."""
        removed = []
        for digest in sorted(self.digests() - referenced):
            self._blob_path(digest).unlink()
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


async def enforce_budget(session: AsyncSession, store: BundleStore) -> None:
    """Prune oldest bundle-bearing runs until the store fits the budget; never the newest run;
    then GC blobs no surviving run references. Runs in the ingest transaction — a rolled-back
    ingest re-orphans blobs at worst, and orphans are re-collected on the next enforce."""
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
        return

    def referenced(remaining: list[sa.Row[tuple[int, str | None]]]) -> set[str]:
        return {digest for _, digest in remaining if digest is not None}

    if store.budget_bytes is not None:
        while len(rows) > 1 and sum(store.size(d) for d in referenced(rows)) > store.budget_bytes:
            oldest_id = rows[0].id
            oldest = await session.get(Run, oldest_id)
            if oldest is not None:
                await session.delete(oldest)
            rows = rows[1:]
        await session.flush()
    store.gc(referenced(rows))
