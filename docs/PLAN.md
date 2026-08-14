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

## Phase 2 — Determinism layer (THE RISK PHASE) ✅ 2026-08-13 — 30/30

Record/replay for clock, random, fs, net, proc in Python. Cassette = ordered ledger, keyed
`(surface, normalized_call, per-key ordinal)`; per-input sessions + an import-session so
`from x import y` bindings capture the shims (`determinism/_shims.py`, stdlib-only, copied into
the sandbox beside the worker).

- [x] Session/cassette ledger with per-key ordinal queues and global order
- [x] Shims: clock (`time.time/_ns/monotonic/_ns`, `datetime.now/utcnow/today`), random
      (`random.*` incl. index-keyed choice + permutation-keyed shuffle, `os.urandom` → covers
      uuid4/secrets), fs (`open` r/w/a with content capture, `os.listdir/path.exists/getcwd`,
      env proxy), net (`urlopen` incl. HTTPError replay + raw-socket guard — ADR-0010), proc
      (`subprocess.run`, `os.system`, Popen guard)
- [x] Effect divergence: ledger comparison with first divergent index; cassette miss =
      `DIVERGENT(CASSETTE_MISS)`; internal-machinery interactions excluded from the ledger
- [x] Un-interceptable surface → `UNPROVEN(UNINTERCEPTABLE_EFFECT)` naming the exact surface
- [x] `prove_impure_target`: record → base replay-verify → head replay, 3x flake confirmation,
      wired into `tempest prove` for IMPURE_RECORDABLE targets
- [x] 30-function corpus (10 HTTP via loopback, 10 fs, 10 time/random) + `tempest.dev.corpus_check`
      (in `make verify`)

**Gate passed 2026-08-13** — real output:
```
$ python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
tempest corpus check: 30 impure functions × 5 replays
  STABLE   httpfns.fetch_user_name('__LOOPBACK__',)
  ... (all 30 lines STABLE — incl. retry_on_404, double_read_same_endpoint,
       shuffled_copy, request_id, append_audit_line, env_or_file_setting)
30/30 stable across 5 consecutive replays        # bar: ≥24 — exit 0
```
Real bugs the phase surfaced and fixed: from-import bindings bypassing shims (fixed via
pre-import install + import-session), loopback server threads polluting the ledger (internal
thread flagging), record-side urlopen env probes leaking into effects (internal-passthrough
rule), HTTPError paths unreplayable (recorded error payloads).

## Phase 3 — TypeScript support (analysis half ✅ 2026-08-13; gate NOT met yet — execution half open)

- [x] `ts-sidecar` analysis: JSON-RPC over stdio; ts-morph target selection over tsconfig
      (path aliases; project references still root-only), innermost-fn resolution, classification
      mirroring the Python rules (27 sidecar tests, real temp projects, zero mocks)
- [x] `valuePools`: type-checker-driven deterministic per-parameter pools (numbers/strings/
      unions/optionals/interfaces/Records; NaN/Infinity as `specials`) — the fast-check
      compiler's precursor
- [x] Python bridge `targets/ts_sidecar.py` (persistent client, 30s deadlines, actionable
      unavailable-errors; launched via `node --experimental-strip-types`, locked erasable-only)
- [ ] Node execution worker + determinism shims (`--import` loader: Date/Math.random/crypto/
      timers/fs/http/child_process/env)
- [ ] V8 precise coverage via inspector protocol; type→fast-check arbitrary compiler
- [ ] TS fixture corpora (12+12 and 30-impure equivalents); stage-1/5 engine wiring for
      `Lang.TYPESCRIPT`

**Gate:** Phase 1 and Phase 2 gates re-run against TS corpora, same thresholds (12/12 + 0 false;
≥24/30 × 5). **Not yet run — the boxes above stay honest.**

## Phase 4 — API + persistence ✅ core 2026-08-13 (orchestration/auth/MinIO deferred, listed below)

- [x] Data model per master spec §7: repos, runs, targets, divergences, cassettes, run_events,
      api_tokens (SQLAlchemy 2 async, typed Mapped[]; divergence evidence NOT NULL **in the DDL**,
      proven by below-the-app IntegrityError tests; JSONB-on-Postgres via one TypeDecorator)
- [x] Alembic initial migration + migration↔model parity test (upgrade head ≡ create_all) + clean
      downgrade; aiosqlite locally / Postgres 16 in CI+prod (ADR-0009 — dialect CI job is a
      recorded standing obligation)
- [x] Bundle ingestion `POST /v1/runs/{id}/bundle`: multipart zip → guarded extract → engine
      `read_bundle` → single-transaction fan-out; corrupted bundles → 400 with stable codes and
      **atomically nothing written**; verdicts stored verbatim, never re-derived
- [x] §8 surface: createRun (202, Idempotency-Key replay + 409 on body mismatch), listRuns
      (opaque cursor `{items,next_cursor}`, filters), getRun/getTarget/getDivergence,
      getDivergenceRepro (text/x-python download), getHealth; stable ErrorCode enum; engine enums
      imported from `tempest.model` only
- [ ] Run orchestration via arq + SSE `/v1/runs/{id}/events` (run_events ledger already
      populated; stream endpoint lands with orchestration)
- [ ] MinIO bundle-blob retention; auth issuance (api_tokens table shipped — ADR-0007)

**Gate passed 2026-08-13** — real output (independently re-verified in the main session):
```
$ uv run pytest packages/api -q      # incl. Hypothesis round-trip property (25 derandomized
33 passed, 1 warning in 1.43s        #  arbitrary bundles): write→zip→upload→GET-reconstruct→equal
$ uv run mypy --strict packages/api/src
Success: no issues found in 25 source files
```

## Phase 5 — Web dashboard (views ✅ 2026-08-13; E2E + SSE timeline open)

- [x] Runs list (verdict chips, `?verdict=` filter as URL state, cursor pagination, honest empty
      state with real CLI/API commands)
- [x] Run detail (per-target table grouped by classification; **double-bordered NOT PROVEN
      panel** with reason chips; deps-mismatch warning; SSE stage timeline pending the
      `RunEvent`/`Stage` contract — see API-gap list in session log)
- [x] Divergence detail (minimized input + copy; base vs head side-by-side; repro script via
      generated text hook with copy/download; collapsible original input + shrink path)
- [x] Target detail (CSS coverage bar — green only at 100%, inputs/equivalent/unprovable counts,
      divergence links; arc-curve + cassette summary pending contract fields)
- [ ] Repo settings view (budgets/tolerances → tempest.toml PR)
- [x] Generated client + hooks only (generator now emits path/query-param typed hooks +
      `urlFor*` for text downloads); zero handwritten API shapes; exhaustive switches over all
      8 contract enums with `assertNever` — drift gate proven empirically (fake variant → 4 TS
      errors)
- [x] a11y: keyboard-first rows, global `:focus-visible` ring, `prefers-reduced-motion`, dense
      mono instrument-panel aesthetic
- [ ] Dev-mode Zod boundary parse; ESLint no-raw-fetch rule; Playwright E2E (integrated pass)

**Gate — drift half passed 2026-08-13** (`pnpm gen:api && git diff --exit-code …` → zero drift,
byte-identical across reruns; typecheck + `next build` green, 4 routes). **E2E half not yet run**
(Playwright suite is an open item above). Live smoke was executed instead: real pyfix run →
real API ingest → all four routes rendered with zero console errors, incl. an all-UNPROVEN run
(SANDBOX_UNAVAILABLE) and an error-envelope path.

## Phase 6 — CI integration

- [x] GitHub Action wrapping the CLI (`action/action.yml` + `action/README.md`): installs the
      engine via `uv tool install`, runs `tempest prove`, always uploads the run bundle as an
      artifact, renders the comment with `tempest ci-comment`, posts/updates a single PR comment
      (`<!-- tempest-report -->` marker, `gh api`)
- [x] PR check: fail only on `DIVERGENT` (or `ERROR` — Tempest's own failure); `UNPROVEN` =
      exit 0 + one `::warning` annotation per unexercised target with its reason code
- [x] PR comment with minimized repros (`tempest ci-comment --bundle <dir>` — deterministic GFM;
      golden-tested in `tests/unit/test_ci_comment.py`); `tempest.toml` respected
      (`tempest/config.py`: `[budgets] max_inputs`/`max_wall_seconds`, `[compare] float_rel_tol`,
      `[ignore] globs`; precedence CLI flag > file > default; unknown keys are a listed hard
      error; tested in `tests/unit/test_config.py`)
- [x] Self-test workflow `.github/workflows/tempest-selftest.yml`: runs the action against the
      materialized pyfix fixture on every PR (TEMPEST_DEV=1 ProcessSandbox path, ADR-0008) and
      asserts DIVERGENT is caught, the check fails, and the comment carries the evidence

**Gate:** end-to-end on a real GitHub repo — a seeded behavior-change PR → check fails with the
minimized repro in the comment (requires the repo to be published to GitHub first; the selftest
workflow is that gate's standing rehearsal, and the full pipeline — prove → bundle → ci-comment →
verdict-case logic incl. the jq annotations — was executed locally against pyfix: 12/12 divergent,
exit 1, comment rendered with minimized inputs + repros).

## Phase 7 — Hardening (core ✅ 2026-08-13; container-leg review open)

- [x] Sandbox escape review — `docs/SANDBOX_REVIEW.md` (container-leg verification requires a
      Docker-equipped machine; tracked there, not hidden)
- [x] Perf target measured, not assumed: 5 pure targets at the default 300-input budget →
      **3.9 s wall** (bar: <60 s), both seeded bugs caught, 0 false alarms on the no-ops
- [x] Bundle schema migration tests (newer-version refusal with upgrade guidance; integer
      version pinned from day one)
- [x] Flake hunt: full corpus ×20 — **30/30 stable, zero nondeterminism in Tempest itself**
      (`docs/flake-hunt-20x.log`)
- [x] Transport bug found by the hardening pass and fixed with regression tests: `frozenset`
      inputs NameError'd in the extended-literal parser

**Gate status 2026-08-13** — `make verify` **exit 0**, real output:
```
All checks passed!                                  # ruff (112 files formatted)
Success: no issues found in 65 source files         # mypy --strict engine+api
373 passed · coverage 88.95% (bar 85%)              # pytest engine+api
30/30 stable across 5 consecutive replays           # corpus_check (§13)
typecheck: Done ×3 · sidecar 27 passed              # pnpm -r
✓ Compiled successfully                             # next build
gen:api … + git diff --exit-code                    # zero contract drift
── verify: all live steps green ──
```
§13 steps NOT yet live (open items above, never skipped silently): `pnpm test:e2e`
(Playwright suite not built yet) and the TS-corpus half of corpus_check (Phase 3 execution
half). The v1 definition-of-done requires both.
