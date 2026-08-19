# Tempest AI v2 — The 21 Features (master prompt v2.0.0 §4, normative)

> Source: the v2.0.0 master prompt (2026-08-18). Laws L1–L14 all still bind; L15–L24 are in
> `CLAUDE.md`. Where v2 conflicts with v1, **v1 wins** unless an ADR says otherwise.
> Every feature ships only when its gate passes with pasted output. Phase mapping: `PLAN-V2.md`.
>
> The strategic frame, in one sentence: **every other coding agent tells you it's done;
> Tempest shows you the evidence — or tells you it couldn't get any.** A feature a thin
> wrapper could ship in a weekend does not belong here.

---

## GROUP A — the proof-native agent core

### F1. The Verdict Loop — a coding agent that cannot claim done  *(Phase 21)*

**What.** Full agentic coding: plan → multi-file edit → run commands. Before any change is
presented, the orchestrator runs a differential proof of the shadow worktree against the
pre-task baseline. The turn terminates on a **verdict**, never on self-assessment.

**How.** `plan → edit (shadow, L19) → engine.prove(baseline, shadow) → verdict`.
`DIVERGENT`-as-intended (F2) → present. `DIVERGENT`-unintended → repair signal (F3), budgeted.
`UNPROVEN` → present labeled UNPROVEN with the blocking symbols named — never as verified.
The proof stage streams live in the UI.

**Acceptance criteria / gate:**
- [ ] 50-task benchmark (bug fixes + refactors on real repos): `python -m tempest.dev.agent_bench --tasks 50 --require-verdict-coverage 1.0`
- [ ] 100% of presented changes carry a real verdict traceable to a stored bundle.
- [ ] Zero "verified" labels without a bundle — enforced by DB constraint **and** an
      adversarial test that attempts to forge one (L16).

### F2. Intent Contracts — natural language compiled to an executable equivalence relation  *(Phase 21)*

**What.** The user states intent (*"fix the rounding on refunds; nothing else changes"*);
Tempest compiles it to a typed contract: which symbols may change behavior, which must not,
along which dimensions. Divergences classify as `INTENDED` / `UNINTENDED` / `UNCLASSIFIED`.

**How.** LLM drafts a **structured contract object** (never free text) → committed to
`.tempest/contracts/` as reviewable YAML the user can edit. The comparison stage consumes it.
`UNCLASSIFIED` divergences are surfaced *most* prominently — nobody predicted them.

**Acceptance criteria / gate:**
- [ ] Seeded 40-task corpus with known intended/unintended splits: `python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0`
- [ ] ≥90% correct classification.
- [ ] **Zero** unintended divergences misclassified as intended (safety-critical; a false
      "intended" is worse than no feature).

### F3. Proof-Guided Repair — the minimized repro as a fitness function  *(Phase 21)*

**What.** On an unintended divergence the agent receives the minimized failing input, both
observations, and the effect-ledger diff — then repairs; the loop re-proves. Iterates until
the divergence set matches the contract or the budget is spent (default 4 attempts).

**How.** Repair context is a compact evidence packet: minimized input, base vs head
observation, first divergent effect index, changed-line coverage, failing contract clause.
Every attempt journaled and visible — never hide the loop.

**Acceptance criteria / gate:**
- [ ] `python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats`
- [ ] Repair success ≥60% on the F1 benchmark.
- [ ] **Zero** repairs that "succeed" by weakening the contract, deleting the divergent
      path, or making the target unreachable — one adversarial test per cheat, permanent.

### F4. Behavioral Spec Synthesis — what the code actually does, from execution  *(Phase 22)*

**What.** Point at a function → a behavioral spec derived from observed execution across
generated inputs: real I/O pairs, edge cases, exception conditions, effect sequence, with a
natural-language summary grounded in each claim.

**How.** Input generator with no head revision; cluster observations by behavior class;
every sentence links to the inputs that support it. Export as Markdown, docstrings, or a
test suite (F10). Claims with no supporting execution are not written.

**Acceptance criteria / gate:**
- [ ] Every generated claim resolves to ≥1 stored observation.
- [ ] Adversarial test: a function with a subtle bug produces a spec describing the *buggy*
      behavior, not the behavior its name implies.

### F5. Semantic Merge — resolve conflicts by behavior, not text  *(Phase 27)*

**What.** On a merge conflict, generate candidate resolutions and **prove** each against both
parents: which candidate preserves branch A's intended change *and* branch B's? Ranked by
evidence.

**How.** Three-way differential (base/ours/theirs/candidate). Valid = union of both branches'
intended divergences, no others. Can't exercise the region → `UNPROVEN` + plain manual
conflict UI. Bias hard toward refusing.

**Acceptance criteria / gate:**
- [ ] 30 real OSS conflicts with known true resolutions: top-ranked correct ≥70%.
- [ ] **Zero** confidently-wrong resolutions (wrong #1 with a clean verdict = P0, impossible
      by construction).

### F6. Proven Migration Agent — port code and prove the port  *(Phase 25)*

**What.** Cross-language/framework migration (Python→Rust, JS→TS, Express→Fastify, Pydantic
v1→v2) presented only when proven behaviorally equivalent on generated inputs.

**How.** Stage 6 accepts two *different* runtimes. Canonical value protocol: strict versioned
wire format (ints, floats, strings, bytes, sequences, maps, sets, null, tagged domain types);
anything unmappable → `UNPROVEN`. Cassettes shared across runtimes — the port provably makes
the same external calls.

**Acceptance criteria / gate:**
- [ ] `python -m tempest.dev.migration_bench --ports 20 --bad-ports 5`
- [ ] 20 real functions ported Py→TS and Py→Rust, each proven on ≥200 inputs.
- [ ] 5 deliberately subtly-wrong ports each caught.
- [ ] Wire format spec published.

---

## GROUP B — autonomous code health

### F7. The De-Slop Agent — deduplication with proof at every step  *(Phase 25)*

**What.** Detect *semantic* duplication, consolidate, and prove behavioral equivalence on
every atomic step. Nobody runs autonomous refactoring because nobody can verify it; we can.

**How.** Clone detection = normalized AST + behavioral fingerprinting (identical observations
across a shared generated input set). Refactor = sequence of atomic individually-proven steps
with a full rollback ledger; an unprovable step halts and reports. Never big-bang.

**Acceptance criteria / gate:**
- [ ] On an AI-slop corpus: measurable duplication reduction; 100% of applied steps carry a
      proof bundle; zero unproven steps applied; rollback demonstrated from any intermediate point.

### F8. Proven Dead Code Elimination  *(Phase 25)*

**What.** Delete only what is statically unreachable **and** behaviorally inert (removal
produces zero divergence across the exercised surface).

**How.** Static reachability → candidates; then remove + differential across the dependent
surface. Any divergence → not dead, with the *why* reported. Production cassettes (F10)
optionally consumed as reachability evidence.

**Acceptance criteria / gate:**
- [ ] `python -m tempest.dev.deadcode_trap --expect-refusals 20`
- [ ] Trap corpus of 20 dynamically-reached symbols static analysis calls dead: all 20 refused.
- [ ] False-deletion rate exactly zero — one mistake ends the feature's credibility.

### F9. Adversarial Self-Validation — the agent tries to prove itself wrong  *(Phase 24)*

**What.** After `EQUIVALENT_UNDER_BUDGET`, inject mutations into head and check whether the
input search would have caught them: *"my search caught 47/50 injected faults."* A falsifiable
claim about evidence strength.

**How.** Mutation operators (boundary shift, operator swap, off-by-one, null injection, early
return, condition negation) on changed lines; LLM proposes additional *semantic* mutations
(generating candidate faults, never verdicts — L17). Surviving mutants feed the input
generator; the system strengthens as it runs.

**Acceptance criteria / gate:**
- [ ] `python -m tempest.dev.mutation_bench --report-scores`
- [ ] Mutation score reported on every `EQUIVALENT_UNDER_BUDGET` verdict.
- [ ] Below-floor targets downgrade to `WEAK_EVIDENCE` — new verdict value, exhaustively
      handled in all four languages (requires an L2 vocabulary ADR — see QUESTIONS).

### F10. Cassette-to-Suite — production traces become a real test suite  *(Phase 24)*

**What.** Import recorded traffic (Tempest cassettes, Keploy, VCR, HAR, OTel spans) →
synthesize a durable suite asserting *observed* behavior.

**How.** Per-format importers normalize into the cassette schema. Cluster by code-path
coverage; minimal covering set (set-cover, not first-100). Tests generated in the repo's
existing framework and idiom. PII scrubbing at import, on by default, preview of exactly
what was scrubbed.

**Acceptance criteria / gate:**
- [ ] Real Keploy recording + OTel trace set imported; generated suites run green on base,
      catch a seeded regression on head.
- [ ] Scrubber tested with planted secrets (letter-segmented — trap 19): zero leakage.

---

## GROUP C — the coding surface (parity is the floor, proof is the ceiling)

### F11. Inline Completion & Next-Edit Prediction  *(Phase 20)*

**What.** Tab completion + multi-line next-edit prediction; local-model capable (offline,
air-gapped). **Twist:** a behavioral risk indicator — completions touching symbols with high
historical divergence rates, low proof rates, or many dependents are flagged from *measured*
data.

**How.** Speculative decoding, aggressive prefix caching, measured debounce. llama.cpp via a
Rust-side runner. Ghost text in CodeMirror 6 without layout thrash.

**Acceptance criteria / gate:**
- [ ] p50 < 120 ms, p95 < 300 ms on an M-series laptop with a local model.
- [ ] Acceptance rate instrumented.
- [ ] Zero dropped keystrokes: synthetic input-storm test, 15 keys/s × 60 s.

### F12. Multi-File Composer with Proof Preview  *(Phase 23)*

**What.** Plan → multi-file edit → review, Cursor-class. **Twist:** the diff has a third
column — behavioral impact per hunk: verdict, divergences caused, changed-line coverage.
Accept/reject at hunk granularity; proof re-runs incrementally on partial acceptance.

**How.** Shadow worktree; incremental proof via call-graph-affected targets; optimistic UI
with rollback; virtualized diff rendering.

**Acceptance criteria / gate:**
- [ ] 500-file changeset renders <300 ms, 60 fps scroll.
- [ ] Partial-acceptance re-proof <2 s for a 10-file selection.

### F13. Execution-Grounded Codebase Chat & Search ⭐  *(Phase 22)*

**What.** Natural-language questions over a hybrid index. The sleeper: the **execution
index** — which functions ran, on which inputs, producing which values, across every run.
Answers questions source text cannot: *"what actually happens when `user_id` is null?"*,
*"which functions have never been exercised?"*, *"whose behavior changed in 30 days?"*.

**How.** Three indices, one query planner: vector (sqlite-vec/LanceDB, local), structural
(tree-sitter call graph, incremental), execution (observation store from all bundles).
Every answer cites source spans *and* observation IDs.

**Acceptance criteria / gate:**
- [ ] `python -m tempest.dev.retrieval_bench --questions 40 --require-citations`
- [ ] 40-question benchmark; the 15 source-impossible ones answered with observation
      citations; any uncited answer fails.
- [ ] Retrieval p95 < 400 ms on a 500k-LOC repo.

### F14. Sandboxed Agent Terminal  *(Phase 23)*

**What.** The agent runs builds/tests/scripts with streaming output. Commands execute at
differential-runner isolation (L19); every command + side effects land in the audit log and
undo journal (L20). Network-touching commands need explicit approval, remembered per-project.

**How.** PTY via the Rust host. Approval policy in `tempest.toml` (allowlist/denylist/prompt).
Streaming with backpressure + hard output cap (runaway loops can't OOM the app).

**Acceptance criteria / gate:**
- [ ] Escape suite extended to the agent terminal, all tiers, all OSes.
- [ ] 1M lines streamed without dropped frames or memory-budget breach.

### F15. Project Memory & Rules  *(Phase 23)*

**What.** `AGENTS.md` / `.tempest/rules/`, versioned, directory-scoped, auto-injected.
**Twist:** rules can be **behavioral** — *"nothing in `billing/` changes behavior without an
intent contract"* — compiled into Verdict Loop gates, not prompt suggestions.

**How.** Hierarchical resolution, hot reload, conflict detection with precedence display.
Behavioral rules compile to contract clauses consumed by Stage 7.

**Acceptance criteria / gate:**
- [ ] A behavioral rule violation is blocked by the engine even when the model is explicitly
      instructed to violate it.
- [ ] Prompt-injection suite cannot defeat it (rules enforced outside the model — prove the
      structural impossibility).

### F16. MCP Client + MCP Server ⭐  *(Phase 23)*

**What.** **Client:** Tempest consumes MCP servers (Linear, GitHub, Sentry, Postgres…).
**Server:** Tempest exposes `prove`, `explain_behavior`, `minimize_repro`,
`check_intent_contract`, `mutation_score` over MCP — the verification oracle for every
coding agent on the market, competitors included.

**How.** Full MCP client (stdio + HTTP, OAuth, tool-approval UI). Server mode respects all
sandbox/policy rules; licensable separately.

**Acceptance criteria / gate:**
- [ ] End-to-end demo, recorded: Claude Code connected to Tempest's MCP server refuses to
      mark a refactor complete when Tempest returns `DIVERGENT`.
- [ ] Injection suite green across MCP tool responses (attacker-controlled in the threat model).

---

## GROUP D — ambient & advanced

### F17. Parallel Agent Fleet in Isolated Worktrees  *(Phase 26)*

**What.** N agents, own worktrees, concurrent, in the background. Results ranked by
**verdict, proof rate, mutation score, intent-contract conformance** — never by "looks best."
Cross-agent divergence shown: *"agents 1 and 3 behaviorally identical; agent 2 differs on
these 2 inputs."*

**How.** Worktree pool with resource governance (L11). Per-agent budgets. Live fleet
dashboard.

**Acceptance criteria / gate:**
- [ ] 8 concurrent agents on a 4-core laptop stay within CPU/memory budgets; UI at 60 fps.
- [ ] Ranking fully reproducible from stored bundles — no model in the ranking path (L17).

### F18. Ambient Regression Watch ⭐  *(Phase 26)*

**What.** Continuous background proving of the working tree against last-known-good as you
type. Gutter divergence markers within seconds of a save — before commit, PR, CI.
*"This edit changed behavior for `days_used=0`"* thirty seconds after typing it.

**How.** On save: call-graph diff → affected targets → prove only those. Content-hash caching
of cassettes/harnesses/adapters. Strict idle-only scheduling, immediate yield on activity,
pause on battery/thermal (L11). Debounced, coalesced, cancellable.

**Acceptance criteria / gate:**
- [ ] Single-function edit → gutter marker <5 s p50, <15 s p95.
- [ ] Editor input latency delta with watch on vs off <5 ms.
- [ ] Battery drain measured and published.

### F19. Time-Travel Behavioral Debugger  *(Phase 27)*

**What.** Step the minimized repro on base and head **simultaneously**, side by side,
scrubbable timeline, exact step where they part marked.

**How.** Instrumented replay capturing per-step state deltas; variable-level diffing at each
step; effect ledger interleaved on the same timeline; bounded capture with sampling for long
executions.

**Acceptance criteria / gate:**
- [ ] 10,000-step execution scrubs at <500 ms with bounded memory.
- [ ] Divergence-point identification exact against known fixtures.

### F20. Team Behavioral Knowledge Base  *(Phase 27)*

**What.** Org-wide accumulated contracts, cassettes, specs, divergence history. Agent
retrieves from it. Behavioral ownership derived from proof history, not git blame.

**How.** Extends the Phase 13 sync server. Content-addressed, redaction-respecting (source
stays local unless policy allows).

**Acceptance criteria / gate:**
- [ ] F1 benchmark run with and without KB retrieval; the delta reported.
- [ ] Delta zero → the feature is decoration; say so and cut it.

### F21. Model Arena — objective model selection by proof ⭐  *(Phase 27)*

**What.** Same task across multiple models in parallel worktrees; ranked by verdict, proof
rate, mutation score, cost, latency. Auto-route future tasks per task type to whichever
model actually performs best **on this codebase**.

**How.** Task-type classifier (refactor/bugfix/feature/migration); per-type routing table
learned from local proof outcomes, stored locally, never phoned home. Cost-aware routing.
Leaderboard visible and exportable.

**Acceptance criteria / gate:**
- [ ] After 100 tasks the router beats fixed single-model selection on success-per-dollar.
- [ ] Methodology published; leaderboard exportable.

---

## Cross-cutting gates (every feature, no exceptions)

- **L16:** no code path presents agent output as verified without a differential run. No
  `--skip-proof`, no fake fast mode.
- **L17:** models never write confidence/verdict/risk fields; narration is visually distinct
  from evidence in every view.
- **L21:** cost visible before spent; hard caps per task/session/day.
- **L22:** the §5 performance budgets are CI gates from Phase 19 (`python -m tempest.dev.perf_suite --enforce-budgets`).
- **L24:** Tempest proves its own PRs; the Tempest-on-Tempest proof rate is published in the README.
- The six numbers (`docs/METRICS.md`) reported in every status update.
