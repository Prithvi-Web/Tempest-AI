"""Sync push engine (Phase 13): content-addressed, delta-only, idempotent, resumable.

The local bundle store IS the durable queue: a push that fails leaves it untouched, so the
next attempt resumes exactly where the network died — no separate queue state to corrupt, no
duplication (the wire payload's sha256 is the identity on both ends; the server's import is
digest-idempotent). The policy boundary (`syncstrip`) runs BEFORE hashing, so presence checks
and server-side dedup operate on what actually crosses the wire. A dead server is a counted
outcome (`remaining`), never an exception — the app is never blocked by an unreachable server
(L8)."""

import asyncio
import hashlib

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.bundlestore import BundleStore, bundle_store
from tempest_api.db.models import Run
from tempest_api.schemas.sync import SyncReport
from tempest_api.syncstrip import strip_source_for_sync


def _wire_payload(store: "BundleStore", digest: str) -> bytes:
    """Blocking read+strip — always dispatched via asyncio.to_thread."""
    return strip_source_for_sync(store.get(digest))


async def push_all(
    session: AsyncSession, server_url: str, *, timeout_s: float = 30.0
) -> SyncReport:
    store = bundle_store()
    digests = list(
        (
            await session.execute(
                sa.select(Run.bundle_digest)
                .where(Run.bundle_digest.is_not(None))
                .order_by(Run.created_at.asc(), Run.id.asc())
            )
        )
        .scalars()
        .all()
    )
    seen: set[str] = set()
    unique: list[str] = []
    for digest in digests:
        assert digest is not None
        if digest not in seen:
            seen.add(digest)
            unique.append(digest)

    candidates = len(unique)
    pushed = skipped = failed = 0
    errors: list[str] = []
    # Review m5: ONE bundle in memory at a time, stripped off the event loop — a large store
    # must neither freeze the API nor OOM. Per-bundle presence keeps the delta property and
    # per-bundle resume granularity; the store remains the durable queue.
    async with httpx.AsyncClient(base_url=server_url, timeout=timeout_s) as client:
        for index, digest in enumerate(unique):
            try:
                wire = await asyncio.to_thread(_wire_payload, store, digest)
            except KeyError:
                failed += 1
                errors.append(f"local blob {digest[:12]}… missing from the store; skipped")
                continue
            wire_digest = hashlib.sha256(wire).hexdigest()
            try:
                resp = await client.post("/v1/bundles/presence", json={"digests": [wire_digest]})
                resp.raise_for_status()
                if wire_digest in resp.json()["present"]:
                    skipped += 1
                    continue
                imported = await client.post(
                    "/v1/runs/import",
                    files={"file": (f"{wire_digest}.tempest.zip", wire, "application/zip")},
                )
            except httpx.HTTPError as exc:
                # The network died mid-sync: everything not yet pushed stays queued in the
                # store; the next push resumes from the presence check. Stop hammering.
                errors.append(f"push interrupted at bundle {index + 1}/{candidates}: {exc}")
                break
            if imported.status_code == 200:
                pushed += 1
            else:
                failed += 1  # a rejected bundle must not block the rest
                errors.append(f"server rejected {wire_digest[:12]}…: HTTP {imported.status_code}")
    remaining = candidates - pushed - skipped - failed
    return SyncReport(
        candidates=candidates,
        pushed=pushed,
        skipped=skipped,
        failed=failed,
        remaining=remaining,
        errors=errors,
    )
