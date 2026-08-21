# Tempest AI v2 — Platform Foundations (P1–P14) adopted from LibreChat

> Source: v2.0.0 master prompt §4.5, normative. Legal record: `THIRD_PARTY_LICENSES.md`.
> Decision record: `docs/DECISIONS.md` ADR-0038. Proof-native features: `docs/FEATURES-V2.md`.
>
> **These are platform features, not the differentiator.** They make Tempest feel complete.
> F1–F21 are why anyone switches.

---

## The correct mental model

LibreChat (MIT, ~28k stars) is a **self-hosted multi-user ChatGPT platform**: Node/Express +
React + MongoDB, deployed as a web service. Tempest is a Rust/Tauri + Python + SQLite
**local-first desktop application**. You cannot vendor their codebase, and you should not try.

What you *can* do — and should, aggressively — is treat LibreChat as a **reference
implementation of solved problems**. They have spent years getting multi-provider abstraction,
resumable streaming, and MCP client behavior right in the open. Reading a battle-tested
implementation before writing your own is the single highest-leverage thing available here.

**L25, the discipline: adopt the capability, re-implement it in our stack, subordinate it to
the proof engine.** A LibreChat feature that arrives unchanged is a bolt-on. A LibreChat
feature that arrives wired into the Verdict Loop is a moat extension.

**The test for any adoption, present or future:** *does this make a proof more likely, more
trustworthy, or more legible?* If no, reject it — regardless of how good it looks on a
comparison chart.

## Legal requirements — non-negotiable

- LibreChat is **MIT licensed**: commercial use, modification, and redistribution permitted,
  no copyleft, no network-deployment clause.
- **If any code is copied or closely adapted, the MIT copyright notice and license text must be
  preserved.** `THIRD_PARTY_LICENSES.md` carries the notice and the per-module derivation
  table; it is updated **at the moment of adoption**, not at release. Gated by
  `python -m tempest.dev.license_check --third-party-notices`.
- **Trademarks, logos, and brand assets are NOT licensed.** No LibreChat naming, marks, or
  visual identity anywhere in Tempest; nothing implying endorsement or affiliation.
- Their **RAG API** is a separate repo (`danny-avila/rag_api`) with its own license — reviewed
  independently before anything is adopted from it.
- The MIT grant on existing code is irrevocable and unaffected by the ClickHouse acquisition.
  Do not build on assumptions about a specific future roadmap.

---

## THE FOURTEEN FOUNDATIONS

Each entry: **capability → proof-native wiring → gate → phase.**

---

### P1. Multi-provider endpoint abstraction ⭐ *highest-value adoption*  — Phase 19

**Capability.** Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, Google, Vertex AI, the OpenAI
Responses API, plus any OpenAI-compatible endpoint with no proxy — Ollama, groq, Mistral,
Cohere, together.ai, OpenRouter, Perplexity, DeepSeek, Qwen, Apple MLX, koboldcpp. Study their
endpoint config schema and adapter layer, then **re-implement in Rust**.

**Proof-native wiring.** This *is* the substrate for **F21 Model Arena**. Every provider
supported is another competitor in the objective, proof-ranked leaderboard. Breadth here
directly increases F21's value — which is the rare case where breadth serves the thesis
instead of diluting it. Keys in the OS keychain, never plaintext, never synced (L18).

**Gate.** `python -m tempest.dev.provider_matrix --min-providers 12` — 12+ providers
configurable; a provider is added **without touching feature code** (adapter layer only,
generated from the boundary-D tool schema); all keys in the OS keychain.

### P2. Resumable streams ⭐ *genuinely hard, and they solved it* — Phase 21

**Capability.** Responses reconnect and resume after a dropped connection; sessions sync across
tabs and devices.

**Proof-native wiring.** An agent turn that includes a 60-second proof run **must** survive
sleep, network loss, and app restart. This is the direct implementation of zero-data-loss
(L15.5). Adapted to Tauri: a durable turn journal in SQLite, resumable from any interruption
point, **with the proof stage checkpointed** — a killed turn resumes without re-proving what
was already proven.

**Gate.** `python -m tempest.dev.resume_test --kill-mid-proof --sleep-mid-stream` — kill the
app mid-agent-turn mid-proof, relaunch, the turn resumes with zero lost work; sleep the machine
10 minutes mid-stream, it resumes.

### P3. Agent Skills (`SKILL.md` bundles) — Phase 23

**Capability.** Reusable instruction bundles, invoked manually, automatically, or always-on.

**Proof-native wiring.** Extended to **Proof Skills**: a skill declares required intent
contracts, mandatory mutation-score floors, and forbidden divergence classes. Skills become
**executable policy, not prompt text** — merging cleanly with F15's behavioral rules, and
enforced in the same place: the engine, outside the model.

**Gate.** A Proof Skill's declared floor is enforced by the engine **even when the model is
explicitly instructed to ignore it**.

### P4. Subagents with isolated context windows — Phase 23

**Capability.** Delegate focused work to child agent runs that don't pollute the parent context.

**Proof-native wiring.** This is the missing execution primitive for **F17 Agent Fleet** and
**F7 De-Slop** (each atomic refactor step becomes an independently-proven subagent). Each
subagent gets **its own shadow worktree and its own verdict**.

**Gate.** 8 nested subagents with independent verdicts, correct budget accounting (L21), and
full cancellation propagation.

### P5. MCP client, production-grade — Phase 23

**Capability.** A mature reference MCP client: transport handling, OAuth flow, tool-approval
model.

**Proof-native wiring.** Completes the client half of **F16**. Their tool-approval UX patterns
are worth copying closely. **Every MCP tool response is attacker-controlled input** in the
threat model — never instruction (see `THREAT-MODEL-V2.md` T1/T6).

**Gate.** Connect to 10 real MCP servers including OAuth ones; tool approval respects org
policy; the injection corpus includes MCP-response payloads and does not alter agent behavior.

### P6. Conversation branching, forking, edit-resubmit ⭐ *better here than there* — Phase 28

**Capability.** Fork a conversation, branch context, edit and resubmit.

**Proof-native wiring.** Combined with shadow worktrees this becomes something they cannot do:
**fork an agent run at any turn, take a different approach, and compare branches by verdict.**
Not "which reply do I prefer" but *"branch A is EQUIVALENT_UNDER_BUDGET with a 0.94 mutation
score; branch B is DIVERGENT on 2 inputs."* A behavioral tree of attempts.

**Gate.** Fork from any turn; both branches independently proven; side-by-side verdict
comparison; merge a branch back.

### P7. Presets → Proof Profiles — Phase 28

**Capability.** Saved model + parameter + instruction configurations, shareable.

**Proof-native wiring.** Becomes **Proof Profiles**: model choice, input budget, float
tolerance, required mutation floor, and sandbox tier bundled together. *"Strict mode for
`billing/`, fast mode for `scripts/`."* Shareable across a team via the Phase 13 sync server.

**Gate.** Profiles resolve hierarchically by directory, hot-reload, and display clear
precedence on conflict.

### P8. Artifacts — generative UI in the response stream — Phase 28

**Capability.** React, HTML, and Mermaid rendered inline in chat.

**Proof-native wiring.** The agent renders **behavioral artifacts** — call graphs,
effect-sequence timelines, divergence tables, coverage maps, minimized-input trees — inline and
interactive. **This is how proof evidence stops being a wall of JSON.** Sandboxed renderer,
strict CSP, no arbitrary network.

**Gate.** Artifacts render in <100 ms; the sandbox escape suite covers the artifact renderer;
every artifact is exportable into the run bundle.

### P9. Web search with scraping and reranking — Phase 23

**Capability.** Search providers + content scrapers + rerankers.

**Proof-native wiring.** The agent looks up library docs, changelogs, and migration guides —
feeding **F6 Proven Migration** directly. Retrieved content is **hostile input** in the threat
model, never instruction.

**Gate.** *Security gate, not a feature gate:* an injection corpus embedded in retrieved pages
must not alter agent behavior.

### P10. Enterprise auth: OAuth2, LDAP, email ⭐ *a real gap in the v1 plan* — Phase 29

**Capability.** OAuth2, LDAP, and email auth. LDAP in particular is required by a category of
enterprise buyer the v1 Phase 14 plan does not serve.

**Proof-native wiring.** Extends Phase 14 identity. The architectural difference is
load-bearing: LibreChat is multi-user-server-first; Tempest is **local-first with optional
sync (L8)**. Auth gates *team* features only. **Local operation must never require login.**

**Gate.** LDAP against a real directory; **airplane mode gives full local functionality with
zero auth prompts.**

### P11. Token spend tracking, quotas, moderation — Phase 19

**Capability.** Token accounting, quotas, spend limits.

**Proof-native wiring.** Directly implements L21. Extended with **cost-per-verified-outcome** —
dollars spent per successfully *proven* task, per model. Combined with F21 this is a metric no
competitor can compute, and it is the number a VP of Engineering actually wants.

**Gate.** Cost meter accurate to ±2% against provider billing; **hard caps enforced at the
router, not the UI** (a UI-enforced cap is not a cap).

### P12. Import / export — Phase 28

**Capability.** Import from ChatGPT and Chatbot UI; export as markdown, JSON, text, screenshot.

**Proof-native wiring.** Export an agent session **with its proof bundles attached** — a
portable, replayable record of what changed, why, and what the evidence was. That artifact is
what a developer pastes into a PR description and what an auditor asks for. Arguably the most
enterprise-valuable item in this section.

**Gate.** `python -m tempest.dev.session_roundtrip --export-import --require-runnable-repros` —
an exported session re-imports on another machine with all bundles intact and every repro still
runnable.

### P13. Multimodal input — Phase 28

**Capability.** Image upload and analysis.

**Proof-native wiring.** **Deliberately narrowed**: screenshot a broken UI, a stack trace, a
profiler flamegraph, a whiteboard architecture sketch. General-purpose vision chat is rejected.
Every image is scrubbed of embedded metadata before it reaches any provider.

**Gate.** Screenshot-of-stack-trace → correct file/line navigation. EXIF and geolocation
stripped, verified by test.

### P14. Internationalization — Phase 29

**Capability.** 30+ locales with a managed translation pipeline.

**Proof-native wiring.** v1's plan was "scaffolding only, English ship." Adopt the i18n
*structure* now — dramatically cheaper than retrofitting — and ship English plus the four
locales the enterprise pipeline demands. **All error messages, `reason_code` explanations, and
verdict vocabulary must be translatable**, because those are the strings that matter most: a
verdict a user cannot read is not evidence.

**Gate.** `python -m tempest.dev.i18n_check --no-hardcoded-strings --pseudo-locale --rtl` —
zero hardcoded user-facing strings (lint-enforced); pseudo-locale catches truncation and layout
breakage; RTL layout verified.

---

## EXPLICITLY REJECTED — and why this list matters as much as the one above

The owner asked for "all the features." **Taking all of them would make Tempest worse.** Each
rejection has a stated reason. If you disagree, overturn it **with an ADR, not by drifting** —
and a future contributor reading this must be able to see why image generation is absent rather
than "helpfully" adding it.

> **OVERTURNED — 2026-08-21, v3 convergence (owner decision).** All six rejections below were
> overturned exactly the way this section demands: with ADRs, not drift. Image generation →
> ADR-0063 · TTS/STT → ADR-0065 · agent marketplace → ADR-0066 (**partial**: mandatory capability
> signing is retained — the supply-chain threat named below is real and survives the overturn) ·
> chat as the primary surface → ADR-0067 · MongoDB → ADR-0068 (the data model and wire protocol
> only; the SSPL binary still never ships) · general-assistant framing → ADR-0069. The table is
> retained verbatim below because its reasons are the constraints those ADRs carry forward.
> Normative scope now: `docs/TEMPEST-V3-MASTER-PROMPT.md` §5, `docs/FEATURES-V3.md`.

| Rejected | Why |
|---|---|
| **Image generation** (DALL·E, Flux, Stable Diffusion, GPT-Image) | Zero proof story, zero relationship to code correctness. Pure surface area. It is the single clearest signal that a product has lost its thesis. |
| **Text-to-speech / audio playback** | Nobody listens to code. Speech-to-text *input* is defensible later; TTS output is not. |
| **Agent Marketplace (open community bazaar)** | For a tool with file-write and shell access, an open marketplace is a supply-chain attack surface aimed directly at the most security-sensitive customers. **Replaced with:** a signed, curated, org-scoped Proof Skill registry with mandatory review. |
| **Chat as the primary surface** | Tempest's primary surface is the editor and the evidence view. Chat is a panel. Making it a ChatGPT clone with a proof feature inverts the product. |
| **MongoDB** | SQLite local, Postgres server. Do not introduce a third datastore. |
| **General-purpose assistant framing** | "Do anything" is the opposite of "prove this." Every general capability added dilutes the one sentence that sells this product. |

---

## The sequencing rule that protects all of this

**Platform features (P*) never precede the proof feature they serve.** Building conversation
branching before the Verdict Loop gives you a chat app. Building it after gives you a
behavioral decision tree. *Same code, completely different product.*

| Phase | Platform work | Serves |
|---|---|---|
| 19 | P1 providers, P11 cost | F21 arena, L21 |
| 21 | P2 resumable turns | F1 verdict loop, L15.5 |
| 23 | P3 skills, P4 subagents, P5 MCP client, P9 web search | F15, F17/F7, F16, F6 |
| 28 | P6 branching, P7 profiles, P8 artifacts, P12 export, P13 multimodal | F1 comparison, evidence legibility |
| 29 | P10 auth, P14 i18n | enterprise reach |

**Failure mode 9, the specific risk this section introduces:** LibreChat is an excellent
general-purpose assistant platform, and general-purpose is the exact opposite of what makes
Tempest defensible. If the chat panel ever becomes the primary surface, or if a single adopted
feature ships without proof-native wiring, we have drifted. Re-read L25.

> **v3 note (2026-08-21).** Chat as the primary surface is now the design (ADR-0067), and this
> failure mode is **upgraded, not deleted**: ADR-0067 names the structural mechanisms — L28
> (every path proof-gated, forge test per path), L31 (verdict vocabulary reserved, lint-proven),
> L35 (parity ledger tracks proof features at the same rigour), and master prompt §13.2 (a week
> with no proof work landed is drift, said out loud) — that keep chat-primary from becoming
> exactly this failure. L25's adoption test is superseded by L30's honest classification
> (`PROOF_NATIVE` / `PROOF_ADJACENT` / `PLATFORM`), gated by `feature_ledger`.
