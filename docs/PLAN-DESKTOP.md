# Tempest AI — Desktop & Enterprise Phase Plan (Phases 9–18)

> Source: the Phase 8+ master prompt (desktop application & enterprise production readiness).
> Same rules as `docs/PLAN.md`: a phase is complete **only** when its gate commands ran and their
> real output is pasted; claimed-passing is failing. Every deviation → ADR in `docs/DECISIONS.md`.
> Phase 8 (Truth Audit) is complete — see `docs/AUDIT-PHASE8.md`. **Phase 9 does not begin until
> the user has reviewed that audit.**

**Language optimization policy (owner directive, 2026-08-13):** pick the best language per part —
**Rust** for the desktop host and any performance-critical hot path (process supervision, audit
log, license verification, sandbox construction; candidates for later Rust ports behind
property-tested parity gates: canonical-bytes encoding, bundle hashing, ledger diff). **Python**
stays the engine of record — the nine stages and the determinism moat are validated there
(30/30×20); rewriting them now would re-open proven ground. **TypeScript** owns the webview UI
only. Any hot-path Rust port must ship with a differential test proving byte-identical output
against the Python implementation before it replaces it. (ADR-0011.)

**Starting point (honest):** `apps/desktop` already contains a working Tauri v2 shell — frozen
PyInstaller engine sidecar (23 MB, ~2 s to healthy), five views, live-verified in-app prove runs,
kill-on-exit watchdog. It is a v1-era bridge: it talks HTTP on 127.0.0.1 and has no generated
tri-boundary contract, no crash-restart supervision, no process-group ownership, and zero Rust
tests. Phase 9 evolves this shell to the §3 architecture; it does not start from nothing.

---

## Phase 9 — Desktop Shell Migration

- [x] Restructure `apps/desktop` → `packages/desktop` (aa65156; history preserved via git-mv)
- [x] Boundary A: JSON-RPC 2.0 over stdio with Content-Length framing (`tempest-server --stdio`,
      `tempest_api.stdiorpc`; dispatch table derived from the live routes). Verified on the
      installed app: `lsof` shows **zero listening TCP sockets** on any tempest process
- [x] Boundary A types: openapi.json → domain-schema.json (int32-pinned) → `cargo typify` →
      committed `src-tauri/src/generated/domain.rs` with `specta::Type` derives
- [x] Boundary B: `tauri-specta` → committed `src/generated/bindings.ts` (8 typed commands +
      typed `SidecarStateEvent`); handwritten-`invoke` ban enforced as a `verify-desktop` grep
      (same mechanism as the S-A-F-E grep; a dedicated ESLint setup remains a nice-to-have)
- [x] Boundary C: the TS domain types ship inside generated `bindings.ts` (same schema through
      the same pipeline); `shared-schema/types.ts` remains the committed API-level artifact —
      no third generator needed (recorded in ADR-0014)
- [x] `make gen-contracts` + widened `contract-check` (schema + both desktop generated dirs) in
      Makefile and CI; regeneration proven deterministic (second run diffs empty)
- [x] Sidecar supervision: owned child in its own process group, rpc.ping health loop, crash
      restart with capped backoff, rpc.shutdown→SIGTERM→SIGKILL group sweep; typed lifecycle
      events to the UI
- [x] Five views on generated bindings; `packages/web` deleted (ADR-0014); dead-package grep
      clean outside historical docs
- [x] Round-trip gate: **10000/10000** payloads byte-stable Python→Rust→TS (Pydantic + serde +
      ajv legs, all against the one schema)
- [x] Rust suite: 10 tests (framing codec, enum-discipline exhaustive matches, supervisor
      crash-restart/timeout-correlation/no-orphan-shutdown against a real protocol peer)
- [ ] Playwright/WebDriver E2E against the real app (`pnpm --filter @tempest/desktop test:e2e`
      is wired but the suite is not written yet)
- [ ] Clean-VM validation: needs VMs this machine does not have — CI/manual follow-up; the
      local equivalents (frozen-sidecar parity, orphan gate, no-toolchain .app) are green

*Gate — real output, 2026-08-14:*
```
$ make verify-contract                        → git diff --exit-code … (zero drift)   exit 0
$ cargo clippy --workspace --all-targets -- -D warnings   → clean
$ cargo test -q --workspace                   → 10 passed, 0 failed
$ pnpm --filter @tempest/desktop typecheck && pnpm --filter @tempest/desktop build → ✓ built
$ uv run python -m tempest.dev.roundtrip --py-rust-ts --iterations 10000
roundtrip py→rust→ts: 10000/10000 payloads byte-stable across all three languages
$ uv run python -m tempest.dev.parity --cli-vs-desktop
cli-vs-desktop parity: byte-identical bundles (targets.json, 1 repro script(s),
manifest minus created_at) — the shipped sidecar and the CLI produce the same evidence
  (this gate first CAUGHT a real bug: Hypothesis derandomize is runtime-digest-seeded, so the
   frozen binary generated different inputs than the venv CLI — fixed with an explicit @seed)
$ uv run python -m tempest.dev.orphan_check
orphan check: zero sidecar processes survive SIGKILL of the host (cleared in 2.7s, bar 15s)
```

## Phase 10 — Sandboxing Without Docker ⚠️ (the phase that can kill the product)

- [ ] Tiered isolation, selected at runtime, tier always recorded in the bundle:
      T1 Docker/Colima/Podman if present · T2 macOS `sandbox-exec` (SHIPPED) / Windows
      AppContainer+Job Object (CI) / Linux bubblewrap+seccomp-bpf+userns+cgroups v2 (CI) ·
      T3 separate user + rlimits (reported in the UI as reduced assurance, limitation named)
- [x] **macOS T2 lands** (`SeatbeltSandbox`, ADR-0015): `select_sandbox` ladder T1→T2→UNPROVEN;
      this machine now proves untrusted user repos with no Docker (was SANDBOX_UNAVAILABLE)
- [x] Enforced on T2: network denied outright, home denied except the repo worktree +
      interpreter, writes only to the scratch mount, children inherit the sandbox, CPU/wall
      limits; fork bombs bounded by timeout + pgroup-SIGKILL (macOS NPROC is per-UID)
- [x] Escape suite: 27 adversarial payloads (6 egress, 6 secret/home read, 5 persistence, 6
      process/privilege, fork bomb, 2 controls) through the real `sandbox.popen` path —
      **T2 contains 27/27**, T3 leaks 18/27; wired into `make verify` + an integration test
- [x] Egress monitor (L10): **0 outbound connections** on T2 (`tempest.dev.egress_check`)
- [x] Tier recorded in every bundle (manifest v2) → API (runs table, Alembic 0002) → CLI report
      + desktop UI chip; reduced assurance flagged. Never silently degraded (§3)
- [x] T2 perf delta measured: **1.16×** the no-wrapper baseline (~5 ms/spawn), well under the 3× bar
- [x] External security review scheduled → ADR-0015 ([ASK ME]: engagement + budget)
- [ ] Linux (bubblewrap) + Windows (AppContainer) T2 backends, and the true T3 (separate-user):
      CI/other-OS follow-ups — this host is macOS-only
- [ ] netns deny-all packet-capture leg (a Linux construct) — CI

*Gate — real output, 2026-08-14 (macOS T2):*
```
$ python -m tempest.dev.escape_suite --tier T2
27/27 contained on tier T2
escape suite: every hostile payload contained.
$ python -m tempest.dev.escape_suite --tier T3      # baseline: the tier distinction is real
9/27 contained on tier T3        (network, home reads, /tmp writes, parent-kill all leak)
$ python -m tempest.dev.egress_check --expect-zero
outbound connections that succeeded: 0 (required: 0)
egress check: zero outbound connections from sandboxed runner code (L10).
```
*Machine constraint (stated, not hidden): this dev machine has no Docker and only macOS. The T1
Docker delta and the Linux/Windows escape legs run in CI runners; the matrix marks each
PENDING(CI) rather than skipping it silently.*

## Phase 11 — Local-First Data & Performance

- [ ] SQLite (WAL) primary store + migration framework + forward+backward migration test
      (older app refuses newer DB cleanly, never corrupts)
- [ ] Content-addressed bundle store with GC + user-controlled size budget
- [ ] FTS over divergences; `.tempest` portable import/export
- [ ] Targets asserted in CI on a 4-core profile: cold launch <1.5 s; 10k-run list first paint
      <200 ms @60 fps; 5 MB observation detail <400 ms; idle <250 MB RAM / <1% CPU
- [ ] L11: cancel stops everything <2 s; battery/thermal pause engages
- [ ] 8-hour soak: memory growth <10%

*Gate:* `make bench && python -m tempest.dev.bench_guard --max-regression 15` (fails the build)

## Phase 12 — Distribution: Signing, Notarization, MDM

- [ ] macOS Developer ID + hardened runtime + notarization + stapling, universal binary,
      `.dmg`+`.pkg` — verified `spctl -a -vvv` and `codesign --verify --deep --strict`
- [ ] Windows EV cert (or Azure Trusted Signing), WiX MSI silent-install, SmartScreen plan
- [ ] Linux AppImage/`.deb`/`.rpm`, signed repos
- [ ] MDM: Intune + Jamf docs, pre-seeded config profile, complete uninstall
- [ ] Auto-update: signed manifests, staged rollout, mandatory-update flag, rollback,
      enterprise version pinning respected
- [ ] SBOM (CycloneDX) per release; reproducible builds where feasible

*Gate:* clean-VM installs (macOS latest+latest-1, Win 11, Ubuntu LTS) with zero warnings;
N-1→N auto-update succeeds and rolls back on forced failure; paste `spctl`/`signtool` output.
*Owner dependency: Apple Developer ID and Windows EV certificates are purchases only the owner
can make — flagged as [ASK ME] items when Phase 12 starts.*

## Phase 13 — Team Sync Server (optional, self-hosted first)

- [ ] Customer-run container: Postgres + object storage; Helm chart + docker-compose; signed image
- [ ] Sync: content-addressed, resumable, idempotent, delta-only; bundles immutable by design
- [ ] Redaction at the boundary: source snippets stripped unless org policy enables sharing
      (default OFF) — proven by test
- [ ] Offline queue with durable retry; app never blocks on an unreachable server

*Gate:* kill network mid-sync → clean resume, no duplication, no loss; push=pull byte-identical
property test; redaction test proves no source text crosses with default policy.

## Phase 14 — Enterprise Identity, Policy & Audit

- [ ] OIDC + SAML 2.0 (Okta, Entra, Google Workspace); system browser + PKCE loopback only
- [ ] SCIM 2.0 provisioning/deprovisioning; offline grace configurable
- [ ] RBAC enforced server-side; org policy pushed and enforced locally (min sandbox tier,
      verdict thresholds, telemetry, source-sharing, allowed repos)
- [ ] Hash-chained append-only audit log, local + server; JSON + CEF export; tamper-evidence
      verified by a mutate-and-detect test

*Gate:* end-to-end SSO against real Okta + Entra dev tenants; SCIM deprovision revokes access;
audit-chain tamper test passes. Paste output. *Owner dependency: tenant signups are [ASK ME].*

## Phase 15 — Air-Gapped Deployment & Licensing

- [ ] Zero mandatory egress; configured PyPI/npm mirrors + fully vendored offline cache
- [ ] Ed25519 offline license files (org, seats, expiry, features); clock-tamper grace window,
      never a hard brick
- [ ] Offline update bundles IT can stage; air-gap install docs with a customer-runnable checklist

*Gate:* full install + complete prove-run on a VM with **no network interface attached** — recorded.

## Phase 16 — SOC 2 Type II Readiness

- [ ] Compliance platform picked and wired (Vanta/Drata/Secureframe) — [ASK ME]: subscription
- [ ] Control set written; in-repo enforcement (branch protection, review, signed commits,
      dependency/secret scanning, SAST, license scanning)
- [ ] Third-party pen test scoped to app, sandbox, sync server — [ASK ME]: budget
- [ ] Trust Center page: architecture, data-flow, subprocessors, L10 egress results, pen-test letter
- [ ] DPA, CAIQ/SIG-lite answers, MSA, SLA drafted

*Gate:* platform shows all controls with automated evidence; criticals/highs remediated + retested.

## Phase 17 — Reliability, Observability & Support Surface

- [ ] Opt-in crash reporting, provably source-free (planted-secret fixture test)
- [ ] Opt-in aggregate telemetry (proof rate, tier distribution, phase durations, UNPROVEN
      reason distribution), org-disableable
- [ ] Redacted diagnostic bundle export the user can inspect before sending
- [ ] Structured logging + rotation + in-app log viewer; health self-check command
- [ ] Support runbook, escalation path, known-issues list

*Gate:* redaction suite with planted secrets — zero leakage; `docs/PRIVACY.md` documents the
diagnostic bundle line-by-line.

## Phase 18 — GA Readiness

- [ ] First-run onboarding: repo detection, bundled demo prove, real divergence <90 s from install
      (time-to-first-divergence instrumented — the activation metric)
- [ ] Docs: install, air-gap, MDM, CI, `tempest.toml`, ReasonCode reference w/ remediations,
      sandbox tiers
- [ ] WCAG AA audit, full keyboard nav, VoiceOver + NVDA, `prefers-reduced-motion`, 200% zoom
- [ ] Localization scaffolding (extract strings, ship English)
- [ ] Pricing/packaging wired to license features; seat management UI
- [ ] Release process documented, rehearsed, rollback-tested

*Gate:* five external design partners install unaided from the signed artifact and reach a real
divergence on their own codebase; report proof rate + time-to-first-divergence for each.

---

## `make verify-desktop` (grows with the phases; full §7 list is the desktop done bar)

```
make verify                                   # all v1 gates still green
make gen:contracts && git diff --exit-code packages/desktop/src/generated packages/desktop/src-tauri/src/generated
cargo clippy --all-targets -- -D warnings
cargo test --workspace
pnpm --filter desktop typecheck && pnpm --filter desktop test
pnpm --filter desktop test:e2e
python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
python -m tempest.dev.escape_suite --all-tiers --all-os
python -m tempest.dev.egress_check --expect-zero
python -m tempest.dev.redaction_check --planted-secrets
python -m tempest.dev.roundtrip --py-rust-ts --iterations 10000
python -m tempest.dev.parity --cli-vs-desktop
make bench && python -m tempest.dev.bench_guard --max-regression 15
make sign:verify
```

## The three numbers (reported in every status update)

1. **Proof rate** — % of changed symbols actually exercised to a verdict. Below 60% on real code:
   engine work outranks every enterprise feature. Current measurement: `docs/METRICS.md`.
2. **False divergence rate** — must be effectively zero; more important than proof rate.
3. **Time-to-first-divergence** — install → real finding on the user's own code; target <90 s.
