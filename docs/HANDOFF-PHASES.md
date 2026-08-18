# HANDOFF — remaining phases (start here for Phases 11–18)

**Purpose:** a fresh session's entry point for the desktop/enterprise roadmap. Pairs with the
repo `HANDOFF.md` (read that first — status table + traps) and `docs/PLAN-DESKTOP.md` (the full
Phase 9–18 checklist with exact gate commands). This file adds the *how to resume*, the standing
traps you must not relearn, and the owner decisions that block specific phases.

**As of 2026-08-14 (evening) · published at `github.com/Prithvi-Web/Tempest-AI` · CI green on
`main` at `1f408d3`; Phase 11 commits are LOCAL, awaiting the owner's push · `make verify`
exit 0 with the Phase 11 work in · 8-hour soak in flight (see §2).**

---

## 1. Read order for a new session

0. **`docs/HANDOFF-NEXT.md` — START THERE. The current live state, the CI-fix context,
   the frontend↔backend integration law, the remaining-work order, and the per-phase
   loop. It supersedes every older "live state" section including this file's header.**
1. `CLAUDE.md` — the contract (Laws L1–L14, §9b tri-boundary, §13 verify bar).
2. `HANDOFF.md` — status-at-a-glance table + the standalone traps.
3. This file — remaining phases + resume procedure.
3b. **`docs/HANDOFF-WORLD-CLASS.md` — the forward plan (owner, 14 Aug eve): flawless
    frontend↔backend first (E2E suite = the gap), Apple-grade UI + AI-key Settings via
    keychain, LLM harness synthesis (BYOK), real-world proof rate. Read it before choosing
    what to build next.**
4. `docs/PLAN-DESKTOP.md` — per-phase checklist with the exact gate command for each box.
5. `docs/DECISIONS.md` — ADR-0001..0015; every deviation from spec is here.
6. `docs/AUDIT-PHASE8.md`, `docs/METRICS.md` — the truth audit + the three numbers.

**User is a non-coder** — plain English, copy-paste commands, verify by running the real app.
**Subagents FORBIDDEN as of 15 Aug 2026** (owner re-reversal: "don't use sub agents anymore.
Just build with one but go all out") — single-agent, maximum-depth work; STOP after every
phase for owner review, and rebuild+reinstall the app to /Applications each phase.
**Check in after each phase/feature**, flawless bar.

---

## 2. What is DONE (don't redo)

| Phase | State | Where the evidence lives |
|---|---|---|
| 8 Truth Audit | ✅ | `docs/AUDIT-PHASE8.md` — 3 honesty defects found+fixed |
| 9 Desktop Shell | ✅ core | stdio JSON-RPC (no TCP), Rust supervisor, generated tri-boundary types + drift gate, 5 views on typed bindings, **Next.js `packages/web` deleted** (ADR-0014) |
| 10 Sandboxing w/o Docker | ✅ macOS T2 | `SeatbeltSandbox` (ADR-0015); escape suite **27/27**, egress **0**, tier→bundle→API→UI |
| Perf | ✅ | `PersistentWorker` — pyfix **118→20 s (5.9×)** |
| **11 Local-First Data & Perf** | ✅ 5/6 boxes 2026-08-14 (ADR-0016..0019) | Versioned WAL store w/ refuse-newer; content-addressed bundle store + budget GC; FTS + `.tempest` import/export; bench gate green (`bench_guard: PASS`, darwin baseline committed, CI `bench` job added); L11 cancel <2 s + battery/thermal pause. **8-h soak PASS 21:35: 937/937 proves, 0 failures, growth −3.7% (bar 10%)** — Phase 11 fully ✅ |
| **17 Reliability & Observability** | ✅ 2026-08-14 (ADR-0020) | Redaction-first, local-only, opt-in: `tempest.redact` + gate `redaction_check --planted-secrets` **14/14 contained** (in verify + CI); crashes scrubbed at write time (excepthook CLI + sidecar); counters-only opt-in telemetry wired into local prove; `tempest diagnose` (inspectable zip, transmits nothing); `tempest.obslog` JSON-lines + rotation + `tempest logs show` + desktop LOGS view; `tempest doctor` (live: T2, all pass). `docs/PRIVACY.md` + `docs/SUPPORT.md`. No transmission path exists until Phase 13 (L10 zero-egress preserved) |
| **13 Team Sync (core)** | ✅ protocol 2026-08-14 (ADR-0022) | `checkBundlePresence` + `syncPush`: delta-only, idempotent, resumable — the store IS the queue; source stripped BEFORE hash/wire by default (`syncstrip`, opt-in `TEMPEST_SYNC_SHARE_SOURCE=1`); gates ran against a REAL killed-and-restarted second server: no dup/loss, push=pull byte-identical. **PENDING(docker):** compose end-to-end, Postgres sync gate, Helm, image signing (`docs/DEPLOY-SYNC.md`) |
| **Flawless bar (owner, 14 Aug eve)** | ✅ 2026-08-14 (ADR-0023) | **Coverage gate = 100%** (`fail_under=100`; 802 tests; 4,676 stmts + 1,320 branches, 0 missed; subprocess coverage via scripts/covstart; justified pragmas only). **Adversarial-review wave**: 4 critical + 12 major + 11 minor confirmed findings fixed test-first (verdict integrity, GC-after-commit, sync source-strip, redaction 23/23, process safety, docker -i/named-kill). verify green, parity byte-identical, orphan 2.7 s, fresh app installed |
| **12 Distribution (GitHub-only)** | ✅ rescoped + built 2026-08-14 (ADR-0021) | Owner decision: no Apple ID/certs — `release.yml` on tag: wheel/sdist + unsigned .app + SHA256SUMS + install-check job (`uv tool install` + doctor on clean runners); README install docs. **Gate fires on first tag push** |
| **HW-C Phase 18 onboarding (demo)** | ✅ 2026-08-17 late night (ADR-0032) | "Try a demo proof" in the empty runs state → `POST /v1/local/demo` → the engine writes a REAL demo repo (first-party marker — works on Docker-less laptops) and proves it through the ORDINARY machinery: real run row, ledger, bundle, pushed progress, downloadable repro (nothing special-cases "demo" but the repo builder + one ledger sentence). The seeded change teaches the vocabulary on one screen: rounding "cleanup" DIVERGENT (int cents → float truncation moves money) beside an honest EQUIVALENT_UNDER_BUDGET refactor. Repo-identity through ingest = constant leaf under a unique parent. **Measured activation: click → visible DIVERGENT in 6.4 s (bar 90 s)**, pinned by a timed E2E spec + the API test (evidence chain to the repro text; demo-twice independence). Gates: {GATES32} |
| **HW-C 1.1 hardening + 3.3 accessibility** | ✅ 2026-08-17 night (ADR-0031) | **Enum vocabulary, two nets** (`src/vocabulary.tsx`): every rendered enum through a never-guarded switch (new Python variant breaks tsc) + vitest drives every function/chip over every variant READ FROM the generated schema (copy proven non-empty; guard THROWS on unknown — stale bundles crash honestly). L2-bound copy; views consume it (tooltips + actionable UNPROVEN remediation). **reportUiError**: window error/unhandledrejection → typed command → `/v1/ui-errors` → PRODUCTION redaction → obslog → LOGS view; unbreakable reporter (burst cap 20, 4KB truncation); planted-secret + [EMAIL]-scrub proven, E2E end-to-end. **Desktop logic coverage gate**: vitest 100%/100% over vocabulary+router in `pnpm -r test` (scope stated — views are pinned by the 28-spec Playwright suite; L4 trade in vitest.config.ts). **Accessibility**: skip link, Primary landmark, focus-to-title on navigation, aria-live engine pill, reduced-motion dead, zero horizontal scroll at 200% zoom — 5 E2E specs. **BUILT-app driver leg: platform-blocked (tauri-driver has no macOS/WKWebView backend), stated in ADR-0031 §5 with the compensating gates** (orphan check launches the real .app; parity; same webview bundle in E2E). Dividend: router bug (`?view=run` → run #0) + StrictMode focus-guard bug, both caught by the new tests. Gates: {GATES31} |
| **HW-C 3.2 Settings + watch in the app** | ✅ 2026-08-17 late (ADR-0030) | **One config law**: `settings.json` in the data dir (versioned, refuse-newer; corrupt/unknown-key = explicit error, never a silent reset) with **environment > file > default** — and every env-forced field is NAMED through the boundary (`EnvOverride{field,variable}`), so the screen disables that control and says which variable to unset instead of lying. Engine read path degrades a damaged file to defaults (L8) *while still applying the environment* — a broken file must not switch off an opted-in export. Budget ceiling 2 GiB, stated (Boundary B integers are 32-bit). **Sync/Storage/Privacy groups** render real config (server URL + source-sharing + Push now w/ SyncReport; budget slider + live store size + Open data folder; telemetry toggle + diagnostic export). **Test key** = ONE `messages.create(max_tokens=1, "ping")` on the SAME synthesis egress surface — no source, no repo, nothing stored; keyless = zero network + the actionable sentence. **Diagnostics have one implementation** (`write_diagnostic_bundle`, shared CLI+API); the host's `reveal_in_data_dir` accepts only a plain leaf (`safe_leaf`), joined to the app's own data dir. **Watch in the app** (`watchsession.py` + Watch destination): a watched commit becomes an ORDINARY run — same list, ledger, cancel, bundle, search, RunProgressEvent (the host tracks the loop's active run) — and the proven-commit feed is a QUERY over the `watch.commit` ledger mark, so it survives restarts and cannot drift. L11: commit taken at prove START (no infinite re-prove), the battery/thermal hold is entered with a CancelScope so Stop returns mid-hold, and Stop cancels the in-flight prove → CANCELLED, never a verdict. **Trap 36** (greenlet-crossing coverage attribution) fixed structurally. Gates: **1019 tests / 100.00% BOTH denominators** (5,782 stmts + 1,644 branches; linux 1013/100.00%), corpus 30/30 stable ×5, escape 27/27 contained (T2), redaction 24/24, vitest 27, cargo 12+5, desktop E2E **20/20** console-clean, contract drift 0, parity byte-identical, frozen TOC carries the `.mjs` pair (trap 32), orphan 2.2s, app 20:57 |
| **HW-C 2.4 Continuous agent** | ✅ 2026-08-17 (ADR-0029) | `tempest watch`: every new commit proven incrementally (prev→new, per-commit bundles; L11 pause between polls, Ctrl-C clean, `--from`/`--once` deterministic under test — 6 arms pinned w/ real repos+proves). **AI narratives**: `DivergenceRecord.ai_narrative` (bundle schema v3, tolerant reader; alembic 0005 + local-store step + REVISION_CHAIN — the gate caught the chain gap: stamped older DBs would have silently missed the column), generated FROM evidence AFTER verdicts by the BYOK key (keyless→None zero-egress; API failure→None; labeled "AI narrative" in CLI + app; DROPPED WHOLE under sync source-strip — a paraphrase can't be scrubbed span-wise, L9 — planted-literal sweep covers it). Keyed synthesis gate proves narratives end-to-end vs the local peer, identical verdicts. Gates: 949/100.00% + 943/100.00% linux (5,391+1,592), redaction 24/24, E2E 14, vitest 27, parity, orphan 2.1s, app 12:12 |
| **HW-C 2.3 TypeScript exec wave 1** | ✅ 2026-08-16 late (ADR-0028) | **Tempest is BILINGUAL**: exported module-level `.ts` functions (sync+async) execute under node native type stripping (offsets preserved → honest per-input V8 coverage w/ count-0 subtraction); `ts_shims.mjs` = L3's JS half (seeded Math.random/Date/perf/crypto — worker runs byte-identical); `ts_dual.py` verdicts via the SAME comparator (base self-agreement → NONDETERMINISTIC_BASE; fresh-pair confirm; typed-pool inputs; `.mjs` repros; ddmin=wave 2 stated); prove.py per-symbol TS honesty replaces the blanket record. **Classifier followed capability** (async runnable; shimmed ambient pure) — which EXPOSED `fetch` missing from IO-globals (masked by the old async arm; async IO would have been blessed off error paths) — fixed+pinned. tsfix gate 8/8 (zero false divergences; shim-dependent no-op IS the shim proof); ts_dual arms 16+6; frozen app bundles the `.mjs` pair (verified in TOC — parity can't see TS). Gates: 938/100.00% + 932/100.00% linux (5,320+1,582), E2E 14, vitest 27, orphan 2.1s, app 23:22 |
| **HW-C stage-2 env repro** | ✅ 2026-08-16 night (ADR-0027) | **THE NUMBER MOVED: 21% → 34%** (humanize 0→88% w/ 6 real DIVERGENT; slugify 0→71% w/ 1). `envrepro/deps.py`: static pyproject/setup.py-AST metadata (constant folding, name may stay None — never executed), dist-info shim, `_version.py` shim from `git describe` (hatch-vcs pattern), wheels-only `uv pip install --target` offline-first (`--fetch-deps`/`TEMPEST_FETCH_DEPS=1` opt-in, cache → offline reruns); worktrees self-describe (`.tempest-deps` symlink + remediation note → introspect UNPROVEN). **T2/T1 carve fix:** the symlink target was outside the Seatbelt repo carve/Docker mounts — profile gains the resolved site dir; gate grew a REAL T2 leg (ProcessSandbox-only integration is blind to profile bugs). First re-measure moved nothing — both hypotheses falsified by bundles, fixes landed only after reproducing each import by hand. Residual 12 import failures = dev scripts, out of scope, stated |
| **HW-C 2.5 Engine depth wave 1** | ✅ 2026-08-16 (ADR-0026) | Free proof rate, keyless: static/classmethods pinned (were provable, never exercised — pyfix c04/c05); `harness/typed.py` TYPE-driven dataclass constructor synthesis (AST-only, zero-values, TYPE_SYNTHESIZED tri-boundary, strict no-raise probe via new `probe_raised` — an unattributable raise never anchors a comparison); async targets via worker `asyncio.run` (classifier arm removed, c07). Re-measured identical corpus SHAs: **21% unchanged, verified why** — its unreachable mass is 99 plain-class instance methods + 12 generators (zero new-lever shapes); ceiling raised, corpus number awaits key + stage-2 env repro (now the #1 measured lever). Gates: 865 tests / **100.00% both denominators** (4,883+1,414), redaction 24/24, E2E 14, parity, fresh app |
| **HW-C 2.2 Real-world proof rate** | ✅ 2026-08-16 (ADR-0025) | **THE NUMBER: 42/198 = 21% keyless** (5 OSS repos, real release pairs, T2, exact SHAs — docs/METRICS.md). Shipped: `[roots].source` (monorepos provable; worktrees self-describe; repro sys.path prologue), one config law (tempest.toml honored by CLI+desktop+CI — closed a real gap), `tempest.dev.real_world`, `tempest-live.yml` (evidence comment on own PRs; reports, never blocks) + root tempest.toml + seeded `tempest-live-demo` branch. Local T2 self-prove: `tempest.config._vocabulary` DIVERGENT, minimized repro with roots prologue. Distribution names the levers: 112 instance methods (→ synthesis w/ key), 39 import failures (→ env repro). Gates: 842 tests / **100.00% both denominators** (4,791+1,362), redaction 24/24, E2E 14, parity, fresh app |
| **HW-C 2.1 AI harness synthesis** | ✅ 2026-08-16 (ADR-0024) | `harness/llm.py`: model writes ONLY constructor adapters (BYOK, default `claude-sonnet-5`); acceptance = real sandboxed execution on BASE; `.tempest/adapters/` cache → offline reruns (L8); `SYNTHESIS_DECLINED` + `SYNTHESIZED` across all three boundaries; repros embed adapter source (L7); coverage attribution via `trace_module`. pyfix +c01–c03: **0/3 keyless honest → 3/3 exercised** vs a local Messages-API peer (real SDK→HTTP, L4); suite scrubs real keys. Gates: 821 tests, **100.00% both denominators**, redaction 24/24, egress 0, roundtrip 10000/10000, parity byte-identical, E2E 14, orphan 2.1 s, fresh app installed |

**Architecture now:** Python engine (the nine stages + determinism moat — the validated core;
kept in Python by ADR-0011, user-confirmed) · Rust host (`packages/desktop/src-tauri`: supervisor,
IPC, framing, lifecycle) · TypeScript webview UI (generated bindings only). The CLI and the
desktop app share the identical engine and produce byte-identical bundles (parity gate).

---

## 3. Open stragglers in completed phases (do these opportunistically)

- **Phase 9:** ~~desktop E2E suite~~ **DONE 15 Aug** — 11 Playwright tests, real UI × real
  engine via `e2e/bridge.mjs` (stdio frames) + `e2e/shim.js` (`__TAURI_INTERNALS__`),
  console-clean gate, in `make verify-desktop` (see `docs/PLAN-DESKTOP.md` Phase 9 box).
  Still open: BUILT-app (tauri-driver) leg, CI leg (runners lack the cached browsers),
  clean-VM launch test (needs a VM this Mac lacks).
- **Phase 10:** Linux (bubblewrap+seccomp+userns+cgroups) and Windows (AppContainer+Job Object)
  T2 backends; the true T3 (separate-user); netns deny-all packet-capture egress leg; T1-vs-T2
  Docker perf delta. **All are other-OS/CI legs** — this host is macOS-only. Each is marked
  PENDING(CI) in the escape/egress output, never silently skipped.

---

## 4. Remaining phases 11–18 (gates verbatim in `docs/PLAN-DESKTOP.md`)

For each: the goal, the approach that fits this codebase, and the owner blocker if any.

### Phase 11 — Local-First Data & Performance
- SQLite WAL is already the local store; add a **content-addressed bundle store** with GC + a
  user size budget, **FTS over divergences**, and **`.tempest` import/export**.
- **Forward+backward migration test:** an older app must refuse a newer DB cleanly. The Alembic
  chain is at `0002`; parity test `packages/api/tests/test_migrations.py` already proves
  `upgrade head` ≡ `create_all` — extend it for the refuse-newer case.
- Assert perf targets in CI on a 4-core profile: cold launch <1.5 s, 10k-run list first paint
  <200 ms @60 fps, 5 MB observation <400 ms, idle <250 MB / <1% CPU. L11: cancel stops
  everything <2 s; battery/thermal pause. 8-hour soak, memory growth <10%.
- *Gate:* a CI bench that fails on >15% regression. **No owner blocker.** Good next phase.

### Phase 12 — Distribution: GitHub-only (rescoped, ADR-0021)
- Owner decision 2026-08-14: ship from the public repo — GitHub Releases (wheel/sdist +
  PyInstaller CLI binaries + unsigned .app + SHA-256 checksums), README install docs
  (`uv tool install` / release download, honest Gatekeeper note). **No Apple ID, no paid
  certificates, no MDM.** L13 satisfied via checksums + Actions build provenance
  (Sigstore keyless later, free).
- *Gate:* a tagged release builds green in Actions; a clean machine installs from GitHub
  unaided and `tempest doctor` passes.

### Phase 13 — Team Sync Server (optional, self-hosted first)
- A customer-run container: Postgres + object storage; content-addressed, resumable, idempotent,
  delta-only sync; **redaction at the boundary — source snippets stripped unless org policy
  enables it, default OFF, proven by test**; offline queue with durable retry.
- *Gate:* kill network mid-sync → clean resume, no dup/loss; push=pull byte-identical; redaction
  test proves no source crosses with default policy. No owner blocker to start the container.

### Phase 14 — Enterprise Identity, Policy & Audit
- OIDC + SAML 2.0 (system browser + PKCE loopback, never an embedded webview); SCIM 2.0
  provisioning/deprovisioning; RBAC server-side; org policy pushed+enforced locally (min sandbox
  tier, verdict thresholds, telemetry, source-sharing, allowed repos); **hash-chained
  append-only audit log** (local + server), JSON + CEF export, tamper-evidence test.
- **[ASK ME]:** real Okta + Entra developer tenants for the end-to-end gate.

### Phase 15 — Air-Gapped Deployment & Licensing
- Zero mandatory egress (already true locally — L8/L10); configured PyPI/npm mirrors + vendored
  cache; **Ed25519 offline license files** (org/seats/expiry/features), clock-tamper grace
  window (never brick a paying customer); offline update bundles; air-gap install docs.
- *Gate:* full install + prove-run on a VM with **no network interface**. VM needed.

### Phase 16 — SOC 2 Type II Readiness
- Compliance platform (Vanta/Drata/Secureframe) wired to evidence; control set; in-repo
  enforcement (branch protection, signed commits, dep/secret/SAST scanning); third-party pen
  test; Trust Center page publishing the L10 egress results + pen-test letter.
- **[ASK ME]:** compliance-platform subscription; pen-test budget. Do NOT build compliance
  theater before the proof rate is real on live PRs (failure-mode #7).

### Phase 17 — Reliability, Observability & Support
- Opt-in crash reporting **provably source-free** (planted-secret scrubber test — zero leakage);
  opt-in aggregate telemetry (proof rate, tier distribution, UNPROVEN reasons); redacted
  diagnostic bundle the user inspects before sending; structured logging + rotation + viewer;
  health self-check command.
- *Gate:* redaction suite with planted secrets — zero leakage; `docs/PRIVACY.md`. No owner blocker.

### Phase 18 — GA Readiness
- First-run onboarding: repo detection → bundled demo prove → **real divergence <90 s from
  install** (instrument time-to-first-divergence — the activation metric); full docs;
  WCAG AA + keyboard + VoiceOver/NVDA + 200% zoom; localization scaffolding (ship English);
  pricing/seat management wired to license features; rehearsed + rollback-tested release.
- *Gate:* five external design partners install unaided and reach a real divergence on their own
  code; report proof rate + time-to-first-divergence for each. **This is the number that says
  whether there's a company.**

**Recommended order from here:** ~~11~~ ✅ → ~~17~~ ✅ → ~~13 core~~ ✅ → ~~12 (GitHub-only)~~ ✅
→ **open question for the owner:** with GitHub-only distribution as the product direction, do
the enterprise phases (14 SSO/SCIM, 15 licensing, 16 SOC 2) still apply, or does the roadmap
jump to 18-style GA polish (onboarding, docs, accessibility, live-PR proof rate)? 14–16 remain
blocked on owner resources either way; 18's design-partner gate needs the first tagged release.

---

## 5. Standing traps — do NOT relearn these

1. **Sandbox tiers (ADR-0015):** no Docker on macOS now means **T2 Seatbelt**, not
   SANDBOX_UNAVAILABLE. Ladder T1 Docker→T2 Seatbelt→UNPROVEN in `execute/sandbox.py::select_sandbox`.
   `TEMPEST_NO_SEATBELT=1` forces the no-tier path (tests use it). **ProcessSandbox/T3 is never
   offered for untrusted user code** (escape suite: it leaks 18/27). First-party fixtures still
   use ProcessSandbox with the repo marker + `TEMPEST_DEV=1`.
2. **The Seatbelt profile must carve read access to the worker interpreter** (`cmd[0]`) + its
   realpath + prefix — a home-based `~/.local/bin/python3.12` is under `$HOME` (denied) and the
   worker won't start otherwise (shows as HARNESS_SYNTHESIS_FAILED). Also `.resolve()` every
   profile path — macOS `/var`→`/private/var` symlink voids an unresolved scratch mount.
3. **The worker is stdlib-only** (`execute/_worker.py` incl. its new `serve` mode). It runs where
   tempest isn't installed; `canonical.py`+`_shims.py` are copied beside it. Nothing it imports
   may be non-stdlib. **Cannot call Rust** — that's why the execution core stays Python.
4. **Perf model (`PersistentWorker`):** one pooled worker pair per pure target + per shrink
   ladder; **the 3× divergence confirmations MUST stay on fresh process pairs** (§14.2 — that
   freshness is the 0-false-alarm defense; never pool those). Determinism batches keep
   one-process-per-batch.
5. **Rebuild the frozen sidecar after ANY engine change** before testing the app:
   `./packages/desktop/build-server.sh`. A stale PyInstaller cache ships old code — wipe
   `packages/desktop/{build,dist}` if a path moved. The bug in §trap-2 was caught only by the
   live installed-app test, not by `make verify`.
6. **Tri-boundary drift gate:** after touching API Pydantic schemas run `make gen-contracts` and
   commit the regenerated `packages/shared-schema` + `packages/desktop/src/generated` +
   `packages/desktop/src-tauri/src/generated`. `verify-contract` fails on any diff.
7. **The string S‑A‑F‑E must never appear in product surfaces** (L2) — CI greps for it.
8. **E501 line length = 100**, enforced. **specta pinned `2.0.0-rc.25`** (no stable). **i64 is
   banned at the TS boundary** — the domain schema pins integers to int32.
9. **PLAN checkboxes flip only with real gate output pasted.** Claimed-passing is failing.
10. **macOS RLIMIT_NPROC is per-UID** — don't cap it (throttles the whole session); fork bombs
    are bounded by the per-input timeout + pgroup-SIGKILL instead.
11. **This Mac is fast; CI Linux runners are not.** Worker startup (spawn + interpreter boot +
    target import) is ~30 ms here and can be seconds there. It must never be charged to the
    per-input timeout — `_STARTUP_GRACE_S` in `execute/runner.py` covers the first result after
    a spawn, or a healthy fast input is mismarked `HUNG` and Tempest invents a HANG divergence.
    Any new timing assertion needs the same headroom.
12. **GitHub Actions raw logs AND job summaries need a signed-in session** — an outside agent
    cannot read either (verified 15 Aug: `output.summary` comes back empty from the public API).
    The ONLY publicly readable failure channel is check-run ANNOTATIONS
    (`GET /repos/{owner}/{repo}/actions/runs/{id}/jobs` → step conclusions, and
    `GET .../check-runs/{id}/annotations` → the `::error::` lines). The `python` job's
    "surface pytest failure" step emits failing tests, the coverage total, AND every non-100%
    coverage-table row (with missing line numbers — `show_missing` is on) as `::error::`.
    Keep that step; it is how a red build is diagnosed from outside.
13. **Pushing needs the owner.** The CLI has no stored GitHub credential (the repo is published
    and pushed through GitHub Desktop). Commit locally, then ask the owner to click *Push origin*.
    Remote: `https://github.com/Prithvi-Web/Tempest-AI.git`.
14. **The CI python job MUST install node deps** (`setup-node` + `corepack enable` +
    `pnpm install --frozen-lockfile`) before pytest. Without them the six ts-sidecar bridge
    tests skip silently and `ts_sidecar.py` coverage collapses (23% vs 80%) — Linux lands at
    84.23% and the 85% gate fails while every test "passes." Silent suite-narrowing (§14.1);
    fixed in `1f408d3`, do not regress it.
15. **Local green ≠ CI green.** This Mac runs macOS-only tests (Seatbelt) and has node deps
    installed; Linux CI skips the former and — before trap 14 — lacked the latter, so the two
    coverage totals differ by design. When touching the coverage config or adding skips, sanity
    check what the LINUX denominator will look like, not just the local one.
16. **Growing any VARCHAR-backed enum changes the computed column width** — the parity test
    fails until a widening alembic migration ships (see `0004`, ADR-0019). For the LOCAL
    sqlite store such width-only revisions are stamp-only forward steps (`_FORWARD_STEPS`
    entry `()`): sqlite type affinity ignores widths, and the forward-equivalence test
    compares width-insensitively for exactly that case. Never relax the parity test itself.
17. **Battery/thermal pause (L11) vs gates:** every gate/suite invocation must run with
    `TEMPEST_NO_POWER_PAUSE=1` (Makefile + both conftests set it) or an unplugged laptop
    pauses proves and the gate hangs. Pause tests force the condition with
    `TEMPEST_FORCE_POWER_PAUSE`, which outranks the opt-out. Precedence: FORCE > NO > probes.
18. **`make verify | tail` lies about the exit code** — the pipe reports tail's status. Use
    `set -o pipefail` (or read `PIPESTATUS[0]`) before believing a piped verify.
19. **Planted secrets vs GitHub push protection:** realistic Slack-shaped fixtures in the
    redaction suite BLOCK the owner's push (Slack tokens carry no checksum, so GitHub cannot
    tell fake from real; ghp_/sk- plants pass because their checksums fail). Keep plants
    letter-segmented (`xoxb-PLANTED-FAKE-…`) — same redactor pattern, no scanner match. The
    one historical hit was cleared via GitHub's "used in tests" bypass (it was fictional).
20. **mypy specializes `sys.platform` per checking host** — a `sys.platform != "darwin"` guard
    makes darwin-only code "unreachable" under --strict on Linux CI (first CI run caught it in
    powerstate.py). Use `platform.system()` for runtime platform guards, and `make verify`
    now runs `mypy --strict --platform linux` so the Linux view is checked locally too.
    (mypy --platform win32 has 13 pre-existing findings in process-control code — that is the
    Phase 10 Windows leg's problem, stated here, not silently ignored.)
21. **The Linux COVERAGE denominator differs too** (first 100%-gate CI run): macOS-only tests
    (Seatbelt escape/report, zombie-pgid kill fallbacks — Linux kernels keep a dead unreaped
    leader's pgid signalable, so that scenario is unstageable there) leave their exclusive
    lines unexecuted on Linux. Darwin-only regions carry `# pragma: darwin-only` so both
    platforms measure the SAME set, and `make verify-linux-denominator` reproduces CI's exact
    suite locally — run it before pushing coverage-heavy changes. Formatter warning: pragmas
    on a `def` line get moved when ruff rewraps the signature — put them on a stable body line.
22. **ubuntu runners ship a LIVE Docker daemon** (this Mac has none): every real-ladder call
    (`doctor`'s healthy-machine test) selects **T1 there, T2 here** — so a rung below T1 that
    only real ladders reach is covered on macOS and silently unexecuted on Linux (the 15 Aug
    99.95% CI failure: `select_sandbox`'s seatbelt rung + `SeatbeltSandbox.available()`).
    `make verify-linux-denominator` CANNOT see this class — it deselects tests but still runs
    on macOS, so runtime-arc divergence inside shared tests is invisible to it. Any ladder
    rung or platform-probing path needs an explicit test staging the probe result identically
    on every OS (nonexistent absolute binary path, fake executable on PATH) with
    platform-aware assertions, never skipifs — see
    `test_seatbelt_rung_is_probed_when_docker_is_absent`.

*(Traps 23–35 are indexed in `docs/HANDOFF-NEXT.md` §6, where each one's full text lives
alongside the phase that paid for it. The list resumes here for 36.)*

36. **Coverage mis-attributes the line right AFTER a greenlet crossing.** SQLAlchemy's async
    layer switches greenlets on every `await session.execute(...)`; the statement that
    immediately follows can be reported as never executed while every line around it is
    covered — a `return [...]` comprehension read as dead code although the test asserting its
    output passed. Do NOT chase it with a pragma on the whole block, and do NOT conclude the
    code is unreachable: move the post-await work into a plain synchronous helper, so only the
    single call line carries a justified pragma and the logic itself is genuinely measured
    (`routers/watch.py::_to_feed`; `localprove.py:214` documents the same artifact from the
    other direction). Related but distinct from trap 27 (the worker's settrace window).

---

## 6. Resume commands

```bash
make sync                 # uv + pnpm install
make verify               # every live gate — must be exit 0 before any completion claim

# The Phase 8–10 gates (all green today):
uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
uv run python -m tempest.dev.escape_suite --tier T2          # 27/27 contained
uv run python -m tempest.dev.egress_check --expect-zero      # 0 outbound
uv run python -m tempest.dev.roundtrip --py-rust-ts --iterations 10000
uv run python -m tempest.dev.parity --cli-vs-desktop         # needs the frozen sidecar built
uv run python -m tempest.dev.orphan_check                    # needs Tempest.app installed

# Rebuild + reinstall the desktop app after engine/host changes:
./packages/desktop/build-server.sh                           # frozen engine sidecar
cd packages/desktop && pnpm tauri build
rm -rf /Applications/Tempest.app && ditto \
  packages/desktop/src-tauri/target/release/bundle/macos/Tempest.app /Applications/Tempest.app

# Prove a repo from the CLI (T2 on macOS):
uv run tempest prove --base <ref> --head <ref> --repo <path>
```

**Toolchain:** uv + pnpm at `~/.local/bin`, cargo at `~/.cargo/bin`. Put both on PATH.

---

## 7. Owner decision queue ([ASK ME] — surface these before the phase that needs them)

1. ~~Git history slim~~ **DONE** (verified 14 Aug: `.git` 1.4 MB, largest historical blob
   0.2 MB, all commits intact). Backup at `Desktop/Claude Code/.tempest-backup-pre-history-slim.git`
   can be deleted once the owner is comfortable.
2. ~~GitHub publish~~ **DONE** — live at `https://github.com/Prithvi-Web/Tempest-AI` (Public).
   **CI fully green on `main`** as of `1f408d3` (all 6 jobs). Natural next step: open a PR with
   a seeded behavior change to fire `tempest-selftest.yml` — the Phase 6 live-PR gate — and
   record the first real-world proof-rate number in `docs/METRICS.md`.
3. **External security review** of the T2 profile + escape corpus + sync boundary (ADR-0015,
   prompt §10) — engagement + budget. Before GA.
4. ~~Phase 12: Apple Developer ID + Windows EV certificates~~ **CANCELLED by owner decision
   2026-08-14 (ADR-0021): GitHub-only distribution — releases + checksums, no paid signing.**
5. **Phase 14:** Okta + Entra developer tenants.
6. **Phase 16:** compliance-platform subscription + pen-test budget.

---

## 8. The three numbers (report every status update — `docs/METRICS.md`)

1. **Proof rate** — fixture 100%; **real-world still UNMEASURED** (needs the live-PR gate +
   design partners). Below 60% on real code, engine work outranks enterprise features.
2. **False divergence rate** — effectively 0 (3× fresh-pair confirmation; preserved through the
   perf rework).
3. **Time-to-first-divergence** — not yet instrumented; it's the Phase 18 activation metric.
