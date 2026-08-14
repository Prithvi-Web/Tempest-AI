"""Sync push engine (Phase 13): content-addressed, delta-only, idempotent, resumable.

The local bundle store IS the durable queue: a push that fails leaves it untouched, so the
next attempt resumes exactly where the network died — no separate queue state to corrupt, no
duplication (the wire payload's sha256 is the identity on both ends; the server's import is
digest-idempotent). The policy boundary (`syncstrip`) runs BEFORE hashing, so presence checks
and server-side dedup operate on what actually crosses the wire. A dead server is a counted
outcome (`remaining`), never an exception — the app is never blocked by an unreachable server
(L8)."""

import hashlib

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tempest_api.bundlestore import bundle_store
from tempest_api.db.models import Run
from tempest_api.schemas.sync import SyncReport
from tempest_api.syncstrip import strip_source_for_sync

_PRESENCE_CHUNK = 500


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
    payloads: list[tuple[str, bytes]] = []  # (wire digest, wire bytes) in push order
    errors: list[str] = []
    for digest in digests:
        assert digest is not None
        if digest in seen:
            continue
        seen.add(digest)
        try:
            wire = strip_source_for_sync(store.get(digest))
        except KeyError:
            errors.append(f"local blob {digest[:12]}… missing from the store; skipped")
            continue
        payloads.append((hashlib.sha256(wire).hexdigest(), wire))

    candidates = len(payloads)
    pushed = skipped = failed = 0
    async with httpx.AsyncClient(base_url=server_url, timeout=timeout_s) as client:
        present: set[str] = set()
        try:
            for start in range(0, len(payloads), _PRESENCE_CHUNK):
                chunk = [d for d, _ in payloads[start : start + _PRESENCE_CHUNK]]
                resp = await client.post("/v1/bundles/presence", json={"digests": chunk})
                resp.raise_for_status()
                present.update(resp.json()["present"])
        except httpx.HTTPError as exc:
            errors.append(f"server unreachable during presence check: {exc}")
            return SyncReport(
                candidates=candidates,
                pushed=0,
                skipped=0,
                failed=0,
                remaining=candidates,
                errors=errors,
            )

        for index, (digest, wire) in enumerate(payloads):
            if digest in present:
                skipped += 1
                continue
            try:
                resp = await client.post(
                    "/v1/runs/import",
                    files={"file": (f"{digest}.tempest.zip", wire, "application/zip")},
                )
            except httpx.HTTPError as exc:
                # The network died mid-sync: everything not yet pushed stays queued in the
                # store; the next push resumes from the presence check. Stop hammering.
                errors.append(f"push interrupted at bundle {index + 1}/{candidates}: {exc}")
                break
            if resp.status_code == 200:
                pushed += 1
            else:
                failed += 1  # a rejected bundle must not block the rest
                errors.append(f"server rejected {digest[:12]}…: HTTP {resp.status_code}")
    remaining = candidates - pushed - skipped - failed
    return SyncReport(
        candidates=candidates,
        pushed=pushed,
        skipped=skipped,
        failed=failed,
        remaining=remaining,
        errors=errors,
    )
