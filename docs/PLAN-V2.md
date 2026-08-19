# Tempest AI v2 — Phase Plan 19–32 (master prompt v2.0.0 §9, normative)

> Each phase ends with executable gates. **Paste real output; claimed-passing is failing.**
> The per-phase loop is HANDOFF-NEXT §5 — unchanged, it produced 33 green ADRs. Stop after
> every phase for owner review; rebuild and reinstall the app each phase. No subagents.
>
> **Scope:** 21 proof-native features (`docs/FEATURES-V2.md`) + 14 platform foundations adopted
> from LibreChat (`docs/PLATFORM-V2.md`). Laws: `CLAUDE.md` L1–L26. Threats:
> `docs/THREAT-MODEL-V2.md`. Craft: `docs/CRAFT.md` + `docs/POLISH.md`. Attribution:
> `THIRD_PARTY_LICENSES.md`.

## Sequencing rules (violating these changes what product you are building)

1. **Phases 21 and 22 are the product.** If they slip, cut Group D or defer Phase 28 — **never
   cut them.**
2. **Never cut Phase 30 or 31.** A slow, unpolished world-class idea is not world-class.
3. **Platform features (P\*) never precede the proof feature they serve.** Building conversation
   branching before the Verdict Loop gives you a chat app. Building it after gives you a
   behavioral decision tree. *Same code, completely different product.*

> **None of the `tempest.dev.*` v2 gate modules exist yet.** As of 2026-08-18 `tempest/dev/`
> contains exactly: `bench`, `bench_guard`, `corpus_check`, `egress_check`, `escape_suite`,
> `orphan_check`, `parity`, `real_world`, `redaction_check`, `roundtrip`, `soak`. Every other
> command below is **the gate to be built with its phase**, not something runnable today.
> Writing the benchmark is part of the phase; a gate that has never run is a claim, not a fact
> (trap 37 / the ADR-0021 rehearsal lesson).

Every phase inherits these standing gates on top of its own:

```bash
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify     # all v1+desktop gates, incl. E2E
make verify-linux-denominator
uv run python -m tempest.dev.parity --cli-vs-desktop
uv run python -m tempest.dev.orphan_check              # app installed to /Applications
```

---

## Phase 19 — v1 re-audit + v2 foundations + P1, P11

- [ ] Re-run the Phase 8 audit legs on the current tree; paste output.
- [ ] **Agent Tool Protocol = fourth contract boundary** (ADR-0035): Rust trait +
      `schemars`-derived JSON Schema → generated TS bindings + model-facing tool defs;
      `make gen-contracts` + drift gate extended to boundary D.
- [ ] **Shadow-worktree manager** (L19, ADR-0036) + **journal/undo** (L20).
- [ ] **Model layer** (L18, ADR-0037): keys in OS keychain; llama.cpp local runner; streaming
      with real upstream cancellation; graceful offline (L23).
- [ ] **P1 multi-provider abstraction** — 12+ providers; adapter layer only, generated from
      boundary D; adding a provider must not touch feature code.
- [ ] **P11 cost meter** (L21): live token/dollar per task/session/day; **hard caps enforced at
      the router, not the UI**; pre-flight estimate above a user-set threshold.
- [ ] **Perf budgets in CI from day one** (L22).
- [ ] `THIRD_PARTY_LICENSES.md` wired into `license_check`.

**Exit gate:**
```bash
make gen-contracts && git diff --exit-code                    # FOUR boundaries green
python -m tempest.dev.provider_matrix --min-providers 12
python -m tempest.dev.license_check --third-party-notices
python -m tempest.dev.perf_suite --enforce-budgets
# undo restores any state (property test over randomized agent action sequences)
# cost meter accurate to ±2% against provider-reported usage
```

## Phase 20 — Editor surface

- [ ] CodeMirror 6 editor surface (ADR-0034 — Monaco measured out: 8.1× larger minified).
- [ ] LSP client multiplexer in Rust; language servers never live in the webview.
- [ ] **F11** inline completion + next-edit prediction, local-model capable, behavioral risk
      indicator wired to measured divergence/proof-rate data.

**Exit gate:** all §5 editor budgets met (open file p50 40 ms; keystroke→render p50 8 ms;
completion p50 120 ms / p95 300 ms); input-storm test (15 keys/s × 60 s, zero drops).

## Phase 21 — Agent orchestrator + F1, F2, F3 + P2 ⭐ THE CORE

- [ ] Agent Orchestrator in Rust: turn loop, tool dispatch, budget enforcement, model router.
- [ ] **F1** Verdict Loop; **F2** Intent Contracts; **F3** Proof-Guided Repair.
- [ ] **P2 resumable/durable turns** — durable turn journal in SQLite, **proof stage
      checkpointed**, resumable from any interruption.
- [ ] L16 enforced by construction: DB constraint + adversarial forge test.

**Exit gate:**
```bash
python -m tempest.dev.agent_bench  --tasks 50 --require-verdict-coverage 1.0
python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0
python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats
python -m tempest.dev.resume_test  --kill-mid-proof --sleep-mid-stream
```

## Phase 22 — Index service + F13; F4

- [ ] Index Service in Rust: vector (sqlite-vec/LanceDB) + structural (tree-sitter call graph,
      incremental) + **execution index** over the observation store.
- [ ] **F13** execution-grounded chat & search; **F4** behavioral spec synthesis.

**Exit gate:**
```bash
python -m tempest.dev.retrieval_bench --questions 40 --require-citations
# incl. the 15 source-impossible questions; retrieval p95 < 400 ms on 500k LOC
```

## Phase 23 — Coding surface + MCP both directions + P3, P4, P5, P9

- [ ] **F12** composer with proof preview; **F14** sandboxed agent terminal; **F15** project
      memory & behavioral rules; **F16** MCP client + server.
- [ ] **P3 Proof Skills** (declared contracts, mutation floors, forbidden divergence classes —
      engine-enforced); **P4 subagents** (own shadow worktree, own verdict);
      **P5 MCP client** production-grade; **P9 web search** with retrieved content treated as
      hostile input.

**Exit gate:** Claude Code ↔ Tempest MCP demo recorded (refusal on `DIVERGENT`);
`python -m tempest.dev.redteam --injection` green **including retrieved-page and MCP-response
payloads**; 8 nested subagents with independent verdicts and correct budget accounting; a Proof
Skill's floor holds when the model is told to ignore it.

## Phase 24 — Self-validation + trace ingestion

- [ ] **F9** adversarial self-validation; `WEAK_EVIDENCE` verdict added across all four
      languages (L2 vocabulary ADR required — see QUESTIONS QV4); **F10** cassette-to-suite.

**Exit gate:**
```bash
python -m tempest.dev.mutation_bench --report-scores   # score on every equivalence verdict
# Keploy + OTel import working; scrubber zero-leakage (planted secrets, trap 19)
```

## Phase 25 — De-slop, dead code, migration

- [ ] **F7** de-slop agent; **F8** proven dead-code elimination; **F6** migration agent +
      published canonical value protocol spec.

**Exit gate:**
```bash
python -m tempest.dev.deadcode_trap  --expect-refusals 20   # zero false deletions
python -m tempest.dev.migration_bench --ports 20 --bad-ports 5
```

## Phase 26 — Ambient watch + agent fleet

- [ ] **F18** ambient regression watch (builds on ADR-0029/0030 watch mode); **F17** fleet.

**Exit gate:** gutter marker <5 s p50 / <15 s p95; input-latency delta <5 ms; 8 agents within
budget on a 4-core profile; ranking reproducible from bundles alone (no model in the path, L17).

## Phase 27 — F5, F19, F20, F21

- [ ] **F5** semantic merge; **F19** time-travel debugger; **F20** team KB; **F21** model arena
      (riding P1's provider breadth).

**Exit gate:** zero confidently-wrong merges on the 30-conflict corpus; 10k-step scrub <500 ms;
KB delta on agent_bench reported (zero → cut F20 and say so); router beats fixed selection over
100 tasks on success-per-dollar.

## Phase 28 — Platform completion: P6, P7, P8, P12, P13

- [ ] **P6** run branching — fork an agent run at any turn, **compare branches by verdict**.
- [ ] **P7** Proof Profiles (model, budget, tolerance, mutation floor, sandbox tier; per
      directory, hot-reload, precedence shown).
- [ ] **P8** behavioral artifacts — call graphs, effect timelines, divergence tables, coverage
      maps, minimized-input trees, rendered inline and interactive.
- [ ] **P12** export session **with proof bundles attached**; **P13** narrowed multimodal input.

**Exit gate:**
```bash
python -m tempest.dev.session_roundtrip --export-import --require-runnable-repros
# fork/compare-by-verdict working; artifacts render <100 ms and pass the escape suite;
# screenshot-of-stack-trace → correct file/line; EXIF + geolocation stripped (test-verified)
```

## Phase 29 — Enterprise + reach: P10, P14

- [ ] **P10** OAuth2 / LDAP / email — gating **team features only**.
- [ ] **P14** i18n structure + English plus four locales; verdict vocabulary and `reason_code`
      explanations translatable.

**Exit gate:**
```bash
python -m tempest.dev.i18n_check --no-hardcoded-strings --pseudo-locale --rtl
# LDAP against a real directory; AIRPLANE MODE = full local functionality, zero auth prompts
```

## Phase 30 — Performance campaign  *(never cut)*

- [ ] Every §5 budget met on the 4-core/16GB profile against a 500k-LOC repo.
- [ ] CI perf gate on every PR; public perf dashboard.

**Exit gate:** `python -m tempest.dev.perf_suite --enforce-budgets` green; dashboard live.

## Phase 31 — Craft campaign (§6, L26)  *(never cut)*

- [ ] `docs/POLISH.md` **150 items** verified on all three OSes with screenshots.
- [ ] Visual regression across every view × 2 themes × 3 viewports × 2 densities.
- [ ] **Motion-interrupt suite**: every animation interrupted at 50%, clean settle.
- [ ] **CLS = 0** measured on every view.
- [ ] a11y audit with **VoiceOver and NVDA recordings attached**.
- [ ] **The screenshot test** — any view legible and self-explanatory to a first-time viewer.

**Exit gate:**
```bash
pnpm test:visual-regression --themes 2 --viewports 3 --densities 2
pnpm test:motion-interrupt
python -m tempest.dev.a11y_audit --wcag 2.2 --level AA
```

## Phase 32 — Hardening + GA

- [ ] Red-team suite green: 50+ injection, 20+ exfiltration, 15+ gate-subversion.
- [ ] External security review before GA.
- [ ] 30-day dogfood; Tempest-on-Tempest proof rate published in the README (L24).

**Exit gate:**
```bash
python -m tempest.dev.redteam --injection --exfiltration --gate-subversion
python -m tempest.dev.dogfood --prove-own-pr
```

---

## The performance budgets (master prompt §5 — L22, CI gates from Phase 19)

Measured on a 4-core / 16GB laptop against a 500k-LOC repo. **CI fails on >10% regression.**

| Operation | p50 | p95 |
|---|---|---|
| Cold launch → interactive | 800 ms | 1.5 s |
| Open file (10k lines) | 40 ms | 100 ms |
| Keystroke → render | 8 ms | 16 ms |
| Inline completion (F11) | 120 ms | 300 ms |
| Codebase search (F13) | 150 ms | 400 ms |
| Agent first token | 400 ms | 1 s |
| Incremental proof, 1 function (F18) | 5 s | 15 s |
| Full proof, 10-file PR | 25 s | 60 s |
| Diff render, 500 files (F12) | 150 ms | 300 ms |
| Debugger scrub step (F19) | 100 ms | 500 ms |
| Idle RAM | 300 MB | 450 MB |
| RAM, 8 agents (F17) | 2 GB | 3 GB |
| Idle CPU | <0.5% | <1% |

**Mandatory techniques, not optional:** virtualize every list and diff over 50 rows; incremental
parse and index only (never full re-index); content-hash caching of harnesses, cassettes, and
adapters; all heavy work off the UI thread; React 19 transitions with `useDeferredValue` on
every filter; streaming with backpressure; speculative prefetch of likely-next views; SQLite in
WAL with prepared statements and covering indices for every hot query.

---

## `make verify-v2` (full definition-of-done, accumulated by Phase 32)

```bash
make verify-desktop                                # all v1 + desktop gates
make gen-contracts && git diff --exit-code         # 4 boundaries
cargo clippy --workspace -- -D warnings && cargo test --workspace
pnpm -r typecheck && pnpm -r test && pnpm test:e2e
python -m tempest.dev.agent_bench --tasks 50 --require-verdict-coverage 1.0
python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0
python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats
python -m tempest.dev.retrieval_bench --questions 40 --require-citations
python -m tempest.dev.mutation_bench --report-scores
python -m tempest.dev.deadcode_trap --expect-refusals 20
python -m tempest.dev.migration_bench --ports 20 --bad-ports 5
python -m tempest.dev.redteam --injection --exfiltration --gate-subversion
python -m tempest.dev.perf_suite --enforce-budgets
python -m tempest.dev.a11y_audit --wcag 2.2 --level AA
pnpm test:visual-regression --themes 2 --viewports 3 --densities 2
pnpm test:motion-interrupt                          # every animation interruptible at 50%
python -m tempest.dev.provider_matrix --min-providers 12
python -m tempest.dev.resume_test --kill-mid-proof --sleep-mid-stream
python -m tempest.dev.session_roundtrip --export-import --require-runnable-repros
python -m tempest.dev.i18n_check --no-hardcoded-strings --pseudo-locale --rtl
python -m tempest.dev.license_check --third-party-notices   # MIT attribution present
python -m tempest.dev.dogfood --prove-own-pr        # L24
```

**You may not say "done", "working", "complete", or "zero errors" without pasting the actual
output.**

---

## The v2 failure modes to re-read before every phase (master prompt §11)

1. **Becoming a wrapper.** Every feature answers: *what makes this impossible for Cursor to ship
   next month?*
2. **The agent learning to cheat the gate.** Contract-weakening / test-deletion /
   target-unreachability adversarial tests are mandatory and permanent.
3. **Model text leaking into evidence fields** (L17).
4. **Perf death by a thousand features** — budgets enforced from Phase 19, not Phase 30.
5. **Breadth over depth** — if 21/22 aren't exceptional, stop and fix before 23.
6. **Prompt injection via repo content** — every file, README, MCP response, and retrieved page
   is hostile.
7. **Proof latency making the agent unusable** — incremental proof, caching, and speculative
   proving are load-bearing.
8. **Softening `UNPROVEN` to make demos look good** — never; it is the only thing we have that
   they don't.
9. ⚠️ **Becoming a chat app with a proof feature** — the specific risk introduced by the
   LibreChat adoption. If the chat panel becomes the primary surface, or a single adopted
   feature ships without proof-native wiring, we have drifted. Re-read L25.
10. **Adopting code without attribution** — `THIRD_PARTY_LICENSES.md` is updated at the moment
    of adoption; `license_check` gates it. Missing notices surface during enterprise
    procurement diligence, which is the worst possible moment.
11. **Apple-caliber becoming Apple-imitation** — adopt the principles (`docs/CRAFT.md`), express
    them in Tempest's own identity. Never clone chrome, icons, or trade dress.
