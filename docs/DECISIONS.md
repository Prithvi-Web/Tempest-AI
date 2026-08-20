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

## ADR-0026 — Engine depth: the free proof rate (2026-08-16)

**Context.** The first real-world measurement (ADR-0025: 21% keyless) named the levers.
Three of them cost no key, no network, and no new trust surface: static/class methods
(already executable, never exercised), typed dataclasses (mechanically constructible),
and async functions (awaitable at the call site).

**Decision.**
1. **Static/classmethods** were provable all along — the classifier passes them through
   and the worker's getattr chain resolves them. What was missing was PROOF: pyfix gains
   c04 (staticmethod seeded change → DIVERGENT) and c05 (classmethod no-op → EQUIVALENT),
   pinned keyless in the engine-depth gate.
2. **Type-driven constructor synthesis** (`harness/typed.py` — the `TypeDrivenSynthesizer`
   the architecture spec named): for an instance method on a typed dataclass, derive the
   adapter from the AST ALONE (defaulted fields keep their defaults; defaultless
   builtin-shaped fields get zero values; anything else gives up). Tried BEFORE the LLM
   rung; user code is never imported in-process (L6); fully offline (L8). Provenance is
   distinct: `classification=TYPE_SYNTHESIZED` across all three boundaries — a mechanical
   adapter is never dressed up as an AI one (or vice versa).
3. **Strict acceptance for mechanical guesses.** The synthesis probe now prefers a CLEAN
   completion and records `probe_raised` when every completing probe raised. Mirrored-
   parameter adapters (the LLM rung) may legitimately raise — the target's own behavior.
   The typed rung REJECTS a raising probe: with a guessed constructor, the raise could be
   the guess itself, and an unattributable raise must never anchor a comparison — it falls
   through to the next rung instead.
4. **Async targets**: the classifier's async→UNREACHABLE arm is gone; the worker awaits
   coroutine functions via `asyncio.run` on a fresh loop per call — frames still trace
   (coverage), effects still hit the determinism shims. Generators remain honestly
   unreachable (lazy iteration has no single observable return).

**Consequences.** pyfix c04–c07 prove keyless (the engine-depth gate); the real-world
corpus was re-measured on identical SHAs and both tables live in docs/METRICS.md — the
delta is the honest value of this phase. The remaining big lever is stage-2 env
reproduction (install the target package and deps into the sandbox), which the same
measurement shows blocking humanize/slugify wholesale.

## ADR-0027 — Stage-2 env reproduction: wheels only, offline first, self-described (2026-08-16)

**Context.** The measured #1 lever (ADR-0025/0026): real repos fail wholesale on
`importlib.metadata` lookups of the package under test (humanize's 24/24) and on
uninstalled third-party imports (slugify, the 39 introspection failures). Naive fixes
violate the laws: `pip install <repo>` executes build backends — arbitrary repo code
OUTSIDE the sandbox (breaks L6's whole story); default network fetching breaks the
keyless-offline promise (L8/L10).

**Decision** (`envrepro/deps.py`):
1. **Repo code never runs during materialization.** The target package's name, version,
   and dependency list come from STATIC `pyproject.toml` parsing. A synthesized
   `.dist-info` shim satisfies `importlib.metadata` while the code itself keeps importing
   from the worktree — the package is never built. A dynamic version gets the
   self-evidently synthetic `0.0.0+tempest-unresolved`.
2. **Wheels only.** Third-party deps install via `uv pip install --target … --only-binary
   :all:` into a fingerprint-keyed cache dir. A wheel unpack runs no hooks, no backends,
   no scripts. Sdist-only deps fail honestly with the reason.
3. **Offline first.** The default install runs `--offline` against uv's cache. Fetching is
   an explicit opt-in (`--fetch-deps` / `TEMPEST_FETCH_DEPS=1`) — one fetch, then every
   run is offline again (the ADR-0024 once-then-offline shape). Keyless egress stays zero
   by default; the sandboxed runner NEVER fetches (the egress gate's surface is untouched).
4. **Worktrees self-describe** (the ADR-0025 pattern): `attach_deps` leaves a
   `.tempest-deps` symlink (workers and future repros find the site dir by convention)
   and a `.tempest-deps-note` with the exact remediation when materialization is
   incomplete; the introspection-failure UNPROVEN appends the note verbatim — the error
   message is the product.

**Amended same night — what the measurement falsified and taught:** the first re-measure
moved NOTHING, because both hypotheses were wrong: humanize fails on a build-time-generated
`_version.py` (hatch-vcs), not a metadata lookup — fixed with a worktree version-file shim
whose version comes from `git describe` (the same source vcs build tools read); slugify has
no pyproject at all — fixed with AST-only setup.py parsing including module-level constant
folding (name may stay honestly unresolvable; deps still install). And the deps symlink
resolves OUTSIDE the Seatbelt repo carve — T2 denied every wheel until the profile gained
the resolved site dir as a read root (Docker T1 gets the equivalent read-only mount). The
gate now includes a REAL T2 leg (a user repo through the honest tier ladder), because
ProcessSandbox-only integration is structurally blind to profile bugs.

**Consequences.** The env-reproduction gate proves both killers end-to-end, hermetically
(a hand-built local wheel + UV_NO_INDEX/UV_FIND_LINKS — zero PyPI in the suite): the
humanize pattern DIVERGENT keyless+offline; missing wheels UNPROVEN with the fix named;
reachable wheels flip the same repo to DIVERGENT. The real-world corpus re-measurement
with fetch enabled is recorded in docs/METRICS.md. Out of scope, stated: sdist-only
dependencies, per-repo interpreter resolution, and dev-dependency scripts (noxfile/docs
conf import failures remain honest UNPROVEN — they are not [project] dependencies).

## ADR-0028 — TypeScript execution wave 1: bilingual, same laws (2026-08-16)

**Context.** The analysis sidecar (target selection, classification, typed value pools)
existed since Phase 3's first half; every changed `.ts` file still surfaced as one blanket
`UNPROVEN(RECORD_REPLAY_UNAVAILABLE)`. The last keyless proof-rate lever.

**Decision.** The execution half, scoped to what can be flawless in one wave:
1. **`ts_worker.mjs`** — one node process per batch imports the target via native type
   stripping (erasable syntax keeps offsets AND line numbers, which is what makes V8
   coverage honest), invokes the export per input (awaiting promises), and emits canonical
   observations: NaN/±Infinity/−0/undefined/bigint/Date/Map/Set tagged, object keys
   sorted, functions/symbols/class instances honestly `unrepresentable`, throws recorded
   as observations, per-input console output captured. Per-input executed lines come from
   in-process V8 precise-coverage deltas with count-0 sub-range subtraction.
2. **`ts_shims.mjs`** (preloaded `--import`) — L3's JS half: seeded Math.random, pinned
   monotonic Date/performance.now, seeded crypto.getRandomValues/randomUUID. The
   classifier followed the capability: Date/Math.random/global-crypto references are now
   ambient-deterministic PURE, async functions are runnable (the worker awaits), while
   IMPORTED node:crypto randomness binds the unpatched module and stays impure.
3. **`ts_dual.py`** — verdicts through the SAME comparator as Python (`compare.compare`):
   base runs twice first (self-disagreement → NONDETERMINISTIC_BASE, never compared),
   candidate divergences reconfirm on fresh process pairs or are discarded, inputs draw
   deterministically from the sidecar's typed pools, coverage is the executed-∩-changed
   union. Minimization is wave 2 — repros embed the found input verbatim, stated.
4. **`prove.py`** — per-symbol TS records replace the blanket: sidecar UNREACHABLE reasons
   pass through verbatim (not-exported, generators, methods), IMPURE targets say "JS
   record/replay is wave 2", `.tsx`/`.d.ts` say why type stripping cannot run them, T1
   Docker says its image lacks node — every gap stated, nothing silent.

**What the gate caught while landing this (the honesty dividend):** removing the sidecar's
async→UNREACHABLE arm exposed that `fetch` was never in its IO-globals list — async IO
functions would have EXECUTED and been blessed off their error paths. `fetch`,
`XMLHttpRequest`, `WebSocket`, `setInterval` are now IO; the tsfix gate pins the whole
contract (seeded changes DIVERGENT with self-contained `.mjs` repros, no-op + shim-dependent
churn EQUIVALENT with zero false divergences, unexported/impure honest UNPROVEN).

**Consequences.** Tempest is bilingual on the wave-1 surface: exported module-level
typed functions (sync or async) in `.ts`. Wave 2, stated: JS record/replay cassettes,
methods/constructor synthesis, ddmin for JS inputs, node in the T1 image, `.tsx`.

**Amended 2026-08-17 (the first Linux CI run, trap 35):** V8 workers CANNOT run under
`RLIMIT_AS` — Wasm (the type stripper) and V8's pointer cage RESERVE multi-GiB virtual
ranges at import while resident use stays tiny; the 2 GiB address-space cap killed every
TS prove on Linux ("Cannot allocate Wasm memory"), and macOS never enforces AS, so no
local run or simulated-Linux view could reveal it (the trap-22 class: kernel behavior,
not test selection). Fix: `sandbox.popen(..., v8=True)` selects `_set_child_limits_v8`
(CPU/core/nproc limits, no AS) and the worker carries `--max-old-space-size=256` —
JS memory containment is the V8 heap cap + CPU rlimit + batch wall budget + group kill,
never the address space. The cap's delivery to the worker is pinned end-to-end.

## ADR-0029 — The continuous agent: watch mode + AI narratives (2026-08-17)

**Context.** HANDOFF-WORLD-CLASS 2.4, the last feature-sized roadmap item: prove commits
as they happen, and make the evidence readable in plain English — the owner's own bar.

**Decision.**
1. **`tempest watch`** (`cli/watch.py`): poll HEAD; every NEW commit is proven
   incrementally (prev → new) — per-commit verdicts, per-commit bundles. L11 end to end:
   battery/thermal pause honored between polls, Ctrl-C exits cleanly through run_prove's
   cancel discipline, one prove at a time. `--from`/`--once` make the loop deterministic
   under test; the desktop live-feed leg belongs to the Part-3 UI pass, stated.
2. **AI divergence narratives** (`report/narrative.py` + `DivergenceRecord.ai_narrative`,
   bundle schema v3): after every verdict and repro is FINAL, each divergence may gain a
   2-3 sentence plain-English explanation generated from the already-recorded evidence
   (symbol, class, minimized input, both observations) by the user's own model (BYOK,
   sharing ADR-0024's key + kill switch). Hard lines, each pinned: keyless → None with
   zero egress; any API failure → None (readability never takes a run down); every
   surface labels it "AI narrative"; the verdict NEVER depends on it.
3. **Propagation with honesty intact**: nullable DB column (alembic 0005 + local-store
   forward step), tri-boundary regen, CLI report + desktop panel render only when
   present. Under sync source-strip the narrative is DROPPED WHOLE — a paraphrase of
   observed values cannot be scrubbed span-by-span (L9); the planted-literal wire sweep
   now covers it.

**Consequences.** The keyed synthesis gate also proves narratives end-to-end against the
local Messages peer (identical verdicts with and without them); keyless suites and
byte-stability gates are untouched (None everywhere). Bundle readers tolerate pre-v3
bundles; older engines refuse v3 per the schema discipline.

## ADR-0030 — Settings as one config law, and watch inside the app (2026-08-17)

**Context.** HANDOFF-WORLD-CLASS §3.2 left four Settings groups unfinished (sync, storage,
privacy, and the "Test key" ping) and §4 asked for the watch loop to be reachable from the
app. Both touch the same question: where does a user preference LIVE, and how does the app
avoid lying about it? Until now the answers were environment variables read at four unrelated
call sites (`TEMPEST_SYNC_SHARE_SOURCE`, `TEMPEST_BUNDLE_BUDGET_BYTES`, `TEMPEST_TELEMETRY`,
plus a sync URL that was never stored at all).

**Decision.**

1. **`settings.json` in the data dir, with the environment on top** (`tempest/settings.py`).
   It lives in the data dir, so it belongs to one store — the app keeps its own, a bare CLI run
   uses `~/.tempest`, and a shared `TEMPEST_DATA_DIR` makes them one, exactly as the bundle
   store, logs, and telemetry counters already behave. What is unconditionally shared is the
   precedence law, the same one `tempest.toml` already follows: **environment variable >
   settings.json > built-in default**. A `TEMPEST_*` export in a shell, a CI job, or a script
   therefore stays authoritative — and because an invisible override would make the Settings
   screen a liar, `effective_settings()` returns the NAME of every field the environment is
   forcing, the API forwards the variable name, and the UI disables that control and says
   which variable to unset. Versioned like the local store (refuse-newer); a corrupt,
   non-object, or unknown-keyed document is an explicit error, never a silent reset — these
   are recorded intentions, privacy choices among them. The engine's read path
   (`load_effective_or_defaults`) degrades a damaged file to defaults so a prove still runs
   (L8) *while still applying the environment*: a broken file must not switch off something a
   `TEMPEST_*` export turned on. Only the Settings surface reports the problem, where it can
   be repaired — writing any setting publishes a fresh valid file.
   The AI key is deliberately absent: keychain only (L9).
   The budget's ceiling is 2 GiB and stated out loud — the tri-boundary integer is 32-bit
   (specta forbids BigInt-style types across Boundary B), so the limit is a named constant
   with its own refusal message rather than a silent truncation.

2. **"Test key" travels the synthesis egress path, not a second one** (`harness/llm.verify_key`).
   One `messages.create` with `max_tokens=1` and the literal content `"ping"` — no source, no
   repo name, no diff, nothing stored. With no key configured it makes no network call at all
   and says what to do instead. Same client construction, same `TEMPEST_SYNTHESIS_BASE_URL`
   knob, so the egress surface stays exactly one function wide (L10).

3. **The diagnostic export has ONE implementation.** `cli/diagnose.write_diagnostic_bundle`
   is now shared by `tempest diagnose` and `POST /v1/diagnostics`; the redaction path and its
   gate cannot diverge between the CLI and the app. The API answers a bare `filename` inside
   `<data dir>/diagnostics/`, and the Rust host's `reveal_in_data_dir` accepts only a plain
   leaf (`safe_leaf`: no separators, no `..`, no dotfiles) which it joins to the app's own
   data dir — the webview can never turn a string into a path outside it.

4. **Watch in the app produces ORDINARY runs** (`tempest_api/watchsession.py`). The loop
   polls HEAD and, on a new commit, creates a run row and proves `previous → new` through the
   same local-prove machinery. That is the whole design: no second kind of evidence, so the
   run list, ledger, cancellation, bundles, search, and the host's `RunProgressEvent` all keep
   working unchanged (the host tracks whatever run the loop reports as active, so a watched
   prove pushes progress exactly like a hand-started one). The feed of proven commits is a
   QUERY over runs carrying the `watch.commit` ledger mark — not an in-memory list — so it
   survives a restart and cannot drift from the runs it describes (L1).
   L11 is explicit: the commit is taken (and `last_sha` advanced) when the prove STARTS, so a
   cancelled prove can never make the loop re-prove the same commit forever; the battery /
   thermal hold is entered with a CancelScope the session cancels, so Stop returns the loop
   immediately even mid-hold; and Stop cancels the in-flight prove, which lands CANCELLED —
   an honest terminal state, never a verdict (L2).

**Consequences.** Four env-var reads became one document with one precedence rule, and the
screen states the truth about its own configuration including overrides it cannot change.
Watch gained a UI without gaining a parallel data model. New shapes (`SettingsIn/Out`,
`EnvOverride`, `AiKeyTestResult`, `DiagnosticBundle`, `WatchStatus/Run/StartRequest`) and a
new `ErrorCode.WATCH_ALREADY_ACTIVE` flow through the tri-boundary generator as usual.

**Paid-for lesson (trap 36).** Coverage under SQLAlchemy's async layer mis-attributes the
line immediately AFTER a greenlet crossing: `return [ ... ]` right after an awaited
`.execute()` reported as never executed while every line around it was covered. The fix is
structural, not a pragma sprawl — move post-await shaping into a plain synchronous helper, so
only the single call line carries a justified pragma and the logic itself is genuinely
measured. (`localprove.py` documents the same artifact from the other direction.)

## ADR-0031 — 1.1 hardening + the accessibility pass (2026-08-17)

**Context.** HANDOFF-WORLD-CLASS left four §1.1 hardening items open (exhaustive-enum
component renders, `reportUiError`, a desktop-src coverage gate, the BUILT-app driver leg)
and §3.3's accessibility pass. These close the gap between "the E2E suite is green" and
"the frontend cannot lie, crash silently, or lock a keyboard user out."

**Decision.**

1. **The enum vocabulary is one module with two nets** (`src/vocabulary.tsx`). Every enum
   the UI renders (Verdict, ReasonCode, DivergenceClass, Severity, TargetClassification,
   RunStatus, Lang) passes through an exhaustive switch with a `never` guard — a new Python
   variant regenerates the union and breaks `tsc` until it has copy (compile-time net). The
   vitest suite reads the variant lists from the GENERATED domain schema and drives every
   function and chip component over every variant (runtime net) — so the copy is proven
   non-empty and the schema and the switches cannot drift apart silently. Copy is L2-bound:
   EQUIVALENT_UNDER_BUDGET explicitly disclaims correctness, CANCELLED claims no verdict,
   and the guard THROWS on an unknown variant (a stale bundle must crash into the error
   surface, never invent copy). Views consume it — chips carry honest tooltips and every
   UNPROVEN panel carries actionable remediation.

2. **`reportUiError` — the webview must never fail silently.** Window `error` and
   `unhandledrejection` handlers (installed before first render) report through a typed
   command to `POST /v1/ui-errors`; the engine scrubs message/source/stack through the
   PRODUCTION redaction context before the obslog write (planted secrets are the proof),
   and the record surfaces in the LOGS view and `tempest diagnose` like any engine error.
   The reporter is itself unbreakable: never throws, burst-capped at 20 (a crash loop's
   first reports are evidence; the ten-thousandth is noise), fields truncated at 4 KB.

3. **Desktop logic coverage gate, scope stated.** `vitest --coverage` holds 100% over
   `vocabulary.tsx` + `router.ts` and runs inside `pnpm -r test` (so `make verify` carries
   it). hooks/views/App are deliberately OUTSIDE this gate: their behavior is pinned by the
   28-spec Playwright suite against the real engine, and unit-covering them would demand a
   mocked sidecar — the L4 trade stated in `vitest.config.ts`.

4. **Accessibility (§3.3), asserted not promised**: skip link as the first Tab stop; a
   named Primary navigation landmark; focus moves to the new view's title after in-app
   navigation (VoiceOver announces the destination); the engine pill is an `aria-live`
   status; motion stays 150–200 ms ease-out and is fully dead under
   `prefers-reduced-motion`; and no view forces horizontal scroll at 200% zoom (WebKit
   halves the CSS viewport, so the spec drives 590×400 and asserts zero `.content`
   overflow — evidence strings wrap, control rows re-flow). Five E2E specs pin all of it.

5. **The BUILT-app driver leg is platform-blocked, stated.** `tauri-driver` has no macOS
   backend (WKWebView exposes no WebDriver endpoint), so a driven-UI test of the built
   .app is not possible on this machine's OS. The compensating gates, already live: the
   orphan check LAUNCHES the built app and proves its real sidecar spawns and dies with
   it; parity proves the frozen sidecar produces byte-identical evidence to the CLI; and
   the E2E suite drives the identical webview bundle against the identical engine over the
   identical framing. A Linux CI leg can adopt tauri-driver when the Linux desktop ships.

**What the new tests caught (the dividend, again):** `?view=run` with no id parsed as
run #0 — `Number(null)` is `0`, so the presence check was vacuous; ids now require a
positive integer. And React StrictMode's double-effect broke a boolean "first render"
focus guard — the guard now compares routes, which the dev double-mount cannot fool.

**Consequences.** Adding an enum variant now fails three builds (Rust, tsc, vitest) until
handled everywhere — the §9b discipline finally reaches the pixels. New shapes
(`UiErrorReport/Recorded`) ride the generator as usual.

## ADR-0032 — Onboarding: the demo proof (2026-08-17, late night)

**Context.** Phase 18's activation metric is time-to-first-divergence; the roadmap asked
for a bundled demo repo reaching one in under 90 seconds. An empty app previously offered
only a form asking for a repository path — the coldest possible start.

**Decision.** "Try a demo proof" in the empty runs state → `POST /v1/local/demo`
(`demorepo.py` + the ordinary local-prove machinery). Three properties are load-bearing:

1. **The demo is real, not staged.** The engine writes a fresh git repository (base/head
   branches, first-party marker so the process sandbox may run it on a Docker-less laptop)
   and proves it exactly like any user repo — the run row, ledger, bundle, live progress
   events, and downloadable repro are all the ordinary machinery. Nothing anywhere special-
   cases "demo" except the repo builder and one ledger sentence (L4 extends to marketing).
2. **The seeded change teaches the vocabulary.** A "harmless" rounding cleanup
   (`total -= total * 3 // 100` → `int(total * 0.97)`) is DIVERGENT — integer-cents versus
   float truncation moves real money — while a genuinely equivalent label refactor lands
   EQUIVALENT_UNDER_BUDGET on the same screen. The first thing a new user learns is the
   difference between the two claims, which IS the product.
3. **Identity through ingest**: the bundle manifest carries the repo DIRECTORY's name and
   ingest verifies manifest-vs-run identity, so the repo lives at
   `<data>/demo/<unique>/tempest-demo` — constant leaf, fresh worktree per click.

**Measured.** Click → visible DIVERGENT in **6.4 s** (bar: 90 s), pinned by a timed E2E
spec; the API test pins the same bar, the two-verdict lesson, the evidence chain down to
the repro text, and demo-twice independence.

**Consequences.** `startDemoProve` rides the tri-boundary generator; the watcher tracks the
demo run like any other, so live progress is pushed, not polled. The README's "see it work"
story can now be one sentence. TS wave 2 and the `v0.2.0` tag remain the open distribution
items (the tag is the owner's push).

## ADR-0016 amendment — the stamp is a claim, not a fact (2026-08-18, trap 37)

**The field defect that forced this.** The owner's own store — the first real user store —
answered every write with `table runs has no column named sandbox_tier`, while stamped at
the migration head. History (reconstructed from the file): created in the pre-versioning
era, adopted by a build carrying the pre-review-M3 adoption bug (stamp written, columns
not), then forward-migrated 0003→0005 *from the lying stamp* — so it gained `ai_narrative`
while never gaining the 0001/0002 columns. Review M3 fixed adoption for stores not yet
adopted; it could not reach stores the bug had already mis-stamped. Every open since
trusted the stamp (`stamp == HEAD → return`), so the store stayed bricked forever.

**The amendment.** Every open of the local store now ends in `_verify_and_repair`: the live
schema is compared against the models (the fact), regardless of what `alembic_version`
says (the claim). Drift the idempotent forward steps can supply is repaired in place —
existing rows untouched, proven on a byte copy of the real field store (its runs survive;
a demo prove then lands DIVERGENT on the healed file). Drift they cannot supply raises
`DamagedDatabaseError` naming every missing column with the remediation (move the file
aside or restore a backup) — a store that half-works lies with every answer it manages to
give, and refuse-loudly is the only honest posture (L2 applied to storage). Repairs are
obslogged, so the LOGS view records that one happened.

**Trap 37, the general lesson:** version stamps, cache markers, and "already done" flags
are CLAIMS about state, and code that trusts a claim it could cheaply verify inherits
every historical bug that ever wrote the claim wrong. Verification on open costs one
schema inspection; the alternative was a permanently bricked user store that no shipped
fix could reach.

## ADR-0033 — Corpus mining was dead in every real prove (2026-08-18, trap 38)

**The field finding that forced this.** The owner's first hand-made proof: a "harmless"
shipping cleanup (`items >= 5` → `items > 5`) came back EQUIVALENT_UNDER_BUDGET on every
seed. The verdict was HONEST — the budget genuinely never exercised `items == 5` — but the
recall was broken: `5` sits in the repo's own source, and corpus mining exists precisely to
harvest it ("real values find real bugs", master spec stage 5).

**Root cause.** `mine_literals` skipped any path whose PARTS contain a skip-dir name — and
the engine's own worktrees live at `<repo>/.tempest/cache/worktrees/<sha>/`, so every file
of the very worktree being mined carried `.tempest` in its path. Mining returned `[]` in
every real `run_prove` since the cache moved under `.tempest`. No gate noticed because the
fixtures' knife-edges (0, 1, −1, boundaries of clamp/is_non_negative) all coincide with the
CURATED edge pools — the corpus proved recall of edges, never recall of mined values.

**Fix + pins.** Skip-dirs are judged relative to the mining root (a nested `.venv`/`.tempest`
inside a worktree is still skipped; the root's own location is not the root's business).
Pinned at three levels: unit (a root under a skip-named directory is mined; skip-dirs below
the root are not), and an end-to-end recall pin driving `run_prove` over the exact field
scenario — the `>= 5`→`> 5` boundary must land DIVERGENT with `items == 5` in the minimized
input. The field repo now answers: DIVERGENT, minimized `(0, 5)`, base 0 vs head 500.

**Trap 38, the general lesson:** a component can be simultaneously green and dead — every
mining unit test mined a plain tmp directory, and every integration fixture found its bugs
through a second mechanism (curated edges). When a stage's whole VALUE is additive recall,
it needs at least one end-to-end case that FAILS without it: a bug only that stage can find.

## ADR-0021 amendment — v0.2.0 release rehearsal (2026-08-18)

**The dry-run caught a release-blocking bug before the first real run ever fired:** the
`python-dist` job built `--package tempest`, but the workspace package is named
`tempest-engine` — the workflow's very first job would have failed on tag push. Every
release job is now rehearsed locally before tagging: `uv build --package tempest-engine`
(produces `tempest_engine-0.2.0` wheel + sdist), the install-check leg in an isolated
`UV_TOOL_DIR` (`tempest version` → 0.2.0; `doctor --json` assertions pass), and the app
build + `ditto` zip leg. The rehearsal habit is the lesson: a workflow that has never run
is a claim, not a fact — the same class as trap 37.

**Versions unified at 0.2.0** across engine (`__version__` + pyproject), api, tauri.conf,
desktop Cargo.toml, and every package.json — the release tag, `tempest version`, the app's
About, and the health pill all now agree. The openapi contract regenerated (it embeds the
app version) and the drift gate holds. Vitest's `coverage/` output was untracked and
gitignored (build artifacts had slipped into the tree with the 1.1 hardening).

## ADR-0034 — CodeMirror 6, not Monaco, for the v2 editor surface (2026-08-18)

**Date:** 2026-08-18 · **Status:** accepted (v2, Phase 20)

**Context.** v2 puts a real editor in the Tauri webview (F11 inline completion, F12 composer
diffs, F18 gutter divergence markers). The v2 master prompt asserts CodeMirror 6 over Monaco
and demands that disagreement come with *measured numbers, not preferences*. Agreeing with a
spec is not evidence either — so this ADR measures both rather than repeating the assertion.

What decides it is not taste, it is `docs/PLAN-V2.md`'s budget table: **idle RAM 300 MB p50 /
450 MB p95** and **cold launch → interactive 800 ms p50**, both of which the app must hit
*with* the editor loaded. Measured today (`make bench`, this audit): idle **115.2 MB RSS**,
cold launch **0.3375 s**. So the editor's whole allowance before breaching the v2 p50 idle
ceiling is roughly **185 MB**, and everything parsed at startup comes out of a ~460 ms margin.

**Measured** (esbuild `--bundle --minify --format=esm`, monaco-editor 0.56.0, CodeMirror 6 —
`codemirror` 6.0.2 + `@codemirror/lang-javascript` + `@codemirror/lang-python`; gzip -9):

| Bundle | minified | gzipped | languages included |
|---|---|---|---|
| **CodeMirror 6** (`basicSetup` + JS + Python) | **545,591 B** (533 KB) | **185,342 B** (181 KB) | 2 |
| Monaco core (`editor.api`) | 2,637,749 B (2.52 MB) | 677,392 B (662 KB) | **0** |
| Monaco main (`editor.main`) | 4,433,553 B (4.23 MB) | 1,147,142 B (1.09 MB) | all built-in |

On-disk footprint a lockfile drags in: `@codemirror/*` + `codemirror` ≈ **3.0 MB** vs
`monaco-editor` **98 MB** (33×). Monaco additionally ships **9 web-worker entrypoints** and a
24 MB prebuilt `min/vs` tree; CodeMirror needs no workers.

The honest comparison is CM6-with-two-languages against `editor.main`, because monaco's
`editor.api` is an editor that cannot yet highlight Python: **8.1× smaller minified, 6.2×
smaller gzipped.** The master prompt estimated "~5 MB plus worker overhead" and "~10× lighter";
measured, Monaco is 4.23 MB minified and CM6 is 8.1×/6.2× lighter — the spec's direction is
right and its magnitude is slightly optimistic. Recorded as measured, not as asserted.

**Decision.** CodeMirror 6, with LSP spoken by a **Rust-side multiplexer** that owns language
server lifecycles and pushes diagnostics over IPC — language servers never live in the webview.

Three reasons, in order of weight:

1. **Payload.** 662 KB gzipped buys an editor with no languages; 181 KB buys one with the two
   we need. Against a ~460 ms cold-launch margin and a ~185 MB idle-RAM allowance, that
   difference is the budget.
2. **Workers and process count.** Monaco's language intelligence assumes dedicated web workers
   per language — 9 entrypoints, each a separate bundle and a separate JS heap inside the
   webview. Tempest already supervises a Python sidecar and, in v2, an agent orchestrator and
   an index service; adding webview workers pushes against the same L11 ceiling that F17's
   8-agent fleet (2 GB p50) has to fit under. CM6 needs none — and with LSP in Rust the real
   language intelligence lives in a process the host already starts, health-checks, restarts
   with backoff, and kills by process group (the boundary-A pattern that already works).
3. **Incrementality.** CM6's state/view split is incremental by construction and tree-sitter
   friendly, which is exactly F18's requirement: gutter markers updating on save with a <5 ms
   input-latency delta. Monaco's model layer is a fine editor; it is not built around an
   external incremental parse tree.

**What we give up, honestly.** Monaco ships VS Code's TypeScript/JavaScript language service,
so out of the box it has better JS/TS smarts than a bare CM6. We pay for that with the LSP
multiplexer instead — real language servers, per language, which is strictly more capable and
is the only design that serves Python (Tempest's primary language) as well as it serves TS.
Monaco would have bought a faster start and a worse ceiling.

**Consequences / risk.** Phase 20 is editor **plus** multiplexer plus completion — the LSP work
is not deferrable, because CM6 without it is a text box. Risk: CM6's smaller default feature
surface means more editor UX (minimap, sticky scroll, multi-cursor niceties) is ours to build
or to consciously omit; `docs/POLISH.md` is where those get enumerated rather than discovered.
**This ADR is falsifiable:** if Phase 20 measures CM6 breaching any editor budget in the §5
table, re-open it with the numbers. Measurement script preserved in the phase-20 branch notes;
re-runnable against any future version pair.

## ADR-0035 — The Agent Tool Protocol is the FOURTH contract boundary (2026-08-18)

**Date:** 2026-08-18 · **Status:** accepted (v2 foundation, Phase 19)

**Context.** v1 desktop has three generated boundaries (L12): Python↔Rust (A), Rust↔TS (B),
Python↔TS (C). v2 introduces a fourth shape that crosses every one of them and additionally
crosses into a *model*: the schema of every tool the agent may call. Hand-writing that schema
in three places plus a prompt is exactly the drift L12 exists to forbid — and the failure mode
is worse than a type error, because a model handed a stale tool schema produces plausible
calls that silently do the wrong thing.

**Decision.** The Agent Tool Protocol is a first-class fourth boundary with the same law:
**one root of truth, everything else generated.** Root: a Rust trait per tool with
`schemars`-derived JSON Schema. From it we generate (a) the TS bindings the webview uses,
(b) the model-facing tool definitions, per provider, and (c) the audit-log entry shape.
`make gen-contracts` covers boundary D and the drift gate diffs it like the rest:

```
make gen-contracts && git diff --exit-code   # four boundaries, one truth
```

Rust is the root here, not Python, because the orchestrator owns tool dispatch, budget
enforcement, and capability checks — the enforcement point and the schema must not be able to
disagree. Domain *values* inside tool arguments remain Pydantic-rooted (boundary C) and are
referenced, never redefined.

**Consequences / risk.** Adding a tool, or changing an argument, breaks the TS build and the
drift gate until regenerated and committed — the design working, as with enum discipline.
Per-provider adaptation (Anthropic/OpenAI/Google tool formats) is a pure function of the
generated schema, so adding a provider never touches feature code (§7 of the master prompt).
Risk: `schemars` output must stay stable across versions or the gate churns; the version is
pinned and bumped deliberately, like `typify`.

## ADR-0036 — Shadow-worktree execution: the agent never writes the user's tree (2026-08-18)

**Date:** 2026-08-18 · **Status:** accepted (v2 foundation, Phase 19)

**Context.** L19 says the agent is untrusted code that happens to be on your side, and L20
says every agent action is reversible. Both are unachievable if agent edits land directly in
the user's working tree: a half-finished multi-file edit interleaved with the user's own
uncommitted work cannot be cleanly undone, and "hopefully git has it" is not a journal.
There is also a proof requirement: F1 must prove *a candidate state* against a baseline, and
a baseline that mutates under the user's fingers while the proof runs is not a baseline.

**Decision.** All agent file writes are staged in a **shadow worktree** — a git worktree under
`.tempest/agent/worktrees/<task-id>/`, created from the task's baseline commit, never the
user's checkout. The proof engine runs base = baseline, head = shadow. Acceptance copies the
accepted hunks into the user's tree as one atomic, journaled operation; rejection deletes the
worktree. Agent terminal commands (F14) execute at differential-runner isolation tiers with
the shadow worktree as their cwd.

Every mutation — file write, acceptance, terminal side effect Tempest initiated — is appended
to a journal that supports one-keystroke undo of any agent change, including multi-file ones
(L20). The journal is the mechanism; git is not relied upon for reversibility, because the
user's own uncommitted work must survive an undo untouched.

**Consequences / risk.** Disk cost: one worktree per active task (and per fleet agent, F17) —
governed by the worktree pool and L11 resource budgets, with reaping of completed tasks.
Correctness win: the proof baseline is immutable for the turn's duration, which is what makes
F1's verdict meaningful. Risk: worktrees and the `.tempest` cache root interact with mining
skip-dirs — trap 38's exact class — so the shadow root is judged relative to the mining root,
already fixed in ADR-0033 and re-pinned when the agent worktrees land.

## ADR-0037 — BYO inference only: Tempest never proxies your source (2026-08-18)

**Date:** 2026-08-18 · **Status:** accepted (v2 foundation, Phase 19)

**Context.** L9 (source never leaves the machine without explicit per-repo opt-in) and L10
(egress is tested, not promised) are the enterprise position and the reason the L10 egress
monitor output is a sales artifact. v2 adds a generative layer that, done the ordinary way,
would ship source code to a vendor-operated proxy — silently converting the product's central
claim into a false one.

**Decision.** **L18: BYO inference, always.** Users supply their own API keys (Anthropic,
OpenAI, Google, any OpenAI-compatible endpoint) or run local models via llama.cpp behind a
Rust-side runner. Keys live in the OS keychain — never plaintext, never synced. Tempest
operates no inference proxy in v2; a hosted option may exist later and is explicitly out of
scope now.

Consequences for the laws already in force: the egress monitor (L10) is extended to the agent
tier, and requests to the *user's own configured provider* are the only sanctioned generative
egress — allowlisted per project, visible, and absent entirely in local-model mode. L23
(graceful offline) is therefore a first-class mode, not a degradation story: with no network
and no local model, every proof feature works fully and every generative feature is disabled
with a specific reason and a one-click path to configure a local model — never a spinner,
never a silent failure.

**Consequences / risk.** We lose the ability to ship a zero-configuration generative
experience; first-run must make key configuration or model download painless (the onboarding
work of ADR-0032 extends here). We gain: the air-gapped and enterprise segments remain
addressable, and L9/L10 stay literally true — provable by the same test that already proves
them. Risk: local-model quality varies wildly; F21's Model Arena is the honest answer,
ranking whatever the user actually has by measured proof outcomes on their own repo rather
than by vendor claims.

## ADR-0038 — LibreChat adoption scope: fourteen capabilities, six refusals (2026-08-18)

**Date:** 2026-08-18 · **Status:** accepted (v2 §4.5) · **Legal record:** `THIRD_PARTY_LICENSES.md`

**Context.** The owner asked for "all the features" of LibreChat merged into Tempest. Taken
literally that request makes the product worse, so this ADR records what we adopt, what we
refuse, and — the part that matters most in twelve months — **why each refusal is a refusal**,
so a future contributor cannot "helpfully" re-add image generation and call it progress.

LibreChat is MIT-licensed, ~28k stars, Node/Express + React + MongoDB, deployed as a
**multi-user web service**. Tempest is Rust/Tauri + Python + SQLite, a **local-first desktop
application**. Their code cannot be vendored into this stack. What they genuinely own is years
of solved problems in the open: multi-provider abstraction, resumable streaming, and MCP client
behavior. Reading a battle-tested implementation before writing your own is the highest-leverage
move available.

**Decision — adopt the capability, re-implement it in our stack, subordinate it to the proof
engine (L25).** Fourteen foundations, P1–P14, each with an explicit proof-native wiring and its
own gate (`docs/PLATFORM-V2.md`). The wiring is not decoration on the adoption; it is the
adoption's justification. Three examples of what that means concretely:

- **P1 multi-provider** is not "support more models." It is the substrate for F21's Model Arena:
  every provider added is another competitor in a leaderboard ranked by *verified correctness on
  the user's own repository*. This is the rare case where breadth serves the thesis.
- **P6 conversation branching** in their product answers "which reply do I prefer." Combined with
  our shadow worktrees it answers *"branch A is EQUIVALENT_UNDER_BUDGET with a 0.94 mutation
  score; branch B is DIVERGENT on 2 inputs."* Same feature name, different category of product.
- **P2 resumable streams** is not a networking nicety here. An agent turn contains a 60-second
  proof run; the turn journal and the checkpointed proof stage are how L15.5 (zero data loss)
  becomes real rather than aspirational.

**Refused, with reasons** — this list is as load-bearing as the one above:

| Refused | Reason |
|---|---|
| Image generation (DALL·E, Flux, SD, GPT-Image) | Zero proof story, zero relationship to code correctness. The clearest single signal that a product has lost its thesis. |
| Text-to-speech / audio playback | Nobody listens to code. Speech-to-text *input* is defensible later; TTS output is not. |
| Agent Marketplace (open bazaar) | For a tool with file-write and shell access, an open marketplace is a supply-chain attack surface aimed at our most security-sensitive customers. Replaced by a signed, curated, org-scoped Proof Skill registry with mandatory review. |
| Chat as the primary surface | Our primary surface is the editor and the evidence view. Chat is a panel. Inverting that makes a ChatGPT clone with a proof feature. |
| MongoDB | SQLite local, Postgres server. A third datastore buys nothing. |
| General-purpose assistant framing | "Do anything" is the opposite of "prove this." Every general capability dilutes the one sentence that sells this product. |

**The standing test for any future adoption:** *does this make a proof more likely, more
trustworthy, or more legible?* If no, reject — regardless of how good it looks on a comparison
chart. Overturning any refusal above takes an ADR, not a drift.

**Legal.** MIT permits commercial use, modification, and redistribution with no copyleft. It is
permissive, **not free of obligation**: any copied or closely-adapted code must preserve the
copyright notice and license text. `THIRD_PARTY_LICENSES.md` exists as of this ADR, carries the
verbatim MIT notice, and holds a per-module derivation table that is currently empty —
**adoption is reference-only today; no LibreChat code has been copied.** Attribution lands in
the same commit as any future derivation, never later, and `license_check` gates it. Trademarks
and brand assets are not licensed and appear nowhere. Their RAG API (`danny-avila/rag_api`) is a
separate repo under its own terms and is reviewed independently if ever adopted.

**Consequences / risk.** The plan grows from twelve phases to fourteen (19–32): platform
completion lands in Phase 28 and enterprise reach in Phase 29, both *after* the proof features
they serve, per the sequencing rule that P\* never precedes its F. **The specific risk this ADR
introduces is failure mode 9: becoming a chat app with a proof feature.** The mitigation is
structural rather than cultural — chat is a panel, never the primary surface; every P has a
named F it serves and a gate that tests the wiring, not just the capability; and any P shipping
without its proof-native wiring is a build failure under L25, not a style disagreement.

## ADR-0038 amendment — Tempest is MIT; copying LibreChat code is authorized (2026-08-18)

**Two owner decisions, and one defect the first one exposed.**

**1. Tempest AI is released under the MIT Licence.** The audit for this change found that the
repository had **no `LICENSE` file at all** — and a repository published publicly with no
licence is *all rights reserved by default*, which is the exact opposite of the open-source
intent. Every visitor since publication has technically had no grant to use, copy, or modify
anything. Fixed: `LICENSE` (MIT, `Copyright (c) 2026 Prithvi Vinay`) plus `license = "MIT"` in
both pyprojects and all four `package.json` files, so a built wheel or npm package carries the
grant instead of leaving it behind in the repo.

**2. Copying LibreChat code is authorized** (superseding "reference-only" in ADR-0038). MIT
permits it for commercial use, with modification, no copyleft. The obligation that remains is
attribution, and it is now mechanical rather than cultural — see gate below. The practical
shape of the adoption is unchanged by the permission: LibreChat is Node/Express + React +
MongoDB and Tempest is Rust/Tauri + Python + SQLite, so whole-file vendoring mostly does not
typecheck across that gap. **Copy what ports** (schemas, config shapes, protocol handling,
tool/prompt formats, algorithms), **re-implement what doesn't, attribute either way.** The
React webview is where near-verbatim reuse is genuinely likely and where notices matter most.
L25 still governs: whatever arrives is subordinated to the proof engine.

**The gate (Phase 19.1, built with this ADR — not deferred).**
`python -m tempest.dev.license_check --third-party-notices`, live inside `make verify`. It fails
the build on any of: a missing/non-MIT `LICENSE`, a licence with no copyright holder, package
metadata omitting MIT, a third-party project named without its licence text reproduced, a
section marked `CODE DERIVED` whose derivation table names no module, or a named project absent
from the README. 18 unit pins, each proving a *failure* on a violating tree — a gate that cannot
fail is decoration.

**Two things the gate caught in its own first run, both worth recording.** It flagged
`THIRD_PARTY_LICENSES.md` as code-derived because the prose *discussing* the string
`CODE DERIVED` matched a substring search — **trap 25's class exactly** (a grep that matches the
discussion of a thing rather than the thing). And it read the stub template's
`- **Upstream:** <url>` as a real adoption, because a naive fence toggle mis-tracks nested code
fences. Both fixed structurally: sections are identified by the **structured `- **Upstream:**`
field outside fences**, fence nesting follows CommonMark (a fence of N backticks closes only on
a fence of ≥ N), and fenced content is excluded from field lookup entirely.

**Also corrected: a false attribution claim I had written.** The first draft of
`THIRD_PARTY_LICENSES.md` stated that `corpus/impure/` vendors third-party functions with
per-file attribution headers. It does not. `docs/QUESTIONS.md` Q5 *planned* that; **ADR-0010
overrode it** — the 30 corpus functions are hand-written replicas of named idioms, with no
third-party copyright to attribute. The lesson is small and sharp: a QUESTIONS default is a
proposal, an ADR is the decision, and when they disagree the ADR wins. Verified against the
actual file headers, not the plan.

**Consequences.** `README.md` gains Licence and Credits sections stating plainly that Tempest's
platform layer is **based on LibreChat**, with no affiliation or endorsement implied and no use
of their marks. Attribution is now enforced at the same moment as adoption, which is what L25
asks for and what a procurement reviewer will check.

## ADR-0035 implementation note — boundary D is live (2026-08-18, step 19.2)

**Status: implemented.** `packages/desktop/src-tauri/src/agent_tools.rs` is the root of truth;
`make gen-contracts` emits four committed artifacts (canonical manifest, Anthropic envelope,
OpenAI envelope, and the webview's typed view). Six tools are declared — `read_file`,
`list_dir`, `search_text`, `write_file`, `run_command`, `prove`.

**The drift gate needed no change.** Boundary D's artifacts land inside
`packages/shared-schema` and `packages/desktop/src/generated`, which `verify-contract` already
diffs — so the fourth boundary is gated by the same one-line command as the first three. Four
boundaries, one truth, one gate.

**Proven in both directions, because a gate that cannot fail is decoration.** Mutating one tool
description and regenerating turned `git diff --exit-code` red (exit 1); restoring it returned
exit 0. That experiment is the evidence the gate works, and it is the reason the artifacts are
committed rather than computed at runtime.

**Two invariants moved out of reviewer vigilance and into the type system.** `WriteScope` has no
variant for the user's working tree, so a tool cannot *express* a write to the user's checkout —
L19 holds by construction rather than by discipline, and an unrepresentable state cannot be
reached by a bug. And `ToolSpec::invariants_hold` rejects any networked or destructive tool
declared `Approval::Auto`, and any destructive tool that is not `AlwaysPrompt` — §8 requires
those to be approval-gated *regardless of policy, always*. Both are pinned by tests that
construct violating specs and assert the rejection, so the checks are proven to bite on a
careless future declaration rather than merely to pass today.

**Deliberately the contract and not the runtime.** There is no `execute` and no dispatch;
the orchestrator arrives in Phase 21 and will implement dispatch against these exact
declarations. Shipping the schema first means every later change to the agent's capabilities is
guarded from the start, instead of the tool surface growing unguarded and being retrofitted.

**Dialect recorded rather than assumed:** `schemars` 0.8 emits **draft-07**, not 2020-12. Both
provider envelopes accept it. The first draft of this module claimed 2020-12 in a doc comment;
the generated output falsified it, and the comment was corrected — the same "verify, don't
assert" habit the product sells.

**Cost of the dependency:** `schemars` added **two lines** to `Cargo.lock` (it was already
present transitively), so the fourth boundary costs essentially no new supply-chain surface.

## ADR-0036 amendment — the shadow worktree lives in the ENGINE, not the Rust host (2026-08-18, 19.3)

**The deviation, stated rather than drifted.** ADR-0036 placed the shadow-worktree manager in the
Rust orchestrator. It is implemented in Python instead — `tempest/agent/shadow.py`. Three reasons,
in order of weight:

1. **The Rust host is a supervisor and a typed bridge, not a domain layer.** All 25 commands in
   `commands.rs` delegate to the sidecar; putting git-worktree semantics in Rust would be the
   first piece of domain logic to live there, and would then need its own RPC surface anyway for
   the engine to prove against.
2. **The engine already owns worktrees** (`envrepro/worktree.py` materialises base/head for every
   proof) and the real-git test infrastructure that goes with them.
3. **The 100% coverage gate applies to Python.** `shadow.py` lands at 167 statements / 52
   branches / **100%** with no pragmas, against real repositories — a standard the Rust side does
   not currently hold itself to.

Boundary D (ADR-0035) is unaffected: the orchestrator still owns dispatch and capability
enforcement in Rust; it reaches staging over boundary A like everything else.

**The design decision worth keeping.** The baseline is built with **`git stash create`**, which
writes a commit object capturing the working state *without touching the tree, the index, or the
stash list*. A baseline of bare `HEAD` would have handed the agent a tree that differs from the
user's screen whenever anything is uncommitted — and then every uncommitted edit of theirs would
read as an agent change in the proof diff. Untracked files are carried across separately, because
`stash create` captures tracked changes only. A test asserts the user's tree is byte-identical
before and after `create()`.

**Why a snapshot is a commit.** `snapshot()` commits the shadow onto its own branch and returns a
sha resolvable from the user's repository, so F1's proof step is `prove(baseline_sha,
shadow_sha)` against the existing nine stages — no "prove a dirty directory" concept, no engine
change. That is the whole reason to use a git worktree rather than a copied directory.

**Acceptance is all-or-nothing and already reversible.** Preconditions are validated across the
entire changeset before a byte is written, so one conflict applies nothing. Pre-images are
journalled to `.tempest/agent/journal/<id>/`, which means undo restores the user's bytes **even
when their baseline was never committed** — precisely the case `git checkout` cannot serve, and
exactly why L20 says "journalled, not 'hopefully git has it'". 19.4 generalises this journal to
every agent action and adds the one-keystroke surface; acceptance is reversible from day one so
that no window exists where an agent mutation is unrevertable.

**Conflict policy: the user always wins.** If a target file changed since staging — edited *or
deleted* — acceptance refuses and names the files. Re-creating a file the user deliberately
removed is a silent surprise, so deletion counts as a conflict too.

**Containment is checked against the RESOLVED path**, so a symlink planted inside the shadow
cannot tunnel out; absolute paths, `..` traversal, and anything touching `.git` are refused.
Seven traversal shapes and a real symlink escape are pinned as tests.

**Trap 38 interaction, noted for 19.4+:** these worktrees live under `.tempest`, and corpus mining
judges skip-dirs relative to the mining root (ADR-0033). Nothing regressed here — mining a shadow
is not yet wired — but the pin belongs with whatever first proves a shadow.

## ADR-0039 — The agent journal: one record, append-only, ordered undo (2026-08-18, step 19.4)

**Context.** L20 requires one-keystroke undo for any agent change, "journalled, not 'hopefully
git has it'". That phrasing decides the design: git can only restore what was committed, and the
state a user most wants back is usually the *uncommitted* one they had five seconds ago. So the
journal stores **pre-images**, not refs.

**Decision.** `tempest/agent/journal.py` — an append-only JSONL log plus a directory of
pre-images per entry, with three properties that make undo trustworthy rather than merely present:

1. **Append-only.** Undoing appends an `undo` record; it never rewrites a line already written.
   The log is therefore a complete account of what happened *including the undos* — the same
   tamper-evident posture L14 requires of the audit log.
2. **Durable and stateless.** Every query reads disk, so undo survives a crash, a restart, or a
   sleep. That is precisely the case an in-memory undo stack fails, and the case P2 (resumable
   turns) will depend on.
3. **Ordered.** `undo_last()` reverses the most recent *pending* entry. Out-of-order undo is
   **refused with a reason**, because if two entries touched the same file, restoring the older
   pre-image would silently overwrite the newer content. The refusal is pinned by a test that
   asserts the tree did not move.

**One journal, not two.** `shadow.accept` (19.3) was refactored to write through this journal
instead of keeping its own pre-image copy. An acceptance is now an ordinary entry, so
`undo_last()` reverses it exactly as it reverses an edit, and `shadow.revert()` is a thin alias
for `journal.undo()`. There is one reversal path, which means there is one place for undo to be
correct. The refactor also **deleted shadow.py's only `# pragma: no cover`** — its defensive
rollback branch is now the journal's context manager, covered by a real test that raises
mid-action and asserts the tree is unchanged and nothing lingers in the undo stack.

**Command entries exist before the terminal does.** `KIND_COMMAND` is in the vocabulary now, with
the same reversal mechanism as an edit, so F14's sandboxed terminal (Phase 23) journals its side
effects the moment that surface lands rather than having reversibility retrofitted onto it —
which is how the "terminal side effects Tempest initiated" half of L20 gets honoured.

**The gate, met.** Phase 19's exit criterion is *"undo restores any state"*. That is a property
test: randomised sequences of writes and deletes across overlapping files, twelve seeds, then
undo everything and assert the tree matches byte-for-byte where it started. It covers the
interleaving that breaks naive implementations — an entry deletes a file, a later entry
recreates it — where LIFO restore is the only order that lands correctly.

**Tolerant reader (trap 37's lesson, applied).** The log is a file on disk and can be
hand-edited or truncated. Blank lines and non-object JSON records are skipped rather than
thrown on, because a reader that crashes takes the user's undo away at exactly the moment they
need it. Pinned by a test that appends junk and then undoes successfully.

**Typing note.** JSON parsing uses `Any` at the boundary and narrows with `isinstance`, matching
`settings.py`'s existing pattern — no `type: ignore` anywhere in the module.

**Coverage:** `journal.py` 111 statements / 30 branches / **100%**, `shadow.py` 139 / 40 /
**100%** after the refactor, 67 tests, zero pragmas.

## ADR-0040 — P1: sixteen providers, two wires, one code path (2026-08-18, step 19.5)

**The observation the whole design rests on.** The master prompt asks for 12+ providers and for
"adding a provider must not touch feature code". Both fall out of one fact: **two wire protocols
cover the entire market.** Anthropic speaks its own Messages API; everyone else — OpenAI, Azure,
Google's compatibility endpoint, groq, Mistral, DeepSeek, OpenRouter, Together, Perplexity, xAI,
Fireworks, Cerebras, and every local runner (Ollama, LM Studio, llama.cpp) — speaks OpenAI Chat
Completions.

So breadth costs **two request builders and N rows in a table**, not N integrations. Sixteen
providers ship in `tempest/inference/providers.py`; `tempest/inference/client.py` contains no
per-provider branch anywhere. The claim is *checked*, not asserted: a test invents a provider
that appears nowhere in the registry file and drives a full completion through it.

**Stdlib only, no vendor SDK.** `urllib.request` rather than a per-provider client library. A
vendor SDK is a per-provider dependency, which is precisely the cost this design exists to
avoid; it also keeps the frozen sidecar small and keeps the entire egress surface visible in one
file (L10).

**Cancellation actually cancels (master prompt §7).** `stream()` checks the cancel token between
chunks and **closes the response**, tearing down the upstream connection so the model stops
generating — and stops billing. The test proves it from the *server's* side: the peer records a
broken pipe, which is observable evidence the connection died rather than the client merely
having stopped displaying tokens. That second behaviour is what most clients ship, and the user
pays for the pretence.

**No invented model ids.** `default_model` is `None` for every provider whose current model
naming I cannot assert, and the error says why: *"model ids change faster than a pinned table can
stay honest."* Anthropic keeps `claude-sonnet-5` because the repo already uses it. When a model
is rejected, the client surfaces the **provider's own message verbatim** rather than guessing on
the user's behalf. A registry full of plausible-looking but stale model names would be exactly
the kind of confident wrongness this product exists to refuse.

**The gate answers QV10 honestly.** `provider_matrix --min-providers 12` runs **entirely
offline** by default: it checks registry integrity and then *exercises the real request path for
every one of the sixteen* against a loopback peer speaking that wire. Free, deterministic, and
runnable in CI on every PR — because a gate needing twelve sets of paid credentials is a gate
that never runs, and a gate that never runs is a claim (trap 37). `--live` additionally calls
only the providers whose keys are actually present and reports **"N of M verified live"**. That
number is deliberately partial: claiming twelve live providers we never called would be unearned.

**L23 becomes concrete, not aspirational.** Three local runners need no key and work with the
network unplugged. The `Offline` error names them, and states that proof features are unaffected
because only generative features need a model.

**Placement, stated rather than drifted.** ADR-0037 framed the model layer as Rust. It is
implemented in the Python engine, for the same reasons recorded in the ADR-0036 amendment: the
Rust host is a supervisor and typed bridge, the engine already owns the one existing model call
path and its fake-peer test discipline, and the 100% coverage gate is Python's. The Rust
orchestrator reaches it over boundary A like everything else.

**Tracked, not silently deferred: `harness/llm.py` and `report/narrative.py` still use the
Anthropic SDK** for synthesis and narratives. Migrating them onto this client (which would drop
the `anthropic` dependency entirely and leave exactly one model path) is **step 19.5b** in
`docs/PLAN-V2.md`, deliberately not folded into this step — those are proven paths, the frozen
sidecar spec references the SDK, and destabilising them mid-phase to save one commit is a bad
trade. Two model paths is a wart with a name and a due date, which is the honest form of it.

**Trap 41, paid for during this step: `tempest/model.py` already existed.** The layer was first
written as `tempest/model/` — a package that silently *shadowed* the existing domain-enum module
(`Verdict`, `ReasonCode`, `Stage`), breaking imports in 25 files. Nothing in the sandbox caught
it, because the sandbox had no `tempest/model.py`; `mypy --strict` caught it in one run, in the
repo. Renamed to **`tempest/inference/`**, which is unambiguous and matches L18's "BYO
inference" language. The lesson is about the *rehearsal*: proving a module in an isolated
scratch package is excellent for logic and worthless for collisions — the tree it will actually
live in is the only place a name can be proven free.

## ADR-0041 — The cost meter: caps at the router, dollars never guessed (2026-08-18, step 19.6)

**Context.** L21 says cost is visible before it is spent: estimates above a threshold, a running
meter, hard caps per task/session/day, never a surprise bill. Each clause decided a detail.

**Caps live where the spending happens.** `Meter.spend()` checks every budget and appends the
ledger record **under one lock**, so passing the gate and spending are the same act. A cap
enforced in a UI is not a cap — any caller that skips the UI skips the limit — which is why the
master prompt says "hard caps enforced at the router, not the UI" and why the enforcement sits
next to the request rather than next to the button. `preflight()` answers "may I, and what will
this cost" *before* a request is built, so an operation that is not allowed to finish never
starts.

**The concurrency case is real, not theoretical.** F17 dispatches a fleet that spends in
parallel. Without the lock, two turns each read a total below the cap and both proceed, so a
"hard" cap admits N charges instead of one. A test starts eight threads against a cap that
admits exactly two and asserts exactly two land.

**Tokens are measured; dollars are computed from a rate the user supplies.** Token counts come
from the provider's own `usage` field via `inference.Usage`. Prices do not: they are absent from
the response, they change, they differ per contract, and a hardcoded price table goes stale
**silently** — the worst failure mode available, because it produces a confident wrong number on
a billing screen. So **this module ships no price list.** With no rate configured the meter still
counts tokens exactly and reports `dollars = None`, which a UI renders as "not priced" rather
than as `$0.00`. A partial total also carries `unpriced_charges`, so a figure that is incomplete
says so instead of quietly under-reporting.

This is the same discipline as ADR-0040's refusal to invent model ids, applied to money, where
the cost of being confidently wrong is higher.

**An unevaluable limit never passes.** A dollar cap with no configured rate raises
`RateUnknown` rather than allowing the spend. *"I could not check your limit"* must never be
indistinguishable from *"you are within your limit"* — that is the L15.3 rule (no silent
failures) applied to the one subsystem where a silent pass costs the user money. Token caps work
with or without rates, so a user who has configured no prices still gets real hard caps.

**Durable, append-only, tolerant.** The ledger is JSONL beside the agent journal: totals survive
a crash and a restart, because an in-memory counter loses exactly the history a user asks about
after something goes wrong. Blank and non-object lines are skipped rather than thrown on (trap
37's lesson again — a hand-edited ledger must not take the meter down).

**Cache hit rate reports `None`, not `0.0`, when nothing has been spent** (§7 asks for it to be
surfaced so users see the saving). Zero would read as "the cache never works"; `None` reads as
"nothing to report yet".

**Deferred with a name:** cost-per-verified-outcome — dollars per *proven* task, the metric
`docs/METRICS.md` calls the one no competitor can compute — needs F21's proof-ranked outcomes and
lands with Phase 27, not here. The ledger already records provider, model, and scope keys, which
is everything that metric will need.

## ADR-0042 — The §5 budgets as a gate that reports its own coverage (2026-08-18, step 19.7)

**Context.** L22 makes the §5 performance table gates, not aspirations. But **ten of its thirteen
budgets measure surfaces that do not exist yet** — the editor (Phase 20), the agent (21), the
index (22), the composer (23), the fleet and ambient watch (26), the debugger (27). The tempting
shape is to enforce the three we can measure and print `perf: PASS`, which a reader takes to mean
*thirteen budgets met*. That is manufactured confidence, and it is precisely the failure this
product exists to refuse.

**Decision.** `tempest/dev/perf_suite.py` encodes the **whole table** and reports every row in one
of four states, then states the coverage explicitly:

* `MET` / `OVER` — measured against real data and enforced.
* `NOT-YET-MEASURABLE` — the surface does not exist; the row **names the phase that will build
  it**, so a gap has an owner rather than being merely absent. Never counted as met.
* `NOT-YET-MEASURED` — the surface exists but this run did not collect what the budget needs.

Every run ends with *"3 of 13 §5 budgets are measurable today; the rest are NOT-YET-MEASURABLE
and are never counted as met."* A budget written down with an owner is a commitment; a budget
left out of the file is one nobody will be held to — which is why the ten unbuildable rows are in
the table from the start.

**Why p95 is usually `NOT-YET-MEASURED`.** `tempest.dev.bench` stores aggregates, and for cold
launch it stores **`min(samples)`** — the most flattering statistic available. A p95 cannot be
derived from a minimum, so p95 is enforced only when the bench emits raw `samples`, and reported
as not-yet-measured otherwise. Comparing a best-case number against a p95 budget would be worse
than not checking it, because it would *look* like coverage. Having the bench emit its raw
samples (it already collects them) is the cheap follow-up that turns three p95s on.

**The gate found something on its first run, and it is recorded rather than tuned away:**

```
PERF-GATE cold_launch: 0.3375s regressed 13.7% over baseline 0.2968s (bar 10%)
```

The **absolute** budget is met with wide margin (0.34 s against a 0.8 s p50). What trips is §5's
**10% regression bar** — tighter than the v1 `bench_guard`'s 15%, which is why this is newly
visible. Two candidate explanations: real drift, or that `bench/bench.json` was captured while
the machine was busy running an audit. **It is deliberately left failing.** Re-baselining to make
a gate green is the exact move v2 failure mode 2 warns about, and a 40 ms delta on a metric with
a 460 ms margin is the kind of thing that must be *decided by a clean measurement*, not by
adjusting the bar. The action is a re-run of `make bench` on a quiet machine, then either the
number returns and nothing was wrong, or it does not and there is a real regression to chase.

**Placement.** `make perf-gate`, not `make verify`. It needs a fresh bench run and its numbers
depend on machine load; `make verify` must stay deterministic. Same reasoning that keeps
`bench_guard` out of it. The CI perf job is where it becomes a blocking gate on every PR.

**Also recorded:** a budget is a **ceiling, not a strict inequality** — 300 MB is within a 300 MB
budget — and the percentile is nearest-rank, defined in one place, so "p95" means one thing
across the repo.

## ADR-0043 — Five defects the review workflow found in Phase 19, and what they teach (2026-08-18)

**Context.** With multi-agent review re-authorised (owner, 18 Aug, capped at ten), four
independent lenses were run over the landed 19.1–19.5 code — agent correctness, inference
correctness, security/Laws, and test quality — with refute-by-default verification of the top
findings. **28 raw findings, 5 verified, 0 refuted.** All five were real, all five are fixed
here, and every fix landed test-first (each new test was watched failing on the old code).

**1. CRITICAL — untracked files poisoned the baseline (`shadow.py`).** `git stash create`
captures *tracked* changes only. `create()` copied untracked files into the worktree but never
into the baseline commit, so `changed_files()` reported the user's own files as agent work,
`accept()` raised a false conflict naming a file the agent never touched, and — acceptance being
all-or-nothing — **one ordinary untracked file anywhere in the repo made every acceptance
impossible**. The same gap corrupted the proof pair: `snapshot()` on an untouched shadow no
longer equalled its baseline, so F1 would have attributed the user's files to the agent. Fixed by
committing the carried files into the baseline, so the baseline is *true*: a claim about what the
agent started from that actually holds.

**2. CRITICAL — the API key leaked on redirect (`inference/client.py`).** `urlopen` follows 3xx,
and CPython's redirect handler copies every header onto the new request, so `x-api-key` /
`authorization` were re-sent verbatim to whatever host a `Location` named — past the per-project
egress allowlist, exactly the exfiltration THREAT-MODEL T2 exists to prevent. Fixed by refusing
redirects: a provider that genuinely moves is a configuration change the user makes deliberately,
not something a response header does silently. The refusal names the host and **not** the key,
and uses `raise ... from None` because the chained context would carry the request, and the
request carries the key.

**3. CRITICAL — the test that hid defect 1.** `test_untracked_user_files_are_carried_into_the
_baseline` set up the exact precondition and then stopped one assertion short: it checked the
bytes arrived in the shadow and never called `changed_files()` or `accept()`. **This is the
finding that matters most**, because it explains how the other two survived a 100% gate.

**4. MAJOR — the conflict comparison was wrong in both directions (`shadow.py`).** It compared
against `_git()` output, which does `.strip()` — leading *and* trailing whitespace, not the
trailing newline the comment claimed. So it invented conflicts on any file whose content begins
with a blank line (ordinary YAML and markdown), and it **missed real user edits that changed only
surrounding whitespace, silently overwriting their work**. Now compared as bytes via a raw git
wrapper.

**5. MAJOR — `list_shadows()` rebuilt the wrong baseline.** It read the branch tip, but
`snapshot()` moves that branch forward, so after a restart a shadow diffed against itself,
`changed_files()` returned `[]`, and `accept()` silently applied nothing — losing agent work in
exactly the flow the docstring advertised ("survives a restart with no state"). The baseline is
now *recorded* on disk at creation and never re-derived from a mutable ref. The metadata lives
**outside** the worktree, because the first fix put it inside and `changed_files()` immediately
reported it as agent work — the same class of bug, caught within the minute.

**The lesson worth more than the fixes: 100% line and branch coverage proved nothing about
these.** Every arm was executed — just never in the *state* that mattered (an untracked file
present; a snapshot taken and then reloaded; a file beginning with whitespace; a server that
answers with a redirect). Coverage measures which lines ran, not which situations were
considered. **Trap 43:** when a module's behaviour depends on external state (a git tree, a
network peer, the filesystem), enumerate the *states* explicitly — coverage will not do it for
you, and a green 100% gate is exactly the thing that makes you stop looking.

**Process note.** The reviewing lens that found defect 3 did so by mutation testing — editing
`shadow.py` in the real tree to see whether a test would catch the break. Correct technique,
wrong sandbox: it raced a commit. Reviewers now get read-only instructions explicitly, or
`isolation: 'worktree'` (trap 42).

## ADR-0044 — A test asserted a false fact about the repo, and only CI could see it (2026-08-19)

**Context.** Phase 19 was handed off as complete with a green local `make verify` (`MAKE_EXIT=0`,
1243 passed / 100.00%). CI on the same commit `5717c41` was still `in_progress` at hand-off and
came back **failure**: `1 failed, 1235 passed, 7 skipped`, coverage still 100.00%. The two docs
commits CI ran above it (`037ec90`, `b68f212`) failed identically, so the red was deterministic.
The one failure was `test_perf_suite.py::TestCli::test_the_real_repo_bench_file_is_evaluated` —
`AssertionError: the repo ships a committed bench.json`.

**The defect.** The test reached into the repo for `bench/bench.json` and asserted the repo ships
it. That sentence is **false**: `bench/bench.json` is `.gitignore`d (line 44) because it is *this
machine's* latest measurement, produced by `make bench`. The only bench file the repo ships is
`bench/baseline-darwin.json`. The test passed on the author's Mac purely because a generated copy
happened to be sitting in the working tree; on CI's fresh checkout there was no such file.
Introduced by 19.7 (`6cc3acb`) and pushed in the same batch as `5717c41`, so CI ran it for the
first time only on the tip — the failure is as old as the test.

**Why the 100% gate could not see it.** Coverage was 100.00% *in the same run that failed*.
`tempest/dev/*` is omitted from the coverage denominator anyway, but the deeper point is trap 43's
in a new dress: the gate measures the code, and this defect was in a **claim about the
repository** — an environmental fact no coverage number ranges over.

**Decision.** Point the test at `bench/baseline-darwin.json`, the file the repo genuinely ships,
and add the assertion that was missing: that the path is **in the committed tree**, not merely
present on disk. The check is `git cat-file -e HEAD:<repo-relative-path>` and deliberately **not**
`git ls-files --error-unmatch`, which reports the *index*: a file that has been `git add`ed but
never committed answers "tracked" there while a fresh checkout would still lack it — the same
defect one step later. (The first draft of this fix used `ls-files`; a throwaway repo showed it
answering TRACKED for a staged-only file, so it was tightened before landing.) The `rev:path` form
also takes a literal path rather than a pathspec, so glob metacharacters in a filename cannot be
reinterpreted, and it was checked against a depth-1 shallow clone in detached HEAD — what
`actions/checkout` actually produces.

**The count is asserted, not just the phrase.** The first draft asserted only
`exit_code in (0, 1)` and `"of 13 §5 budgets" in out`. Review showed that could not distinguish
"3 of 13 evaluated" from "**0** of 13": `ps.evaluate({}, None, None)` renders
`"0 of 13 §5 budgets…"`, which contains the substring, and returns 0, which is in `(0, 1)` — so
the case passed while the gate read *nothing* from the committed file. That is exactly the "gate
that manufactures confidence" the module exists to prevent, and it would have hidden a real
schema drift between `perf_suite` and the artifact the repo ships. Now `"3 of 13 §5 budgets are
measurable today"` is asserted. `Report.measured` counts MET and OVER alike, so the number is
pinned to the metric *key set*, not to any measured value — it is deterministic on every machine
and moves only when the shipped artifact or the budget table does. Phase 20 turns three editor
budgets on and it becomes 6, deliberately and visibly.

**Rejected.**
- *Skip the test when the file is absent.* It would go permanently silent on CI — the one place
  it runs against a fresh checkout. Weakening a gate to make it pass is v2 failure mode 2.
- *Commit `bench.json`.* It is per-machine measurement output, regenerated by `make bench`, so
  committing it would leave the tree dirty after every run and would present one laptop's latest
  numbers as a fact about the project. (An earlier draft also objected that it "would have Linux
  CI evaluating a darwin measurement". Review pointed out the *accepted* fix does exactly that,
  since `baseline-darwin.json` is darwin data too. The objection was wrong and is **withdrawn**:
  evaluating darwin bytes on Linux is fine here, because the test asserts the gate reaches a
  verdict on committed input, not that the numbers describe the runner.)
- *Assert an exact exit code.* Coupling the case to baseline *data values* would conflate "the
  baseline changed" with "the gate broke". The measurable *count* above is a different thing.

**What is pinned, and what is NOT.** `test_the_committed_check_tells_a_shipped_file_from_a_local
_measurement` asserts the predicate answers `True` for `baseline-darwin.json` and `False` for
`bench.json`, so the guard's discriminating power is tested rather than incidental and this test
file cannot quietly regress. **That is the instance and this file — it is not a repo-wide gate.**
`_is_committed` is module-private and nothing stops a new test elsewhere from using bare
`Path.is_file()` on a repo path. A mechanical repo-wide check is **queued, not built** (§4 of the
handoff).

**The sweep, stated accurately.** Exactly one instance of *this* defect exists — a test reading a
repo file that no CI step produces. Every other `bench.json` reference in the tests is a synthetic
`tmp_path` file. An earlier draft added "and no test reads any other gitignored artifact", which
review showed to be **false** and which is withdrawn. Known reads of gitignored artifacts, all
deliberate and all produced by an explicit CI step:
- `node_modules/` is gitignored (`.gitignore:15`) and `pnpm install --frozen-lockfile` produces
  it; the built sidecar comes from `build-server.sh`. Both are steps in `ci.yml`.
- **`test_prove_scope.py:41-52` is the one worth watching**: it gates *which assertion runs* on
  `default_sidecar_dir()/node_modules/ts-morph` existing — `DIVERGENT` when present, `UNPROVEN`
  when not. It never fails; it silently downgrades. CI installs the dependency so the strong arm
  runs there, but the pattern is trap 44's, and it is queued for a follow-up.
- `test_license_check.py:138` and the corpus fixture loaders use bare `Path.is_file()` on repo
  paths. Those files *are* committed, so the tests are correct today; the pattern is the one
  trap 44 warns about.

The distinction that actually matters is therefore **not** "is it gitignored" but **"does a CI
step produce it on a fresh checkout?"** Nothing produces `bench.json`. That is the sharper test.

**One honest limit.** "The input is committed bytes" is true of a *clean* tree. `_is_committed`
asks HEAD; the evaluation that follows reads the working copy from disk. If someone edits
`baseline-darwin.json` without committing, the guard still passes and the gate reads the edited
bytes. Determinism here rests on the tree being clean, which is also what `verify-contract`
already assumes.

**The process lesson, which is the larger one.** The hand-off recorded "green" from a local run
while the CI run that contradicted it was still in flight. Both numbers were true; only one of
them travels. **A local `make verify` is evidence about this machine, and the claim "Phase N is
complete" is a claim about the repository** — so it is not settled until the fresh-checkout run
answers. Confirm CI before writing "complete", not after.

**Trap 44 — a test that reads a repo file must assert the file is COMMITTED, not merely present.**
Local green is measured in a working tree that contains build output, measurements and scratch
files; CI is measured in a fresh checkout that contains only what is tracked. Prove it with
`git cat-file -e HEAD:<repo-relative-path>` at the point of use — and note that this ADR needed
two passes to get right, because the first fix's own guard (`ls-files`) and its own assertions
("of 13") repeated the very shape of the bug they were closing.

## ADR-0045 — The editor reads files in Rust, behind one guard, and what a hard link taught (2026-08-19)

**Status:** accepted (v2, Phase 20.1 / 20.1b) · **Commits:** `f1b3502`, `43fbb25`, `31a40cc`,
`453075b`, `2a0a998` · CI green on `2a0a998`, all seven jobs.

**Context.** Phase 20 puts a CodeMirror 6 editor in the webview. An editor must open files, and
every other command in `commands.rs` forwards to the Python sidecar. §5 budgets "open file
(10k lines)" at a p50 of **40 ms**, and a JSON-RPC round trip through a second process to hand
back bytes the OS already has spends that budget on nothing. `agent_tools.rs` already declared a
`read_file` tool whose own docstring says absolute paths, `..` traversal and the credential
denylist "are rejected by the orchestrator" — an orchestrator that does not exist until Phase 21.

**Decision.** `read_project_file` is a Tauri command that reads directly in Rust, and the safety
the sidecar boundary would have supplied comes from **one module**, `pathguard`, which Phase 21's
`read_file` dispatch will use as its second caller. The owner chose this shape explicitly over
giving the editor its own reader: a rule stated in two implementations is a rule that can
disagree with itself, which is the reasoning that put the Agent Tool Protocol behind a generated
contract (ADR-0035). `ProjectFile` is a Tauri-local type, not a Boundary A domain type —
nothing about opening a file in an editor exists in the Pydantic model, and minting a domain
shape for a desktop-local capability would put a fiction in the contract (`SidecarStateEvent`
sets the precedent).

**The guard, and the four things review changed about it.** A path is readable only if it is
inside a root that is itself a git working tree, contains no `..`, resolves inside that root,
names no credential, is a regular file with exactly one link, is valid UTF-8, and fits the cap.
Four of those clauses exist because a thirteen-lens review found them missing:

1. **A hard link defeated the credential denylist entirely.** The module argued that applying the
   denylist twice — to the requested path and to the resolved one — closed the "innocent name,
   secret bytes" hole. It closed the *symlink* form of it. A hard link IS the file: no target to
   follow, and `canonicalize("notes.txt")` answers `"notes.txt"`, so both applications pass. A
   probe read `SECRET=hunter2` through it, and a verifier reproduced the same bypass for all
   three denylist mechanisms (`.env` by segment, `.ssh/id_rsa` by segment, `server.pem` by
   suffix) while the symlink control was correctly refused. **No name-based rule can ever see a
   hard link**, so the fix is not a better name rule: a file with more than one link is refused,
   because a file with more than one name cannot be judged by the name it was requested under.
   Cost, accepted: pnpm hard-links its store into `node_modules`, so those files do not open.
2. **`.git` was readable under every root the guard accepts** — and the guard *guarantees* `.git`
   is present, since that is how it recognises a project. `.git/config` carries remote URLs with
   embedded tokens. Now denied, with `.git-credentials`, `.npmrc`, `.pypirc`, `id_ed25519` and
   `id_ecdsa` — the list had named only the legacy ssh key and the `$HOME`-shaped secrets, and
   missed the ones that live in the project it was pointed at.
3. **The cap gated on metadata and then read to EOF**, so the size limit applied to a number and
   never to the bytes. The read is now taken through a capped reader and re-checked.
4. **Resolve-then-reopen was two passes over a name.** `open_within` now opens once and asks the
   descriptor for its type, size and link count, so what was checked is what is read.

**Trap 45 — a guard's argument is not a proof of the guard.** Every one of those four survived
because the module's own prose was persuasive: it named the attack it defeated, and the reader
(its author) stopped there. Coverage was no help — this is trap 43 in a security dress. The
cheap technique that found it is worth repeating: **write the bypass and run it.** A ten-line
probe against the real function found in one minute what careful reading had missed for hours.
For a rule that decides whether bytes escape, the standing states are: symlink · **hard link** ·
directory symlink · `.git` as a file (a worktree) and as a directory · case-folded spellings ·
the file growing between stat and read · a name that resolves to a different file than it names.

**Measurement, and the two ways it was wrong.** 20.1b armed the editor budgets, taking the count
from 3 of 13 to **5 of 13** measurable, with both p95s enforced because the leg emits raw samples.
The first instrument resolved on `requestAnimationFrame` and reported keystroke p50 8.25 ms
against an 8 ms budget — a *failing* budget that was 100% instrument, since a rAF median is half
a 60 Hz frame (8.33 ms). Re-measured to the DOM mutation the real figure is **1.3 ms**. The
open-file instrument was wrong twice over: the loop alternated two files, so eleven of twelve
"opens" were react-query cache hits, and the wait polled for "any text", which the *outgoing*
document also satisfies — it resolved synchronously before React committed. Rebuilt over twelve
distinct files each waited for by its own marker, the honest number is **15.6 ms** against 40 ms.
Had either flawed instrument been trusted, the response would have been optimising code that was
already fast, or relaxing a budget that was being met.

**Claims made true rather than edited away.** Three assertions in the commit messages were false
and are now enforced instead of softened: the UI branches on every refusal variant behind a
TypeScript `never` check, so adding a variant really does break the build; a measurement recorded
against a different commit is now *discarded*, not merely annotated; and the "universal" refusal
test iterates a list the compiler refuses to let fall behind, having previously covered nine of
twelve variants — the three it missed being the three most recently added.

**Rejected.** Routing editor reads through the sidecar (spends the 40 ms budget on IPC for bytes
the OS has). A second file-read implementation for the editor (two implementations of one
security rule). Mirroring `PathRefusal` into a parallel TS enum (a second copy of the vocabulary
to keep in step). Sending the `TooLarge` byte counts over the wire (specta widened `f64` to
`number | null`, a null Rust cannot emit — the numbers already ride in the message).

**Known and NOT addressed here.** `tauri.conf.json` ships `security.csp: null` while
THREAT-MODEL-V2.md T8 promises a CSP, in the webview that now holds a file-read primitive. And
**no CI job runs the E2E suite at all**, so all 37 specs — including every editor test written
for this phase — are Mac-only evidence. Both predate this work; both are recorded in the handoff
as the next items rather than smuggled into a fix commit.

## ADR-0046 — Phase 20 as a whole: an editor that can be reached, eleven lenses over what 20.2/20.3 claimed, and six more over the fixes (2026-08-19)

**Status:** accepted (v2, Phase 20 complete) · **Commits:** `da171eb`, `d63e968`, `2cc1810`,
`93c726e`, `d72c66d`, `af58163`, `2149642`, `f577f7d`, `23f4e9f`, on top of the landed 20.1–20.3e
set. ADR-0045 covers 20.1/20.1b only; this covers the phase.

> **Read §"The fixes were reviewed too" before trusting anything below it.** The first eight
> sections describe the 20.4–20.6 fix wave as it was written. A second review then found
> **eighteen defects in those fixes**, several of them regressions the fixes introduced, and the
> corrections are recorded at the end. Nothing above has been edited to look better in hindsight.

**Context.** 20.1–20.3e all landed and were pushed, `make verify` was green, coverage was 100%,
and CI was green on all seven jobs for `6b417c4`, `05eb5c9` and `30f970a` (re-confirmed at the
start of this session, along with a local `make verify` — `MAKE_EXIT=0`, 1262 passed, 100.00% —
and `make verify-linux-denominator` — `MAKE_EXIT=0`, 1256 passed, 100.00%). None of that was
evidence about 20.2 or 20.3, because **the Phase 20 review had never been run**, and every
earlier phase's review found real defects in code with exactly those numbers. The handoff said so
in §1a and listed three things that had to happen before the phase could be called complete.

**Decision — run the review first, then fix, then finish.** Eleven read-only lenses (handshake
ordering · JSON-RPC and framing conformance · process lifecycle and orphans · the completion race
· the local model runner · risk-indicator honesty · the CSP · E2E harness fidelity · a
commit-message claims audit · the Boundary-B security surface · test quality) over 20.2 and 20.3,
each finding adversarially verified by **two** refute-by-default verifiers. 138 agents, 63
findings judged, 126 verdicts, **37 confirmed unanimously**.

**Reviewers were read-only, explicitly** (trap 42), and were told so in the prompt rather than by
convention — a `make verify` coverage run was in flight and a mutating reviewer would have
corrupted it.

### What the review found, and what it teaches

**Two claims were false in ways a ten-line probe settled in a minute.** 05eb5c9 said the
multiplexer's "Drop runs with the app and no language server is orphaned". `tao`'s macOS event
loop ends in `process::exit` (tao-0.35.3 `event_loop.rs:202`) and tauri's own `App::run` is
documented "the process is exited directly using `std::process::exit`" — which runs no
destructors. `shutdown_all` had **zero production callers**; `lib.rs` had always swept the
sidecar explicitly for exactly this reason and the multiplexer was left out; and `orphan_check`
could never have caught it, because it greps for `tempest-server`. The probes:

    child.kill() only (SHIPPED): direct child alive=false | GRANDCHILD alive=true
    process_group(0) + killpg:   direct child alive=false | GRANDCHILD alive=false

    reader thread STILL BLOCKED after 3s -> join() would HANG FOREVER

The second is the sharper one: a pipe reports EOF when the LAST write end closes, so a shim's
surviving grandchild kept `read_frame` blocked, and `Running::kill`'s `join()` never returned —
on the Tauri command thread, holding the multiplexer's mutex, for the life of the process. **Trap
45 generalises: a guard's argument is not a proof of the guard, and neither is a lifecycle
argument a proof of a lifecycle.** Both were fixed by using the process-group sweep
`supervisor.rs` has always used — the same two functions, not a second copy.

**A feature can be inert in two independent ways and look honest in both.** The behavioural risk
indicator — the only part of F11 that is Tempest's rather than everyone's — could never leave
`unmeasured`. Its escalation set named `{"HIGH","CRITICAL"}` while the wire carries
`LOW | NORMAL | HEADLINE`, and its lookup asked `searchDivergences`, whose FTS index covers
`detail`, `base_summary` and `head_summary` and has never contained `qualname`. Every `detail`
string the comparator writes is value-shaped ("return values differ"), so a search for
`calculateTotal` could only hit by accident. **Both failures rendered as "unmeasured", which is
the honest answer — so no test and no gate could tell the feature apart from a working one.**

The fixes are structural, not textual. A real `divergencesForSymbol` endpoint queries
`targets.qualname` (whole qualname and final segment, LIKE-escaped so `a_b` cannot match `axb`),
and severity crosses as the GENERATED union rather than through `String()`, behind a
`Record<Severity, boolean>` — so the bug that shipped no longer compiles, proved both ways:

    error TS2353: 'HIGH' does not exist in type 'Record<Severity, boolean>'
    error TS2741: Property 'HEADLINE' is missing ... but required

**Three gates were measuring the wrong thing, and two of them only admitted it once corrected.**
The contrast gate scored every span against the editor host's background regardless of what the
element sits on, so the gutter and the risk badge — both on `--surface-sunken` — were judged
against `--surface`, and a badge at a real 4.30:1 measured as a passing 5.07:1; it also
enumerated `.cm-line span` only, so F11's two widgets did not exist when it ran. Given a correct
ruler (compositing the real backdrop bottom-up to an opaque base, folding in `opacity` and the
text colour's own alpha) it went red on real colours: ghost text at **3.48:1 light / 3.68:1
dark**. The input storm claimed to run "with inline completion live" and never pressed F11 — the
extension's only trigger — so 900 keystrokes exercised an idle extension; made to press it, the
run failed with the document's tail reading "…no recorded runs name this symbol", because its
ruler stripped only `[data-testid="ghost-text"]` and the badge counted as typed text. **A gate
that measures the wrong thing is not a weaker gate; it is a gate that reports green about
something it never looked at.**

**`percentile` had two definitions and a test that asserted the invented value.** This repo's
webview computed `ceil`; `perf_suite` computed `round(x + 0.5)`, and Python's banker's rounding
split them whenever `pct/100 * n` is an integer — under a TS test named "matching perf_suite"
asserting the number perf_suite does not produce. And `percentile(xs, -5)` returned the smallest
sample while its own test, titled "answers null … rather than inventing one", asserted exactly
that. Both are `ceil` now, both refuse a percentile outside 0..100, and the same three vectors
are asserted in both languages so neither can drift alone.

**Coverage lied about a line, and the answer was to restructure rather than to pragma.**
`make verify` came back `MAKE_EXIT=2` with 1270 passing and 99.99% coverage, naming one line in
the new by-symbol lookup. A mutation settled it: raising there failed 7 of 8 tests, so the line
runs. That is **trap 36** — SQLAlchemy's async layer crosses a greenlet inside `session.execute`
and coverage.py mis-attributes the statement that follows the crossing. Four arrangements were
measured, including the exact shape of the already-covered `_search_fts`, and all reported the
line missing; folding the await INTO the return so no statement follows the crossing, with the
mapping in a sync helper, reports 100%. **No pragma was added**: one would have silenced a gate
that was measuring correctly-executed code and left the next reader believing the line is
unreachable.

### The three things §1a said had to happen

1. **`lsp_hover` is reachable.** A CodeMirror hover tooltip calls it. The DECISION half —
   which outcomes are ordinary and which the user must be told about — is a separate, pure,
   100%-covered module, because an E2E harness can only reach the outcome its environment
   happens to produce. `Unsupported` is silence (the state of every fresh install); `ok(null)` is
   silence and is a real answer; **everything else is a sentence**, because rendering a
   timed-out server as "nothing to say" is the confusion between no-evidence and
   evidence-of-nothing that this product exists to refuse. Contents render as `textContent`,
   never markup — a language server is an arbitrary binary and this is the renderer.
2. **Both runners have a settings surface** (`runners.rs`), desktop-local by the same reasoning
   as `ProjectFile`, with the environment still winning and saying so, and with whether the
   program can be FOUND stated rather than left to a silent failure.
3. **The review ran.** This ADR is its record.

### Rejected

- **Making the badge honest by rewording it** rather than giving it a real by-symbol lookup. The
  words were already honest; the feature was not.
- **A `# pragma: no cover` on the greenlet-shadowed line.** It would have made a true gate lie.
- **Adding `perf-gate` to CI** to make the Makefile's claim true. Arming it needs a committed
  `bench/baseline-linux.json` and a decision about cold_launch (deliberately RED on environment
  drift); adding an untested gate to close a documentation defect would risk red CI to fix a
  comment. The comment now states where it actually runs, and the work is queued.
- **`continue-on-error` anywhere.** Weakening a gate to make it pass is v2 failure mode 2.
- **Trusting the verification pass over lsp.rs after the fixes landed.** Several verifiers read
  already-fixed code and refuted findings on that basis — one even mis-attributed the fix to
  `05eb5c9`. The finder lenses all ran against pristine `origin/main`, so the findings stand;
  this is recorded as trap 46 rather than quietly resolved in the fixes' favour.

### What is still open, stated rather than implied

- **The cold-launch baseline** still needs one `make bench` on a machine with no Claude session
  running. It could not be taken here: this session IS the load. `make perf-gate` remains RED on
  `cold_launch` (11.5% over a 10% bar, absolute budget met with wide margin at 0.33s against
  0.8s), and re-baselining under load is forbidden.
- **`perf-gate` runs in no CI job**, and the §5 editor numbers come from
  `bench/editor-metrics.json`, which is gitignored and written only by a Mac-local
  `make bench-editor`. "6 of 13 measured" is a claim about this laptop and is now phrased that
  way, with all three states counted separately.
- **The E2E harness has no Rust host**, so the §5 open-file and completion spans exclude
  `pathguard` and Tauri IPC and include an HTTP hop to a node bridge. Stated in the spec.
- **`update_editor_runners` chooses a binary this host later spawns.** Nothing routes model
  output into settings and the CSP forbids injected script; that is the whole mitigation.


### The fixes were reviewed too, and that found eighteen more defects

The 20.4–20.6 commits were new code with fresh tests, 100% coverage and green gates — which is
exactly the state 20.2/20.3 were in when eleven lenses found 37 defects in them. So the same
treatment was applied to the fixes: six lenses (the new concurrency · the new Rust logic · the
new webview logic · the engine endpoint and changed gates · the new claims · regression risk),
refute-by-default verification, 56 agents. **Eighteen confirmed unanimously**, fixed in `f577f7d`
and `23f4e9f`.

**The worst one is a lesson about a fix that looked complete.** `#[tauri::command(async)]` on a
SYNCHRONOUS fn does not take work off the runtime: tauri-macros' `body_async` spawns the future
on tokio's multi-thread runtime and the sync body then blocks a WORKER. With no in-flight guard
on hover and a ten-second timeout held across the multiplexer's mutex, ordinary reading over a
slow server could occupy every worker and starve every other async command — including the
Settings screen, the user's only way to clear the bad command. The doc comment written with the
fix reasoned solely about the main thread. **The stall had been moved, not removed.** All three
host commands now run their blocking half on `spawn_blocking`, and `hoverTooltip` has the
in-flight guard F11 already had — CodeMirror's `checkHover` skips only when a tooltip is already
SHOWN, so every ~300 ms rest started another request.

**Four were regressions the fixes introduced**, which is the specific risk of a large repair
wave and the reason it was reviewed:

| The fix | What it broke |
|---|---|
| `trim()` to refuse whitespace answers | deleted the LEADING indentation that IS a mid-token FIM answer |
| `model_spec` parsing a command line | split `TEMPEST_LOCAL_MODEL`, which has always named a whole program — breaking every launcher whose model path contains a space, which is WHY a wrapper exists |
| the by-symbol suffix match | used `LIKE`, whose case behaviour is a DIALECT property: case-insensitive on SQLite, so `post` matched a recorded `ledger.POST` |
| the risk badge's symbol | `prefix + raw completion` is an identifier only for the OFFLINE source; a model answers with code, so the badge went inert for exactly the users who configured one |

**And three claims that were not true**, in a fix wave whose whole subject was untrue claims: a
test that timed out during the HANDSHAKE and never reached the large write it names;
`assert 3 + 3 + 7 == 13`, which the interpreter folds before the test runs and would pass with
`perf_suite` deleted; and a doc describing a `default: never` arm the function deliberately does
not have.

**A flake shipped and was caught by the gate, not by a reviewer.** `runners.rs`'s tests put the
env mutex inside `EnvGuard`, serialising the SETTERS while the readers raced — cargo runs tests
as threads in one process and environment variables are process-global. It failed 2 runs in 6,
and passed the two full `make verify` runs before that. Every test now takes the lock, including
those touching no environment today.

**The last defect was found only because an earlier fix worked.** Making the symbol lookup
correct made the risk indicator able to reach `elevated` for the first time — and the contrast
gate immediately failed it at 4.25:1. Both non-`unmeasured` states had shipped below the bar
(`elevated` 4.22:1 light; `high` 4.16:1 light, 3.28:1 dark) because `--unproven` and
`--divergent` are tuned against `--surface` and nobody had measured them on their own tinted
chips. `high` still could not appear in a fixture — it needs a recorded HEADLINE divergence — so
the gate now mounts all three shipped `.cm-risk-*` classes on the editor's own backdrop and
asserts each is present before measuring. Fixing only the colour would have left the same hole
for the next change.

**Trap 48 is the general lesson**: *the review of a fix is not optional because the fix was
careful.* Eighteen of these were in code written specifically to be correct, by an author who
had just read 37 findings about the same modules.


### Postscript — the CI run on `070f046`, and what it is NOT evidence of

All twelve commits were pushed. The run is **6 of 7 green**; `ci / desktop` failed after 1m at its
first cargo command, with `quote`, `proc-macro2` and `serde_core` build scripts exiting 126 —
"cannot execute binary file". That is an architecture mismatch on the runner: the executable cargo
had just produced could not be run.

Recorded as evidence rather than as a verdict, because the phase is not settled until it is
re-run:

* `target/` is not tracked (`git ls-files | grep -c src-tauri/target` → 0) and CI has no cargo
  cache, so those build scripts were produced by that run.
* `Cargo.toml` and `Cargo.lock` are byte-identical to the last 7/7-green run
  (`git diff --stat 30f970a..HEAD` over both → empty).
* **`contract-check` — same `macos-latest`, same `dtolnay/rust-toolchain@stable`, same
  `build-server.sh`, and it compiles the very same proc-macro crates via `cargo install
  cargo-typify` and `make gen-contracts` — passed in 3m in the SAME workflow run.**
* The failure precedes any Tempest code compiling.
* The same commit is green locally: `make verify` `MAKE_EXIT=0` (1273 passed, 100.00%),
  `verify-linux-denominator` `MAKE_EXIT=0` (1267 passed, 100.00%), `cargo test --workspace` 115
  passed, `clippy -D warnings` exit 0, parity byte-identical, `pnpm tauri build` exit 0,
  `orphan_check` clear in 2.1 s.

The next session's FIRST action is to re-run that job, not to change code. **If the answer is to
change CI, it is to pin the runner or make the toolchain arch explicit — never
`continue-on-error`, never dropping `-D warnings`.** A gate weakened to make a red build green is
v2 failure mode 2, and this ADR would be the wrong place to start doing it.

Until that re-run, the honest statement is: **Phase 20 is code-complete and locally verified on
every gate; it is not yet CI-confirmed.** ADR-0044's rule stands — a local green is evidence about
one machine, and "Phase 20 is complete" is a claim about the repository.

### Settled — the `desktop` failure on `070f046` was a transient runner defect (2026-08-20)

**It did not reproduce, and the re-test was stronger than the re-run the postscript asked for.**

Before the owner clicked anything, `3860c23` (the §0 documentation commit) was pushed on top of
`070f046`, and CI ran on it: **workflow run `32317420375`, 7 of 7 green**, `desktop` included.
Step 10 — `cargo clippy --workspace --all-targets -- -D warnings`, the exact step that exited 101
on `070f046` — **passed**, as did `cargo test --workspace`, `typecheck` and the E2E leg.

That run is a better experiment than "Re-run failed jobs" would have been, because the bytes it
compiled are provably the same ones:

| Claim | How it was checked | Result |
|---|---|---|
| `3860c23` changes **only** `docs/` | `git diff --name-only 070f046 3860c23` | `docs/DECISIONS.md`, `docs/HANDOFF-NEXT.md` — nothing else |
| every non-`docs` tree object is **identical** | `git ls-tree <c> \| grep -v docs \| git hash-object --stdin` on both commits | `0b33d57228bd462cb1bb272eea946aec7bf85435` — the same hash for both |
| it ran on a **fresh** `macos-latest` allocation | runner `1000000612` (the failing job had `1000000607`) | different runner, fresh checkout, no cargo cache |

A re-run replays a job inside the original run's context; a new push gets a new runner allocation
and a new checkout. Identical source object + different runner + green is exactly the shape of a
transient infrastructure fault, and it is the shape the postscript predicted.

**Decision: no code change and no CI change.** `runs-on` is not pinned and `-D warnings` is not
touched. Pinning a runner to work around a fault that occurred once, and did not recur on
identical bytes, would trade a real cross-arch signal for the appearance of stability — the
weakening this project refuses (v2 failure mode 2). The evidence for pinning is a *second*
occurrence, not the first.

**The recurrence signature, so the next session recognises it in one look instead of re-deriving
it:** a `macos-latest` job failing inside the first minute of its first cargo command, with
`exit 126` and `cannot execute binary file` from `quote` / `proc-macro2` / `serde_core` build
scripts — dependency build scripts, before any Tempest code compiles. If that appears again, it
IS reproducible — and the fix is to **pin the host**, `runs-on: macos-14`, and nothing else.
**Not** `targets:` on `dtolnay/rust-toolchain`, which an earlier draft of this paragraph offered
as an equal alternative: `targets:` installs cross-compilation standard libraries affecting
artifacts under `target/<triple>/`, while a cargo build script is always compiled for and executed
on the **host** triple and lands in the untriple'd
`target/debug/build/<crate>-<hash>/build-script-build` — the exact path in the failing log.
Checked here: that path exists, and `target/` contains only `debug/`, `release/` and `tmp/`, no
triple directory at all. A remedy aimed at a directory the failure does not live in would have
looked like diligence and changed nothing.

**`PHASE 20 IS COMPLETE AND CI-CONFIRMED.`** ADR-0044's rule is satisfied the way it demands: not
by a local green, but by a fresh-checkout run of the repository — 7/7 on source bytes identical
to the phase tip.

**One warning is still live and is NOT settled by this**: `actions/setup-node@v4`,
`actions/upload-artifact@v4` and `astral-sh/setup-uv@v6` target Node 20 and are already "being
forced to run on Node.js 24" by the runner — a deprecation the runner currently absorbs for us.
When it stops absorbing it, the affected jobs go red for a reason that has nothing to do with
Tempest. **Scope, counted rather than asserted: 5 of the 7 jobs** — `desktop` (all three),
`python` / `bench` / `contract-check` (two each), `node` (one) — while `forbidden-verdict-grep`
and `compose-validate` use only `actions/checkout@v5`, already Node 24, and cannot carry the
warning at all. It is **10 `uses:` lines in `ci.yml`, 16 across all workflows**, not three. An
earlier draft of this paragraph said "every job" and "three lines"; both were false, and the
review of this settlement caught them — trap 48, applied to a settlement about false claims.
Queued in HANDOFF-NEXT §4, not fixed here, because changing CI actions is a change only a CI run
can verify and this session must not leave an unverified workflow behind.

## ADR-0047 — A measurement that carries the conditions it was taken under, and two reviews that found 27 defects in the work that got it there (2026-08-20)

**Status:** accepted · **Supersedes nothing; amends the CARRIED list in HANDOFF-NEXT §1a.**

**Context.** `make perf-gate` had been RED on `cold_launch` for three sessions — `0.3309s regressed
11.5% over baseline 0.2968s (bar 10%)` — while the absolute budget was met with wide margin
(0.33 s against 0.8 s). Every session recorded the same hypothesis ("probably load, not drift")
and the same remedy ("re-measure on an idle machine"), and every session failed to take the
measurement because the session itself was the load. **The reason it could not be settled is that
nothing anywhere recorded what conditions a measurement was taken under.** `bench.json` and
`bench/baseline-darwin.json` were compared by `perf_suite` as though they came from the same
machine in the same state; neither carried a single fact about the machine. That is trap 47's
shape: a ruler with no error bars, and a question that therefore could not be answered by data —
only re-argued.

**Decision — record the conditions as FACTS, and let the gate own the JUDGEMENT.**

`bench` writes a `conditions` block: `os.getloadavg()[0]` sampled **before any bench work**, the
same sampled at the end, `cpu_count`, the source, and — see below — `covers`. It records; it does
not judge. `perf_suite` owns `QUIET_LOAD_PER_CPU` and decides. The split is deliberate: changing
the bar must not require re-taking every measurement, and a measurement file must never carry a
verdict its own author chose.

**The one-sided rule, which is why this makes the gate STRICTER rather than softer.** Background
load can only make a *duration* slower, never faster. Therefore a latency budget that **passes**
under load still binds — the quiet number can only be lower — while one that **misses** proves
nothing and is reported `INCONCLUSIVE(load)`. Inconclusive is **not** a pass: `report.ok` is false
and the exit code is exactly as red as before. What changes is the instruction the operator reads,
from one that invites the forbidden repair ("regressed" → re-baseline) to one that names the real
problem ("re-measure on a quiet machine; re-baselining to clear it is forbidden"). On a quiet
machine the behaviour is byte-identical to before. A run recording no conditions behaves exactly
as before and says so.

**Three deliberate narrowings, each of which a review had to force.**

1. **Only the BACKGROUND sample is judged on.** Every later sample includes this process seeding
   its own store and cannot separate foreign load from our own work. The final sample is recorded
   for a human and never judged on. Load that *starts* after the sample is invisible — stated in
   the payload, not left implicit.
2. **`covers` — the sample only speaks for what this process measured.** `open_file_ms`,
   `keystroke_ms` and `completion_ms` are durations, and they are **not** measured by `make bench`:
   they are merged from `bench/editor-metrics.json`, which `make bench-editor` writes in a separate
   Playwright run gated only on a matching HEAD, so it can be hours old and taken under entirely
   different load. Qualifying them with this sample would answer about the wrong process, in both
   directions — hiding a real editor miss and excusing a fake one. They keep their plain verdict
   and the report says why. Closing that gap means recording conditions in the editor leg too; it
   is not built.
3. **The bar is PROVISIONAL and labelled so, because it is a guess.** See below.

**The bar's derivation was itself a false claim, and the code now says so.** The first version of
`QUIET_LOAD_PER_CPU`'s comment called it "empirical, not aesthetic" and cited ADR-0044 for
"~25-30% background load producing +11.7% on cold_launch". A review refuted all three parts:
ADR-0044 contains no load measurement at all (its only match for "load" is the word *loaders*);
"25-30% background load" is a CPU-**utilisation** estimate while the constant is a **run-queue
depth** per CPU, and nothing justifies reading one as the other; and `os.getloadavg` appeared
nowhere in this repository before this module, so no `(load-per-cpu, latency)` pair has ever been
recorded here. The comment now states the bar is provisional, names the single load figure this
project has actually written down (**3.96 on 8 CPUs = 0.495/cpu**, sampled while two heavy apps
ran, in the same session `cold_launch` read 0.3309 s and 0.3762 s against a 0.2968 s baseline), and
says plainly that it is not derived from a measured curve because there is not one. Recording the
raw load with every run is what will eventually let a session replace the guess with a curve.
A test pins the *label*, not the number: relabelling it "empirical" fails.

### Two reviews, 171 agents, 27 confirmed defects — and the second one is why this ADR is honest

| Wave | Agents | Findings | Confirmed | Of which regressions the fixes introduced |
|---|---|---|---|---|
| Over the §0 CI-settlement write-up | 78 | 37 | **9** | — |
| Over the fixes to those nine, plus this (then unreviewed) code | 93 | 44 | **18** | **8** |

The first wave found five distinct defects in a document whose entire subject was a false-looking
CI failure: a scope claim ("every job… all seven go red") false for 2 of 7 jobs; "three `uses:`
lines" when there are 10 in `ci.yml` and 16 across the workflows; a printed `curl` command that
dies in zsh because `?per_page=10` was unquoted — three lines below its own warning that this
shell is zsh; a remedy offering `targets:` on `dtolnay/rust-toolchain`, which cannot fix a build
script's `exit 126` because build scripts are host artifacts in `target/debug/build/` and this
tree has no triple directory at all; and **trap 49's own point 4**, an un-run diagnosis written
into the trap about un-run diagnoses.

The second wave found the fix for that last one had pasted a `>>>` transcript showing three error
lines under a bare `json.loads` in a loop — which raises on the first iteration and can only print
one. **The same failure, one layer down, in the same session.** It also found that `machine_conditions`
caught only `OSError` while the platform its branch exists for (Windows, where CPython omits
`getloadavg` entirely) raises `AttributeError`, which is not an `OSError` subclass — so `make bench`
would have died at its first statement on the one platform the code was written for, while its
docstring promised a recorded `unavailable`. And that four printed row counts summed to **14 of 13**
budgets, because a row whose p50 was MET and whose p95 was inconclusive was counted twice.

**Trap 48 held exactly: 8 of the 18 were regressions the fixes themselves introduced.**

### The tests were then mutation-tested, and one gap survived the fix

Nine mutations, each the one-line change a reviewer named. Eight were caught. The survivor was
`except (OSError, AttributeError)` → `except OSError`: the *code* had been fixed but the *test*
still monkeypatched a function that raises `OSError`, so the absent-attribute state was never
exercised. `monkeypatch.delattr` closed it, and the mutation is now caught.

**A fix is not verified by the test that motivated it. Run the mutation.** That is the reusable
lesson, and it is why the producer half now has its own integration test: deleting the single line
`"conditions": conditions_block(...)` from `bench.main` turned the whole feature into a silent
no-op with the entire unit suite still green — the lines all ran, and the state "nobody wires them
up" was not considered (trap 43).


### The measurement, taken 2026-08-20 — and `perf-gate` is GREEN

The carried item is closed, and **not** by getting an idle machine. It is closed because the
one-sided rule made an idle machine unnecessary.

```
  cold launch #1: 0.326s   #2: 0.326s   #3: 0.325s
  cold_launch_s = 0.3248   baseline 0.2968   regression +9.43%  (bar 10%)
  background load 2.047 on 8 CPUs = 0.256/cpu   (quiet bar 0.20 — OVER it)
  perf_suite: every measurable budget met (L22)          PERF_GATE_EXIT=0
```

**The machine could not be made quiet, and that itself is a measurement.** Load was watched for
four minutes after `make verify` finished, with the two heavy applications already closed at the
owner's hand. It decayed to a floor of **0.24–0.30/cpu and stopped**: `WindowServer` at ~41% and
`Claude Helper` at ~14% are the Claude desktop app drawing the session that is asking for the
measurement. **On this Mac, with this session open, the 0.20 bar is unreachable** — which is
precisely why three sessions in a row recorded the same hypothesis and none of them could test it.
Before this feature that floor was invisible; it is now a number.

**Why the result binds anyway.** 0.3248 s was measured at 0.256/cpu, over the bar, so it is an
*upper bound*: a quieter machine can only produce a lower number. An upper bound of +9.43% against
a 10% bar therefore proves there is no regression, a fortiori. The gate reports `MET`, not
`INCONCLUSIVE`, because the asymmetry runs that way — and that is the whole design earning its
keep on the first real measurement it was asked to judge.

**The honest caveats, stated because the number is close to its bar:**

* It passed by **0.57 percentage points**. That is a pass, not a comfortable one. The *absolute*
  budget — the one §5 actually cares about — is met with 0.475 s of headroom (0.3248 s against
  0.8 s).
* The baseline still records **no conditions of its own**, so this remains a comparison against a
  reference of unknown provenance. The gate says so on every run. It stops being true the first
  time someone commits a baseline taken with this instrumentation.
* The hypothesis three sessions carried — "probably load, not drift" — is now **supported but not
  proven**: 0.3309 s at unmeasured-but-higher load, 0.3248 s at 0.256/cpu. Two points on an
  uncontrolled axis are a direction, not a curve. The way to prove it is the same way the bar gets
  its evidence: more runs, with their conditions recorded.
* `perf_suite` now reports **3 of 13** measured rather than 6. Nothing regressed: the editor
  metrics in `bench/editor-metrics.json` predate HEAD, so the staleness guard discarded them
  exactly as designed, and `open_file` / `keystroke` / `completion` correctly read
  NOT-YET-MEASURED. `make bench-editor` restores them.

## ADR-0048 — Phase 19a: the keyless rung widens from dataclasses to plain classes (2026-08-20)

**Status:** accepted · **Answers QV1's engine-first mandate without running into QV2.**

**Context.** The owner answered QV1 on 2026-08-20: **engine work before feature work**, per the
standing rule that below a ~60% real-world proof rate the engine outranks features. The measured
rate is 34%. `docs/METRICS.md` names the lever precisely: of 130 UNPROVEN targets across five OSS
repos, **112 are `TARGET_UNREACHABLE`** — 86% of everything unproven, an order of magnitude above
the next bucket (12), and every one an instance method.

`targets/symbols.py` classified **every** instance method unreachable by a blanket rule, before
any attempt was made, with the detail "v1 does not synthesize instances". `prove.py` then ran a
two-rung ladder: rung 1 `harness/typed.py` (deterministic, offline, no key) and rung 2
`harness/llm.py` (ADR-0024, **key-gated**). Rung 1 refused everything that was not a `@dataclass`,
at one line. So all 112 fell to the rung that needs an API key — **the engine-first answer to QV1
ran straight into QV2 (who pays) for no reason except that a constructor was never attempted.**

**Decision.** Widen rung 1 to plain classes by deriving the constructor call from `__init__`'s
signature instead of from dataclass fields. Everything else is reused unchanged.

**Why this is safe, and why it is not a loosening.** Acceptance was already **execution, not
review**: the rendered call must pass `harness.synth.synthesize` on BASE in the sandbox or the
target falls through. Rendering a call is a *guess*; the probe decides. Widening changes which
guesses get made, never which get believed. The give-up arms are the honesty surface and they
stay: an unannotated defaultless parameter, an annotation with no zero value, and an
`async def __init__` all return None and hand the target to the next rung.

**Which constructor is real decides which arm reads it.** A `@dataclass` normally has no
`__init__` and gets a generated one from its fields, so only the field path can see its
parameters. A `@dataclass(init=False)` with a hand-written `__init__` is the reverse. The presence
of an explicit `__init__` therefore wins over the decorator, for both kinds of class.

**Positional-only parameters are passed positionally.** `def __init__(self, fee, /)` raises
`TypeError: got some positional-only arguments passed as keyword arguments` for `fee=0`, and a
probe failing on our own rendering bug is indistinguishable from a class that cannot be built — a
wrong answer arrived at honestly, which is the worst kind.

**Refused attempts are cleaned up.** Widening took refusals from a handful to the common case, and
each one used to leave a `_tempest_typed_adapter_*.py` in BOTH worktrees. Those trees are what the
differential runner executes and what coverage is attributed against, and a `.tempest` shadow
worktree is a real git worktree the user can open. The shim is now removed when the probe rejects.

### The measured result, and the consequence it forced

On the `pyfix` fixture, the three instance-method targets went from **0 of 3 proven keyless** to
**3 of 3**: `Discounter.apply` DIVERGENT, `Wallet.withdraw` DIVERGENT, `Tally.bump`
EQUIVALENT_UNDER_BUDGET — no key, no network, no money.

That success broke something, and the break was the important part. **Rung 1 now short-circuits
rung 2 for exactly the fixtures that tested rung 2**, so ADR-0024's LLM constructor synthesis
would have kept passing its unit tests while losing its only end-to-end exercise — a feature going
quietly untested because a cheaper path started winning. Two of its integration tests failed and
said so.

The fixture is therefore **split by which rung the target reaches**:

| Module | `__init__` | Rung | What it proves |
|---|---|---|---|
| `c01`/`c02`/`c03` | annotated, zero-valuable | 1, deterministic | the phase's win, keyless |
| `c08` (new) | `(self, seed)` — **unannotated** | 2, key-gated | ADR-0024 still works end to end |

`c08` is also the keyless-honesty case: without a key it is `UNPROVEN(TARGET_UNREACHABLE)` with
the remediation naming what would change the answer. **Do not annotate `seed`** — that would
silently delete the only end-to-end test of the LLM rung, which is why the fixture says so in a
comment next to the parameter.

A test also asserts the deterministic verdicts are **unaffected by what the model says**: a peer
returning prose instead of an adapter takes `c08` down and leaves c01–c03 exactly where they were.
A deterministic proof must not be hostage to an unrelated network reply.

### MEASURED 2026-08-20: 34% → 43%

`tempest.dev.real_world corpus/real-world.toml`, keyless, five OSS repos, 198 targets:
**86/198 (43%)**, up from 68/198. `TARGET_UNREACHABLE` fell **112 → 94**; every one of the 18
newly-proven targets is an instance method the deterministic rung can now construct. packaging
went 25% → 36%; no repo lost a proven target.

`DIVERGENT` fell 12 → 10, and that is **not** this change. Both losses are humanize's
`naturalday`/`naturaldate` — date-relative functions, and the recorded figure is four days old.
The A/B: `typed.py` reverted to dataclass-only and humanize re-measured *today* gives
`4 | 17 | 3`, identical to the new code. Environment, not regression. Recorded in METRICS.md.

**Still below the 60% bar**, so the engine keeps outranking feature work, and
`TARGET_UNREACHABLE` at 94 remains the dominant bucket by an order of magnitude.

**Superseded note:** the paragraph below was written before the measurement and is kept because
its caution was right — the static estimate it cites (93 of 158) was never the number that
mattered. `tempest.dev.real_world` against the five cloned repos
is the number that matters and it has not been re-run. A static scan of those repos' source (test
files excluded) suggests **93 of 158 plain-class instance methods are mechanically constructible
enough to attempt** — but "attempt" is not "prove", every one still faces the probe, and the scan
counts all classes rather than the changed ones Tempest actually targets. **The rate is
re-measured, never asserted**; if it does not move, that is the finding (the ADR-0027 precedent).

---

## ADR-0049 — The agent orchestrator's turn loop lives in the engine, not the Rust host (2026-08-20)

**Status:** accepted · **Deviation from `PLAN-V2.md` Phase 21, recorded rather than drifted into
(CLAUDE.md: "deviating silently is a failure").**

**Context.** `PLAN-V2.md` says "Agent Orchestrator **in Rust**: turn loop, tool dispatch, budget
enforcement, model router". §9c gives the reason boundary D is rooted in Rust: *"the orchestrator
owns tool dispatch, budget enforcement, and capability checks; the enforcement point and the
schema must not be able to disagree."*

But every collaborator the turn loop needs is Python: `prove.run_prove` (the engine),
`agent/shadow.py` (L19 staging — already moved to Python by the ADR-0036 amendment, for the same
kind of reason), `agent/journal.py` (L20), and `inference/` (the model router, 16 providers).
A Rust turn loop would cross the stdio boundary for the proof, the shadow, and every model call —
adding a new boundary-A surface for each, all contract-gated, to orchestrate steps that are
themselves Python.

**Decision.** The **contract and its enforcement stay in Rust**; the **turn loop lives in the
engine** at `tempest/agent/orchestrator.py`.

* `agent_tools.rs` remains boundary D's root. It is the only declaration of what tools exist and
  what policy each carries.
* `tempest/agent/tools.py` **reads the committed `agent-tools.json`** and dispatches from it. It
  declares nothing. `test_agent_tools.py` asserts the handler set and the manifest's tool set are
  equal **in both directions**, so adding a tool in Rust breaks the Python suite until it is
  implemented — the drift gate now covers dispatch, not only shape.
* `model_facing_catalog()` loads the two committed model-facing artifacts and cross-checks both
  against the canonical manifest before use. Three files, one Rust declaration; a silent
  divergence between them is boundary D failing exactly as §9c describes, and it is not a type
  error.

**What this preserves.** The enforcement point and the schema still cannot disagree — they are the
same file, read rather than mirrored. What moves is *where the loop runs*, and the loop is not the
enforcement.

**What it costs, stated plainly.** The Rust host does not today re-validate a tool call before it
reaches Python. That is acceptable while the only caller is the engine itself; it stops being
acceptable the moment the webview can originate a call, and the fix then is for the Tauri command
to validate against the same manifest before forwarding. Written down here so it is a known edge
rather than a discovered one.

### L16 is a state with no constructor

`ProvenChange` — the only type the user may be shown — refuses to exist without a `bundle_id`, and
refuses a `verdict` that is not an engine `Verdict` (L17: a model's string cannot arrive in the
field the UI reads as the answer). `run_task` is the sole producer and always calls `run_prove`,
including when the model errors mid-turn and when the turn budget is spent — because in both of
those cases there are edits in the shadow, and edits without a verdict are the thing L16 exists to
prevent. A test asserts `run_task` is the only producer in the module.

Two adversarial forge attempts are pinned, and two mutations confirm the tests bite: a fast path
that skips the proof when nothing changed and calls it equivalent, and a post-proof overrule that
upgrades UNPROVEN. Both are caught.

**The model cannot run the proof.** `prove` is declared in the manifest so it stays whole, and its
handler refuses: a model that could invoke proving could also decline to, and L16 would be a
request rather than a property.

### One rule for verdicts, imported rather than restated

An earlier draft of `run_task` computed its own worst-first aggregation. It disagreed with the
engine's `bundle.run_verdict` on a mixed EQUIVALENT+UNPROVEN run — a second verdict rule living
next to the model layer, which is the one place L17 says a verdict may never be authored. The
orchestrator now imports `run_verdict`. There is one rule and it belongs to the engine.

## ADR-0050 — Phase 21: F1, F2, F3 and the exit gates; what landed and the one defect that did not (2026-08-20)

**Status:** accepted for what is built · **Phase 21 is NOT complete.** `repair_bench` is red on a
real defect (HANDOFF-NEXT §0) and `resume_test` does not exist.

**Built, at the project's bar (100% coverage on `tempest/agent`, mutation-tested, adversarial
tests where a law demands one):**

* **Tool dispatch** — `agent/tools.py` reads the committed `agent-tools.json` and dispatches from
  it, declaring nothing. A test asserts the handler set and the manifest's tool set are equal in
  BOTH directions, so adding a tool in Rust breaks the Python suite until it is implemented: the
  drift gate now covers dispatch, not only shape.
* **Structured tool calling on both wires** — `inference/client.py`. Fifteen of sixteen providers
  speak the OpenAI shape, so both are exercised over real loopback HTTP. `Completion.stop_reason`
  is normalised so the turn loop has one condition rather than a per-provider branch (§7).
* **F1, the verdict loop** — `agent/orchestrator.py`. `ProvenChange` cannot be constructed without
  a bundle id or with a non-`Verdict` verdict, `run_task` is its only producer, and a test asserts
  the module has exactly one construction site which calls `run_prove`. Two adversarial forge
  tests, and mutations covering "skip the proof when nothing changed" and "overrule the engine
  when it says UNPROVEN" are both caught.
* **F2, intent contracts** — `agent/contracts.py`. TOML rather than the spec's YAML: `tomllib` is
  in the standard library, PyYAML would be a new runtime dependency in an engine that ships
  frozen, and TOML is already this project's config format and supports the comments a
  user-editable contract needs. Nothing is INTENDED unless explicitly listed; a symbol in both
  lists resolves to UNINTENDED; `"*"` is refused at construction because a contract permitting
  everything would classify every divergence INTENDED, which is the one thing F2's gate forbids.
* **F3, proof-guided repair** — `agent/repair.py` + the loop in the orchestrator. Success is
  deliberately NOT "no divergences remain": it also requires the contract to be byte-identical and
  every previously-proven target to still be proven.
* **P2, partial** — `agent/turnlog.py`, a stdlib-`sqlite3`, WAL, `synchronous=FULL` log in the
  engine (the API's SQLAlchemy store wraps the engine; importing it here would invert the
  dependency). `PROVING` and `PROVED` are separate stages because the gap between them is the
  expensive one. **`plan_resume` says what a restarted process should do and nothing consumes it
  yet** — that, and `resume_test`, are what P2 still needs.

### Three defects this phase found in code that already existed

1. **`shadow.snapshot` was not idempotent.** `changed_files` answers "differs from the BASELINE",
   which stays true after the first commit, so a second call reached `git commit` with an empty
   index and died with an empty stderr. Harmless until F3 made proving twice the normal case.
2. **The dispatcher double-counted refusals.** A `ToolError` raised INSIDE a handler incremented
   the turn budget twice. Every test passed because they all used EARLY refusals, which take the
   other path. Found by mutation, not by reading.
3. **A second verdict rule.** An early `run_task` computed its own worst-first aggregation and
   disagreed with `bundle.run_verdict` on a mixed EQUIVALENT+UNPROVEN run — a verdict rule living
   next to the model layer, which is the one place L17 forbids it. The engine's rule is imported
   now.

### The defect that is still open, and why it is being handed over rather than patched

A bundle carries only CHANGED symbols, so a symbol that is **put back** vanishes from it —
indistinguishable, at the bundle level, from one that was **deleted**. Judging every vanished
target a cheat is a false positive on the correct repair of collateral damage;
`repair.reverted_symbols` therefore excuses a symbol whose SOURCE is identical at baseline and
head.

`model-breaks-the-import` defeats exactly that: the agent restores the function byte-for-byte and
adds `import no_such_module_xyz`. The symbol is genuinely identical, so it is excused, and the
engine cannot help — with no changed symbol there is nothing to target, so nothing goes UNPROVEN.
**The fix for a real false positive created a real false negative in the same sitting (trap 48).**

It is left red on purpose. Three candidate fixes are written out in HANDOFF-NEXT §0; choosing
between them is a design decision, and the wrong time to make one is at the end of a long session.
