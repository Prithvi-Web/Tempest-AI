# Tempest AI v2 — Phase Plan 19–30 (master prompt v2.0.0 §9, normative)

> Each phase ends with executable gates. **Paste real output; claimed-passing is failing.**
> The per-phase loop is HANDOFF-NEXT §5 — unchanged, it produced 33 green ADRs. Stop after
> every phase for owner review; rebuild + reinstall the app each phase. No subagents.
>
> **Sequencing rule:** Phases 21 and 22 are the product. If they slip, cut Group D before
> cutting them. Never cut Phase 28 or 29 — an unpolished, slow world-class idea is not
> world-class.
>
> **Feature detail + acceptance criteria:** `docs/FEATURES-V2.md`. Laws: `CLAUDE.md` L1–L24.
> Threats: `docs/THREAT-MODEL-V2.md`. Polish: `docs/POLISH.md`.

> **None of the `tempest.dev.*` v2 gate modules exist yet.** As of 2026-08-18 `tempest/dev/`
> contains exactly: `bench`, `bench_guard`, `corpus_check`, `egress_check`, `escape_suite`,
> `orphan_check`, `parity`, `real_world`, `redaction_check`, `roundtrip`, `soak`. Every
> `agent_bench` / `intent_bench` / `repair_bench` / `retrieval_bench` / `mutation_bench` /
> `deadcode_trap` / `migration_bench` / `redteam` / `perf_suite` / `a11y_audit` / `dogfood`
> command below is **the gate to be built with its phase**, not a command you can run today.
> Writing the benchmark is part of the phase; a gate that has never run is a claim, not a
> fact (trap 37 / the ADR-0021 rehearsal lesson).

Every phase inherits these standing gates on top of its own:

```bash
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify     # all v1+desktop gates, incl. E2E
make verify-linux-denominator
uv run python -m tempest.dev.parity --cli-vs-desktop
uv run python -m tempest.dev.orphan_check              # app installed to /Applications
```

From Phase 19 on, `make verify-v2` accumulates the v2 gates below (each phase adds its own
lines; the full list is §10 of the master prompt and the end of this file).

---

## Phase 19 — v1 re-audit + v2 foundations

- [ ] Re-run the Phase 8 audit legs on the current tree; paste output (v2 on a broken v1 is
      21 features of sand).
- [ ] **Agent Tool Protocol = fourth contract boundary** (ADR-0035): Rust trait +
      `schemars`-derived JSON Schema → generated TS bindings + model-facing tool defs;
      `make gen-contracts` + drift gate extended to boundary D.
- [ ] **Shadow-worktree manager** (L19, ADR-0036): agent writes staged under
      `.tempest/agent/worktrees/`, never the user's tree; acceptance is atomic.
- [ ] **Journal + undo** (L20): every agent-initiated mutation journaled; one-keystroke undo
      for any agent change incl. multi-file edits and terminal side effects.
- [ ] **Model layer** (L18, ADR-0037): BYO keys (Anthropic/OpenAI/Google/OpenAI-compatible)
      in the OS keychain; llama.cpp local-model runner; streaming with real upstream
      cancellation; graceful offline (L23).
- [ ] **Cost meter** (L21): live token/dollar counters per task/session/day; hard caps;
      pre-flight estimate above a user-set threshold.
- [ ] **Perf budgets in CI from day one** (L22): `python -m tempest.dev.perf_suite --enforce-budgets`
      with the §5 table encoded; >10% regression fails.

**Exit gate:**
```bash
make gen-contracts && git diff --exit-code   # FOUR boundaries green
# undo restores any state — property test over randomized agent action sequences
# cost meter accurate to ±2% against provider-reported usage
python -m tempest.dev.perf_suite --enforce-budgets
```

## Phase 20 — Editor surface

- [ ] CodeMirror 6 editor surface in the webview (ADR-0034 — Monaco measured out).
- [ ] LSP client multiplexer in Rust: owns server lifecycles, pushes diagnostics over IPC;
      language servers never live in the webview.
- [ ] **F11** inline completion + next-edit prediction, local-model capable, behavioral risk
      indicator wired to measured divergence/proof-rate data.

**Exit gate:** all §5 editor budgets met (open file p50 40 ms; keystroke→render p50 8 ms;
completion p50 120 ms / p95 300 ms); input-storm test (15 keys/s × 60 s, zero drops).

## Phase 21 — Agent orchestrator + F1, F2, F3 ⭐ THE CORE

- [ ] Agent Orchestrator in Rust: turn loop, tool dispatch, budget enforcement, model router.
- [ ] **F1** Verdict Loop; **F2** Intent Contracts; **F3** Proof-Guided Repair.
- [ ] L16 enforced by construction: DB constraint + adversarial forge test.

**Exit gate:**
```bash
python -m tempest.dev.agent_bench  --tasks 50 --require-verdict-coverage 1.0
python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0
python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats
```

## Phase 22 — Index service + F13; F4

- [ ] Index Service in Rust: vector (sqlite-vec/LanceDB) + structural (tree-sitter call
      graph, incremental) + **execution index** over the observation store.
- [ ] **F13** execution-grounded chat & search; **F4** behavioral spec synthesis.

**Exit gate:**
```bash
python -m tempest.dev.retrieval_bench --questions 40 --require-citations
# incl. the 15 source-impossible questions; retrieval p95 < 400ms on 500k LOC
```

## Phase 23 — Coding surface + MCP both directions

- [ ] **F12** composer with proof preview; **F14** sandboxed agent terminal; **F15** project
      memory & behavioral rules; **F16** MCP client + server.

**Exit gate:** Claude Code ↔ Tempest MCP demo recorded (refusal on `DIVERGENT`);
`python -m tempest.dev.redteam --injection` green; F12/F14 perf gates met.

## Phase 24 — Self-validation + trace ingestion

- [ ] **F9** adversarial self-validation; `WEAK_EVIDENCE` verdict added across all four
      languages (L2 vocabulary ADR required); **F10** cassette-to-suite importers.

**Exit gate:**
```bash
python -m tempest.dev.mutation_bench --report-scores   # score on every equivalence verdict
# Keploy + OTel import working; scrubber zero-leakage (planted secrets, trap 19)
```

## Phase 25 — De-slop, dead code, migration

- [ ] **F7** de-slop agent; **F8** proven dead-code elimination; **F6** migration agent +
      canonical value protocol spec.

**Exit gate:**
```bash
python -m tempest.dev.deadcode_trap  --expect-refusals 20   # zero false deletions
python -m tempest.dev.migration_bench --ports 20 --bad-ports 5
```

## Phase 26 — Ambient watch + agent fleet

- [ ] **F18** ambient regression watch (builds on ADR-0029/0030 watch mode);
      **F17** parallel agent fleet.

**Exit gate:** gutter marker <5 s p50 / <15 s p95; input-latency delta <5 ms; 8 agents
within budget on a 4-core profile; ranking reproducible from bundles alone.

## Phase 27 — F5, F19, F20, F21

- [ ] **F5** semantic merge; **F19** time-travel debugger; **F20** team KB; **F21** model arena.

**Exit gate:** zero confidently-wrong merges on the 30-conflict corpus; 10k-step scrub
<500 ms; KB delta on agent_bench reported (zero → cut F20 and say so); router beats fixed
selection over 100 tasks on success-per-dollar.

---

## The performance budgets (master prompt §5 — L22, CI gates from Phase 19)

Measured on a 4-core / 16GB laptop against a 500k-LOC repo. **CI fails on >10% regression.**
Enforced by `python -m tempest.dev.perf_suite --enforce-budgets`; the existing `make bench` +
`bench_guard --max-regression 15` (Phase 11 envelope) is the v1 ancestor of this gate.

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

**Mandatory techniques, not optional:** virtualize every list and diff over 50 rows;
incremental parse and index only (never full re-index); content-hash caching of harnesses,
cassettes, and adapters; all heavy work off the UI thread; React 19 transitions with
`useDeferredValue` on every filter; streaming with backpressure; speculative prefetch of
likely-next views; SQLite in WAL with prepared statements and covering indices for every hot
query.

---

## Phase 28 — Performance campaign  *(never cut)*

- [ ] Every §5 budget met on the 4-core/16GB profile against a 500k-LOC repo.
- [ ] CI perf gate live on every PR; public perf dashboard.

**Exit gate:** `python -m tempest.dev.perf_suite --enforce-budgets` green; dashboard URL live.

## Phase 29 — Polish campaign  *(never cut)*

- [ ] `docs/POLISH.md` 120 items verified item-by-item on all three OSes with screenshots.
- [ ] Automated visual regression across every view × both themes × three viewports.
- [ ] `python -m tempest.dev.a11y_audit --wcag 2.2 --level AA` green (VoiceOver + NVDA passes).

## Phase 30 — Hardening + GA

- [ ] Red-team suite green: `python -m tempest.dev.redteam --injection --exfiltration --gate-subversion`
      (50+ injection, 20+ exfiltration, 15+ gate-subversion — corpus in THREAT-MODEL-V2).
- [ ] External security review before GA.
- [ ] 30-day dogfood: Tempest proves its own PRs (L24); Tempest-on-Tempest proof rate
      published in the README: `python -m tempest.dev.dogfood --prove-own-pr`.

---

## `make verify-v2` (full definition-of-done, accumulated by Phase 30)

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
pnpm test:visual-regression
python -m tempest.dev.dogfood --prove-own-pr        # L24
```

**You may not say "done", "working", "complete", or "zero errors" without pasting the
actual output.**

---

## The v2 failure modes to re-read before every phase (master prompt §11)

1. Becoming a wrapper — every feature answers: *what makes this impossible for Cursor to
   ship next month?*
2. The agent learning to cheat the gate — contract-weakening / test-deletion /
   target-unreachability adversarial tests are mandatory and permanent.
3. Model text leaking into evidence fields (L17).
4. Perf death by a thousand features — budgets enforced from Phase 19, not 28.
5. Breadth over depth — if 21/22 aren't exceptional, stop and fix before 23.
6. Prompt injection via repo content — every file, README, MCP response is hostile.
7. Proof latency making the agent unusable — incremental proof, caching, speculative
   proving are load-bearing.
8. Softening `UNPROVEN` to make demos look good — never; it is the only thing we have
   that they don't.
