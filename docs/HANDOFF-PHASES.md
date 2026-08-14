# HANDOFF — remaining phases (start here for Phases 11–18)

**Purpose:** a fresh session's entry point for the desktop/enterprise roadmap. Pairs with the
repo `HANDOFF.md` (read that first — status table + traps) and `docs/PLAN-DESKTOP.md` (the full
Phase 9–18 checklist with exact gate commands). This file adds the *how to resume*, the standing
traps you must not relearn, and the owner decisions that block specific phases.

**As of 2026-08-14 · HEAD `07d32d5` · working tree clean · `make verify` exit 0 from a clean clone.**

---

## 1. Read order for a new session

1. `CLAUDE.md` — the contract (Laws L1–L14, §9b tri-boundary, §13 verify bar).
2. `HANDOFF.md` — status-at-a-glance table + the standalone traps.
3. This file — remaining phases + resume procedure.
4. `docs/PLAN-DESKTOP.md` — per-phase checklist with the exact gate command for each box.
5. `docs/DECISIONS.md` — ADR-0001..0015; every deviation from spec is here.
6. `docs/AUDIT-PHASE8.md`, `docs/METRICS.md` — the truth audit + the three numbers.

**User is a non-coder** — plain English, copy-paste commands, verify by running the real app.
**No subagents / inline work** (user preference). **Check in after each feature**, flawless bar.

---

## 2. What is DONE (don't redo)

| Phase | State | Where the evidence lives |
|---|---|---|
| 8 Truth Audit | ✅ | `docs/AUDIT-PHASE8.md` — 3 honesty defects found+fixed |
| 9 Desktop Shell | ✅ core | stdio JSON-RPC (no TCP), Rust supervisor, generated tri-boundary types + drift gate, 5 views on typed bindings, **Next.js `packages/web` deleted** (ADR-0014) |
| 10 Sandboxing w/o Docker | ✅ macOS T2 | `SeatbeltSandbox` (ADR-0015); escape suite **27/27**, egress **0**, tier→bundle→API→UI |
| Perf | ✅ | `PersistentWorker` — pyfix **118→20 s (5.9×)** |

**Architecture now:** Python engine (the nine stages + determinism moat — the validated core;
kept in Python by ADR-0011, user-confirmed) · Rust host (`packages/desktop/src-tauri`: supervisor,
IPC, framing, lifecycle) · TypeScript webview UI (generated bindings only). The CLI and the
desktop app share the identical engine and produce byte-identical bundles (parity gate).

---

## 3. Open stragglers in completed phases (do these opportunistically)

- **Phase 9:** desktop Playwright/WebDriver E2E suite (`pnpm --filter @tempest/desktop test:e2e`
  is wired, the suite is unwritten); clean-VM launch test (needs a VM this Mac lacks).
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

### Phase 12 — Distribution: Signing, Notarization, MDM
- macOS Developer ID + hardened runtime + notarization + stapling, universal binary; Windows EV
  cert + WiX MSI; Linux AppImage/deb/rpm; Tauri signed-manifest auto-update w/ staged rollout +
  rollback + enterprise version pin; SBOM per release.
- **[ASK ME] owner blockers (purchases only the owner can make):** Apple Developer ID
  certificate; Windows EV code-signing certificate (or Azure Trusted Signing). Flag these first.
- *Gate:* clean-VM installs on macOS/Win/Ubuntu with zero warnings; N-1→N update + rollback;
  paste `spctl`/`signtool` output.

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

**Recommended order from here:** 11 (no blocker, high user value) → 17 (no blocker, protects the
brand) → 13 → then 12/14/15/16 as the owner clears their [ASK ME] purchases → 18 last.

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
12. **GitHub Actions raw logs need repo-admin auth** — an outside agent cannot read them, and the
    web view truncates large steps. The `python` job therefore tees pytest output and appends the
    tail to `$GITHUB_STEP_SUMMARY` on failure, which IS readable from the public checks API
    (`GET /repos/{owner}/{repo}/commits/{sha}/check-runs` → `output.summary`). Keep that step.
13. **Pushing needs the owner.** The CLI has no stored GitHub credential (the repo is published
    and pushed through GitHub Desktop). Commit locally, then ask the owner to click *Push origin*.
    Remote: `https://github.com/Prithvi-Web/Tempest-AI.git`.

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

1. **Git history slim (pre-publish):** the repo history still carries ~1.6 GB of old cargo build
   blobs (`.git` ≈ 536 MB). Blocked this session by the auto-mode permission classifier. Mirror
   backup is safe at `Desktop/Claude Code/.tempest-backup-pre-history-slim.git`. To do it (owner
   or an interactive session): `git filter-repo --force --invert-paths --path
   apps/desktop/src-tauri/target/` then `git gc --prune=now --aggressive`. **Publishing works
   without it** (largest blob 57 MB < GitHub's 100 MB limit) — it's just bulky.
2. **GitHub Desktop publish** — still pending; unlocks the Phase 6 live-PR gate
   (`tempest-selftest.yml`).
3. **External security review** of the T2 profile + escape corpus + sync boundary (ADR-0015,
   prompt §10) — engagement + budget. Before GA.
4. **Phase 12:** Apple Developer ID + Windows EV code-signing certificates (purchases).
5. **Phase 14:** Okta + Entra developer tenants.
6. **Phase 16:** compliance-platform subscription + pen-test budget.

---

## 8. The three numbers (report every status update — `docs/METRICS.md`)

1. **Proof rate** — fixture 100%; **real-world still UNMEASURED** (needs the live-PR gate +
   design partners). Below 60% on real code, engine work outranks enterprise features.
2. **False divergence rate** — effectively 0 (3× fresh-pair confirmation; preserved through the
   perf rework).
3. **Time-to-first-divergence** — not yet instrumented; it's the Phase 18 activation metric.
