# Tempest AI

**A behavioral proof agent.** Tempest does not review diffs — it *executes* them: base and head,
side by side, under identical deterministic conditions, and reports the concrete inputs where
observable behavior diverges, each with a minimized reproduction.

## Install (GitHub is the only distribution channel)

The CLI, on any OS with [uv](https://docs.astral.sh/uv/) (or swap in `pipx`):

```bash
uv tool install "git+https://github.com/Prithvi-Web/Tempest-AI#subdirectory=packages/engine"
```

Then prove a change and check your machine:

```bash
tempest doctor
tempest prove --base main --head my-branch --repo /path/to/repo
```

Or see it work before pointing it at anything of yours: open the desktop app and press
**Try a demo proof** — Tempest writes a tiny real repository with a "harmless" rounding
cleanup and proves, with real inputs and a downloadable reproduction, that it changes what
customers pay. First divergence in a few seconds, entirely offline.

The macOS desktop app ships as an **unsigned** zip on the
[Releases page](https://github.com/Prithvi-Web/Tempest-AI/releases) — this project deliberately
has no Apple Developer account (ADR-0021), so on first launch: right-click → Open, or
`xattr -d com.apple.quarantine Tempest.app`. Verify any download against the release's
`SHA256SUMS.txt`. Everything runs fully local (no accounts, no cloud, zero egress — tested,
not promised: see `docs/PRIVACY.md`).

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

## Cost model — bring your own key, or no key at all

Tempest runs **fully offline by default** — the differential engine, input generation, and verdicts
use zero LLM calls and cost zero dollars. One optional feature (LLM-assisted harness synthesis for
hard-to-construct targets) activates **only** if you, the user running Tempest, set your own
`ANTHROPIC_API_KEY`. Your usage bills your key. No key is bundled, and the project maintainer
never pays for anyone's runs.

## Layout

- `packages/engine` — the product: nine-stage differential engine + `tempest` CLI (Python 3.12)
- `packages/ts-sidecar` — TypeScript analysis sidecar (JSON-RPC over stdio)
- `packages/api` — FastAPI ingestion/orchestration (also the desktop's stdio sidecar)
- `packages/desktop` — Tauri v2 desktop app (typed tri-boundary bindings, ADR-0014)
- `packages/shared-schema` — generated OpenAPI + TS types (zero-drift contract)
- `action/` — composite GitHub Action wrapping the CLI (PR check + evidence comment)
- `corpus/` — real-world validation corpora and fixture repos
- `docs/` — `PLAN.md` (phases + gates), `ARCHITECTURE.md`, `DECISIONS.md` (ADRs), `BUNDLE_SCHEMA.md`

## Development

```bash
make sync     # uv sync --all-packages && pnpm install
make verify   # every gate step live for the completed phases (see docs/PLAN.md)
```

Honest status lives in `docs/PLAN.md` — a phase is complete only when its gate commands ran with
real output attached.

## Licence

Tempest AI is open source under the [MIT Licence](LICENSE).

## Credits

Tempest's platform layer is **based on [LibreChat](https://github.com/danny-avila/LibreChat)**
(MIT), an excellent open-source multi-user chat platform. LibreChat solved several problems in
the open that would otherwise have taken us a year to get right — multi-provider endpoint
abstraction, resumable streaming, and production-grade MCP client behaviour — and Tempest adopts
those capabilities under the MIT licence, re-implemented for a local-first Rust/Tauri + Python
desktop application and wired into the proof engine.

Tempest is **not affiliated with or endorsed by LibreChat**, and uses none of its trademarks,
logos, or brand assets. Full attribution, the licence text, and a per-module derivation table
live in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md); the adoption scope — including
what we deliberately did **not** adopt, and why — is recorded in `docs/DECISIONS.md` (ADR-0038)
and `docs/PLATFORM-V2.md`.

The provider badges in the model selector adapt brand glyphs from
[LobeHub Icons](https://github.com/lobehub/lobe-icons) (MIT), used nominatively to label each
provider's own row; the marks remain their owners' property.
