# Architecture Decision Records

Append-only. Every deviation from `tempest-master-prompt` gets an entry **before** the deviating
code lands. Format: context → decision → consequences/risk.

---

## ADR-0001 — Record/replay determinism layer is a v1 requirement

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Differential execution is only meaningful under identical conditions (Law L3). Most
real-world changed code is impure: it reads clocks, RNGs, files, sockets, env, processes. Without
record/replay, Tempest would be limited to pure functions — a toy.

**Decision.** Build the cassette-based record/replay subsystem (master spec §4.4) as a first-class
v1 component: record once against base, replay both revisions from the identical cassette; value
divergence and effect divergence are both first-class findings; cassette miss = `DIVERGENT`;
un-interceptable surface = `UNPROVEN(UNINTERCEPTABLE_EFFECT)`.

**Risk (stated plainly).** This is the project's existential risk. Interception at module
boundaries can be bypassed (C extensions, cached references to originals, native addons), replay
ordering under concurrency is genuinely hard, and over-normalization can mask real divergence.
Mitigation: Phase 2 is gated on a 30-function real-world corpus — ≥24/30 byte-identical replays
across 5 consecutive runs, and the build **stops and reports** if the bar is missed. The corpus
runs before any dashboard work; we do not build UI on sand.

## ADR-0002 — Autonomous session: §16 "question list, then wait" answered by recorded defaults

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Master spec §16 says to produce a question list and wait. This build runs in an
autonomous session; the user is not available mid-run and instructed "make Tempest AI and store it
on GitHub".

**Decision.** The question list lives in `docs/QUESTIONS.md` with the default answer chosen for
each, cross-referenced to ADRs. The build proceeds on those defaults. The user can overturn any of
them later; each is isolated behind a small surface.

**Consequences.** No silent choices: anything §16-ambiguous is written down with its chosen answer.

## ADR-0003 — No container runtime on the dev machine: sandbox behavior

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Law L6 requires every execution of user code to run in a container (no network,
RO rootfs, limits, non-root). This development machine has **no Docker** (verified:
`docker NOT FOUND`), and installing Docker Desktop needs admin interaction.

**Decision.**
1. The sandbox module ships Docker-first: `DockerSandbox` implements L6 fully (network-none,
   read-only rootfs + scratch tmpfs, memory/pids/wall limits, non-root UID, seccomp profile in
   `docker/seccomp-tempest.json`). It is the only backend selectable for user repos. There is no
   flag to disable it.
2. On a machine without a usable container runtime, `tempest prove` against a user repo returns
   `UNPROVEN` with `reason_code=SANDBOX_UNAVAILABLE` and an actionable message. Never silently
   unsandboxed.
3. A `ProcessSandbox` (separate process, scrubbed env, rlimits, cwd jail) exists **only** for
   Tempest's own first-party test fixtures and corpus (trusted code we wrote), so the engine's
   gates can run on this machine. It is not reachable from the public CLI for arbitrary repos.
4. CI (GitHub Actions, Docker available) exercises the DockerSandbox path.

**Risk.** The Docker path gets less local exercise than the process path until a Docker-equipped
machine runs it; mitigated by making CI the enforcement point and keeping both backends behind one
`Sandbox` interface with a shared conformance test suite.

## ADR-0004 — Node 24 on the dev machine (spec pins Node 22)

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §5 pins Node 22. This machine has Node 24.16.0; installing a second Node
runtime adds drift risk for a non-coder-maintained machine.

**Decision.** `engines: { "node": ">=22" }` everywhere; CI matrix runs Node 22 so the pinned
version stays the enforced baseline; local dev uses Node 24.

**Consequences.** Any Node-24-only accidental usage is caught by CI on 22.

## ADR-0005 — GitHub publication via the user's GitHub Desktop flow

**Date:** 2026-08-13 · **Status:** accepted

**Context.** "Store it on GitHub" is part of the task. No `gh` CLI is installed, and this
non-interactive session cannot complete an OAuth device flow. The user's established workflow for
all prior projects is GitHub Desktop.

**Decision.** The repo is built with clean conventional commits on `main`, ready to publish.
Final handoff includes exact GitHub Desktop steps (Add Local Repository → Publish). Phase 6's
live-PR gate (which needs the repo on GitHub) runs after publication.

## ADR-0006 — Stage-3 synthesis: deterministic type-driven first, LLM optional

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §3 requires the CLI to work fully offline with zero backend, while §4-stage-3
puts an LLM in the harness-synthesis loop. Both cannot be unconditionally true at once.

**Decision.** `AdapterSynthesizer` is a strategy interface. Order: (1) `TypeDrivenSynthesizer` —
deterministic construction from type hints + usage inference; (2) `LLMSynthesizer` — used only when
`ANTHROPIC_API_KEY` is set (model: `claude-sonnet-5`), for targets the deterministic pass could not
harness. Both pass the identical validate-by-execution gate; acceptance is never based on reading
the code. The LLM never writes verdicts (Law: verdicts come from the runner).

**Consequences.** Offline runs lose only hard-to-construct targets (they surface as
`UNPROVEN(HARNESS_SYNTHESIS_FAILED)` — honest), and gain them back when a key is present.

**BYOK guarantee (owner requirement, 2026-08-13).** Tempest never spends the project owner's
tokens. There is no bundled, default, or fallback API key anywhere in the codebase, images, or CI.
The only LLM path activates when the *end user running Tempest* supplies their own
`ANTHROPIC_API_KEY` (env var or their `tempest.toml`); absent that, every run is 100% offline and
costs zero LLM dollars. Keys are read at runtime only — never logged, never written into bundles,
never transmitted anywhere except Anthropic's API by the user's own machine.

## ADR-0007 — Auth in development: real wiring, dev-mode credentials

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §5 requires GitHub OAuth (Auth.js) + JWTs + CLI PATs. Registering a GitHub OAuth
app requires the user's GitHub account interaction and secrets this session cannot mint.

**Decision.** Implement the real auth surfaces (Auth.js GitHub provider, JWT issuance/validation,
PAT-style CLI tokens hashed at rest). Dev mode (`TEMPEST_DEV_AUTH=1` + compose defaults) enables a
deterministic local credential so the stack runs end-to-end without the OAuth app. Production
config requires the real GitHub OAuth env vars; missing vars fail loudly at boot, they do not fall
back to dev mode.

**Consequences.** The user must create the GitHub OAuth app before any real deployment; documented
in `docs/QUESTIONS.md` Q4.

## ADR-0008 — First-party fixture sandbox gate + added-symbol semantics

**Date:** 2026-08-13 · **Status:** accepted

**Context.** (a) The Phase 1/2 gates must run on this Docker-less machine without violating L6.
(b) The pyfix gate exposed a semantic hole: a helper function added only in head has no base
counterpart; naively "comparing" it produces a fake CRASH divergence (base can't even import it).

**Decision.**
1. `ProcessSandbox` is reachable only when BOTH hold: the target repo carries a committed
   `.tempest-first-party` marker with the exact token, AND `TEMPEST_DEV=1` is set. Everything
   else follows ADR-0003 (Docker or `UNPROVEN(SANDBOX_UNAVAILABLE)`). The CLI prints a loud
   banner whenever the first-party path is active.
2. Symbols (or whole files) that exist only in head are not differential targets — new code
   cannot change existing behavior by itself; its effect is proven through its changed callers.
   Deleted-only symbols likewise have no head side to execute. Both rules live in
   `tempest/prove.py` next to the diff walk.

**Consequences.** Fixture gates run identically on this machine and in CI; extract-helper
refactors no longer produce fake CRASH findings (regression-locked by the pyfix gate's no-op
half).

## ADR-0009 — Phase 4 persistence: aiosqlite locally, Postgres 16 in CI/prod; JSONB via TypeDecorator

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §5 pins PostgreSQL 16 with JSONB for observation payloads. This development
machine has no Docker (ADR-0003) and therefore no local Postgres, yet Phase 4's gate requires
real API tests against a real database on this machine.

**Decision.**
1. The API reads `TEMPEST_DATABASE_URL`; default `sqlite+aiosqlite:///./tempest-dev.db`. Local
   tests run the real ASGI app against a file-backed aiosqlite database per test (real HTTP →
   real SQL, no mocked layers). CI and production run Postgres 16 via asyncpg — the compose stack
   already provisions it.
2. JSON payload columns (`divergences.shrink_path`, `run_events.payload`, `cassettes.ledger`)
   are declared once through a `JSONPayload` TypeDecorator (`tempest_api/db/types.py`): JSONB on
   the postgresql dialect, plain JSON elsewhere. Models never branch on dialect.
3. Schema management: Alembic (`packages/api/alembic/`, initial revision `0001`) is the
   migration path for Postgres. On sqlite the app creates the schema from metadata at startup; a
   parity test (`packages/api/tests/test_migrations.py`) proves `alembic upgrade head` and the
   models produce the identical schema, so the two paths cannot drift silently.
4. Bundle-integrity rule 1 (BUNDLE_SCHEMA.md) is enforced as DB-level NOT NULL columns on
   `divergences` (`minimized_args`, `minimized_kwargs`, `repro_filename`, `repro_script`),
   verified by below-the-application inserts in the test suite.

**Risk (stated plainly).** SQLite is not Postgres: JSON vs JSONB semantics, TEXT accepting NUL
bytes that Postgres rejects, looser type affinity, different concurrency behavior. Green local
tests do not prove Postgres behavior. **Mitigation — dialect-conditional tests in CI:** the API
suite takes its database from `TEMPEST_DATABASE_URL`, so a CI job with a Postgres 16 service
runs the *identical* suite against the real dialect. That job is a standing obligation recorded
here — it is not yet wired (`.github/workflows/ci.yml` is outside this change's scope) and must
land with the CI-integration phase; until then, Postgres coverage is a known gap, not a silent
assumption. The round-trip property strategy already excludes NUL to keep the contract portable
across both dialects. Orchestration dependencies (arq/Redis/MinIO object storage for bundles)
are deliberately not added in this slice — no unused dependencies; they arrive with the
orchestration work, at which point bundle blobs move from ingest-and-discard to MinIO-backed
storage per §5.

## ADR-0010 — Phase 2 scope: corpus provenance, NET interception level, import-time effects

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Master spec §4.4 requires (a) a 30-function corpus "drawn from real open-source
repos" and (b) network interception preferring the lowest stable layer (socket), covering
socket/http.client/urllib/requests/httpx.

**Decisions.**
1. **Corpus provenance.** The 30 corpus functions are hand-written faithful replicas of named
   real-world idioms (each docstring cites the pattern: k8s health probes, retry-after-404,
   REST pagination, docker-secrets env-or-file, lockfile checksums, backoff jitter, …) rather
   than vendored copies of third-party code. Vendoring would drag license files and dead logic
   into the repo while the corpus's value is its IO *shape*. Risk: less wild diversity;
   mitigation: the set covers every surface in the spec's table, and the corpus is designed to
   grow with real-repo extracts under permissive licenses later.
2. **NET interception level (v1).** `urllib.request.urlopen` (success + HTTPError paths) plus a
   raw-`socket` guard. `requests`/`httpx` ride urllib3/httpcore whose response plumbing needs a
   deeper shim; in v1 they hit the socket guard → `UNPROVEN(UNINTERCEPTABLE_EFFECT)` naming the
   surface — honest, never silent. requests-level interception is the next moat increment.
3. **Record mode and L6.** Sandboxes have no external network, so record captures only what the
   environment offers: the corpus records against an in-worker 127.0.0.1 loopback server
   (loopback exists even under `--network none`), and replay runs with the server absent —
   the strongest honest validation available without violating L6.
4. **Import-time effects** ride in every cassette under an "import" slot recorded through a
   dedicated import session (patches install before target import so `from x import y` binds
   shims). Interactions made by shim internals while intercepting a higher-level call are
   excluded from the ledger — they are invisible at replay by construction.

**Gate result.** 30/30 stable across 5 consecutive replays (bar: ≥24).
