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
> **Parity numerator (ADR-0088):** a row counts toward parity when its status is `ADOPTED` or `SHIPPED`.
> `SHIPPED` marks a LibreChat capability a pre-existing Tempest feature already satisfies, and
> "does Tempest have this capability?" is the only question a parity number is asked — excluding it
> would understate parity and reward re-implementing what the product already has. The denominator is
> **Part 1 only**: counting Part 2 would let Tempest raise its LibreChat-parity score by shipping
> features LibreChat does not have. Published in the README, enforced by `parity_ledger`, and required
> to be 100% at GA.
>
> **C0 note (2026-08-21):** Part-1 row ids use the `LC` prefix (LC01…LC76). The original draft's
> `L` prefix shadowed the Law numbers (a row "L28" beside Law L28, the proof gate) inside the one
> file both are cited in; renamed before `parity_ledger` is built against these ids.

---

## Part 1 — LibreChat capabilities (the parity denominator)

### Providers and models

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC01 | Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, Google, Vertex AI, OpenAI Responses API | PROOF_ADJACENT | C10 | IN_PROGRESS | `provider_matrix --min-providers 16` green, and it enumerates what is there: anthropic, openai, azure-openai, google-gemini. **AWS Bedrock, Vertex AI and the OpenAI Responses API have no registry row**, so four of seven named endpoints exist — measured 2026-08-24, ADR-0088 |
| LC02 | Any OpenAI-compatible endpoint, no proxy (Ollama, groq, Mistral, Cohere, together.ai, OpenRouter, Perplexity, DeepSeek, Qwen, Apple MLX, koboldcpp, Helicone, ShuttleAI) | PROOF_ADJACENT | C10 | IN_PROGRESS | `provider_matrix` green over 14 OpenAI-wire endpoints incl. ollama, groq, mistral, together, openrouter, perplexity, deepseek. **`ANY` is not yet true for a user**: reaching an unlisted endpoint means a registry row or an env override, and user-authored custom endpoints ride the real Config service — C4's own scope note says C6/C10 (ADR-0088) |
| LC03 | Model specs + per-endpoint parameter controls | PLATFORM | C12 | IN_PROGRESS | The capability shipped in C4 and the plan records its mechanics in full: model-spec metadata adopted from upstream's `defaultModels` at the vendored commit, served from the ONE registry through `GET /v1/platform/catalog`, parameter UI lighting up from the client's own per-type tables with zero client edits (`267350a`+`c2efc6b`+`5af38d1`). **It is NOT `ADOPTED`, and this row is the worked example of why (ADR-0088 §5a).** It was promoted to `ADOPTED` during C5's close-out on two cited tests, and an independent audit showed neither verifies it: `test_the_catalog_cross_checks_both_wires_against_the_manifest` is about the AGENT TOOL catalog, and `the_host_decorates_catalog_rows_with_badge_urls_by_provider_id` asserts icon badge URLs. Ledger rule 1 admits no exception for a capability that is obviously built. To move: a test that reads the catalog route and asserts model-spec metadata and per-endpoint parameter shapes for a keyed and a keyless provider |
| LC04 | Reasoning UI for chain-of-thought models | PLATFORM | C5 | ADOPTED | ADR-0081: a reasoning model's thinking is its own content channel. `test_anthropic_thinking_deltas_are_reasoning_and_never_text` and `test_a_completion_carries_reasoning_beside_its_text` pin that reasoning frames stay OUT of the text channel; driven by hand on 24 Aug — a real Qwen3 answer rendered its reasoning in a Thoughts block. Before it, 29 frames of `reasoning_content` and zero of `content` rendered an EMPTY bubble |
| LC05 | Mid-chat endpoint and preset switching | PLATFORM | C7 | NOT_STARTED | E2E switch test |
| LC06 | Adaptive provider smoothing + stream delta batching | PLATFORM | C5 | ADOPTED | read-side seq-preserving delta coalescing on both replay paths (`test_chat_turn` concatenation/cursor/no-hole pins, ADR-0079 §7); the vendored client's own pacing rides C3 |
| LC07 | Configurable HTTP timeouts | PLATFORM | C10 | NOT_STARTED | timeout unit test |

### Agents

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC08 | No-code agent builder | PROOF_NATIVE | C5 | ADOPTED | `agent_bench` 55/55 through the re-target; e2e 23 (create→persist→editable) + 24 (a built agent's turn through `run_task`) |
| LC09 | Unified Tools marketplace (builder-side) | PROOF_NATIVE | C5 | ADOPTED | `runtime_check --single-tool-registry`; e2e 23 pins the Tool Library = the boundary-D manifest |
| LC10 | Agent sharing to users and groups | PLATFORM | C10 | NOT_STARTED | ACL test |
| LC11 | `SKILL.md` bundles — manual / automatic / always-on | PROOF_NATIVE | C8 | IN_PROGRESS | **Re-classified 2026-08-24 (ADR-0088 §5a, after an independent audit refuted the first reading).** The `SHIPPED (P3)` claim was wrong — P3 landed the engine-enforced Proof Skill FLOOR, merged into F15's behavioural rules (`rules.py`, reading `.tempest/rules/*.toml`), and the test the row cited is T16's. But the LibreChat implementation is VENDORED and partly built: `parseSkillMd` and `InvocationModePicker` ship inside the mounted client, and the manual/automatic/always-on triad (`userInvocable` / `disableModelInvocation` / `alwaysApply`) is in the built provider package. What is missing is the half that would make it work — `packages/platform/api` is not in `pnpm-workspace.yaml` until C5/C6, so `SKILL_MANIFEST_FILE` is never served, no Tempest seam wires it, and no test verifies it. Present, not usable, not at parity |
| LC12 | Agent plugins bundling skills + MCP servers | PROOF_ADJACENT | C8 | NOT_STARTED | plugin install + capability signature test |
| LC13 | Subagents with isolated context windows | PROOF_NATIVE | C5 | SHIPPED (P4) | `subagent_bench --depth 8` |
| LC14 | Programmatic tool calling | PROOF_ADJACENT | C5 | ADOPTED | `gate_audit` 6 declared+forged paths incl. agent-chat-surface; `test_agent_turn` dispatch pins |
| LC15 | Per-tool background + intent settings | PLATFORM | C8 | NOT_STARTED | Deferred to C8 by ADR-0079's Consequences ("per-tool background/intent settings (C8, with background execution)") — the decision exists and is NOT to be rebuilt here; phase corrected from C5, which was closed, 2026-08-24 (ADR-0088). Future test: E2E over a per-tool background toggle once background execution lands with LC26 |
| LC16 | Run control: interrupt, steer mid-run, queue follow-ups | PROOF_NATIVE | C5 | ADOPTED | cancel threads TaskSpec→model call→ProveConfig (`TestRunControl`); steer drain pins (`TestSteering`/`TestSteeringWire`); `resume_test` 15/15 |
| LC17 | Reclaim / edit / escalate pending steers | PROOF_NATIVE | C5 | ADOPTED | `TestSteering` pins the lifecycle (`test_a_queued_steer_reaches_the_next_model_call`, `test_no_steer_source_changes_nothing`); the wire's `resume_and_steer_are_never_mis_started` (cargo, `agent_chat.rs`) pins that the preempt arm answers `PREEMPT_UNSUPPORTED` rather than pretending — ADR-0079 §4 |
| LC18 | Human-in-the-loop: pause for input or tool approval, up to 4 questions per form | PROOF_NATIVE | C5 | ADOPTED | e2e `24-agent-turn.spec` — *an agent turn parks on approval, runs the tool, and finishes durably*; engine pins `test_an_approval_runs_the_tool_and_the_park_was_durable`, `test_an_approver_raising_cancellation_unwinds_the_task` and `test_ask_user_without_an_approver_refuses_honestly` (the handler refuses rather than letting the model answer in the user's voice); wire pins `test_approval_round_trips_and_the_command_runs`, `test_a_decision_verb_outside_approve_or_reject_is_refused` and `test_cancel_while_parked_aborts_promptly`. `ask_user` is a boundary-D tool (AlwaysPrompt, writes nothing) |
| LC19 | Generated activity-group headers + live tool intent labels | PLATFORM | C5 | ADOPTED | e2e 24: the header GROUPS its batch (a `button` named for the label, containing the call) — the vendored grouper claims only parts BEFORE the label, so this fails if the ordering regresses; `test_the_activity_header_follows_the_calls_it_covers` pins the part order; `vocab_check` green (labels are functions of the tool kind — L17/L31, ADR-0079 §5) |
| LC19b | Parent phase summaries over an activity group | PLATFORM | C8 | NOT_STARTED | a group's summary line, generated MECHANICALLY (L17 forbids a model writing it); rides C8 with per-tool background/intent settings |
| LC20 | Agent memory with optional per-agent isolation | PROOF_ADJACENT | C10 | NOT_STARTED | memory isolation test |
| LC21 | Context-usage gauge | PLATFORM | C5 | ADOPTED | counts are the provider's own per turn (`TestContextGauge`); denominator only where documented — unknown renders indeterminate, never invented (ADR-0079 §6) |
| LC22 | Agent stream circuit breakers | PLATFORM | C5 | ADOPTED | **Evidence corrected 2026-08-24 (ADR-0089).** `the_stream_gives_up_on_a_missing_engine_within_a_bounded_window` and `the_breaker_outlasts_a_restart_but_not_a_users_patience` pin the TIME bound (cargo) but inject nothing — they are arithmetic over `Instant`s — and e2e 06 drives the masthead health probe with no chat turn in flight. Between them they left the breaker's OUTPUT undriven, and it was broken: the host emitted `status: "error"` with no events and the transport read only frames, so the stream froze OPEN. Now pinned end to end by `the_host_s_circuit_breaker_reaches_the_reader_as_an_error_not_a_frozen_stream` and `a_breaker_that_fires_while_the_page_is_in_flight_is_not_lost_to_the_hold_queue`, both mutation-proven |
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
| LC34 | Web search: providers + scrapers + rerankers (incl. custom Jina URLs) | PROOF_ADJACENT | C8 | IN_PROGRESS | **Re-classified 2026-08-24 (ADR-0088 §5a).** `redteam --injection` (green, 35/35) proves P9's proof-native WIRING — retrieved bytes treated as hostile, delivered through a file, a tool result and an MCP response — which is exactly what PLAN-V2's P9 box claims and all it claims. It does not exercise a web search. The vendored provider package (which IS built) declares `SearchProvider` serper/searxng/tavily, `ScraperProvider` firecrawl/serper/tavily, `RerankerType` infinity/jina/cohere and a configurable `jinaApiUrl`; the implementation behind them lives in `packages/platform/api`, which is not in the workspace build. Tempest's own side has no `web_search` on boundary D (seven tools: `read_file`, `list_dir`, `search_text`, `write_file`, `run_command`, `prove`, `ask_user`) and forwards `/api/agents/tools/web_search/auth` to a node seam stub. Declared, not reachable, not at parity |
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
| LC52 | Resumable streams: reconnect and resume across the process that ran the turn | PROOF_NATIVE | C7 | SHIPPED (P2) | `resume_test --kill-mid-proof --sleep-mid-stream` 15/15 — a real `SIGKILL` mid-proof, resumed by a second process on the same shadow and baseline without asking the model anything |
| LC52b | Multi-tab and multi-device stream sync | PLATFORM | C7 | NOT_STARTED | **Split out of LC52 on 2026-08-24 (ADR-0088)**, on the LC19b precedent: `resume_test` proves survival of the PROCESS, and nothing in it — or anywhere in the tree — concerns a second tab or a second device. No `BroadcastChannel`, storage-event or device-sync path exists. Future test: two attached surfaces observing one run |
| LC53 | Right-aligned user turns, unified multi-part editing, full-message copy, dock-style message rail, smooth streaming | PLATFORM | C12 | IN_PROGRESS | The vendored client renders all five and has since C3 mounted it; `99-screenshots.spec` captures every view in light and dark. It CAPTURES but does not COMPARE — there is no committed baseline, so no visual regression can fail, and under ledger rule 1 that is not a green verifying test. Phase moved off closed C3 to C12, where the visual and a11y gates land (ADR-0088) |

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
| LC66 | Encrypted registered secrets; unique temp credentials when blank | PLATFORM | C10 | IN_PROGRESS | First half done in C4 (`c2efc6b`/`5af38d1`): `credentials.ts` replaced by the OS keychain path, `/api/keys` answered from the keychain for presence, storage and revocation, values never in a response, error or log; `redaction_check --planted-secrets` green over the BYOK key shape. Second half — a unique temp credential when the field is blank — is a multi-user concept and rides C10 with LC63. Phase moved off C4 (ADR-0088) |
| LC67 | Agent marketplace: discovery, community agents, group sharing | PLATFORM | C10 | NOT_STARTED | **unsigned capability-requesting agent must fail to install** |
| LC68 | Moderation | PLATFORM | C10 | NOT_STARTED | moderation policy test |
| LC69 | Token spend tracking, balances, quotas | PROOF_ADJACENT | C4 | SHIPPED (P11) | `test_agent_cost` pins the ledger scopes and both caps (`test_a_breached_cap_ends_the_loop_and_STILL_proves_what_was_staged`, `test_a_session_cap_binds_across_tasks`); `test_a_cap_the_fleet_shares_stops_the_later_children` is the 8-threads-against-a-cap-admitting-2 case. Scope: local-first single-user, so multi-user *balances* are not a Tempest concept — the spend meter and its caps are |
| LC70 | Langfuse observability: encrypted connections, tenant fan-out, per-run suppression | PLATFORM | C10 | NOT_STARTED | **off by default and provably inert** — own `egress_check` case |
| LC71 | Insights / RUM / telemetry | PLATFORM | C10 | NOT_STARTED | own `egress_check` case each |
| LC72 | SSRF checks for speech, OCR, and web tools | PLATFORM | C10 | NOT_STARTED | SSRF corpus |
| LC73 | 44-locale i18n with managed translation pipeline | PLATFORM | C11 | NOT_STARTED | `i18n_check --no-hardcoded-strings --pseudo-locale --rtl` |
| LC74 | Amazon DocumentDB 5.0+ support / document-store compatibility | PLATFORM | C6 | NOT_STARTED | `store_check`; migration parity |
| LC75 | Rolling-upgrade-safe generation protocol | PLATFORM | C6 | NOT_STARTED | upgrade rehearsal |
| LC76 | Customizable dropdown and interface for power users and newcomers | PLATFORM | C12 | IN_PROGRESS | Upstream's interface-customization surface ships inside the mounted client (C3) and the design-token seam restyles it; as with LC53 the verifying test named here — visual regression across 2 themes × 3 viewports × 2 densities — does not exist, only `99-screenshots.spec`'s capture. Phase moved off closed C3 to C12 (ADR-0088) |

**Denominator: 78 rows. Parity % is computed over these.**

> LC19 was split during the C5 close-out. Its single row had claimed activity headers, live
> tool intent labels AND parent phase summaries, while only the first two are built and tested;
> the third is now its own `NOT_STARTED` row. That LOWERS the parity percentage, which is
> ledger rule 4 working as written — an unbuilt capability hidden inside an `ADOPTED` row is
> exactly the unmeasured claim L35 exists to prevent.
>
> **2026-08-24, ADR-0088 — what the first run of `feature_ledger --verifying-tests-resolve`
> found.** Three rows claimed a LibreChat capability on the strength of a test that verifies a
> different one, which is the same defect as LC19's and was invisible while nothing read this
> file:
>
> * **LC11** cited "Proof Skill floor holds when the model is told to ignore it" — which is
>   T16's test, for F15's behavioural rules. P3 shipped the enforced FLOOR; `SKILL.md` bundles
>   and their three invocation modes do not exist. Demoted to `NOT_STARTED`, C8.
> * **LC34** cited `redteam --injection`, which proves retrieved bytes are treated as hostile.
>   That is P9's proof-native WIRING; there is no web search to wire it to. Demoted, C8.
> * **LC52** bundled reconnect/resume (real, `resume_test`) with multi-tab and multi-device
>   sync (no code anywhere). Split on the LC19b precedent; LC52b carries the unbuilt half.
>
> Two rows moved the OTHER way — the ledger under-claimed. **LC03** was `NOT_STARTED` while C4
> had recorded model specs and per-endpoint parameter UI as done, and **LC04** was `NOT_STARTED`
> while ADR-0081 had shipped the reasoning channel and it had been driven by hand. A ledger
> nothing reads goes stale in both directions at once.

---

## Part 2 — Tempest capabilities (never reduced, never demoted)

### The engine — shipped

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T01 | Nine-stage differential engine (targets → envrepro → harness → determinism → generate → execute → compare → minimize → bundle) | PROOF_NATIVE | SHIPPED | `make verify`; `corpus_check --min-pass 24 --repeats 5` 30/30 |
| T02 | Four verdicts: `DIVERGENT`, `EQUIVALENT_UNDER_BUDGET`, `UNPROVEN`, `ERROR` | PROOF_NATIVE | SHIPPED | `test_verdict_vocabulary_is_exactly_the_four_lawful_verdicts`; the `SAFE` grep in `verify-grep-safe` + the `forbidden-verdict-grep` CI job; exhaustive matching in three languages (Rust `match` with no wildcard, TS `never` guard, Python `assert_never`) |
| T03 | Determinism layer: clock, random, fs, net, proc record/replay | PROOF_NATIVE | SHIPPED | `corpus_check` 30/30 × 20 |
| T04 | Delta minimization with class-preserving ddmin + standalone repro scripts | PROOF_NATIVE | SHIPPED | `test_property_minimized_input_always_still_diverges` (Hypothesis) plus `test_never_returns_a_non_diverging_input` and `test_shrink_path_is_recorded` in `test_minimize` |
| T05 | Sandbox tier ladder; no tier → `UNPROVEN(SANDBOX_UNAVAILABLE)` | PROOF_NATIVE | SHIPPED | `escape_suite` |
| T06 | Run bundles: schema-versioned, replayable, one producer many renderers | PROOF_NATIVE | SHIPPED | `roundtrip` |
| T07 | `tempest prove` CLI, fully offline, first-class product | PROOF_NATIVE | SHIPPED | `parity --cli-vs-desktop` byte-identical |
| T08 | GitHub Action: PR check + evidence comment | PROOF_NATIVE | SHIPPED | the `tempest-selftest` workflow runs the composite action against this repository on every push; `test_ci_comment` pins the evidence comment's shapes |

### The agent — shipped

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T09 | **F1** Verdict Loop — an agent that cannot claim done | PROOF_NATIVE | SHIPPED | `agent_bench --tasks 50 --require-verdict-coverage 1.0` 55/55 |
| T10 | **F2** Intent Contracts | PROOF_NATIVE | SHIPPED | `intent_bench --min-accuracy 0.90 --max-false-intended 0` 54/54 |
| T11 | **F3** Proof-Guided Repair | PROOF_NATIVE | SHIPPED | `repair_bench --min-success 0.60 --check-cheats` 22/28, 11/11 |
| T12 | **F4** Behavioral Spec Synthesis | PROOF_NATIVE | SHIPPED | `test_a_claim_cannot_be_constructed_without_evidence` (the type refuses it) and `test_every_claim_carries_at_least_one_observation`; `test_a_symbol_nothing_ran_gets_no_claims_and_says_why` pins the honest empty case |
| T13 | **F12** Composer with per-hunk proof preview | PROOF_NATIVE | SHIPPED | `compose_bench --files 500 --selection 10` 11/11 |
| T14 | **F13** Execution-grounded codebase chat and search | PROOF_NATIVE | SHIPPED | `retrieval_bench --questions 40 --require-citations` 40/40 |
| T15 | **F14** Sandboxed agent terminal | PROOF_NATIVE | SHIPPED | `escape_suite --surface agent-terminal` 27/27 |
| T16 | **F15** Project memory + behavioral rules (engine-enforced), carrying P3's Proof Skill floor | PROOF_NATIVE | SHIPPED | `test_it_holds_when_the_model_is_told_to_ignore_it` in `TestARuleIsAWall` — the rule is read from disk by the host and consulted after the model's turn, so nothing the model emits is on that path. **This is also the test LC11 was wrongly discharging itself with (ADR-0088): it verifies the enforced floor, which is P3's, not `SKILL.md` bundles** |
| T17 | **F16** MCP server: `prove`, `explain_behavior`, `minimize_repro`, `check_intent_contract` | PROOF_NATIVE | SHIPPED | `mcp_check` 16/16 |
| T18 | Shadow worktrees (L19) | PROOF_NATIVE | SHIPPED | `test_agent_shadow` — 38 tests at 100% coverage, incl. `test_a_directory_git_never_registered_is_also_reclaimed` |
| T19 | Journal + one-keystroke undo (L20) | PROOF_NATIVE | SHIPPED | `test_agent_journal` — a 12-seed randomized property test over journal/undo round-trips |
| T20 | **F11** Inline completion + next-edit prediction with behavioral risk indicator | PROOF_NATIVE | SHIPPED | e2e `14-editor-budgets.spec` measures the §5 editor budgets and writes them for `perf_suite`; e2e `17-input-storm.spec` holds 15 keys/s for 60 s with zero dropped keystrokes |

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
| T36 | **Local model downloads** — a curated free-and-permissive catalogue, fetched in-app with resume + sha256 verification, deletable, sizes shown before the spend (ADR-0080) | PLATFORM | C5 | ADOPTED | e2e spec 25 downloads a model through the REAL panel and the progress bar MOVES (mutation-proven: with the poll disabled the spec fails), stops mid-body and resumes from the partial with a `Range:` past zero, and removes it; `egress_check` huggingface ledger closed in both directions; 57 downloader pins incl. the byte budget, `Content-Range`, the 416 arm, and cancel observed at the fd; **airplane mode: every outbound call refused and an installed model still resolves, with the `llamacpp` row pinned loopback** |
| T37 | **Local model serving** — a supervised loopback `llama-server` child, off by default, appearing in the existing picker through the `llamacpp` row (ADR-0080 §1) | PLATFORM | C5 | ADOPTED | a REAL child is started, probed, statused and swept with its port (mutation-proven: a `stop()` that forgets the child leaves the port answering); the spawned ARGV is read rather than the constant beside it; the exit sweep's membership fails on a commented-out call; a busy port is refused rather than adopted; a dead child stops being reported as serving; `orphan_check --all-children --after-sigkill` ORPHAN_EXIT=0 with zero TCP listeners; the refusal names Tempest's OWN `runners/` folder first (a place the user can always put a file), then the official `bin-macos-arm64` release, with `brew` only as a secondary — `resolve_runner_in` is passed an EMPTY search path so the refusal is reachable on every machine, including one that already has a runner. **Scope, corrected 2026-08-24 (ADR-0088).** The hermetic tests still prove the SUPERVISION with a stub, because no CI runner has a `llama-server`. What is no longer true is the rest of that sentence: on 24 Aug a real llama.cpp b10612 in `~/Library/Application Support/com.prithvi.tempest/runners/` served a real Qwen3-0.6B-Q8_0, resolved from Tempest's own folder by a Finder-launched app, and was chatted with by hand — reasoning in a Thoughts block, the model named in the header. T38 (bundle a signed runner) remains open, so zero-setup is still one install away. |

### Known-open, carried honestly

| # | Item | Phase | Note |
|---|---|---|---|
| T32 | TypeScript **execution** half: Node worker, determinism shims, V8 precise coverage, type→fast-check compiler, TS corpora | C0 → 3 | Analysis half is done. **Blocks any parity claim that includes TypeScript proving.** |
| T33 | Recorded Claude-Code ↔ Tempest MCP demo | owner | No hermetic gate can assert it |
| T34 | Ten real MCP servers + authorization-code OAuth | owner | `mcp_client_check` drives a real stdio peer and the client implements OAuth 2.0 client-credentials (the flow a headless client can complete); AUTHORIZATION-CODE needs a browser round trip and ten real third-party servers need accounts, so neither is hermetically gateable. Note added 2026-08-24 — the row had carried no reason at all (ADR-0088) |
| T35 | 19.5b — one model path, drop the `anthropic` SDK | C4 | Open since Phase 19 |
| T38 | Bundle a signed `llama-server` per platform | C8 | ADR-0080 §6. Until then the feature is one `brew install` short of zero-setup, and says so in the refusal rather than hiding it. |

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
