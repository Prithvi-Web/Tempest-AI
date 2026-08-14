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
