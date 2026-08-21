# Tempest AI v3 — Convergence Phase Plan C0–C12

> Source: `TEMPEST-V3-MASTER-PROMPT.md` §8, normative. Laws: `CLAUDE.md` L1–L36.
> Dispositions: `docs/MERGE-CONTRACT.md`. Decisions: ADR-0063…ADR-0076. Ledger: `docs/FEATURES-V3.md`.
>
> **Execute in order, one item at a time, inline (no subagents — owner preference).** A phase is
> complete **only** when its gate commands have been run and their real output pasted into the
> session log, with the checkbox flipped in the same commit. **Claimed-passing is failing.**
> Stop after every phase for owner review. Rebuild and reinstall the app each phase.
>
> **Seven of the eight new `tempest.dev.*` gate modules do not exist yet; the eighth,
> `egress_check`, exists and lacks its `--platform-tree` extension** (verified at C0 against
> `tempest/dev/`). Writing each one is part of the phase that needs it. A gate that has never
> run is a claim, not a fact.

---

## Sequencing rules — violating these changes what product you are building

1. **C4 and C5 come before any feature is built on top of the runtime or the router.** Building on
   an implementation you are about to replace is how you do the work twice.
2. **C1's datastore spike is measured before C6 starts.** Deciding the store on architecture taste
   rather than numbers is how a schedule dies.
3. **Phases 24–27 may run in parallel with C6–C11 only after C5 lands.** Every one of them builds on
   the agent runtime.
4. **C12 is never cut.** A fast, unpolished world-class idea is not world-class. (Unchanged from the
   v2 rule protecting phases 30–31.)
5. **`egress_check --airplane-mode-full-function` runs every phase, not at the end.** Local-first
   erodes silently; it is never recovered in one pass at the end.

---

## Phase C0 — Re-audit: establish the honest baseline

Nothing moves until the current tree's real state is known. If something is red that the docs say is
green, that discovery is worth more than any code written today.

- [x] `make verify` on the current tree; paste full output. **Run 2026-08-21 on `a242dce`:
      `MAKE_EXIT=0` — "verify: all live steps green". pytest 1936 passed, TOTAL 9070 stmts
      0 miss / 2590 branch 0 partial = 100.00%; agent_bench 55/55 · intent_bench 54/54, 0 false
      INTENDED · repair_bench 22/28 (79%), 11/11 cheats refused · resume_test 15/15 ·
      subagent_bench 13/13 · retrieval_bench 40/40 + 15/15 grounded, p95 0.2 ms ·
      escape_suite exit 0 · redteam 35/35 · mcp_check 16/16 · mcp_client_check 11/11 ·
      compose_bench 11/11 · redaction 24/24 · license_check green · provider_matrix 16 ·
      vitest 27 + 86 · cargo 115 + 5 · Playwright E2E 51 passed · contract drift-free.
      Full log in the C0 session report.**
- [x] `make verify-linux-denominator`; paste output. **`DENOM_EXIT=0` — 1929 passed, 1 skipped,
      6 deselected; TOTAL 9070/0 + 2590/0 = 100.00%.**
- [x] `uv run python -m tempest.dev.parity --cli-vs-desktop`; paste output. **`PARITY_EXIT=0` —
      "byte-identical bundles (targets.json, 1 repro script(s), manifest minus created_at)";
      fixture verdicts {'clamp': 'DIVERGENT', 'total': 'EQUIVALENT_UNDER_BUDGET'}.**
- [x] `uv run python -m tempest.dev.orphan_check` (app installed to `/Applications`); paste
      output. **`ORPHAN_EXIT=0` — "zero sidecar processes survive SIGKILL of the host (cleared
      in 2.2s, bar 15s)".**
- [x] Write the §2.1 known-open items into this plan as real, numbered items rather than prose:
      Phase 3's TS **execution** half (Node worker, determinism shims, V8 precise coverage,
      type→fast-check compiler, TS corpora); the Claude-Code↔Tempest MCP demo recording (owner);
      ten real MCP servers with authorization-code OAuth (owner); item 19.5b.
      **Done — the known-open ledger below (KO-1…KO-4), including the measured KO-1 correction
      (wave 1 of TS execution SHIPPED in ADR-0028; wave 2 is what is open).**
- [x] Commit ADR-0063…ADR-0076 into `docs/DECISIONS.md`. Amend ADR-0038's refusal table with
      pointers — **do not delete the refusal text.** **Done — fourteen ADRs appended verbatim
      from the addendum; ADR-0038's table retained with a v3 pointer note.**
- [x] Land `docs/PLAN-V3.md`, `docs/MERGE-CONTRACT.md`, `docs/FEATURES-V3.md`; amend
      `docs/PLATFORM-V2.md` with the overturn pointers. **Done — plus
      `docs/TEMPEST-V3-MASTER-PROMPT.md` and `docs/DECISIONS-V3-ADDENDUM.md` landed so every
      cross-reference in the v3 doc set resolves inside the repo, and `CLAUDE.md` gained
      L27–L36 (which `MERGE-CONTRACT.md` and this file cite). Three read-only review lenses ran
      over the landing; all findings fixed (law-summary fidelity ×7, stale-§2.1 correction,
      LC row-id rename).**

**Gate:** every command above run with output pasted. No code written this phase.

### The known-open ledger (§2.1), as numbered items — written at C0, 2026-08-21

Measured against the tree at `a242dce`. Each item names its owner and the phase that closes it;
`docs/FEATURES-V3.md` T32–T35 are the same four items in ledger form.

- [ ] **KO-1 — TypeScript execution, wave 2** (= T32; scheduled C0 → 3-continuation per §8.6).
      **Correction, measured at C0:** master prompt §2.1 says "the Node execution worker and V8
      coverage are not [done]" — that predates ADR-0028 (2026-08-16). Wave 1 SHIPPED and is in
      `make verify`: `ts_worker.mjs` (Node execution worker), `ts_shims.mjs` (determinism shims:
      seeded `Math.random`/`Date`/`performance`/`crypto`), per-input V8 precise coverage with
      count-0 subtraction, `ts_dual.py` (the same comparator), tsfix corpus 8/8 keyless.
      **Actually open:** TS cassettes/recorded-IO, instance methods, `.tsx`, the T1(Docker) Node
      leg, the type→fast-check compiler, TS corpora growth. Blocks any parity claim that includes
      TypeScript proving beyond wave-1 scope.
- [ ] **KO-2 — Recorded Claude-Code ↔ Tempest MCP demo** (= T33). **Owner action** — no hermetic
      gate can assert it; `mcp_check` prints this itself.
- [ ] **KO-3 — Ten real MCP servers with authorization-code OAuth** (= T34). **Owner action.**
- [ ] **KO-4 — 19.5b, one model path** (= T35; closes in C4, ADR-0076 rider): migrate
      `harness/llm.py` and `report/narrative.py` onto `tempest/inference/` and drop the
      `anthropic` SDK. `grep -rn "^import anthropic\|from anthropic" packages/engine/src` finding
      no SDK import is part of C4's gate.

---

## Phase C1 — Vendor, attribute, and measure the store

- [ ] Vendor LibreChat at a pinned commit into `packages/platform/{server,api,data,provider,client}`,
      preserving their directory structure (L27).
- [ ] **In the same commit:** strip every brand asset — logos, wordmarks, favicons, brand imagery,
      brand colour tokens — so they are never in the tree. MIT does not license trademarks.
- [ ] **In the same commit:** `THIRD_PARTY_LICENSES.md` gains the derivation table rows (source path,
      adopted SHA, disposition, modification summary) and LibreChat's own dependency obligations are
      merged into ours.
- [ ] Extend `tempest.dev.license_check` to `packages/platform/**`, with unit pins that each prove a
      **failure** on a violating tree (the existing 18 pins are the pattern).
- [ ] Write `packages/platform/UPSTREAM.md`: adopted SHA, merge procedure, empty delta ledger.
- [ ] Build `tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete`.
- [ ] Build `tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store`.
- [ ] **The datastore spike (ADR-0068).** Stand up FerretDB 2.x + embedded PostgreSQL + DocumentDB
      on the 4-core/16 GB reference profile. Measure and paste: cold launch → interactive, idle RAM
      (all sidecars), idle CPU, and p95 for the ten hottest LibreChat queries.
- [ ] Record the measurement in ADR-0068. If any §10 budget is missed by >25%, engage the
      pre-approved fallback (Mongoose models/methods over an engine-SQLite document adapter) and
      record that instead. **No new ADR needed to take the fallback — only to record the numbers.**

**Gate:**
```bash
python -m tempest.dev.license_check --third-party-notices --platform-tree
python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store
python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete
# spike numbers pasted against the §10 table; ADR-0068 amended with the measured choice
grep -ri "librechat" packages/platform/client/public packages/desktop/src --include='*.svg' --include='*.png'   # zero brand assets
```

---

## Phase C2 — Boundary E

- [ ] `packages/shared-schema/platform.schema.json` — the root of truth for every message crossing
      Rust ↔ Node. Domain values reference boundary C's Pydantic-rooted types; they are never
      redefined.
- [ ] Generation into Rust and TS, wired into `make gen-contracts`, landing inside the paths
      `verify-contract` already diffs.
- [ ] JSON-RPC 2.0 over a **Unix domain socket** (named pipe on Windows), length-prefixed framing —
      reuse `framing.rs`, which already does this for boundary A. **No TCP listener, ever.**
- [ ] **Bidirectional validation in production, not only in dev.** LibreChat is JavaScript, so TS
      types are advisory at runtime. A validation failure is a surfaced, diagnosable error with an
      ID (L15.3), never a swallowed exception.
- [ ] Node API supervised by `supervisor.rs` under L34: process-group ownership, health checks,
      exponential-backoff restart, teardown that survives `SIGKILL` of the parent.
- [ ] Extend `orphan_check` to `--all-children --after-sigkill`.

**Gate:**
```bash
make gen-contracts && git diff --exit-code      # FIVE boundaries, one truth
uv run python -m tempest.dev.orphan_check --all-children --after-sigkill
# a port probe proving no TCP listener is opened by any child, on all three OSes
# an enum-drift probe: add a ReasonCode in Python → Rust build, TS build, AND boundary E
#   validator all fail. Paste all three failures, then revert.
```

---

## Phase C3 — The merged shell

- [ ] LibreChat's React client mounts in the Tauri webview. **One router, one state layer, one
      design system.** Tempest's `packages/desktop/src/views/**` and `editor/**` are absorbed into
      it. (Upstream ships Recoil *and* Jotai; adopt both as they stand — do not consolidate
      actively-developed code for zero user benefit. Adding a **third** is what is forbidden.)
- [ ] `vocabulary.tsx` becomes the reserved-verdict rendering layer and the L31 enforcement point.
- [ ] Restyle into Tempest's identity via the design-token seam — **not** by rewriting components.
      A user must never be able to tell where one codebase ends and the other begins.
- [ ] Auth becomes optional: local single-user mode short-circuits to an implicit local principal
      through a distinct code path with its own tests. **Never a bypass flag.**
- [ ] Every telemetry surface (LibreChat telemetry, Langfuse, RUM, insights, error reporting) is off
      by default and **provably inert**, each with its own `egress_check` case.
- [ ] Build `tempest.dev.egress_check --platform-tree --deny-all --airplane-mode-full-function`.
- [ ] Build `tempest.dev.vocab_check --reserved-verdicts --platform-tree`.

**Gate:**
```bash
python -m tempest.dev.egress_check --platform-tree --deny-all --airplane-mode-full-function
python -m tempest.dev.vocab_check  --reserved-verdicts --platform-tree
python -m tempest.dev.perf_suite   --enforce-budgets     # cold launch, merged-app row
# every route renders with zero console errors; screenshots attached
```

---

## Phase C4 — One provider router (ADR-0076)

- [ ] LibreChat's provider configuration schema, model-spec metadata, per-endpoint parameter UI, and
      reasoning UI mapped onto `tempest/inference/`.
- [ ] Adaptive provider smoothing and delta batching adopted onto the single router.
- [ ] `credentials.ts` replaced by the OS keychain path (`keychain.rs`). No plaintext key storage,
      no exception for dev builds.
- [ ] Caps enforced at the router. Cost meter remains the single spend-enforcement point and still
      ships **no price list**.
- [ ] **19.5b:** migrate `harness/llm.py` and `report/narrative.py` onto the unified client; drop the
      `anthropic` SDK dependency.
- [ ] Raise `provider_matrix` floor to `--min-providers 16`.

**Gate:**
```bash
python -m tempest.dev.provider_matrix --min-providers 16
grep -rn "^import anthropic\|from anthropic" packages/engine/src && exit 1 || true
# cap test: 8 threads against a cap admitting 2 → exactly 2. Paste output.
# dollar cap with no user-supplied rate RAISES rather than passing. Paste output.
```

---

## Phase C5 — One agent runtime ⭐ THE LARGEST ITEM (ADR-0075)

This phase decides whether the merge produced one product or two. Budget for it accordingly, and do
not let anything else land while it is in flight.

- [ ] `api/server/services/Agents/**` becomes a thin client over boundary E, delegating every turn
      to the Python orchestrator, speaking unchanged shapes to the React client.
- [ ] Tool registries unify on `agent_tools.rs` (boundary D). `WriteScope` keeps its property that a
      write to the user's working tree is **unrepresentable**.
- [ ] LibreChat's agent surface adopted in full and re-targeted: no-code builder, unified tools
      marketplace, skills, plugins, subagents, run control (interrupt, steer mid-run, queue
      follow-ups, reclaim/edit/escalate pending steers), human-in-the-loop pause for input and tool
      approval, generated activity-group headers, parent phase summaries, live tool intent labels,
      context-usage gauge, stream circuit breakers.
- [ ] Build `tempest.dev.runtime_check --single-orchestrator --single-tool-registry`.
- [ ] Build `tempest.dev.gate_audit --enumerate-paths --require-forge-test-per-path`: enumerate every
      code path by which agent-authored change reaches a user, and require a forge test per path.
- [ ] `docs/MERGE-CONTRACT.md` and `UPSTREAM.md` updated with the `services/Agents/` delta.

**Gate:**
```bash
python -m tempest.dev.runtime_check --single-orchestrator --single-tool-registry
python -m tempest.dev.gate_audit    --enumerate-paths --require-forge-test-per-path
./scripts/agent-gates.sh                                              # all four, through the NEW surface
python -m tempest.dev.agent_bench  --tasks 50 --require-verdict-coverage 1.0   # must still be 55/55
python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0  # must still be 54/54, 0 false
python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats
python -m tempest.dev.resume_test  --kill-mid-proof --sleep-mid-stream
```

**If `agent_bench` is not still 55/55 through the new surface, the merge broke the thing the product
is for. Fix it before anything else lands.**

---

## Phase C6 — Datastore cutover

- [ ] Every LibreChat model, method, and migration green against the store C1 selected.
- [ ] Migration up/down parity test.
- [ ] Their data-layer test suites run inside `make verify-v3` (merge contract §6 rule 4).
- [ ] Redis interface backed by in-process LRU + engine SQLite; real Redis retained as config.
- [ ] The five declared cross-store references implemented as opaque ids; `store_check` reads the
      table in `MERGE-CONTRACT.md`.

**Gate:**
```bash
pnpm --filter "./packages/platform/data/**" test          # their suites, green
python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store
python -m tempest.dev.perf_suite --enforce-budgets        # document-store p95 row
# migration up → down → up parity, output pasted
```

---

## Phase C7 — The conversation platform (absorbs P6, P7, P12)

- [ ] Forking, branching, edit-and-resubmit, continue. **Combined with shadow worktrees**: fork an
      agent run at any turn and **compare branches by verdict** — not "which reply do I prefer" but
      *"branch A is EQUIVALENT_UNDER_BUDGET with a 0.94 mutation score; branch B is DIVERGENT on 2
      inputs."*
- [ ] **P7 Proof Profiles**: presets extended to carry model, input budget, float tolerance, required
      mutation floor, and sandbox tier. Resolve hierarchically by directory, hot-reload, display
      precedence on conflict.
- [ ] Prompts with user and group sharing; bookmarks and tags; full-text virtualized search across
      all messages and conversations; shared conversations with stable URLs and
      continue-as-personal-copy.
- [ ] Import from LibreChat / ChatGPT / Chatbot UI. Export to markdown / JSON / text / screenshot
      — **with proof bundles attached**, so an exported session re-imports on another machine with
      every repro still runnable.
- [ ] Resumable streams (P2) extended: the **proof stage** is checkpointed so a killed turn resumes
      without re-proving what was already proven.

**Gate:**
```bash
python -m tempest.dev.session_roundtrip --export-import --require-runnable-repros
python -m tempest.dev.resume_test --kill-mid-proof --sleep-mid-stream
# fork from any turn; both branches independently proven; side-by-side verdict comparison;
#   merge a branch back. Screenshots + pasted verdicts.
# Proof Profile precedence displayed on conflict; hot-reload verified.
```

---

## Phase C8 — Tools and execution

- [ ] **Code interpreter** (ADR-0070): Python, Node/TS, Go, C/C++, Java, PHP, Rust, Fortran; file
      upload/process/download; background code and shell execution; sandbox images returned as
      viewable artifacts. **On Tempest's tier ladder — no tier, no execution.**
- [ ] **Cassette link**: a recording made in the interpreter is replayable by the differential
      runner. This is what moves the interpreter from `PROOF_ADJACENT` toward `PROOF_NATIVE`.
- [ ] **MCP convergence** (merge contract BRIDGE→REPLACE, removal date = end of this phase): port
      LibreChat's dynamic tool refresh, parsed response media types, and runtime OAuth recovery onto
      the Python client; retire the bridge.
- [ ] Custom actions from OpenAPI specs; web search with providers, scrapers, rerankers; skills;
      plugins; subagents; scheduled runs (ADR-0073).
- [ ] **RAG, file chat, OCR** (ADR-0071), local-by-default embeddings, PII scrubbing on by default
      with a preview of exactly what was scrubbed.
- [ ] Extend `redteam --injection` to RAG chunks, file contents, OCR output, and code-interpreter
      channels. **Every retrieved byte is attacker-controlled input, never instruction.**

**Gate:**
```bash
python -m tempest.dev.escape_suite --surface code-interpreter   # all tiers, three OSes
python -m tempest.dev.redteam --injection                        # incl. RAG, OCR, interpreter, MCP
python -m tempest.dev.mcp_client_check                           # bridge retired, one client
# a cassette recorded in the interpreter replayed by the differential runner. Paste output.
```

---

## Phase C9 — Artifacts, including behavioral artifacts (absorbs P8)

- [ ] React, HTML, and Mermaid rendered inline; fullscreen preview; Mermaid export to SVG and PNG;
      `.potx` templates across upload, search, and code execution; original Office file download.
- [ ] **Behavioral artifacts** in the same renderer: call graphs, effect-sequence timelines,
      divergence tables, coverage maps, minimized-input trees — inline and interactive. **This is how
      proof evidence stops being a wall of JSON.**
- [ ] Sandboxed renderer, strict CSP, no arbitrary network. Every artifact exportable into a run
      bundle.

**Gate:**
```bash
python -m tempest.dev.escape_suite --surface artifact-renderer
python -m tempest.dev.perf_suite --enforce-budgets         # artifact first render row
# every artifact type exports into a run bundle and re-renders from it. Paste output.
```

---

## Phase C10 — The overturned features + platform completion

- [ ] **Image generation** (ADR-0063): GPT-Image-1, DALL·E 3/2, Stable Diffusion, Flux, MCP image
      servers. EXIF and geolocation stripped before any provider call, test-verified.
- [ ] **Speech** (ADR-0065): STT and TTS via OpenAI, Azure OpenAI, ElevenLabs; automatic send and
      playback; local STT path available. **Verdicts are never spoken as prose.**
- [ ] **Marketplace** (ADR-0066): community agents, skills, plugins, discovery, group sharing —
      with capability declaration and **signature verification** required for anything requesting
      file-write, shell, or network.
- [ ] **Admin panel** (ADR-0072): users, groups, roles, live config overrides, delegated config
      sections, encrypted registered secrets. Gates team features only. **Cannot disable the proof
      gate.**
- [ ] Multi-user auth: OAuth2, LDAP, email. Moderation, token spend tracking, balances, quotas.
      Langfuse with encrypted connections and per-tenant fan-out — off by default.
- [ ] Multimodal input, memory with per-agent isolation, insights, SSRF checks on speech/OCR/web
      tools, configurable HTTP timeouts.
- [ ] Build `tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform`.

**Gate:**
```bash
python -m tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform
python -m tempest.dev.redteam --gate-subversion
# adversarial: an UNSIGNED capability-requesting agent must FAIL to install. Paste the refusal.
# adversarial: an admin attempting to disable the proof gate must find no such path. Paste.
# LDAP against a real directory; airplane mode = full local function, zero auth prompts.
# EXIF + geolocation stripped, test-verified. Paste.
```

---

## Phase C11 — i18n across the merged surface (ADR-0074)

- [ ] All 44 locales adopted wholesale; Tempest strings added as new keys in the same pipeline.
- [ ] Every verdict, every `reason_code` explanation, every `UNPROVEN` blocking reason translatable.
      **A verdict a user cannot read is not evidence.**
- [ ] Zero hardcoded user-facing strings, lint-enforced across both trees.
- [ ] Pseudo-locale for truncation and layout breakage; RTL verified, not assumed.
- [ ] Untranslated Tempest keys fall back to English with a visible dev marker, silent in production
      — never a raw key in front of a user.

**Gate:**
```bash
python -m tempest.dev.i18n_check --no-hardcoded-strings --pseudo-locale --rtl   # both trees
```

---

## Phase C12 — Convergence hardening + GA *(never cut)*

- [ ] **Performance campaign.** Every §10 budget met on the 4-core/16 GB profile against a 500k-LOC
      repo and a 10k-conversation history. CI perf gate on every PR. Public perf dashboard live.
- [ ] **Craft campaign.** All 150 `docs/POLISH.md` items verified on macOS, Windows, Linux with
      screenshots. Visual regression across every view × 2 themes × 3 viewports × 2 densities.
      Motion-interrupt suite: every animation interrupted at 50%, clean settle. **CLS = 0** on every
      view. a11y audit at WCAG 2.2 AA with VoiceOver and NVDA recordings attached. The screenshot
      test: any view legible and self-explanatory alone.
- [ ] **Red team.** 50+ injection, 20+ exfiltration, 15+ gate-subversion, covering the code
      interpreter, RAG, marketplace, MCP, and boundary E.
- [ ] **External security review** before GA.
- [ ] **Upstream merge rehearsal, executed for real.** `make upstream-merge && make verify-v3` green
      against a live upstream LibreChat commit. Not a dry run.
- [ ] **Parity ledger at 100%.** Every LibreChat capability `ADOPTED` with a verifying test that ran
      green. README publishes the number.
- [ ] **30-day dogfood.** Crash-free session rate ≥ 99.9%; agent turn failure rate ≤ 0.5%.
      Tempest proves its own PRs with Tempest, gated in CI; the Tempest-on-Tempest proof rate
      published in the README (L24).

**Gate:**
```bash
make verify-v3                                                    # complete, exit 0
python -m tempest.dev.parity_ledger --require-100-at-ga --print-percentage
python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete
python -m tempest.dev.redteam --injection --exfiltration --gate-subversion
python -m tempest.dev.perf_suite --enforce-budgets
python -m tempest.dev.a11y_audit --wcag 2.2 --level AA
python -m tempest.dev.dogfood --prove-own-pr
pnpm test:visual-regression --themes 2 --viewports 3 --densities 2
pnpm test:motion-interrupt
```

---

## Interleaving with phases 24–32

Phases 24–27 remain live in `docs/PLAN-V2.md` and are **the proof half of the product**. Cutting them
turns this into a chat app with a defensible README.

```
C0 → C1 → C2 → C3 → C4 → C5 ┬→ C6 → C7 → C8 → C9 → C10 → C11 → C12
                             │
                             └→ 24  F9 adversarial self-validation · F10 cassette-to-suite
                                25  F7 de-slop · F8 proven dead code · F6 migration agent
                                26  F18 ambient regression watch · F17 agent fleet
                                27  F5 semantic merge · F19 time-travel debugger ·
                                    F20 team KB · F21 model arena
```

- Phases 24–27 may run in parallel with C6–C11 **only after C5 lands.**
- Phases **28 and 29 are absorbed**: P6/P7/P12 → C7, P8/P13 → C9, P10 → C10, P14 → C11.
- Phases **30, 31, 32 merge into C12** and are never cut.
- Phase 3's TypeScript **execution** half is a C0 item and blocks any parity claim that includes
  TypeScript proving.

---

## New gate modules to be built, and where

| Module | Phase | Law |
|---|---|---|
| `upstream_check` | C1 | L27 |
| `store_check` | C1 | L33 |
| `egress_check --platform-tree` (extension) | C3 | L32 |
| `vocab_check` | C3 | L31 |
| `runtime_check` | C5 | L29 |
| `gate_audit` | C5 | L28 |
| `feature_ledger` | C10 | L30 |
| `parity_ledger` | C12 | L35 |

**Also not built yet — inherited from the v2 plan, and this plan uses them in gates.** Verified
absent from `tempest/dev/` on 2026-08-21: `mutation_bench`, `deadcode_trap`, `migration_bench`,
`session_roundtrip`, `i18n_check`, `a11y_audit`, `dogfood`. Each is built by the phase that first
needs it — `session_roundtrip` in C7, `i18n_check` in C11, `a11y_audit` and `dogfood` in C12, and
the remaining three in phases 24–25. **Writing the benchmark is part of the phase.** Do not paste a
gate command into a report before you have made it runnable and watched it run.

Plus extensions to existing modules: `license_check --platform-tree` (C1),
`orphan_check --all-children --after-sigkill` (C2), `provider_matrix --min-providers 16` (C4),
`escape_suite --surface code-interpreter|artifact-renderer` (C8, C9),
`redteam` new channels (C8, C10), `perf_suite` new rows (C1 onward),
`i18n_check` both trees (C11).
