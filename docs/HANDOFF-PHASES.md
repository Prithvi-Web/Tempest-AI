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
