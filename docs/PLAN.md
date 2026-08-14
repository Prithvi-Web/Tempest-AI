# Tempest AI — Phase Plan

> **For agentic workers:** execute phases in order, inline (no subagents — user preference).
> A phase is complete **only** when its gate commands have been run and their real output pasted
> into the session log, with the checkbox flipped in the same commit. Claimed-passing is failing.
> Every deviation from the master spec → ADR in `docs/DECISIONS.md`. `make verify` runs every gate
> step that is live for the phases completed so far; the `CLAUDE.md` §13 full list is the v1 done bar.

**Goal:** `tempest prove --base main --head HEAD` produces evidence-backed differential verdicts
(`DIVERGENT` / `EQUIVALENT_UNDER_BUDGET` / `UNPROVEN` / `ERROR`) for Python and TS changes, locally
and in CI, with a dashboard rendering the identical run bundles.

**Architecture:** nine one-directional stages (see `docs/ARCHITECTURE.md`). CLI is the source of
truth; API ingests the CLI's bundles; the web app renders them. Pydantic schemas → generated TS.

**Tech stack:** pinned in `CLAUDE.md` §5.

---

## Phase 0 — Skeleton ✅ 2026-08-13

- [x] Monorepo layout per master spec §6 (pnpm workspaces + uv workspace)
- [x] `packages/engine` — Python 3.12, `ruff` + `mypy --strict` + `pytest` configured
- [x] `packages/api` — FastAPI + Pydantic v2 skeleton with `/v1/health`, schemas package
- [x] `packages/ts-sidecar` — TS strict skeleton, vitest (JSON-RPC framing + 5 tests)
- [x] `packages/web` — Next.js 15 App Router, TS strict, Tailwind, TanStack Query
- [x] `packages/shared-schema` — generated `openapi.json` + `types.ts` (committed build output)
- [x] `pnpm gen:api` pipeline: FastAPI → openapi.json → openapi-typescript → typed client → hooks
- [x] `docker/` — compose stack (Postgres 16, Redis, MinIO, API, web) + sandbox image + seccomp profile
- [x] `.github/workflows/ci.yml` — lint / typecheck / test / contract-check / SAFE-grep
- [x] `Makefile` with `verify` target (grows per phase)
- [x] `CLAUDE.md`, `docs/PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`

**Gate passed 2026-08-13** — `make verify` output (abridged; full log in session):
```
All checks passed!                                   # ruff check
21 files already formatted                           # ruff format --check
Success: no issues found in 12 source files          # mypy --strict
7 passed, 1 warning in 0.47s  (coverage 97.85%)      # pytest --cov-fail-under=85
packages/shared-schema typecheck: Done               # pnpm -r typecheck ×3
packages/ts-sidecar   test: 5 passed (5)             # vitest
✓ Generating static pages (4/4)                      # next build
gen:api: openapi.json, types.ts, api-client.ts, hooks.ts regenerated
git diff --exit-code packages/shared-schema packages/web/src/generated   # zero drift
── verify: all live steps green ──
```
Live smoke test: uvicorn + `next dev` booted; browser rendered the dashboard shell with
`api ok · engine 0.1.0 · bundle schema v1` fetched through the *generated* client — zero console
errors. (Caught two real gaps: missing CORS middleware, undeclared uvicorn dep — both fixed.)

**Gate commands (for re-runs):**
```bash
make verify   # phase-0 scope: ruff, mypy --strict, pytest, pnpm -r typecheck, pnpm -r test,
              # gen:api drift check, web build, SAFE grep
```
Local constraint: `docker compose up` cannot be exercised on this machine (no Docker — ADR-0003);
compose files are validated with `docker compose config` in CI instead.

## Phase 1 — Pure-function differential, Python only ✅ 2026-08-13

Stages 1, 2, 3, 5, 6, 7, 8, 9 for `PURE_CANDIDATE` targets.

- [x] Stage 1 `targets/`: diff parsing, AST symbol extraction, changed-symbol classification
      (`PURE_CANDIDATE` / `IMPURE_RECORDABLE` / `UNREACHABLE` — every UNREACHABLE actionable);
      transitive-caller expansion is folded into classification's same-module callee scan for v1,
      full cross-module caller targets land with the TS work
- [x] Stage 2 `envrepro/`: `git worktree` materialization of base+head, env normalization
      (`LC_ALL=C.UTF-8`, `TZ=UTC`, `PYTHONHASHSEED=0`), lockfile fingerprints surfaced
- [x] Stage 3 `harness/`: deterministic type-driven adapters validated by EXECUTION (3-probe limit
      → `UNPROVEN(HARNESS_SYNTHESIS_FAILED)` with attempts); LLM synthesizer is BYOK-optional
      (ADR-0006) and intentionally not wired until a key-bearing env exists to exercise it
- [x] Stage 5 `generate/`: Hypothesis `from_type` (derandomized) + curated edge pools + corpus
      mining + structural mutation top-up; budgets; `changed_line_coverage` in every result
- [x] Stage 6 `execute/`: separate processes per revision, stdlib-only sandboxed worker,
      crash/hang as observations, settrace line+arc coverage, 3x fresh-pair flake confirmation,
      `NONDETERMINISTIC_BASE` → UNPROVEN
- [x] Stage 7 `compare/`: canonical trees (NaN==NaN, signed-zero LOW class, bool≠int), audited
      normalization ruleset, full `DivergenceClass` taxonomy
- [x] Stage 8 `minimize/`: greedy structural ddmin, DivergenceClass-preserving (property-tested),
      standalone repro scripts (always-valid syntax; summaries injected via repr)
- [x] Stage 9 `bundle/`: schema-versioned bundle + zip, §7 integrity enforced at the writer,
      round-trip tested; `docs/BUNDLE_SCHEMA.md`
- [x] `tempest prove --base <ref> --head <ref>` CLI end-to-end (exit 1 on DIVERGENT)
- [x] Fixture `corpus/fixtures/pyfix` (12 seeded behavior changes + 12 no-op refactors)

**Gate passed 2026-08-13** — real output (abridged; the gate also runs as
`tests/integration/test_prove_pyfix.py` in every CI run):
```
$ TEMPEST_DEV=1 tempest prove --base base --head head --repo pyfix --max-inputs 40
DIVERGENT — 31 divergence(s) across 12 target(s).
b01..b12  → all 12 DIVERGENT, changed-line coverage 100%, minimized repros written
n01..n12  → all 12 EQUIVALENT_UNDER_BUDGET, 0 false divergences
e.g. b01.clamp  minimized input (0,)  base: returned 0 / head: returned 1  → repros/b01_clamp_0.py
     b11        EXCEPTION_MESSAGE minimized to (-1,)
     b12        RETURN_VALUE (low severity) signed-zero at (0.0,)
exit code: 1 (DIVERGENT)                              # TEMPEST-EXIT=1 verified
$ pytest packages/engine -q
162 passed in 120.94s
```
Bugs the gate itself caught before passing: fake CRASH divergence on head-only helper symbols
(ADR-0008 §2) and repro scripts with unescaped quotes — both fixed and regression-locked.

## Phase 2 — Determinism layer (THE RISK PHASE)

Record/replay for clock, random, fs, net, proc in Python. Cassette = ordered content-addressed ledger.

- [ ] `determinism/cassette.py`: interaction ledger, keying `(surface, normalized_call_signature, ordinal)`
- [ ] `determinism/record.py` + `replay.py`: shim installer injected into target processes
- [ ] Shims: clock (`time.*`, `datetime.now/utcnow`), random (`random`, `os.urandom`, `uuid4`, `secrets`),
      fs (`open`, `os.*`, `pathlib`), net (`socket`-guard + `http.client` layer), proc (`subprocess`, `os.environ`)
- [ ] Effect-divergence detection: sequence diff, cassette miss = `DIVERGENT`, first divergent index
- [ ] Un-interceptable surface → `UNPROVEN(UNINTERCEPTABLE_EFFECT)` naming the exact surface
- [ ] 30-function real-world corpus (10 HTTP, 10 fs, 10 time/random) + `tempest.dev.corpus_check`

**Gate (run, paste real output; if <24/30 stable, STOP and report to the user):**
```bash
python -m tempest.dev.corpus_check --min-pass 24 --repeats 5   # byte-identical observations across 5 runs
```

## Phase 3 — TypeScript support

- [ ] `ts-sidecar`: JSON-RPC over stdio; ts-morph target selection over tsconfig (aliases, project refs)
- [ ] type→arbitrary compiler (TS type → fast-check arbitrary)
- [ ] Node determinism shims: `--import` loader, `Date`/`Math.random`/`crypto`/timers/fs/http/child_process/env
- [ ] V8 precise coverage via inspector protocol
- [ ] TS fixture corpus equivalent to Phase 1's + impure corpus equivalent to Phase 2's

**Gate:** Phase 1 and Phase 2 gates re-run against TS corpora, same thresholds (12/12 + 0 false; ≥24/30 × 5).

## Phase 4 — API + persistence

- [ ] Data model per master spec §7 (SQLAlchemy 2 async + Alembic; divergence row constraint:
      minimized input + repro script URI required — a DB constraint, not a code comment)
- [ ] Bundle ingestion `POST /v1/runs/{id}/bundle` → fan-out to tables; MinIO object storage
- [ ] Run orchestration via arq; SSE `GET /v1/runs/{id}/events`
- [ ] Full API surface per §8, cursor pagination, `{error:{code,message,details?}}`, idempotency keys
- [ ] Auth: GitHub OAuth (Auth.js) + short-lived JWTs + CLI PAT tokens

**Gate (run, paste real output):**
```bash
pytest packages/api -q   # includes round-trip property test:
                         # CLI bundle → ingest → reconstruct → no data loss
```

## Phase 5 — Web dashboard

- [ ] Runs list (verdict chips, filters, honest empty state)
- [ ] Run detail (SSE stage timeline; per-target table; **prominent "Not proven" panel**)
- [ ] Divergence detail (minimized input | base vs head observation diff | repro script copy/download;
      collapsible original input + shrink path)
- [ ] Target detail (changed-line coverage, arc-discovery curve, cassette summary)
- [ ] Repo settings (budgets, tolerances → writes `tempest.toml` PR, not server-only config)
- [ ] Generated client + hooks only; zero handwritten API types; exhaustive switches with `never` guards
- [ ] a11y: keyboard nav, focus states, `prefers-reduced-motion`, WCAG AA

**Gate (run, paste real output):**
```bash
pnpm test:e2e   # Playwright vs real API + seeded DB: CLI-run → ingest → render → repro-download
pnpm gen:api && git diff --exit-code packages/shared-schema packages/web/src/generated
```

## Phase 6 — CI integration

- [ ] GitHub Action wrapping the CLI
- [ ] PR check: fail only on `DIVERGENT`; `UNPROVEN` = neutral status + loud explanation
- [ ] PR comment with minimized repros; `tempest.toml` respected

**Gate:** end-to-end on a real GitHub repo — a seeded behavior-change PR → check fails with the
minimized repro in the comment (requires the repo to be published to GitHub first).

## Phase 7 — Hardening

- [ ] Sandbox escape review
- [ ] Budget/timeout tuning; perf targets measured (<60 s pure-PR on laptop)
- [ ] Bundle schema migration test
- [ ] Flake hunt: full corpus 20× — any nondeterminism in Tempest itself is a P0

**Gate:** full `CLAUDE.md` §13 list green + 20× corpus stability log attached.
