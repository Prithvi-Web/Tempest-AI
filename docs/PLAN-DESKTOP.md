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

- [ ] Restructure `apps/desktop` → `packages/desktop` (workspace consistency with the plan text)
- [ ] Boundary A: replace HTTP-on-127.0.0.1 with JSON-RPC 2.0 over stdio + length-prefixed
      framing to the sidecar (no listening TCP port anywhere in local mode)
- [ ] Boundary A types: Pydantic `model_json_schema()` → `typify` → committed
      `src-tauri/src/generated/domain.rs`
- [ ] Boundary B: `tauri-specta` → committed `src/generated/bindings.ts`; ESLint ban on
      handwritten `invoke()`
- [ ] Boundary C: same JSON Schema → `json-schema-to-typescript` → committed
      `src/generated/domain.ts`
- [ ] `make gen:contracts` + CI job `contract-check` extended to the desktop generated dirs
- [ ] Sidecar supervision: health checks, crash restart with backoff, process-group/job-object
      ownership (orphan-free under SIGKILL of the host)
- [ ] Port the five views to the desktop SPA; delete `packages/web` (Next.js) — removal ADR;
      `git grep next` in package manifests returns nothing
- [ ] Round-trip property test: Python → Rust → TS → structural equality, in CI
- [ ] Rust host test suite (currently zero tests) incl. a process-table assertion after SIGKILL
- [ ] Clean-VM validation: app launches with no Python/Node/Docker installed; full prove-run
      completes; bundle byte-identical to the CLI's for the same commit

*Gate:*
```
make gen:contracts && git diff --exit-code packages/desktop/src/generated packages/desktop/src-tauri/src/generated
cargo clippy --all-targets -- -D warnings && cargo test --workspace
pnpm --filter desktop typecheck && pnpm --filter desktop test
python -m tempest.dev.roundtrip --py-rust-ts --iterations 10000
python -m tempest.dev.parity --cli-vs-desktop
# SIGKILL the app mid-run → process-table assertion: zero orphaned sidecars/runners
```

## Phase 10 — Sandboxing Without Docker ⚠️ (the phase that can kill the product)

- [ ] Tiered isolation, selected at runtime, tier always recorded in the bundle:
      T1 Docker/Colima/Podman if present · T2 macOS `sandbox-exec`+App Sandbox / Windows
      AppContainer+Job Object / Linux bubblewrap+seccomp-bpf+userns+cgroups v2 ·
      T3 separate user + rlimits (reported in the UI as reduced assurance, limitation named)
- [ ] Every tier enforces: no network, read-only FS except one scratch mount, no `~` access
      outside the target repo, CPU/memory/wall limits, no unconstrained children
- [ ] Escape test suite: 25+ adversarial payloads (egress, traversal, fork bombs, privilege
      escalation, parent-kill, `~/.ssh` read, Tempest-DB read, persistence) × 3 OSes × all tiers
- [ ] Egress monitor (L10) wired into CI; zero outbound packets from runner processes
- [ ] T1-vs-T2 performance delta documented (>3× slower is a surfaced finding, not hidden)
- [ ] External security review scheduled → noted in `docs/DECISIONS.md`

*Gate:*
```
python -m tempest.dev.escape_suite --all-tiers --all-os   # paste the full matrix
python -m tempest.dev.egress_check --expect-zero
```
*Machine constraint (stated, not hidden): this dev machine has no Docker and only macOS — the
cross-OS legs run in CI runners; the audit records which legs ran where.*

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
