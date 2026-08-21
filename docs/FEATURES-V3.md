# FEATURES-V3 — the unified parity ledger

> Normative and **machine-read**. `tempest.dev.parity_ledger` parses this file; `tempest.dev.feature_ledger`
> enforces that every row carries an L30 relationship. Laws: L30 (every feature declares its proof
> relationship), L31 (verdict vocabulary is reserved), L35 (parity is measured, not asserted).
>
> **Status vocabulary:** `ADOPTED` (verifying test ran green) · `IN_PROGRESS` · `NOT_STARTED` ·
> `SHIPPED` (pre-existing Tempest capability, gate green) · `PLANNED` (Tempest capability with a
> phase). A row is `ADOPTED`/`SHIPPED` **only** when its verifying test has run green with output
> pasted. Nothing else counts.
>
> **L30 relationship:** `PROOF_NATIVE` (wired into the Verdict Loop; changes meaning because of it) ·
> `PROOF_ADJACENT` (serves proof indirectly; carries proof context) · `PLATFORM` (complete,
> excellent, honestly unrelated to proof — and therefore forbidden from borrowing verdict vocabulary,
> verdict colours, or evidence surfaces).
>
> **Parity % = ADOPTED rows ÷ total LibreChat rows.** Published in the README. Required to be 100% at GA.
>
> **C0 note (2026-08-21):** Part-1 row ids use the `LC` prefix (LC01…LC76). The original draft's
> `L` prefix shadowed the Law numbers (a row "L28" beside Law L28, the proof gate) inside the one
> file both are cited in; renamed before `parity_ledger` is built against these ids.

---

## Part 1 — LibreChat capabilities (the parity denominator)

### Providers and models

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC01 | Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, Google, Vertex AI, OpenAI Responses API | PROOF_ADJACENT | C4 | NOT_STARTED | `provider_matrix --min-providers 16` |
| LC02 | Any OpenAI-compatible endpoint, no proxy (Ollama, groq, Mistral, Cohere, together.ai, OpenRouter, Perplexity, DeepSeek, Qwen, Apple MLX, koboldcpp, Helicone, ShuttleAI) | PROOF_ADJACENT | C4 | NOT_STARTED | `provider_matrix` |
| LC03 | Model specs + per-endpoint parameter controls | PLATFORM | C4 | NOT_STARTED | `provider_matrix`; parameter round-trip test |
| LC04 | Reasoning UI for chain-of-thought models | PLATFORM | C4 | NOT_STARTED | E2E render test |
| LC05 | Mid-chat endpoint and preset switching | PLATFORM | C7 | NOT_STARTED | E2E switch test |
| LC06 | Adaptive provider smoothing + stream delta batching | PLATFORM | C4 | NOT_STARTED | streaming smoothness bench |
| LC07 | Configurable HTTP timeouts | PLATFORM | C10 | NOT_STARTED | timeout unit test |

### Agents

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC08 | No-code agent builder | PROOF_NATIVE | C5 | NOT_STARTED | `agent_bench` through the new surface |
| LC09 | Unified Tools marketplace (builder-side) | PROOF_NATIVE | C5 | NOT_STARTED | `runtime_check --single-tool-registry` |
| LC10 | Agent sharing to users and groups | PLATFORM | C10 | NOT_STARTED | ACL test |
| LC11 | `SKILL.md` bundles — manual / automatic / always-on | PROOF_NATIVE | C5 | SHIPPED (P3) | Proof Skill floor holds when the model is told to ignore it |
| LC12 | Agent plugins bundling skills + MCP servers | PROOF_ADJACENT | C8 | NOT_STARTED | plugin install + capability signature test |
| LC13 | Subagents with isolated context windows | PROOF_NATIVE | C5 | SHIPPED (P4) | `subagent_bench --depth 8` |
| LC14 | Programmatic tool calling | PROOF_ADJACENT | C5 | NOT_STARTED | `gate_audit` path enumeration |
| LC15 | Per-tool background + intent settings | PLATFORM | C5 | NOT_STARTED | E2E |
| LC16 | Run control: interrupt, steer mid-run, queue follow-ups | PROOF_NATIVE | C5 | NOT_STARTED | steer-mid-proof test; `resume_test` |
| LC17 | Reclaim / edit / escalate pending steers | PROOF_NATIVE | C5 | NOT_STARTED | steer lifecycle test |
| LC18 | Human-in-the-loop: pause for input or tool approval, up to 4 questions per form | PROOF_NATIVE | C5 | NOT_STARTED | HITL pause/resume E2E |
| LC19 | Generated activity-group headers, parent phase summaries, live tool intent labels | PLATFORM | C5 | NOT_STARTED | E2E render; **L31 vocab lint** |
| LC20 | Agent memory with optional per-agent isolation | PROOF_ADJACENT | C10 | NOT_STARTED | memory isolation test |
| LC21 | Context-usage gauge | PLATFORM | C5 | NOT_STARTED | accuracy test vs. real token counts |
| LC22 | Agent stream circuit breakers | PLATFORM | C5 | NOT_STARTED | fault-injection test |
| LC23 | Support-contact exposure, safely | PLATFORM | C10 | NOT_STARTED | redaction test |

### Tools and execution

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC24 | Code interpreter: Python, Node/TS, Go, C/C++, Java, PHP, Rust, Fortran | PROOF_ADJACENT | C8 | NOT_STARTED | `escape_suite --surface code-interpreter`, all tiers, 3 OSes |
| LC25 | Interpreter file handling: upload, process, download | PLATFORM | C8 | NOT_STARTED | round-trip test |
| LC26 | Background code + shell execution | PROOF_ADJACENT | C8 | NOT_STARTED | budget + cancellation test (L15.4) |
| LC27 | Sandbox images returned as viewable artifacts | PLATFORM | C9 | NOT_STARTED | artifact render test |
| LC28 | Stateful interpreter sessions (experimental) | PLATFORM | C8 | NOT_STARTED | session reuse test |
| LC29 | MCP client: stdio + HTTP, OAuth, tool approval | PROOF_NATIVE | C8 | SHIPPED (P5/F16) | `mcp_client_check` 11/11 |
| LC30 | MCP dynamic tool refresh | PROOF_ADJACENT | C8 | NOT_STARTED | refresh test |
| LC31 | MCP parsed response media types | PLATFORM | C8 | NOT_STARTED | media-type test |
| LC32 | MCP runtime OAuth recovery | PLATFORM | C8 | NOT_STARTED | token-expiry recovery test |
| LC33 | Custom actions from OpenAPI specs | PROOF_ADJACENT | C8 | NOT_STARTED | action round-trip test |
| LC34 | Web search: providers + scrapers + rerankers (incl. custom Jina URLs) | PROOF_ADJACENT | C8 | SHIPPED (P9) | `redteam --injection` 30/30 |
| LC35 | Scheduled agent runs | PROOF_ADJACENT | C8 | NOT_STARTED | scheduled run journalled + proof-gated |

### Artifacts and generative UI

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC36 | React / HTML / Mermaid rendered inline | PLATFORM | C9 | NOT_STARTED | render < 100 ms; `escape_suite --surface artifact-renderer` |
| LC37 | Fullscreen artifact preview | PLATFORM | C9 | NOT_STARTED | E2E |
| LC38 | Mermaid export to SVG and PNG | PLATFORM | C9 | NOT_STARTED | export round-trip |
| LC39 | `.potx` PowerPoint templates: upload, search, code execution | PLATFORM | C9 | NOT_STARTED | template round-trip |
| LC40 | Original Office file download from the artifact panel | PLATFORM | C9 | NOT_STARTED | download test |
| LC41 | Shell script upload across common MIME variants | PLATFORM | C8 | NOT_STARTED | MIME matrix test |

### Conversation

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC42 | Fork messages and conversations | PROOF_NATIVE | C7 | NOT_STARTED | fork → both branches proven → verdict comparison |
| LC43 | Conversation branching | PROOF_NATIVE | C7 | NOT_STARTED | as above |
| LC44 | Edit, resubmit, continue | PROOF_NATIVE | C7 | NOT_STARTED | re-proof on resubmit |
| LC45 | Presets: create, save, share → **Proof Profiles** | PROOF_NATIVE | C7 | NOT_STARTED | hierarchical resolution + hot-reload + precedence display |
| LC46 | Prompts with user and group sharing | PLATFORM | C7 | NOT_STARTED | ACL test |
| LC47 | Bookmarks and tags | PLATFORM | C7 | NOT_STARTED | E2E |
| LC48 | Full-text search across all messages and conversations, virtualized | PLATFORM | C7 | NOT_STARTED | 10k-conversation search p95 < 300 ms |
| LC49 | Shared conversations: badge, stable URL, continue-as-personal-copy | PLATFORM | C7 | NOT_STARTED | share lifecycle E2E |
| LC50 | Import from LibreChat, ChatGPT, Chatbot UI | PLATFORM | C7 | NOT_STARTED | import fixture suite |
| LC51 | Export to markdown, JSON, text, screenshot — **with proof bundles attached** | PROOF_NATIVE | C7 | NOT_STARTED | `session_roundtrip --require-runnable-repros` |
| LC52 | Resumable streams: reconnect, resume, multi-tab and multi-device sync | PROOF_NATIVE | C7 | SHIPPED (P2) | `resume_test --kill-mid-proof --sleep-mid-stream` |
| LC53 | Right-aligned user turns, unified multi-part editing, full-message copy, dock-style message rail, smooth streaming | PLATFORM | C3 | NOT_STARTED | visual regression |

### Files, multimodal, RAG

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC54 | Image upload and analysis | PLATFORM | C10 | NOT_STARTED | EXIF + geolocation stripped, test-verified |
| LC55 | Chat with files across all endpoints | PROOF_ADJACENT | C8 | NOT_STARTED | `redteam --injection` on file contents |
| LC56 | RAG: chunking, embedding, retrieval | PROOF_ADJACENT | C8 | NOT_STARTED | local-by-default embedding test; injection suite |
| LC57 | OCR | PROOF_ADJACENT | C8 | NOT_STARTED | injection suite on OCR output; SSRF check |
| LC58 | S3 / CloudFront media addressing, signed cookies, secured downloads | PLATFORM | C8 | NOT_STARTED | adapted to local CAS; cloud remains config |

### Speech and images

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC59 | Speech-to-text (OpenAI, Azure, ElevenLabs) + local path | PLATFORM | C10 | NOT_STARTED | STT round-trip; `egress_check` for the local path |
| LC60 | Text-to-speech + automatic playback | PLATFORM | C10 | NOT_STARTED | TTS test; **vocab lint: no verdict spoken as prose** |
| LC61 | Text-to-image: GPT-Image-1, DALL·E 3/2, Stable Diffusion, Flux, MCP servers | PLATFORM | C10 | NOT_STARTED | generation test; `vocab_check` (never in an evidence surface) |
| LC62 | Image-to-image editing | PLATFORM | C10 | NOT_STARTED | edit round-trip |

### Platform, auth, admin

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC63 | Multi-user auth: OAuth2, LDAP, email | PLATFORM | C10 | NOT_STARTED | LDAP against a real directory; **airplane mode zero auth prompts** |
| LC64 | Admin panel: users, groups, roles, live config overrides | PLATFORM | C10 | NOT_STARTED | adversarial: admin cannot disable the proof gate |
| LC65 | Delegated config sections | PLATFORM | C10 | NOT_STARTED | delegation ACL test |
| LC66 | Encrypted registered secrets; unique temp credentials when blank | PLATFORM | C4 | NOT_STARTED | keychain path test; no plaintext |
| LC67 | Agent marketplace: discovery, community agents, group sharing | PLATFORM | C10 | NOT_STARTED | **unsigned capability-requesting agent must fail to install** |
| LC68 | Moderation | PLATFORM | C10 | NOT_STARTED | moderation policy test |
| LC69 | Token spend tracking, balances, quotas | PROOF_ADJACENT | C4 | SHIPPED (P11) | cap test: 8 threads, cap 2 → exactly 2 |
| LC70 | Langfuse observability: encrypted connections, tenant fan-out, per-run suppression | PLATFORM | C10 | NOT_STARTED | **off by default and provably inert** — own `egress_check` case |
| LC71 | Insights / RUM / telemetry | PLATFORM | C10 | NOT_STARTED | own `egress_check` case each |
| LC72 | SSRF checks for speech, OCR, and web tools | PLATFORM | C10 | NOT_STARTED | SSRF corpus |
| LC73 | 44-locale i18n with managed translation pipeline | PLATFORM | C11 | NOT_STARTED | `i18n_check --no-hardcoded-strings --pseudo-locale --rtl` |
| LC74 | Amazon DocumentDB 5.0+ support / document-store compatibility | PLATFORM | C6 | NOT_STARTED | `store_check`; migration parity |
| LC75 | Rolling-upgrade-safe generation protocol | PLATFORM | C6 | NOT_STARTED | upgrade rehearsal |
| LC76 | Customizable dropdown and interface for power users and newcomers | PLATFORM | C3 | NOT_STARTED | visual regression, 2 themes × 3 viewports × 2 densities |

**Denominator: 76 rows. Parity % is computed over these.**

---

## Part 2 — Tempest capabilities (never reduced, never demoted)

### The engine — shipped

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T01 | Nine-stage differential engine (targets → envrepro → harness → determinism → generate → execute → compare → minimize → bundle) | PROOF_NATIVE | SHIPPED | `make verify`; `corpus_check --min-pass 24 --repeats 5` 30/30 |
| T02 | Four verdicts: `DIVERGENT`, `EQUIVALENT_UNDER_BUDGET`, `UNPROVEN`, `ERROR` | PROOF_NATIVE | SHIPPED | SAFE-grep; exhaustive matching in 3 languages |
| T03 | Determinism layer: clock, random, fs, net, proc record/replay | PROOF_NATIVE | SHIPPED | `corpus_check` 30/30 × 20 |
| T04 | Delta minimization with class-preserving ddmin + standalone repro scripts | PROOF_NATIVE | SHIPPED | property test |
| T05 | Sandbox tier ladder; no tier → `UNPROVEN(SANDBOX_UNAVAILABLE)` | PROOF_NATIVE | SHIPPED | `escape_suite` |
| T06 | Run bundles: schema-versioned, replayable, one producer many renderers | PROOF_NATIVE | SHIPPED | `roundtrip` |
| T07 | `tempest prove` CLI, fully offline, first-class product | PROOF_NATIVE | SHIPPED | `parity --cli-vs-desktop` byte-identical |
| T08 | GitHub Action: PR check + evidence comment | PROOF_NATIVE | SHIPPED | selftest workflow |

### The agent — shipped

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T09 | **F1** Verdict Loop — an agent that cannot claim done | PROOF_NATIVE | SHIPPED | `agent_bench --tasks 50 --require-verdict-coverage 1.0` 55/55 |
| T10 | **F2** Intent Contracts | PROOF_NATIVE | SHIPPED | `intent_bench --min-accuracy 0.90 --max-false-intended 0` 54/54 |
| T11 | **F3** Proof-Guided Repair | PROOF_NATIVE | SHIPPED | `repair_bench --min-success 0.60 --check-cheats` 22/28, 11/11 |
| T12 | **F4** Behavioral Spec Synthesis | PROOF_NATIVE | SHIPPED | every claim cites an observation, type-enforced |
| T13 | **F12** Composer with per-hunk proof preview | PROOF_NATIVE | SHIPPED | `compose_bench --files 500 --selection 10` 11/11 |
| T14 | **F13** Execution-grounded codebase chat and search | PROOF_NATIVE | SHIPPED | `retrieval_bench --questions 40 --require-citations` 40/40 |
| T15 | **F14** Sandboxed agent terminal | PROOF_NATIVE | SHIPPED | `escape_suite --surface agent-terminal` 27/27 |
| T16 | **F15** Project memory + behavioral rules (engine-enforced) | PROOF_NATIVE | SHIPPED | rule holds when the model is told to violate it |
| T17 | **F16** MCP server: `prove`, `explain_behavior`, `minimize_repro`, `check_intent_contract` | PROOF_NATIVE | SHIPPED | `mcp_check` 16/16 |
| T18 | Shadow worktrees (L19) | PROOF_NATIVE | SHIPPED | 38 tests, 100% coverage |
| T19 | Journal + one-keystroke undo (L20) | PROOF_NATIVE | SHIPPED | 12-seed randomized property test |
| T20 | **F11** Inline completion + next-edit prediction with behavioral risk indicator | PROOF_NATIVE | SHIPPED | editor budgets met; input-storm 15 keys/s × 60 s |

### The agent — planned (phases 24–27, unchanged)

| # | Capability | Rel. | Phase | Status | Gate |
|---|---|---|---|---|---|
| T21 | **F9** Adversarial self-validation + `WEAK_EVIDENCE` verdict | PROOF_NATIVE | 24 | PLANNED | `mutation_bench --report-scores` |
| T22 | **F10** Cassette-to-suite (Keploy, VCR, HAR, OTel) | PROOF_NATIVE | 24 | PLANNED | seeded regression caught; scrubber zero-leakage |
| T23 | **F7** De-slop agent | PROOF_NATIVE | 25 | PLANNED | 100% of applied steps carry a bundle; rollback demonstrated |
| T24 | **F8** Proven dead-code elimination | PROOF_NATIVE | 25 | PLANNED | `deadcode_trap --expect-refusals 20`, zero false deletions |
| T25 | **F6** Proven migration agent + canonical value protocol | PROOF_NATIVE | 25 | PLANNED | `migration_bench --ports 20 --bad-ports 5` |
| T26 | **F18** Ambient regression watch | PROOF_NATIVE | 26 | PLANNED | gutter marker < 5 s p50; input-latency delta < 5 ms |
| T27 | **F17** Parallel agent fleet in isolated worktrees | PROOF_NATIVE | 26 | PLANNED | 8 agents within budget; ranking reproducible from bundles |
| T28 | **F5** Semantic merge | PROOF_NATIVE | 27 | PLANNED | zero confidently-wrong merges on 30 real conflicts |
| T29 | **F19** Time-travel debugger | PROOF_NATIVE | 27 | PLANNED | 10k-step scrub < 500 ms |
| T30 | **F20** Team knowledge base | PROOF_ADJACENT | 27 | PLANNED | KB delta on `agent_bench` reported; zero → cut and say so |
| T31 | **F21** Model arena — proof-ranked leaderboard | PROOF_NATIVE | 27 | PLANNED | router beats fixed selection on success-per-dollar over 100 tasks |

### Known-open, carried honestly

| # | Item | Phase | Note |
|---|---|---|---|
| T32 | TypeScript **execution** half: Node worker, determinism shims, V8 precise coverage, type→fast-check compiler, TS corpora | C0 → 3 | Analysis half is done. **Blocks any parity claim that includes TypeScript proving.** |
| T33 | Recorded Claude-Code ↔ Tempest MCP demo | owner | No hermetic gate can assert it |
| T34 | Ten real MCP servers + authorization-code OAuth | owner | |
| T35 | 19.5b — one model path, drop the `anthropic` SDK | C4 | Open since Phase 19 |

---

## Ledger rules

1. **A row moves to `ADOPTED`/`SHIPPED` only when its verifying test has run green with output
   pasted.** No other transition is valid.
2. **Every row has an L30 relationship.** `feature_ledger --every-feature-classified` fails on a blank.
3. **No `PLATFORM` row may reference the reserved verdict vocabulary** in its UI, its colours, or its
   typography. `vocab_check` proves it.
4. **Adding a LibreChat capability adds a row to Part 1** and lowers the parity percentage until it
   is adopted. That is the ledger working, not a regression — upstream ships continuously and the
   denominator is supposed to move.
5. **The README publishes the percentage.** An unpublished parity number is an unmeasured claim,
   which is what L35 exists to prevent.
