# Self-hosted team sync server (Phase 13)

The team server is the same `tempest_api` application every desktop runs — self-hosted by
your team, never a vendor cloud (L8). Bundles are immutable and content-addressed, so sync
has no merge conflicts by design; pushes are delta-only, idempotent, and resume cleanly after
any network death.

## Run it

```bash
docker compose -f docker/compose.yaml up
```

That brings up Postgres 16 (runs/verdicts), MinIO (bundle blobs), Redis, and the API on
`:8000` (`docker/compose.yaml`, validated by the `compose-validate` CI job). For a quick
trust-nothing trial you can also run it bare on any machine with
[uv](https://docs.astral.sh/uv/):

```bash
uv run tempest-server --port 8000 --data-dir /srv/tempest
```

## Point a machine at it

```bash
curl -X POST http://your-server:8000/v1/sync/push   # or from the app/CLI host:
# POST /v1/sync/push {"server_url": "http://your-server:8000"} on the LOCAL tempest
```

Every push: presence check (`checkBundlePresence`) → only missing bundles cross → each is
ingested idempotently by its content digest. A dead server leaves everything queued in the
local store (`remaining` in the report); the next push resumes exactly the missing set —
no duplication, no loss (proven by test against a real killed-and-restarted server).

## Source never crosses by default

With the default policy, repro-script source is stripped before bytes are hashed or sent
(`TEMPEST_SYNC_SHARE_SOURCE=1` is the explicit org opt-in; Phase 14 turns this into pushed
org policy). Planted-source tests prove nothing crosses. See `docs/PRIVACY.md`.

## Honest pending legs (no Docker on the dev machine)

Marked PENDING, never silently skipped: running the compose stack end-to-end (CI has
`compose-validate` for config only), the Postgres-backed sync gate, Helm chart, and signed
container images. These are container-runner legs; the sync protocol itself is fully gated
by `packages/api/tests/test_sync_push.py` + `test_sync_strip.py` against real processes.
