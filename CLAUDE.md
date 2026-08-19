# Tempest AI — Session Contract

Every session working in this repo reads this file first, then `docs/PLAN.md` (current phase + gates)
and `docs/DECISIONS.md` (ADRs — every deviation from the master spec is recorded there; deviating
silently is a failure).

---

## 1. Mission

Tempest AI is a **behavioral proof agent**. It does not review diffs — it *executes* them.

Given a code change, Tempest:

1. Reproduces an executable environment for both the **base** (pre-change) and **head** (post-change) revisions.
2. Synthesizes a test harness that can invoke the changed units in isolation.
3. Generates coverage-guided differential inputs.
4. Runs base and head **side by side under identical, deterministic conditions**.
5. Reports concrete inputs where observable behavior diverges — plus a **minimized reproduction**.

The output is **evidence, not opinion**. Canonical output sentences:

> "3 inputs produce different results. Here they are. Here is the smallest one."

> "I could not exercise `module.fn` — it opens a raw socket to an unrecorded host. I am not blessing this change."

**Tempest never guesses.** A change it could not run is `UNPROVEN`, never blessed.

Non-goals for v1: no LLM-authored verdicts (the differential runner computes verdicts; the LLM only
synthesizes harness adapters), no autonomous refactoring, no code-smell scoring, no lint opinions,
no vanity-metric dashboards.

---

## 2. The Laws (violating any of these is a build failure)

**L1 — Evidence or silence.** Every claim in every output is backed by a stored artifact: an input
value, a captured return value, an effect trace, an exit code. No artifact → the claim does not get made.

**L2 — Honest verdict vocabulary.** The only verdicts are:
- `DIVERGENT` — at least one input produced differing observable behavior. Includes the inputs.
- `EQUIVALENT_UNDER_BUDGET` — N inputs across M covered branches produced identical behavior.
  **This is not "correct."** The report states exactly what was and was not exercised.
- `UNPROVEN` — could not build a valid harness, could not reach determinism, or could not reproduce
  the environment. States the specific blocking reason with a machine-readable `reason_code`.
- `ERROR` — Tempest itself failed. Includes the internal trace.

The string `"SAFE"` must not appear anywhere in the product surface. CI greps for it and fails the build.

**L3 — Determinism before comparison.** If base and head cannot be placed in identical conditions,
the run is `UNPROVEN`. Never compare under uncontrolled nondeterminism; never "retry until it agrees."

**L4 — No fabricated execution.** Never write code that simulates, mocks, or hardcodes a run result
to make a test pass. Every green test corresponds to real execution.

**L5 — Contract-first integration.** Backend Pydantic models are the single source of truth.
Frontend types are **generated**, never handwritten. A drift check runs in CI (see §9).

**L6 — Sandbox by default.** Every execution of user code happens inside a container with no network,
a read-only FS except a scratch mount, wall-clock and memory limits, and a non-root user.
No exceptions, no flags to disable in v1. (See ADR-0003 for behavior on machines without a
container runtime: the run is `UNPROVEN` with `reason_code=SANDBOX_UNAVAILABLE` — never silently unsandboxed.)

**L7 — Reproducible run artifacts.** Every run writes a self-contained, replayable bundle.
A divergence a user cannot re-run themselves is worthless.

### Desktop-era Laws (Phase 8+ master prompt — additive; L1–L7 all still binding)

**L8 — Local-first is absolute.** Every core capability works with the network cable unplugged:
prove a change, view history, export a repro, read a bundle. Cloud is additive. A feature that
requires network to function is not a core feature.

**L9 — Source code never leaves the machine without explicit, per-repo, opt-in consent.** Not in
telemetry, not in crash reports, not in diagnostic bundles, not in error strings. This is the claim
the enterprise sale rests on, and it must be **provable by test**, not by policy document (see L10).

**L10 — Egress is tested, not promised.** CI runs the full corpus inside a network namespace with a
deny-all egress monitor. Any outbound connection in local mode fails the build. The test output is
a sales artifact — publish it.

**L11 — The user's machine is not your CI runner.** Every long operation is cancellable, budgeted,
and yields to the user. Tempest must never make a laptop unusable: CPU affinity caps, memory
ceilings, and a hard "pause on battery / on thermal pressure" behavior.

**L12 — Three boundaries, one truth** — **four as of v2.** Type drift across the
Python↔Rust↔TypeScript boundary is the defining integration risk of the desktop architecture,
and it is solved by **generation, not discipline** (see the Tri-Boundary Contract below).
v2 adds a fourth: the **Agent Tool Protocol** (§9c, ADR-0035). Four boundaries, still one truth;
the gate is one command, `make gen-contracts && git diff --exit-code`.

**L13 — Signed or it doesn't ship.** No unsigned artifact reaches a user, ever, including dev
builds shared with design partners.

**L14 — Every destructive or privileged action is audit-logged** to an append-only, tamper-evident
local log, regardless of whether the customer has enterprise features enabled.

### v2-era Laws (v2.0.0 master prompt §2 — additive; L1–L14 all still binding)

> Where v2 conflicts with v1, **v1 wins** unless an ADR says otherwise.
> Feature detail: `docs/FEATURES-V2.md` · phases: `docs/PLAN-V2.md` · threats:
> `docs/THREAT-MODEL-V2.md` · polish: `docs/POLISH.md`.

**L15 — The seven zero-properties are gates, not goals.** "Zero errors" is operationalized as:
1. **Zero unhandled states** — every async operation implements loading, empty, error, partial,
   cancelled, and stale. Lint rule + Storybook coverage check per data-bound component.
2. **Zero untyped boundaries** — no `Any`, no `as any`, no `unwrap()` in Rust outside tests, no
   unchecked JSON; every enum exhaustively matched in all languages.
3. **Zero silent failures** — every `catch` either recovers meaningfully or surfaces to the user
   with an actionable message and a diagnostic ID. A `catch` that logs and continues is a build failure.
4. **Zero unbounded operations** — every loop, retry, agent turn, token spend, and file walk has an
   explicit budget and a cancellation path.
5. **Zero data loss** — every user-visible mutation is journaled and undoable; crash mid-operation
   loses nothing.
6. **Zero regressions escape** — Tempest proves its own PRs with Tempest, gated in CI.
7. **A published, enforced error budget** — crash-free session rate ≥ 99.9%; agent turn failure
   rate ≤ 0.5%; measured in CI and production telemetry; a regression blocks release.

**L16 — The agent may never bypass the proof gate.** Any path where an agent-authored change
reaches the user marked verified without an actual differential run is a critical bug. There is no
`--skip-proof`, no "fast mode" that fakes it. Unproven agent output is labeled `UNPROVEN` with the
same prominence as everywhere else. Enforced by a DB constraint plus an adversarial forge test.

**L17 — The agent's confidence is computed, never generated.** A model may never write into a
confidence, verdict, or risk field; those are engine outputs. Model text goes in explanation fields
only, visually distinguished in the UI as narration, not evidence.

**L18 — BYO inference, always.** Users supply their own API keys or run local models. Tempest never
proxies source code through infrastructure we control (preserves L9/L10). See ADR-0037.

**L19 — The agent runs in the sandbox.** Agent file writes are staged in a shadow worktree, never
the user's working tree, until accepted. Agent terminal commands run at differential-runner
isolation tiers. The agent is untrusted code that happens to be on your side. See ADR-0036.

**L20 — Every agent action is reversible.** One-keystroke undo for any agent change, including
multi-file edits and terminal side effects Tempest initiated. Journaled — not "hopefully git has it."

**L21 — Cost is visible before it is spent.** Token and dollar estimates before any operation over
a user-set threshold; a running meter; hard caps per task, per session, per day. Never a surprise bill.

**L22 — Latency budgets are gates.** The performance table in `docs/PLAN-V2.md` / master prompt §5
is enforced in CI from Phase 19. A feature that misses its budget does not ship; it gets fixed or cut.

**L23 — Offline degradation is graceful and explicit.** With no network and no local model, every
proof feature still works fully and every generative feature is disabled with a clear, specific
reason — never a spinner, never a silent failure.

**L24 — Dogfood or don't ship.** Tempest's own repo runs Tempest on every PR. The Tempest-on-Tempest
proof rate is published in the README and tracked over time.

---

## 5. Stack (fixed — deviations require an ADR in docs/DECISIONS.md)

**Monorepo**: pnpm workspaces + uv workspace.

| Layer | Choice |
|---|---|
| Engine core | Python 3.12, strict typing, `mypy --strict`, `ruff` |
| TS analysis sidecar | Node 22+ + TypeScript 5.x, `ts-morph`, `fast-check`; JSON-RPC over stdio to the Python core |
| CLI | Python, `typer` + `rich`; ships standalone via `uv tool` / PyInstaller |
| Sandbox | Docker (rootless-compatible), per-run ephemeral containers, seccomp profile, no network namespace |
| Backend API | FastAPI, Pydantic v2, async SQLAlchemy 2.x, Alembic |
| DB | PostgreSQL 16 — JSONB for observation payloads, real columns for anything queried |
| Object storage | S3-compatible (MinIO in dev) for run bundles |
| Queue | Redis + `arq` for run orchestration |
| Frontend | Next.js 15 (App Router), React 19, TypeScript strict, Tailwind, shadcn/ui, TanStack Query v5 |
| Charts | Recharts only where a chart genuinely beats a table; default to tables |
| Auth | GitHub OAuth via Auth.js; API uses short-lived JWTs; CLI uses a PAT-style token |
| Tests | `pytest` + Hypothesis (engine), `vitest` (TS sidecar + frontend units), Playwright (E2E) |
| CI | GitHub Actions |

---

## 9. Frontend ↔ Backend Integration Contract — ZERO DRIFT

**Single source of truth: Pydantic v2 models in `packages/api/src/tempest_api/schemas/`.**
Nothing else defines a shape.

**Generation pipeline** — one script, `pnpm gen:api`, wired into `predev`, `prebuild`, and CI:

1. FastAPI emits `openapi.json` → committed to `packages/shared-schema/openapi.json`.
2. `openapi-typescript` → `packages/shared-schema/types.ts`.
3. `openapi-fetch` typed client → `packages/web/src/lib/api-client.ts`.
4. Thin generated TanStack Query hooks → `packages/web/src/generated/hooks.ts`.

**The drift gate.** CI job `contract-check`:

```
pnpm gen:api && git diff --exit-code packages/shared-schema packages/web/src/generated
```

Non-empty diff = red build. No overrides.

**Hard rules:**
- The frontend **never** declares an interface that mirrors a backend model. Import from
  `shared-schema` or fail review.
- No raw `fetch` in components — only generated hooks. ESLint enforces it inside `src/app` and
  `src/components`.
- Enums (`Verdict`, `DivergenceClass`, `ReasonCode`, `Stage`, `ErrorCode`) are defined **once** in
  Python, exported through OpenAPI, consumed as TS union types. Exhaustive `switch` with a `never`
  guard on every one — adding a variant in Python must break the TS build. That is desired.
- Every API response the UI renders gets a Zod parse at the boundary in dev mode (generated from the
  same OpenAPI), so contract violations surface immediately.
- SSE events: one Pydantic `RunEvent` union → one TS discriminated union → one exhaustive reducer.
- Playwright E2E runs against the **real** API with a seeded DB. No mocked network in E2E. MSW only
  in component-level tests, with handlers generated from the OpenAPI spec.
- Loading, empty, error, and partial states are designed for every view before the happy path is
  styled. `UNPROVEN` is a first-class UI state, not an error toast.

---

## 9b. Tri-Boundary Contract (desktop — Phase 8+ §3) — the L12 mechanism

The v1 contract above (one boundary: Python API ↔ TS web) still holds. Desktop adds two more:

```
   Python engine  ──(A)──►  Rust host (Tauri)  ──(B)──►  TypeScript webview
        │                                                        │
        └───────────────────────(C: domain types)────────────────┘
```

**Root of truth:** the Pydantic v2 models remain the single source of all domain types
(`RunBundle`, `TargetResult`, `Divergence`, `Observation`, `Cassette`, `Verdict`,
`DivergenceClass`, `ReasonCode`, `Stage`, `ErrorCode`).

- **Boundary A (Python ↔ Rust):** JSON-RPC 2.0 over stdio with length-prefixed framing — never
  HTTP-on-TCP (a listening port fails enterprise security review; the current shell's
  HTTP-on-127.0.0.1 is a v1-era bridge that Phase 9 must replace). Types: Pydantic JSON Schema →
  `typify` → committed generated Rust. The sidecar is a child process the Rust host owns: started,
  health-checked, restarted with backoff, killed on exit — process-group ownership so orphans are
  impossible even under SIGKILL.
- **Boundary B (Rust ↔ TS):** Tauri IPC with `tauri-specta`-generated bindings for every command
  and event. Handwritten `invoke()` calls are banned; ESLint enforces it.
- **Boundary C (Python ↔ TS):** the same JSON Schema → `json-schema-to-typescript` → committed
  generated domain types. Rust and TS both derive from one schema; they cannot disagree.

**The gate** (runs in `predev`, `prebuild`, and CI as `contract-check`; no overrides, ever):

```
make gen:contracts && git diff --exit-code packages/desktop/src/generated packages/desktop/src-tauri/src/generated
```

**Enum discipline:** every enum exhaustively matched in all three languages — Rust `match` with no
wildcard arm, TS `switch` with a `never` guard, Python `assert_never`. Adding a `ReasonCode` in
Python must break the Rust build *and* the TS build. That is the design working.

**Round-trip property test:** arbitrary `RunBundle` values generated in Python → serialize →
deserialize in Rust → re-serialize → deserialize in TS → structural equality. Runs in CI.

---

## 9c. The FOURTH boundary — Agent Tool Protocol (v2 §3) — ADR-0035

v2 adds a fourth generated boundary: **the schema of every tool the agent can call.** It crosses
all three existing boundaries *and* crosses into a model, where the failure mode is worse than a
type error — a model handed a stale tool schema produces plausible calls that silently do the
wrong thing.

```
   Python engine ──(A)──► Rust host ──(B)──► TypeScript webview
        │                    │  ▲                    │
        └────────(C)─────────┼──┼────────────────────┘
                             │  │
                    (D: Agent Tool Protocol)
                             ▼
                    model-facing tool definitions (per provider)
```

**Root of truth for boundary D: a Rust trait per tool + `schemars`-derived JSON Schema** — Rust,
not Python, because the orchestrator owns tool dispatch, budget enforcement, and capability
checks; the enforcement point and the schema must not be able to disagree. Generated from it:
the TS bindings, the per-provider model-facing tool definitions, and the audit-log entry shape.
Domain *values* inside tool arguments stay Pydantic-rooted (boundary C) — referenced, never redefined.

**The gate — four boundaries, still one truth** (`predev`, `prebuild`, CI `contract-check`; no overrides):

```
make gen-contracts && git diff --exit-code
```

Adding a tool or changing an argument breaks the TS build and the drift gate until regenerated and
committed. That is the design working. Adding a model provider must not touch feature code.

---

## 13. Verification (`make verify` — must pass before any completion claim)

```
ruff check && ruff format --check
mypy --strict packages/engine/src packages/api/src
pytest packages/engine packages/api -q --cov --cov-fail-under=85
pnpm -r typecheck
pnpm -r test
pnpm gen:api && git diff --exit-code packages/shared-schema packages/web/src/generated
pnpm --filter web build
pnpm test:e2e
grep -rn --include='*.py' --include='*.ts' --include='*.tsx' -w 'SAFE' packages/ && exit 1 || true
python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
```

**Rule: never say "done", "working", "complete", or "passing" without pasting the actual output of
these commands in the same message.** Claimed-passing is treated as failing. `make verify` grows with
the phases (see `docs/PLAN.md`); each phase's gate lists exactly which steps are live at that point.
The full list above is the definition-of-done bar for v1.

---

## Working discipline (from master spec §12)

- **TDD, strictly** — failing test → minimal implementation → refactor. Property-based tests for
  comparison, minimization, and cassette logic.
- **Types everywhere** — `mypy --strict`, `tsc` strict. No `Any`, no `as any`, no `# type: ignore`
  without an inline justification.
- **Small, coherent conventional commits.** One logical change each.
- **No dead code, no TODO-as-deferral** — undone work is a `docs/PLAN.md` item, not a comment.
- **Error messages are the product.** Every `UNPROVEN` reason must be actionable.
- **Performance targets:** 200-line PR / 5 pure functions < 60 s on a laptop; with recorded IO < 3 min.
- Append an ADR to `docs/DECISIONS.md` for every deviation from the master spec.
