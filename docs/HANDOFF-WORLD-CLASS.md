# HANDOFF — from "all gates green" to a world-class agent

**Audience:** the next Claude session (and every one after). The owner is a non-coder: plain
English, copy-paste commands, verify by running the real app, check in after each phase.
Subagents are FORBIDDEN (owner, 15 Aug 2026: "just build with one but go all out") —
single-agent, maximum depth; stop after every phase for review and reinstall the app. **The bar, set by the owner on 14 Aug 2026:
100% coverage, zero known defects, no red CI, ever. "Flawless" is the product identity.**

Read order before touching anything: `CLAUDE.md` → `HANDOFF.md` → `docs/HANDOFF-PHASES.md`
(traps 1–21 — they are paid-for lessons, do not relearn them) → this file → `docs/PLAN-DESKTOP.md`
→ `docs/DECISIONS.md` (ADR-0001..0023).

---

## Part 0 — The live state this session left (handle FIRST, in this order)

1. **One unpushed commit** (`caadff7` — the Linux-denominator coverage fix). The owner clicks
   *Push origin* in GitHub Desktop (no CLI credential exists — trap 13). Expected result:
   **all 7 CI checks green**, because the exact Linux suite was reproduced locally:
   `make verify-linux-denominator` → 100.00% (796 tests), full macOS suite → 100.00% (802).
   If the python job is STILL red, the failure is a new environment class: diagnose from the
   check annotations (readable without auth — trap 12), reproduce locally with the
   simulation target, fix, and add the lesson as trap 22. Never bypass, never lower the gate.

2. ~~The 8-hour soak verdict~~ **DONE — PASS recorded (937/937, −3.7%); Phase 11 closed.**
   (original instructions kept below for the record) **The 8-hour soak verdict** (the LAST open Phase 11 box). Started 13:33, ends ≈21:35 in
   `bench/soak.json` (a Monitor watcher + the log at `bench/soak-8h.log`; at 6¾ h it was
   782/782 proves, 0 failures, RSS ~110 MB flat — expect PASS, growth well under the 10% bar).
   - **On PASS:** paste the JSON (minus `samples`) into `docs/PLAN-DESKTOP.md` Phase 11's soak
     box, flip it `[x]`, update the Phase 11 row in `HANDOFF.md` + `docs/HANDOFF-PHASES.md` to
     fully ✅, add one line to `docs/METRICS.md`'s Phase 11 envelope, commit, owner pushes.
   - **On FAIL:** treat as a real leak. `bench/soak.json` has the RSS series; correlate growth
     onset with iteration count; suspects in order: sqlite page cache growth in the sidecar's
     long-lived engine, PersistentWorker pool leaks across proves, obslog handles, FTS index
     memory. Reproduce with `--minutes 30` before touching code. Do not ship around it.

3. **Companion-session reconciliation.** Two side sessions ran from spawned chips: the FTS
   adoption-rebuild fix (landed, committed in the wave) and "Close pre-existing api/telemetry
   coverage gaps" (may still be open — its gaps were ALREADY closed in the main wave, so if it
   produced overlapping work, prefer the committed main-line code and close the chip).
   Check `git status` for stray uncommitted work from any other session before starting yours.

4. **Session-hygiene rules that kept today alive** (make them yours):
   - Before ANY push: `make verify` (pipefail! trap 18) + `make verify-linux-denominator` +
     `uv run mypy --strict --platform linux packages/engine/src packages/api/src`.
   - After ANY engine change: rebuild the frozen sidecar (`./packages/desktop/build-server.sh`),
     re-run parity (`uv run python -m tempest.dev.parity --cli-vs-desktop`), rebuild + reinstall
     the app, re-run `orphan_check` (trap 5).
   - Coverage work: iterate `--no-cov`; the authoritative run must be EXCLUSIVE (concurrent
     pytest sessions clobber `.coverage.*` files).
   - New scrubber category = plant the secret FIRST in `test_redact.py` AND
     `tempest/dev/redaction_check.py` (the gate grows with the scrubber; 23/23 today).
   - Planted secrets must never match real-token scanners (trap 19 — letter-segmented fakes).

---

## Part 1 — PRIORITY ONE: frontend ↔ backend at literally zero issues

The owner's words: "first I want to integrate the frontend and backend flawlessly …
0 issues that is our bar." The tri-boundary contract (CLAUDE.md §9b) already guarantees the
*shapes* can't drift — generated Rust + TS from one Pydantic truth, drift gate in CI. What is
NOT yet guaranteed is *behavior*: nothing today exercises the real UI against the real
sidecar. That is the gap between "types agree" and "zero issues." Close it in this order:

### 1.1 The desktop E2E suite — **CORE LANDED 2026-08-15** (see PLAN-DESKTOP Phase 9 box:
11 tests / 6 specs, real engine, console-clean gate, `11 passed (34.6s)`, in
`make verify-desktop`). Still open from the inventory below: exhaustive-enum component
renders (vitest), `reportUiError` crash honesty, the BUILT-app driver leg, desktop-src
coverage gate. Original brief kept for those:
- `pnpm --filter @tempest/desktop test:e2e` is wired but EMPTY. Stand up WebDriver E2E via
  `tauri-driver` (macOS: use the WKWebView driver; CI leg later) or, pragmatically first, a
  **webview-level Playwright suite against `pnpm dev` + a real sidecar process** — the sidecar
  speaks stdio to the Rust host only, so for pure-UI coverage run the API in HTTP mode
  (`tempest-server --port`) and point a thin dev shim at it; the REAL final gate must use the
  built app (bindings + supervisor + stdio all live).
- **Coverage inventory (every row is a test):** runs list (empty state, populated, verdict
  chips, status filter); NEW PROOF form (validation errors, REPO_NOT_FOUND/REF_NOT_FOUND
  surfacing, 202 → live polling → complete); run detail (RUNNING polling, CANCEL button →
  CANCELLED state, verdict + tier banner incl. reduced-assurance, NOT-PROVEN panel, target
  drill-down); divergence detail (evidence fields, repro download content); search (hits,
  empty, operator junk); LOGS view (live refetch, level filter, empty/error states); sidecar
  lifecycle (kill the sidecar process mid-session → "engine restarting" state appears → auto
  recovery when the supervisor respawns).
- **Zero-issues definition, enforced:** every generated binding invoked by at least one E2E
  test; every enum variant renderable (write an exhaustive-render unit test per enum — the TS
  `never`-guard pattern from CLAUDE.md §9 applied to the desktop components); zero console
  errors and zero unhandled promise rejections during the whole suite (fail the run on any —
  wire a listener); loading/empty/error/UNPROVEN designed for every view (L2: UNPROVEN is a
  first-class state, not an error toast).
- **Frontend crash honesty:** add a window `error`/`unhandledrejection` handler that reports
  into the run ledger/obslog via a new `reportUiError` command (scrubbed by the redactor).
  The UI must never fail silently — that is the frontend's L2.
- **TS test bar:** vitest component tests for every view (states enumerated), and set a
  coverage gate for `packages/desktop/src` (start at 100% for `hooks.ts` + views' logic;
  document any JSX-noise exclusions the way python pragmas are documented — justified inline).
- *Gate:* E2E suite green against the BUILT app on this Mac, wired into `verify-desktop`;
  the console-clean assertion holds; every binding + enum arm exercised. Paste output.

### 1.2 Live progress: replace 1.5 s polling with pushed events — **DONE 2026-08-16**
(commit `350eeda`): `watcher.rs` central 1s probe of live runs (parked when idle, L11) →
typed `RunProgressEvent` with the GENERATED domain enums; `start_local_prove` registers,
terminal probe emits the final event + untracks; RunView's timer deleted (slow 5s
`refetchInterval` fallback stays, stated in-code). Cargo-proven against the frame peer
(PENDING pushes → COMPLETE/DIVERGENT → silence) + an E2E push-refetch test. Original brief:
The Rust host already emits `SidecarStateEvent` via tauri-specta. Extend the same pattern:
a `RunProgressEvent` (typed, generated) emitted by the host as it polls the sidecar once per
second centrally — or better, have `localprove` write progress and the host forward new
run_events rows. One socket of truth, no per-view timers. Keep the polling fallback. This is
UX-critical for the "alive" feel of a world-class tool.

### 1.3 Dev-mode deep validation at Boundary B — **DONE 2026-08-15** (`src/devValidate.ts`:
ajv over `domain-schema.json` in every dev-build `unwrap()`, prod bundles clean of it;
proven catching by E2E spec 07 and by finding a REAL defect on day one — API datetimes
violated their own `format: date-time` (naive-UTC, no offset), fixed via `schemas/rfc3339.py`
`UtcMoment` with the published schema pinned byte-identical). Original brief:
serde already rejects contract violations (code -2). Add the dev-only deep check the v1 spec
had for the web app: in dev builds, validate every command result against the generated JSON
schema (`packages/shared-schema/domain-schema.json` is already in the repo) and fail loudly.
Cheap, catches generator regressions the instant they happen.

---

## Part 2 — The world-class agent roadmap (what separates this from mediocre)

The engine's identity is *proof, not opinion*. World-class means: it proves MORE (proof
rate), explains better, and demands nothing from the user. In priority order:

### 2.1 LLM harness synthesis — the proof-rate lever (BYOK, ADR-0006) — **DONE 2026-08-16**
Shipped as specified below (ADR-0024): `harness/llm.py` synthesis stage, execution-validated
on BASE via the same probe as deterministic adapters, `.tempest/adapters/` offline cache,
`SYNTHESIS_DECLINED` + `SYNTHESIZED` across all three boundaries, pyfix c01–c03
instance-method fixtures, and the synthesis gate (0/3 keyless honest → 3/3 exercised with a
key against a local Messages-API peer; real-model rate awaits an owner key — see 2.2).
The single biggest honest weakness: instance methods are `UNPROVEN(TARGET_UNREACHABLE)` (no
constructor synthesis). This is where the user's AI API key finally plugs in:
- **Engine:** a synthesis stage that, when a target is unreachable AND a key is configured,
  asks the model to write a *harness adapter* (constructor call + fixture setup) — the LLM
  writes ONLY the adapter; verdicts stay computed by the differential runner (Law: no
  LLM-authored verdicts, ever). Validate the adapter by executing it sandboxed on BASE first;
  reject adapters that don't produce a callable target. Cache adapters in the repo
  (`.tempest/adapters/`) so the key is needed once per target shape, and runs stay
  reproducible offline afterwards (L8).
- **Reason codes:** `TARGET_UNREACHABLE` gains remediation text "configure an AI key in
  Settings to attempt constructor synthesis"; new code `SYNTHESIS_DECLINED` when the model's
  adapter failed validation — never silently degrade.
- **Key handling (critical, see Part 3):** OS keychain only. The key must never appear in
  env dumps, logs, crash records, bundles, telemetry, or sync — add `ANTHROPIC_API_KEY` (and
  the generic pattern `sk-ant-[A-Za-z0-9-]{20,}`) to the redactor + plant it in the 23-secret
  gate BEFORE wiring the feature (scrubber grows first — that is the discipline).
- **Model:** default `claude-sonnet-5` for adapters (fast/cheap), owner-configurable.
- *Gate:* pyfix gains instance-method fixtures; proof rate on them 0% → measured N% with a
  key; without a key the honest UNPROVEN remains; redaction gate passes with the key planted.

### 2.2 Real-world proof rate — the number that decides everything (§8) — **MEASURED 2026-08-16**
**The number: 42/198 = 21% keyless** (5 OSS repos, real release pairs, T2, exact SHAs —
docs/METRICS.md has the full table + reason distribution; ADR-0025). Shipped with it:
`[roots].source` config (monorepos provable — Tempest now proves ITSELF), one config law
(tempest.toml honored by CLI + desktop + CI identically), `tempest.dev.real_world` (the
repeatable measurement), and `tempest-live.yml` (evidence comment on the repo's own PRs;
reports, never blocks — the fixture self-test still enforces the contract). Distribution
verdict: instance methods (112) + env reproduction (39) are the engine levers before any
feature below. Original steps, for the record:
1. The live-PR gate: open a PR against the repo itself with a seeded behavior change —
   `tempest-selftest.yml` runs the action and comments the evidence. Record the first
   real-world number in `docs/METRICS.md`.
2. Run `tempest prove` against 3–5 real open-source Python repos (small, typed) and publish
   the honest proof-rate table (UNPROVEN reasons distribution IS the engine roadmap).
If real proof rate is below ~60%, ENGINE work outranks every feature below (failure-mode #7).

### 2.3 TypeScript execution (the Phase 3 half) — **WAVE 1 DONE 2026-08-16 (ADR-0028)**
~~Changed `.ts` files currently surface `UNPROVEN(RECORD_REPLAY_UNAVAILABLE)`~~ — Tempest
is bilingual on the wave-1 surface: exported module-level typed functions (sync AND async)
execute under node with seeded JS determinism shims, V8 per-input line coverage, verdicts
via the same comparator, fresh-pair divergence confirmation, and self-contained `.mjs`
repros; the tsfix gate holds it (zero false divergences; the shim-dependent no-op is the
proof the shims work). Landing it exposed and fixed a real classifier hole (`fetch` was
never IO — masked by the old async arm). Wave 2, stated in the ADR: JS cassettes,
methods, ddmin, node in the T1 image, `.tsx`.

### 2.4 Continuous agent behavior
- **Watch mode:** `tempest watch` — prove every new commit on the current branch
  automatically; desktop shows a live feed. The GitHub Action (`action/`) already covers CI.
- **Divergence narratives:** with a key configured, generate a plain-English explanation of
  each divergence FROM the evidence (inputs, values, traces) — labeled "AI narrative",
  verdict untouched. This is the feature that makes evidence readable by the owner's own
  standard (plain English) and by any non-expert user.

### 2.5 Engine depth (ongoing, test-first) — **CAPABILITY WAVE 1 DONE 2026-08-16 (ADR-0026)**
~~Async targets; classmethod/staticmethod; simple dataclass constructor auto-synthesis WITHOUT
an LLM~~ — all three landed keyless (pyfix c04–c07; `harness/typed.py` TYPE_SYNTHESIZED;
worker `asyncio.run`; strict no-raise probe for mechanical guesses). Re-measurement on the
identical corpus SHAs: 21% unchanged — verified against the bundles, its unreachable mass
is 99 PLAIN-class instance methods + 12 generators, so this corpus moves with a key and
with stage-2 env reproduction (the next engine lever). Still open here: parallel target
proving (workers are per-target; the loop is serial today); Linux T2 bubblewrap backend (CI
runners can actually run its escape-suite leg — turning trap-list PENDINGs into greens);
~~**stage-2 env reproduction — now the single biggest measured lever**~~ — **DONE
2026-08-16 night (ADR-0027): 21% → 34%**; humanize 88%, slugify 71%; wheels-only,
offline-first, worktrees self-describe; remaining corpus levers: the 112 key-gated
instance methods, then comparison-layer work.**

### 2.6 Distribution polish (GitHub-only, ADR-0021)
First release tag (`v0.2.0`) fires `release.yml` — watch its install-check job prove
`uv tool install` + doctor on clean runners. Then: Sigstore keyless signing (free), a
`README` demo GIF of a real divergence, and the Phase 18 onboarding (bundled demo repo,
first divergence <90 s, time-to-first-divergence instrumented — the activation metric).

---

## Part 3 — The Apple-grade UI (and the AI-key Settings)

**STATUS 2026-08-15 — 3.1 + 3.2 (AI-key group) LANDED** (commit `c5d4dea`): tokens + light/dark
+ sidebar shell + overlay titlebar + every view restyled (states preserved, enum text
untouched); Settings with the keychain-backed Anthropic key (redactor grew FIRST — 24/24;
`keychain.rs` w/ temp-keychain tests — the login keychain under an unsigned test binary
summons an unanswerable auth dialog, recorded there; `SpawnConfig.env_provider` injects
ANTHROPIC_API_KEY at every spawn, proven across a crash-restart). Gates: verify exit 0
(E2E 13 passed incl settings spec), linux-denom 803/100.00%, screenshots docs/ui/ (14).
Still open from 3.2: Sync/Storage/Privacy setting GROUPS (need the settings.json
infrastructure), the "Test key" live ping (belongs to the 2.1 synthesis phase), motion
polish beyond view transitions, and the §3.3 accessibility pass. Original brief:

The owner wants "cleaner UI just like Apple." Direction, then mechanics:

### 3.1 Design language
- **Typography:** system stack (`-apple-system, SF Pro`), three sizes only (title 17/600,
  body 13/400, caption 11/400 secondary), generous line height. Kill the current terminal
  aesthetic (ALL-CAPS headers) in favor of sentence case.
- **Layout:** left sidebar navigation (Runs · Search · Logs · Settings) with SF-Symbol-style
  icons, translucent material background (Tauri `windowEffects` vibrancy on macOS), unified
  toolbar with the window traffic-lights inset (`titleBarStyle: overlay`), content on an 8pt
  grid, cards with 10px radii and hairline separators — not tables of monospace.
- **Color:** neutral surfaces from the system palette; color is RESERVED for verdicts
  (DIVERGENT red, EQUIVALENT green-tinted-neutral, UNPROVEN amber, ERROR gray) and one accent
  for primary actions. Automatic light/dark via `prefers-color-scheme` with both palettes
  defined as CSS tokens in one place (`styles.css` → `tokens.css`).
- **Motion:** 150–200 ms ease-out transitions on navigation and state changes;
  `prefers-reduced-motion` respected (Phase 18 requirement anyway).
- **States:** every view keeps its designed empty/loading/error/UNPROVEN states — restyled,
  never removed. The reduced-assurance sandbox banner stays prominent (failure-mode #3).

### 3.2 Settings view (NEW — includes the AI API key)
A new sidebar destination with four groups, each a typed round-trip through the boundary:
1. **AI (BYOK):** "Anthropic API key" secure field. Storage: **macOS Keychain via the Rust
   host** (a `set_ai_key`/`ai_key_status` command pair using the `security-framework` crate or
   `tauri-plugin-keychain`; the TS side only ever sees `{configured: bool, last4: str}`).
   The Rust host injects the key into the sidecar process env at spawn — the key NEVER
   touches the DB, config files, bundles, logs, telemetry, or the webview. Add the key
   patterns to the redactor + the 23-secret gate FIRST (see 2.1). A "Test key" button calls a
   minimal countTokens-style request and reports validity without storing anything else.
2. **Sync:** server URL, source-sharing toggle (maps to `TEMPEST_SYNC_SHARE_SOURCE`, default
   OFF with the privacy explanation inline), "Push now" with the SyncReport rendered.
3. **Storage:** bundle budget (slider, maps to `TEMPEST_BUNDLE_BUDGET_BYTES`), current store
   size, "Open data folder".
4. **Privacy:** telemetry opt-in toggle (default off, counters-only explanation), "Export
   diagnostic bundle" (runs `diagnose`, reveals the zip in Finder), link to PRIVACY.md.
Settings persistence: a `settings.json` in the data dir (NOT the key) with a versioned schema
handled like the local store (refuse-newer semantics), surfaced through generated commands so
the tri-boundary drift gate covers Settings too.
- *Gate:* E2E: set key (mock keychain in test build? No — use a real test keychain entry and
  delete it in teardown), toggle each setting, restart app, values persist; redaction gate
  green with a planted `sk-ant-` key; parity + egress gates unchanged (key must not create
  network traffic outside the synthesis call itself).

### 3.3 Execution order for the UI work
Redesign is a restyle of WORKING views — do it only after Part 1's E2E suite exists, so every
visual change lands with the behavior net already in place. Sequence: tokens + sidebar shell
→ view-by-view restyle (E2E stays green after each) → Settings view (with keychain plumbing +
redactor first) → motion/polish → accessibility pass (VoiceOver, keyboard, 200% zoom — Phase
18's checklist). Screenshot each view into `docs/ui/` for the owner's per-phase check-in.

---

## Part 4 — Suggested session sequencing (each step ends with its gate + an owner check-in)

1. Push `caadff7` → CI green ×7. Record the soak verdict, close Phase 11 completely.
2. Part 1.1 E2E suite (this is big — use subagents per view-cluster, verify their work).
3. Part 1.2 events + 1.3 dev validation. Declare "frontend↔backend: 0 known issues" only
   when the E2E gate + console-clean assertion + exhaustive-enum renders are all green.
4. Part 3 UI: tokens/shell → restyles → Settings + keychain + AI key (with 2.1's redactor
   work done first).
5. Part 2.1 LLM synthesis engine-side, then 2.2 live-PR + real-repo proof-rate measurement.
6. First release tag; onboarding; Phase 18 items as the finish line.
The enterprise phases (14/15/16) stay parked unless the owner says otherwise — GitHub-only
distribution (ADR-0021) is the product direction; the open question to them is already in
`docs/HANDOFF-PHASES.md`.

## Part 5 — The process that made today work (keep it)

TDD with the RED watched; adversarial review waves after every large feature block (two
independent reviewers, verified findings only, fix test-first — today: 4 critical / 12 major
/ 11 minor, all dead); coverage at 100 with every exclusion justified inline; the planted-
secret gate growing before the scrubber; CI's exact view simulated locally before every push;
per-phase plain-English check-ins with real numbers; memory + handoff updated at every
milestone so no session ever starts cold. The bar is the product. Hold it.
