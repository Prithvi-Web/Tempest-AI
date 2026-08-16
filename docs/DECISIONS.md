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

## ADR-0011 — Tauri v2 over Electron for the desktop shell; language-per-part policy

**Date:** 2026-08-13 · **Status:** accepted

**Context.** The Phase 8+ master prompt makes Tempest a desktop application. A shell choice and a
language allocation across the three boundaries (engine/host/UI) had to be fixed. A working Tauri
v2 shell already exists (`apps/desktop`, shipped 2026-08-13) with a frozen PyInstaller engine
sidecar — built before this ADR, validating the choice in practice.

**Decision.** Tauri v2, not Electron:
1. **Footprint & memory** — system webview instead of a bundled Chromium: ~10–20 MB shell vs
   150+ MB, and idle RAM that can meet the Phase 11 <250 MB budget with the sidecar included.
2. **Security posture** — Rust host, capability-scoped IPC, no Node runtime in the UI process
   (the Phase 8+ prompt bans one outright). Electron's main-process Node is a standing liability
   in enterprise security review.
3. **Signing/updater story** — first-class signed-manifest updater and per-OS bundling that fits
   L13 (signed or it doesn't ship).

**Language-per-part policy (owner directive, 2026-08-13: "build things in Rust if needed to make
things faster; choose which language is best for which part").**
- **Rust** — the host: window/tray, sidecar lifecycle + supervision, OS sandbox construction,
  keychain, updater, hash-chained audit log, Ed25519 license verification. Also the designated
  home for hot-path ports (canonical-bytes encoding, bundle hashing, ledger diff) **only** behind
  differential parity tests proving byte-identical output vs the Python implementation.
- **Python** — the engine of record: the nine stages and the determinism moat (30/30×20 validated).
  Rewriting proven ground now would trade verified correctness for speculative speed; ports are
  earned via the parity gate above, not assumed.
- **TypeScript** — webview UI only, consuming generated types (§9b tri-boundary contract).

**Consequences.** WebView2/WebKitGTK rendering differences become a test matrix concern
(Phase 12 clean-VM gates cover it); the tri-boundary contract (L12) becomes load-bearing and is
gated by `contract-check`.

## ADR-0012 — Local-first with an optional self-hosted sync server

**Date:** 2026-08-13 · **Status:** accepted

**Context.** v1 treated FastAPI+Postgres as the product backend. The Phase 8+ prompt inverts
this: the desktop app must be fully functional offline (L8), and source must never leave the
machine without opt-in (L9/L10).

**Decision.**
1. SQLite (WAL) is the local primary store; the FastAPI surface becomes an embedded local sidecar
   the desktop app owns. There is no mandatory cloud dependency; the current sidecar already runs
   engine+API locally against the app's data directory.
2. Team features arrive as an **optional, self-hosted** sync server (Phase 13): Postgres + object
   storage in a customer-run container. The desktop pushes bundles only for repos explicitly
   configured for sharing, with source-snippet redaction ON by default at the boundary.
3. Sync is content-addressed, resumable, idempotent, delta-only; bundles stay immutable so
   conflict resolution is designed out rather than handled.
4. Licensing and updates must both work fully offline (Phase 15) — no license server on the
   critical path, ever (L8: local-first must not degrade because a license server is unreachable).

**Consequences.** Postgres-specific work moves behind the sync server boundary; the v1 dialect
obligation (ADR-0009) transfers to the server component. The web dashboard's remaining v1 gaps
(SSE timeline, Playwright E2E) are superseded by the desktop SPA migration in Phase 9 — tracked
there, not silently dropped.

## ADR-0013 — Tiered OS-native sandboxing replaces Docker-required

**Date:** 2026-08-13 · **Status:** accepted

**Context.** v1's L6 assumed Docker (ADR-0003: no Docker → UNPROVEN(SANDBOX_UNAVAILABLE)).
Enterprise laptops frequently have no Docker and IT often forbids it; a desktop product that
shrugs on every such machine has a proof rate of zero exactly where it is being sold (the Phase 8
audit measured this machine at that limit — every user-repo target is SANDBOX_UNAVAILABLE here).

**Decision.** Runtime-selected isolation tiers, the selected tier recorded in every bundle and
shown in the UI (never silently degraded):
- **T1** Docker/Colima/Podman when present (strongest, existing v1 path).
- **T2 (default)** OS-native: macOS `sandbox-exec` profile + App Sandbox entitlements; Windows
  AppContainer + Job Object + restricted token; Linux bubblewrap + seccomp-bpf + user namespaces
  + cgroups v2.
- **T3 (degraded)** separate user + resource limits — reported in the UI as reduced assurance
  with the specific limitation named.
Every tier must enforce: no network, read-only FS except one scratch mount, no `~` access outside
the target repo, CPU/memory/wall limits, no unconstrained child spawning. The Phase 10 gate is an
adversarial escape suite (25+ payloads × 3 OSes × all tiers) plus the L10 egress monitor.

**Consequences.** ADR-0003's "no Docker → UNPROVEN" rule survives only until T2 lands, then
tightens to "no tier available → UNPROVEN" (expected to be near-zero machines). ProcessSandbox
(ADR-0008) remains a first-party-fixture-only dev path and is unaffected. This is the highest-risk
phase of the desktop plan; an external security review is a scheduled gate item, and Phase 10
blocks GA until the escape matrix is green.

## ADR-0014 — Delete the Next.js web dashboard; desktop SPA is the one renderer

**Date:** 2026-08-14 · **Status:** accepted

**Context.** Phase 9 (desktop master prompt §1) makes Tempest a desktop application and orders
dead paths deleted, not deprecated: "half-migrated code is how flawless integration dies." The
five views already exist in the desktop SPA on generated contracts; the web package's remaining
open items (SSE timeline, Playwright E2E, repo-settings) were superseded by ADR-0012.

**Decision.** `packages/web` (Next.js 15 app, its generated api-client/hooks, and the web build
steps in Makefile/CI) is deleted outright. The generation pipeline shrinks to schema outputs
(`openapi.json`, `types.ts`) plus the desktop tri-boundary generators. The desktop webview is
the only UI renderer; it consumes generated `bindings.ts` exclusively — a `make verify-desktop`
grep bans importing `@tauri-apps/api/core` outside `src/generated` (the no-handwritten-invoke
rule, enforced the same way the S-A-F-E grep enforces L2). The E2E obligation transfers to
`pnpm --filter @tempest/desktop test:e2e` (Phase 9 gate item, still open).

**Consequences.** The optional self-hosted sync server (Phase 13) will need its own thin admin
UI someday — that is a new, server-scoped surface, not a resurrection of this package. Auth.js/
GitHub OAuth (v1 §Auth) leaves the product surface with the web app; desktop/enterprise auth
arrives as OIDC/SAML in Phase 14 (per the Phase 8+ table).

## ADR-0015 — Tiered OS-native sandboxing (Phase 10): macOS T2 Seatbelt lands

**Date:** 2026-08-14 · **Status:** accepted (macOS T2 shipped; Linux/Windows T2 + T3 tracked)

**Context.** ADR-0003 made "no container runtime → UNPROVEN(SANDBOX_UNAVAILABLE)". On a Mac with
no Docker that meant a 0% proof rate for every user repo — the exact wall Phase 10 exists to
remove. The Phase 8+ prompt specifies a runtime-selected tier ladder with the tier recorded in
every bundle and never silently degraded.

**Decision.**
1. **Tier ladder** (`execute/sandbox.py::select_sandbox`), strongest first, for USER repos:
   T1 `DockerSandbox` → T2 `SeatbeltSandbox` (macOS) → UNPROVEN. First-party fixtures keep
   picking trusted `ProcessSandbox` directly (ADR-0008) and never enter the ladder.
2. **macOS T2 = `sandbox-exec`** with a deny-default SBPL profile (`seatbelt_profile`): network
   denied outright; the whole home denied and re-allowed only for the repo worktree and the
   interpreter's own install (no `~` path outside the repo is reachable); writes only to the one
   scratch mount; exec'd children inherit the profile (no `no-sandbox`). Paths are canonicalized
   because macOS returns `/var/folders/…` for temp dirs while Seatbelt evaluates the real
   `/private/var/…` — an unresolved subpath would void the scratch mount.
3. **T3 (rlimit-only ProcessSandbox) is NOT offered for user code.** The escape matrix shows it
   contains only 9/27 vectors (network, home reads, `/tmp` writes, parent-kill all leak). Handing
   untrusted repos to it would be the "silent degrade" failure this ladder prevents. The genuine
   T3 (separate-user) and the Linux (bubblewrap+seccomp+userns+cgroups) / Windows (AppContainer +
   Job Object) T2 backends are follow-ups tracked in `docs/PLAN-DESKTOP.md`.
4. **The tier is data, not a promise.** Recorded in the bundle manifest (schema bumped v1→v2,
   forward-compatible read), rendered in the CLI report, and carried to the UI; reduced-assurance
   tiers name their limitation.

**Evidence (this machine, 2026-08-14).**
- Escape suite: **T2 contains 27/27**; T3 leaks 18/27 (`python -m tempest.dev.escape_suite`).
- Egress (L10): **0 outbound connections** across 6 network vectors under T2
  (`python -m tempest.dev.egress_check --expect-zero`).
- Perf: T2 Seatbelt wrapping adds ~5 ms/spawn — **1.16× the no-wrapper baseline**, far under the
  3× bar. (T1 Docker delta needs a Docker-equipped machine — CI leg.)

**Scheduled external security review.** The T2 profile, the escape corpus, and the sync-server
boundary (Phase 13) are to be reviewed by an external application-security firm before GA
(prompt §10). Owner action ([ASK ME]): engagement + budget. Until then the escape suite + egress
gate are the standing in-repo evidence, re-run in `make verify`.

**Consequences.** On macOS the SANDBOX_UNAVAILABLE path is now only reached when both Docker and
Seatbelt are forced off (`TEMPEST_NO_SEATBELT=1`, used by tests to exercise it). The HANDOFF trap
"no Docker → SANDBOX_UNAVAILABLE" is superseded on macOS by "no Docker → T2 Seatbelt".

## ADR-0016 — Versioned local SQLite store: WAL + stamp + forward-migrate + refuse-newer (Phase 11)

**Context.** The desktop's SQLite file is the primary store (L8), but it was created by
`create_all` with no version marker: an old binary opening a database written by a newer app
would silently misread or corrupt it, and there was no upgrade path besides "delete the file".
The frozen PyInstaller sidecar cannot ship the alembic script directory, so runtime migration
cannot shell out to alembic.

**Decision.** Opening the local store (`tempest_api/db/local_store.py`, wired into the app
lifespan) is a versioned act:

1. **Refuse-newer first, read-only.** Before any connection may touch the file, the
   `alembic_version` stamp is read through a `mode=ro` sqlite URI. A stamp outside the known
   chain raises `NewerDatabaseError` with an actionable message; the file — including its
   journal-mode header — stays byte-identical (proven by hash in the test).
2. **WAL journal mode** on every connection (`PRAGMA journal_mode=WAL` on connect): the desktop
   reads the store while ingest writes it.
3. **Fresh or legacy-unstamped databases** get `create_all` + a head stamp. Adoption of
   unstamped pre-Phase-11 stores is exact because the migration/model parity test proves
   `create_all` ≡ `upgrade head`.
4. **Older stamps forward-migrate in place** via in-code SQL steps that mirror the alembic
   scripts, inside one transaction (a failed migration leaves the old schema intact). The
   in-code chain is pinned to `packages/api/alembic/` by a drift test, and the migrated schema
   is asserted equal to `alembic upgrade head` — mirroring is tested, not promised.

**Consequences.** Postgres deployments still run alembic (ADR-0009) — this mechanism is
sqlite-only. Every future alembic revision must extend `REVISION_CHAIN` + `_FORWARD_STEPS`;
forgetting either fails `test_revision_chain_matches_alembic_scripts` or the forward-migration
equivalence test. Migrations heavier than SQLite `ALTER`s need a new strategy and a new ADR.

## ADR-0017 — Content-addressed bundle store with GC + size budget (Phase 11)

**Context.** Bundles were written under per-run directories with no dedup, no bound on disk
use, and no single place an export/replay could hand back the original artifact (L7).

**Decision.** `tempest_api/bundlestore.py`: every ingested `.tempest.zip` is stored once under
`<data_dir>/bundles/<aa>/<sha256>.tempest.zip` (atomic tmp+rename write; identical content
shares one blob). `runs.bundle_digest` (alembic `0003`) references the blob. GC removes only
blobs no run references. A user-controlled budget (`TEMPEST_BUNDLE_BUDGET_BYTES`, unset/0 =
unlimited, read per-ingest so the desktop can change it without restart) prunes the OLDEST
bundle-bearing runs — row and blob together, cascading through targets/divergences/events —
and never the newest run: the run just proved always survives, and every surviving run keeps
its evidence. Pending runs without bundles are never pruned. SQLite now runs with
`PRAGMA foreign_keys=ON` so ON DELETE CASCADE matches Postgres exactly.

**Consequences.** Ingest and local prove share the one hook in `ingest_zip_bytes`. A rolled-back
ingest can orphan a blob; orphans are collected on the next enforce pass — never the reverse
(a run pointing at a deleted blob) except in the sub-millisecond window between row deletion
flush and commit, accepted and documented here. Budget pruning deletes user history by design;
the budget is opt-in and the newest run is contractually safe.

## ADR-0018 — Divergence FTS + portable `.tempest` import/export (Phase 11)

**Context.** Phase 11 requires text search over divergences and a portable bundle format.

**Decision.** (1) Search: an external-content **SQLite FTS5** index (`divergences_fts` over
detail + base/head summaries) maintained by AFTER INSERT/DELETE triggers — ingest indexes and
budget-prune cascades de-index with no code path able to forget; created idempotently on every
open, rebuilt when adopted stores have unindexed rows; it is an adjunct index, excluded from
migration parity snapshots and NOT in the alembic chain because Postgres deployments search the
same three columns with ILIKE instead (`searchDivergences` picks per dialect). User queries are
re-tokenized into quoted terms so FTS5 operator syntax is inert. (2) Portability: the `.tempest`
file IS the bundle zip. `exportRunBundle` returns the stored blob byte-identical to ingest (L7);
`importRunBundle` creates repo+run from the manifest and reuses the exact upload ingestion path,
idempotently by sha256 — re-importing returns the run that already holds those bytes.

**Consequences.** Desktop UI ships divergence search (RunsView) through a generated
`search_divergences` binding. Export/import UI needs a file-dialog plugin the shell doesn't
carry yet — the HTTP/JSON-RPC surface is the contract for now; UI buttons ride the Phase 9
desktop-E2E straggler. Binary export over the stdio bridge would need a base64 wrapper; not
added until a consumer exists.

## ADR-0019 — L11 mechanics: CancelScope + battery/thermal pause (Phase 11)

**Context.** L11: every long operation is cancellable and the machine is never fought.

**Decision.** (1) **Cancel**: one `CancelScope` per prove (`execute/cancel.py`). The single
spawn choke point (`runner._spawn`) registers every child; `cancel()` — callable from any
thread — SIGKILLs every registered process group instantly, and a cancelled scope refuses new
spawns, so worker-respawn paths raise `ProveCancelled` instead of resurrecting children.
Registering on an already-cancelled scope kills the late child, closing the race. The API is
`POST /v1/runs/{id}/cancel` → 202; the prove thread unwinds into the honest terminal
`RunStatus.CANCELLED` (no verdict, L2) with a `local.cancelled` ledger event; 409
`RUN_NOT_ACTIVE` when nothing is running. The active-prove registry is keyed by
`(database_url, run_id)` — run ids are only unique within one store. (2) **Pause**:
`execute/powerstate.py` probes power state (macOS: pmset battery + thermal CPU limit; probe
failure = don't pause; Linux/Windows probes ride the Phase 10 CI legs) with precedence
`TEMPEST_FORCE_POWER_PAUSE` (tests) > `TEMPEST_NO_POWER_PAUSE` (user opt-out; set by repo
gates so verification never hangs on an unplugged laptop) > real probes. `run_prove`
checkpoints between targets: cancelled → unwind; paused → hold, report the reason once into
the run ledger (the UI shows why the run is holding), cancel unblocks a pause immediately.

**Consequence discovered by the parity gate.** Growing `RunStatus` widened its computed
VARCHAR — alembic `0004` widens `runs.status` (batch mode). For the LOCAL store such
width-only revisions are stamp-only forward steps: SQLite type affinity ignores declared
widths, and the forward-equivalence test compares width-insensitively. The alembic-vs-models
parity gate remains byte-strict — every future enum growth must ship its widening migration.

## ADR-0020 — Phase 17 observability: redaction-first, local-only, opt-in (L9/L10 preserved)

**Context.** Phase 17 asks for crash reporting, telemetry, diagnostics, logging, and a health
check — every one an outbound-candidate surface, in a product whose enterprise claim is "source
never leaves the machine, provably" (L9) with a CI-tested zero-egress bar (L10).

**Decision.** Redaction-first and local-only:
1. `tempest.redact` is the single scrubbing engine (key blocks, secret env values, credential
   shapes, emails, repo names, home paths → basename, the bare username anywhere — temp paths
   leak it too — and traceback source echoes + frame symbols). Idempotent by marker design.
   Proven adversarially: `tempest.dev.redaction_check --planted-secrets` (in `make verify` +
   CI) and the unit suites plant real-shaped secrets — zero may survive (failure-mode #4).
2. Crash records are scrubbed AT WRITE TIME (`tempest.crashlog`; excepthook in CLI + sidecar):
   the raw traceback never touches disk, so no downstream path can leak what was never stored.
3. Telemetry (`tempest.telemetry`) is counters-only by schema (runs, verdict/tier/UNPROVEN
   distributions, duration total), strictly opt-in (`TEMPEST_TELEMETRY=1`, default OFF).
4. `tempest diagnose` packages health report + logs + crashes + telemetry into a zip whose
   every byte re-passes the redactor; the manifest is printed; the command transmits NOTHING.
5. **No network transmission exists in Phase 17 at all** — Sentry-style upload would break the
   L10 zero-egress proof in local mode. Transmission arrives only via the Phase 13 opt-in
   self-hosted sync path with redaction at that boundary. `docs/PRIVACY.md` documents the
   surfaces; `docs/SUPPORT.md` is the runbook.
6. Structured logging (`tempest.obslog`): JSON lines, one shared rotating handler per file
   (two handlers rotating one file would race the rename chain), never-raise emit, viewer via
   `tempest logs show`.

**Consequences.** Support asks for the diagnostic bundle, never raw logs. The scrubber grows
by adding a planted secret FIRST (test-first, adversarial). Doctor (`tempest doctor`) is the
support entry point with an honest exit code (no sandbox = FAIL).

## ADR-0021 — Distribution is GitHub-only (owner decision 2026-08-14): Phase 12 descoped

**Context.** Phase 12 planned Apple Developer ID + notarization, Windows EV signing, MDM —
purchases and accounts only the owner can make. On 2026-08-14 the owner decided: **"make this
an agent someone can download off GitHub. No Apple ID and stuff — only GitHub."**

**Decision.** Tempest ships from the public GitHub repo, nothing else:
1. **GitHub Releases** built by CI on tag: Python wheel + sdist, standalone CLI binaries
   (PyInstaller) for macOS/Linux/Windows runners, and the unsigned macOS .app bundle, each
   with SHA-256 checksums published in the release.
2. **L13 ("signed or it doesn't ship") is satisfied with free, GitHub-native provenance
   instead of paid certificates**: artifact checksums in the release notes + GitHub Actions
   build provenance (the workflow is the auditable builder). Sigstore keyless signing can be
   added later at zero cost. Apple notarization/Windows EV are NOT pursued.
3. **Install paths documented in the README**: `uv tool install` / `pipx install` from the
   repo (primary), or download a release binary. Unsigned macOS artifacts trip Gatekeeper —
   the docs state the right-click-Open / `xattr -d com.apple.quarantine` step honestly
   rather than pretending it away.
4. MDM/enterprise fleet distribution is out of scope until a customer actually asks; the
   old Phase 12 checklist is preserved in git history, not in the live plan.

**Consequences.** The Phase 12 [ASK ME] purchases are cancelled. Phase 18's "install unaided
from the signed artifact" gate becomes "install unaided from the GitHub release." Enterprise
buyers who require notarized binaries are a future decision the owner can reverse with money;
nothing in the codebase blocks it.

## ADR-0022 — Sync protocol: the store is the queue; strip before hash (Phase 13)

**Context.** Phase 13 requires content-addressed, resumable, idempotent, delta-only sync with
redaction at the boundary and an offline queue with durable retry.

**Decision.** (1) **No separate queue exists**: the content-addressed bundle store is the
durable queue. A failed push mutates nothing; the next push re-derives the delta from a
presence check (`checkBundlePresence`) and resumes exactly the missing set. No queue state
means no queue corruption. (2) **The policy boundary runs before hashing**: bundles are
source-stripped (`syncstrip`, default ON stripping; `TEMPEST_SYNC_SHARE_SOURCE=1` opts out)
and the WIRE bytes' sha256 is the identity on both ends — presence, dedup, and the server's
digest-idempotent import all operate on what actually crossed. (3) The team server is the
same `tempest_api` app (one codebase, ADR-0009 Postgres in containers), deployed via the
existing `docker/compose.yaml`. (4) A rejected bundle is counted and skipped, an unreachable
server ends the attempt with `remaining` counted — the app is never blocked (L8), nothing
raises. Gates run against a REAL second server process, killed and restarted mid-flow.

**Consequences.** Sequential pushes (bounded by per-request timeout) — parallelism is a perf
follow-up, not a correctness need. Stripped and unstripped variants of the same run have
different digests by design (they are different artifacts). Container-runner legs (compose
end-to-end, Helm, image signing) are PENDING(docker) — stated in docs/DEPLOY-SYNC.md.

## ADR-0023 — The 100% bar and the adversarial-review wave (owner decision 2026-08-14)

**Context.** After the first Linux CI runs, the owner set the bar: 100% test coverage and zero
known defects — "that is what flawless means."

**Decision.** (1) **Coverage gate = 100%** (`fail_under = 100`, governing Makefile and CI).
Reached honestly: real behavior tests first; subprocess coverage collection (children start
coverage via `scripts/covstart/sitecustomize.py`; SIGTERM flushes); a sys.monitoring arc
supplement for the one module that owns `sys.settrace`; and explicit justified exclusions
only for genuinely unreachable-in-context code (platform arms, defensive guards, one
documented tracer-attribution artifact with its pinning tests named inline). (2) **Two
independent adversarial reviews** (correctness/concurrency; privacy/process-safety) over the
day's code produced 4 critical + 12 major + 11 minor CONFIRMED findings — every one fixed
test-first with the reviewer's failing sequence reproduced as the RED test. Highlights:
zip containers made a pure function of content (delta-sync correctness); GC moved after
commit with an in-flight grace (evidence can no longer be deleted by a concurrent ingest);
FK pragmas on every engine; adoption repairs legacy schemas instead of bricking them;
presence answers from DB truth and import heals lost blobs; Docker T1 runs interactive with
named containers and `docker kill`; harness-synthesized crashes are UNPROVEN, never
comparable evidence (verdict integrity); worker fd-1 isolated from the protocol; killpg
guarded against pgid recycling; CLI Ctrl-C cancels all children; the sync boundary strips
mined source literals and summaries, not just repro scripts; the redactor covers AWS
temporary/STS, Stripe, alg=none JWTs, multi-line PEMs, git-remote identities, and proves the
PRODUCTION context (gate: 23/23 planted secrets contained).

**Consequences.** "Zero bugs" is stated as zero KNOWN defects: every confirmed finding fixed
and pinned; the gates (100% coverage, redaction 23/23, escape 27/27, egress 0, determinism
corpus, parity byte-identical, bench, mypy on both platform views) stand guard in verify+CI.
The scrubber and the finding process grow test-first, adversarially, forever.

## ADR-0024 — LLM constructor synthesis: the model writes adapters, never verdicts (2026-08-16)

**Context.** Instance methods were the biggest honest hole in proof rate: with no way to
construct a receiver, every changed method on a class landed `UNPROVEN(TARGET_UNREACHABLE)`
(HANDOFF-WORLD-CLASS 2.1). The owner's BYOK key (ADR-0006, keychain-only) existed with no
consumer. The master spec's non-goal #1 stands: no LLM-authored verdicts, ever.

**Decision.** A synthesis stage (`tempest/harness/llm.py`) that activates only when a target
is an instance method, classification is UNREACHABLE, and `ANTHROPIC_API_KEY` is set (kill
switch: `TEMPEST_NO_SYNTHESIS=1`). The model (default `claude-sonnet-5`, override
`TEMPEST_SYNTHESIS_MODEL`) is asked for exactly one artifact: a standalone module defining
`adapter(...)` that constructs the class with fixed literals and delegates to the method.
Honesty invariants, each pinned by test:
- **Acceptance is execution, not review.** The adapter passes `harness.synth.synthesize` on
  BASE — the same sandboxed probe every deterministic adapter passes — or the target is
  `UNPROVEN(SYNTHESIS_DECLINED)` with the failure detail. Never a lesser claim, never a
  silent downgrade. Verdicts remain the differential runner's alone.
- **Offline afterwards (L8).** Validated adapters are cached in the user's repo at
  `.tempest/adapters/`, keyed by sha256(target identity + head source). Cache hits skip the
  network, never the re-validation. The synthesis-gate test reruns the corpus with a dead
  base URL and reproduces identical verdicts.
- **One egress surface (L10).** The keyless egress gate stays at zero; the only sanctioned
  call is the Messages API request, carrying the changed class's source — never the diff,
  never repo contents beyond the target module. Tests exercise the real SDK→HTTP path
  against a local Messages-API peer (`helpers_fake_anthropic.py`), nothing monkeypatched (L4).
- **Provenance is visible.** Synthesized proofs carry `classification=SYNTHESIZED` across
  all three boundaries, and the minimized repro embeds `ADAPTER_SOURCE` verbatim — the
  constructor call the model chose is part of the evidence (L7), and the repro stays
  self-contained.
- **Coverage stays honest.** Execution tracing attributes to the *target* module
  (`trace_module`), not the adapter shim, so changed-line coverage numbers keep meaning.

**Consequences.** pyfix gains instance-method fixtures (c01 Discounter, c02 Wallet, c03
Tally no-op); the synthesis gate proves 0/3 keyless (with remediation text naming the fix)
→ 3/3 exercised with a key: seeded changes DIVERGENT, the no-op EQUIVALENT_UNDER_BUDGET,
zero false alarms through adapters. The real-model proof-rate number still awaits an owner
key and the 2.2 live-PR measurement. `anthropic` joins engine dependencies; the keyless
paths import it lazily so keyless installs never touch it at runtime.

## ADR-0025 — [roots].source + one config law + the live gate reports (2026-08-16)

**Context.** HANDOFF-WORLD-CLASS 2.2 requires the real-world proof rate. Two blockers
surfaced immediately: (1) monorepo files (`packages/engine/src/tempest/x.py`) derive
unimportable module names, so Tempest could not prove ITSELF; (2) `tempest.toml` was
honored only by the CLI — the desktop app and any direct `run_prove` caller silently
ignored a repo's declared budgets/ignores, a real defect under the zero-known-defects bar.

**Decision.**
1. **`[roots].source`** in tempest.toml: repo-relative import roots. Module derivation
   strips the longest matching root (whole path segments only); the worker's sys.path and
   coverage target-file resolution gain the same roots; standalone repros embed a
   `sys.path[:0]` prologue so they still run from the repo root (L7). Validation rejects
   absolute paths and `..` with the fix named.
2. **Worktrees self-describe.** `_sys_path_for`/`_target_file` read the WORKTREE's own
   tempest.toml (lru-cached, tolerant): every worker construction site — detection,
   minimization, synthesis validation probes — resolves identically with zero parameter
   threading, and each checked-out revision describes its own layout. A broken historical
   config yields no extra roots (honest UNPROVEN on import), never a crash; the
   working-tree copy is validated at run start.
3. **One config law.** `ProveConfig.ignore_globs`/`source_roots` default to `None` =
   "the repo's tempest.toml decides", resolved inside `run_prove`. The CLI's explicit
   tuple still overrides. The desktop app, the API, parity, and CI now honor the same
   file without per-caller wiring.
4. **The live gate reports, the self-test enforces.** `tempest-live.yml` runs the action
   on the repo's own PR diff and posts the evidence comment, but `continue-on-error` —
   a feature PR legitimately changes behavior; blocking on DIVERGENT would train people
   to ignore the gate. The seeded-fixture contract (DIVERGENT must fail, comment must
   carry evidence, no forbidden word) stays enforced by tempest-selftest.yml.

**Consequences.** Tempest proves Tempest: engine modules resolve as `tempest.*` on PRs.
The first real-world proof-rate measurement (5 OSS repos, real release pairs, T2) is
recorded in docs/METRICS.md with its UNPROVEN reason distribution — instance methods
(what AI synthesis attacks, ADR-0024) and uninstalled-dependency imports (the stage-2
env-reproduction gap, the next engine lever) dominate, as evidence, not opinion.
