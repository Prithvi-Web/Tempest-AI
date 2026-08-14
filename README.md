# Tempest AI

**A behavioral proof agent.** Tempest does not review diffs — it *executes* them: base and head,
side by side, under identical deterministic conditions, and reports the concrete inputs where
observable behavior diverges, each with a minimized reproduction.

> "3 inputs produce different results. Here they are. Here is the smallest one."

And when it cannot exercise a change:

> "I could not exercise `module.fn` — it opens a raw socket to an unrecorded host.
> I am not blessing this change."

The output is **evidence, not opinion**. A change Tempest could not run is `UNPROVEN`, never blessed.

## Verdicts (the only four)

| Verdict | Meaning |
|---|---|
| `DIVERGENT` | ≥1 input produced differing observable behavior — inputs included |
| `EQUIVALENT_UNDER_BUDGET` | N inputs / M covered branches behaved identically. **Not** "correct" — the report states exactly what was and was not exercised |
| `UNPROVEN` | Could not harness / reach determinism / reproduce the env — with a machine-readable `reason_code` |
| `ERROR` | Tempest itself failed — internal trace included |

## Layout

- `packages/engine` — the product: nine-stage differential engine + `tempest` CLI (Python 3.12)
- `packages/ts-sidecar` — TypeScript analysis sidecar (JSON-RPC over stdio)
- `packages/api` — FastAPI ingestion/orchestration; `packages/web` — Next.js dashboard
- `packages/shared-schema` — generated OpenAPI + TS types (zero-drift contract)
- `corpus/` — real-world validation corpora and fixture repos
- `docs/` — `PLAN.md` (phases + gates), `ARCHITECTURE.md`, `DECISIONS.md` (ADRs), `BUNDLE_SCHEMA.md`

## Development

```bash
make sync     # uv sync --all-packages && pnpm install
make verify   # every gate step live for the completed phases (see docs/PLAN.md)
```

Honest status lives in `docs/PLAN.md` — a phase is complete only when its gate commands ran with
real output attached.
