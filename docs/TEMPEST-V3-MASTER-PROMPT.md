# Tempest AI v3.0.0 — THE CONVERGENCE MASTER PROMPT

> **Normative.** This document supersedes the v2.0.0 master prompt where they conflict, and only
> where they conflict. Laws L1–L26 in `CLAUDE.md` all still bind. Every deviation from this
> document is an ADR in `docs/DECISIONS.md` — deviating silently is a build failure.
>
> Supporting normative documents, written alongside this one and referenced throughout:
> `docs/MERGE-CONTRACT.md` (subsystem dispositions) · `docs/PLAN-V3.md` (phases C0–C12 with gates) ·
> `docs/FEATURES-V3.md` (the unified feature ledger — every LibreChat feature, every Tempest
> feature, one table) · `docs/DECISIONS-V3-ADDENDUM.md` (ADR-0063 … ADR-0074, including the six
> rejections this release formally overturns).

---

## 0. HOW TO USE THIS PROMPT

You are Claude Code, working in the `Tempest-AI` repository. This is a multi-month build across
many sessions. Read this section before anything else.

### 0.1 Every session begins the same way

```
1. Read CLAUDE.md            → the session contract, Laws L1–L36
2. Read this file            → the convergence mandate
3. Read docs/PLAN-V3.md      → find the FIRST unchecked box; that is your work
4. Read docs/MERGE-CONTRACT.md for the subsystem you are about to touch
5. Read docs/DECISIONS.md for any ADR the plan item names
6. Run `make verify-v3` BEFORE writing code — know the tree's real state, not its claimed state
```

Then, and only then, write code.

### 0.2 The completion rule, restated because it is the rule most often broken

**You may not write the words "done", "complete", "working", "passing", "integrated", or "zero
errors" without pasting the actual terminal output of the relevant gate command in the same
message.** Claimed-passing is treated as failing. A gate that has never been executed is a claim,
not a fact. A checkbox flipped without pasted output is a lie in the repository's history, and the
repository's history is the only thing that makes any of the rest of this credible.

### 0.3 Work order

- **One plan item at a time.** Land it green, with a gate, with an ADR if it deviated, then stop
  and report. Do not batch five items and present a wall.
- **No subagents** for plan execution (owner preference, unchanged from v1/v2). Subagents may be
  used for read-only reconnaissance of the LibreChat tree.
- **TDD, strictly.** Failing test → minimal implementation → refactor. Property-based tests for
  anything touching comparison, minimization, cassettes, or the merge seams.
- **Small conventional commits**, one logical change each.
- **No TODO-as-deferral.** Undone work is a `docs/PLAN-V3.md` item, never a comment.

### 0.4 When you are blocked or the prompt is wrong

The prompt will be wrong somewhere — it was written from outside the code. When it is:
**stop, write the ADR, and say so.** Do not silently do something else, and do not implement
something you can see is wrong because the document said to. An ADR that overturns a line of this
prompt with real evidence is the single most valuable artifact you can produce.

---

## 1. WHAT YOU ARE BUILDING

**One sentence, and every decision below serves it:**

> **Tempest is the AI application people use instead of ChatGPT and Claude — a complete,
> beautiful, local-first desktop app with every capability of the best open-source chat platform
> ever built, and one thing none of them have: it can prove that the code it wrote does what it
> said it does.**

Two halves, both mandatory, neither optional:

**The platform half.** Everything LibreChat does. Every provider, every agent capability, every
tool, artifacts, code interpreter, image generation, speech in and out, web search, RAG and file
chat, memory, prompts and presets, conversation forking and branching, import/export, search,
sharing, multimodal, the agent builder, the marketplace, the admin panel, 44 locales, resumable
streams, auth. Not a subset. Not "the important ones." **All of it**, at LibreChat's level of
finish or better.

**The proof half.** Everything Tempest does. The nine-stage differential engine, the Verdict Loop,
intent contracts, proof-guided repair, behavioral spec synthesis, execution-grounded search, the
composer with proof preview, shadow worktrees, the journal and one-keystroke undo, the four
verdicts, MCP in both directions, the sandbox tier ladder. Not demoted to a tab. **Wired through
the platform half so that it changes what the platform half means.**

The product is neither "LibreChat with a proof plugin" nor "Tempest with a chat panel." It is
**one application** in which the chat surface is where you work, and the proof engine is what
makes the work trustworthy. A user who never opens the proof view still gets a better ChatGPT.
A user who does gets something that does not exist anywhere else at any price.

### 1.1 The strategic sentence

Every other assistant tells you it is done. **Tempest shows you the evidence — or tells you,
honestly, that it could not get any.** That sentence is the entire moat. Every feature in this
document either serves it or is subordinate to it. Nothing in this document contradicts it.

---

## 2. GROUND TRUTH — THE TREE AS IT ACTUALLY IS

Do not rediscover this. It was verified against both repositories at HEAD on 2026-08-21.

### 2.1 Tempest-AI (this repo) — what exists and is green

```
packages/engine/          Python 3.12, mypy --strict. THE PRODUCT.
  targets/ envrepro/ harness/ determinism/ generate/ execute/ compare/ minimize/ bundle/
                          ← the nine stages, all live
  agent/                  ← orchestrator, shadow worktrees, journal (Phase 21)
  index/                  ← vector + structural + execution indices (Phase 22)
  inference/              ← 16 providers over 2 wires, cost meter (Phase 19)
  compose/                ← per-hunk proof attribution (Phase 23)
  mcp/                    ← MCP server: prove, explain_behavior, minimize_repro,
                            check_intent_contract
  cli/                    ← typer app; `tempest prove` end-to-end
  dev/                    ← 24 gate modules (agent_bench, intent_bench, repair_bench,
                            retrieval_bench, redteam, perf_suite, license_check, escape_suite,
                            provider_matrix, resume_test, subagent_bench, compose_bench, …)

packages/desktop/         Tauri v2. THE SHELL.
  src-tauri/src/          agent_tools.rs, supervisor.rs, keychain.rs, pathguard.rs, lsp.rs,
                          localmodel.rs, runners.rs, watcher.rs, framing.rs, commands.rs
  src/                    React webview: editor/, views/, generated/, vocabulary.tsx

packages/api/             FastAPI. The desktop's stdio sidecar + the Phase 13 sync server.
                          NOT a deployed web backend.
packages/ts-sidecar/      Node 22, ts-morph, JSON-RPC over stdio.
packages/shared-schema/   Generated OpenAPI + TS types + the four agent-tool artifacts.
action/                   Composite GitHub Action.
corpus/                   Real fixture repos: pyfix, tsfix, impure (30 functions).
```

**Phases 0–23 complete**, each with pasted gate output. Phases 24–32 planned in `docs/PLAN-V2.md`
and **still in scope** — see §8.6 for how they interleave with the convergence work.

**Known-open items you must not treat as done** (they are honestly marked in the tree and you
will inherit them): Phase 3's TypeScript *execution* half (analysis is done, the Node execution
worker and V8 coverage are not); the Claude-Code↔Tempest MCP demo recording (owner action); ten
real MCP servers with authorization-code OAuth (owner action); `19.5b` migrating `harness/llm.py`
and `report/narrative.py` onto the unified model client and dropping the `anthropic` SDK.

> **[C0 correction, 2026-08-21 — measured against the tree, original text retained above.]**
> The TypeScript sentence is stale: the Node execution worker and V8 precise coverage SHIPPED in
> ADR-0028 (wave 1 — `execute/ts_worker.mjs`, `execute/ts_shims.mjs`, `execute/ts_dual.py`,
> tsfix corpus 8/8 inside `make verify`). What is genuinely open is **TS wave 2**: cassettes,
> instance methods, `.tsx`, the T1(Docker) Node leg, the type→fast-check compiler, TS corpora
> growth. See `docs/PLAN-V3.md` C0 known-open ledger, item KO-1.

### 2.2 LibreChat — what you are adopting

MIT licensed, `Copyright (c) 2026 LibreChat`. Verified at HEAD.

```
api/server/               Express: routes/ (35+), services/ (Agents, Artifacts, MCP, Files,
                          Endpoints, Runs, Schedules, Skills, Threads, Tools, Config, Auth),
                          controllers/, middleware/, strategies/ (passport: OAuth2, LDAP, email)
api/models/  api/db/  api/cache/  api/app/  api/config/  api/utils/

packages/api/src/         40+ domains: agents, artifacts, mcp, memory, skills, oauth, acl,
                          admin, files, endpoints, prompts, projects, conversations, schedules,
                          shared-links, credentials, crypto, langfuse, telemetry, insights,
                          stream, storage, cdn, cluster, flow, modelSpecs, plugins, apiKeys,
                          favorites, html, rum, auth, cache, db, middleware
packages/data-schemas/    Mongoose: models/, methods/, schema/, migrations/, types/, admin/
packages/data-provider/   Shared client/server contracts, react-query bindings
packages/client/          Shared UI package

client/src/               React 18.2 + Vite 8 + TS 5.9; Recoil 0.7 AND Jotai 2.12 both present.
                          Server: Express 5.2, Mongoose 8.24.
                          components/: Agents, Artifacts, Audio, Auth, Chat,
                          Conversations, Endpoints, Files, Input, MCP, MCPUIResource, Memories,
                          Messages, Nav, OAuth, Plugins, Projects, Prompts, Share, SharePoint,
                          Sharing, SidePanel, Skills, System, Tools, UnifiedSidebar, Variables,
                          Web, Insights, Bookmarks, Banners, Appearance, ui/
                          locales/: 44 locale directories
                          store/ (Recoil), data-provider/, hooks/, routes/, Providers/

e2e/  config/  search/  otel/  redis-config/  skill/
```

**Datastore:** MongoDB via Mongoose throughout `packages/data-schemas`. Redis for cache, cluster
coordination, and resumable-stream delta batching. This is the single hardest integration problem
in the entire merge and §5.4 resolves it.

### 2.3 The three facts that constrain the merge, verified

1. **LibreChat is MIT.** Commercial use, modification, and redistribution are permitted with no
   copyleft and no network clause. **Copying code is legal and expected.** The copyright notice
   and licence text must travel with anything copied or closely adapted.
2. **MongoDB Community Server is SSPL** — declared not an open-source licence by the OSI in 2021,
   and encumbered for redistribution inside a product. **You will not bundle `mongod`.** §5.4.
3. **FerretDB 2.x is Apache 2.0** and speaks the MongoDB 5.0+ wire protocol, but runs on
   PostgreSQL with Microsoft's DocumentDB extension (MIT). FerretDB 1.x had a SQLite backend and
   is legacy. This is the pivot of the §5.4 decision and its measured spike.

**Trademarks are not licensed by MIT.** No LibreChat name, logo, wordmark, favicon, colour system,
or trade dress anywhere in the shipped product. No implication of endorsement or affiliation. This
is not a style preference; it is the one part of the licence that can actually be violated.

---

## 3. THE GOVERNING DECISION

**Owner decision, 2026-08-21:** *LibreChat becomes the base. The product is a desktop
application, not a website.*

That decision resolves to exactly one architecture. It is not open for reinterpretation
mid-build; changing it takes an ADR with a measured spike attached.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Tempest.app — Tauri v2                                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  WEBVIEW — LibreChat's React client, adopted wholesale              │ │
│  │  + Tempest surfaces: Evidence pane, Composer, Editor, Verdict rail  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                              ▲                                           │
│                    Tauri IPC │ (boundary B, tauri-specta)                │
│                              ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  RUST HOST — supervisor.rs owns every child process                 │ │
│  │  keychain · pathguard · LSP mux · local model · sandbox tiers ·     │ │
│  │  signing · audit log · undo journal · lifecycle                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│         │ (A) stdio JSON-RPC   │ (E) UDS         │ (A′) stdio           │
│         ▼                      ▼                 ▼                       │
│  ┌──────────────┐   ┌────────────────────┐   ┌──────────────────┐      │
│  │ Python engine│   │ LibreChat Node API │   │ ts-sidecar       │      │
│  │ 9 stages,    │◄─►│ Express, supervised│   │ ts-morph, V8 cov │      │
│  │ agent, index │   │ NO listening TCP   │   │                  │      │
│  └──────────────┘   └─────────┬──────────┘   └──────────────────┘      │
│                               ▼                                          │
│                     ┌──────────────────┐                                │
│                     │ Document store   │  §5.4 — never SSPL             │
│                     └──────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.1 What this means concretely

- **The Rust host is the application.** It owns the window, the lifecycle, signing, the keychain,
  the sandbox tier ladder, the audit log, the undo journal, and every child process. It does not
  become a thin launcher for a Node server. `supervisor.rs` already does exactly this job for the
  Python engine; the Node API becomes its second supervised child, with the same process-group
  ownership, health checks, backoff restarts, and orphan-impossible teardown.
- **LibreChat's Node API is a sidecar, not a server.** It runs as a child process bound to a
  **Unix domain socket** (named pipe on Windows), never a TCP port on `127.0.0.1`. A listening
  TCP port fails enterprise security review, and Tempest's threat model already says so. This is
  boundary **E** and §7 defines its contract.
- **LibreChat's React client is the primary surface.** Adopted wholesale, restyled into Tempest's
  identity (§12), extended with Tempest's surfaces. Tempest's existing `packages/desktop/src`
  views are **absorbed into it**, not run beside it. One webview, one router, one state layer.
  (Upstream already ships both Recoil and Jotai; adopt both as they stand — "one state layer"
  forbids adding a third, not consolidating theirs. See `MERGE-CONTRACT.md`.)
- **The Python engine keeps every capability it has.** It is not reduced to a "prove" endpoint. The
  agent orchestrator stays in Python (ADR-0049's reasoning is unchanged: the turn loop terminates
  on a proof and the prover is Python). The two agent runtimes are reconciled per §5.3, which is
  the second-hardest problem in the merge.
- **Server mode survives as an optional target, unbuilt for now.** Because the Node API is
  LibreChat's real API, `pnpm --filter @librechat/api start` against a real Postgres still produces
  LibreChat's multi-user web deployment. Do not delete that capability, do not maintain it, do not
  let it drive a single architectural decision. It is a free option you keep, not a product you
  ship. Recorded in ADR-0064.

### 3.2 The shape of the repository after the merge

```
packages/
  engine/         (unchanged, extended)      Python — the proof engine + agent orchestrator
  ts-sidecar/     (unchanged, extended)      TS analysis + execution
  api/            (unchanged)                FastAPI stdio sidecar + sync server
  desktop/        (extended)                 Tauri host; webview becomes the merged client
  shared-schema/  (extended)                 generated contracts, now five boundaries
  platform/       ← NEW. LibreChat, vendored.
    server/         from LibreChat api/
    api/            from LibreChat packages/api/
    data/           from LibreChat packages/data-schemas/
    provider/       from LibreChat packages/data-provider/
    client/         from LibreChat client/  → mounted as the desktop webview
    UPSTREAM.md     the commit adopted, the merge procedure, the local-delta ledger
```

**`packages/platform/` is a vendored fork with a living upstream.** Its directory structure mirrors
LibreChat's so that `git merge` from upstream keeps working. That constraint is Law **L27** and it
outranks your instinct to reorganize their code into something tidier. See §4.

---

## 4. THE LAWS

L1–L26 are in `CLAUDE.md` and **all still bind**. Re-read them; they are not summarized here.
The convergence adds ten. Violating any of these is a build failure, not a code-review comment.

### L27 — Upstream mergeability is a shipped feature.

LibreChat ships continuously. A fork that cannot absorb upstream is a fork that is obsolete within
two release cycles, and the user's requirement is *every* LibreChat feature — including the ones
written next month. Therefore:

- `packages/platform/**` preserves LibreChat's directory structure and module boundaries.
- Integration happens at **declared seams** (`packages/platform/*/tempest/`), never by editing
  their business logic in place.
- Every unavoidable in-place edit is one line in `packages/platform/UPSTREAM.md`'s delta ledger,
  with the reason and the upstream issue link if one exists.
- A quarterly upstream merge is a gated, scheduled obligation:
  `make upstream-merge && make verify-v3`.
- **Gate:** `python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete`

### L28 — The proof gate survives adoption.

L16 said the agent may never bypass the proof gate. The merge creates dozens of new paths by which
model output reaches a user — LibreChat's agent runtime, its tool service, its code interpreter,
its artifacts pipeline, its schedules, its subagents. **Every one of those paths is subject to
L16.** Any code path where an agent-authored change to the user's repository reaches the user
labelled as verified, without a real differential run traceable to a stored bundle, is a P0.

There is no `--skip-proof`. There is no fast mode that fakes it. `ProvenChange` keeps its single
construction site and its bundle-id-required constructor, and the adversarial forge tests grow one
new case per adopted path.

- **Gate:** `python -m tempest.dev.gate_audit --enumerate-paths --require-forge-test-per-path`

### L29 — Two agent runtimes is a bug, not an architecture.

LibreChat has a mature agent runtime. Tempest has a proof-terminated one. Shipping both is how you
get an application with two personalities, two tool registries, two budget meters, two cancellation
stories, and two ways to be wrong. **One runtime.** §5.3 specifies which parts of each survive and
where the seam is. The reconciliation is finished before any feature is built on top of either.

- **Gate:** `python -m tempest.dev.runtime_check --single-orchestrator --single-tool-registry`

### L30 — Every adopted feature declares its proof relationship.

Under L25 an adopted feature had to be proof-native or be rejected. **L30 replaces that test with a
weaker but honest one**, because this release adopts everything (§5.1). Each adopted capability
declares exactly one relationship in `docs/FEATURES-V3.md`:

| Relationship | Meaning | Example |
|---|---|---|
| `PROOF_NATIVE` | Wired into the Verdict Loop; changes meaning because of it | Composer, branching, presets→profiles, artifacts |
| `PROOF_ADJACENT` | Serves proof indirectly; carries proof context when relevant | Web search, RAG, memory, code interpreter |
| `PLATFORM` | Complete, excellent, honestly unrelated to proof | Image generation, TTS/STT, i18n, sharing |

**A `PLATFORM` feature is not a second-class feature.** It ships at full quality. What it may never
do is claim proof it does not have, borrow the verdict vocabulary, or render inside evidence
surfaces. Declaring `PLATFORM` honestly is the whole point of the law: the alternative is features
that imply verification they cannot deliver, and that is the one failure this product cannot
survive.

- **Gate:** `python -m tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform`

### L31 — Verdict vocabulary is reserved.

`DIVERGENT`, `EQUIVALENT_UNDER_BUDGET`, `UNPROVEN`, `ERROR`, and (from Phase 24) `WEAK_EVIDENCE`
are engine outputs. No adopted subsystem may write into a verdict, confidence, or risk field —
this is L17 extended across the merge boundary. LibreChat's UI has confidence-shaped affordances
(agent status chips, streaming state, tool result badges); none of them may render in the verdict
type, the verdict colours, or the verdict typography. Model narration is visually distinct from
evidence, everywhere, without exception.

The existing CI grep for the string `SAFE` extends to a **vocabulary lint** over
`packages/platform/**` and `packages/desktop/src/**`.

- **Gate:** `python -m tempest.dev.vocab_check --reserved-verdicts --platform-tree`

### L32 — Local-first survives the base swap.

L8, L9, L10 are unchanged and now much harder to hold, because LibreChat is a networked
multi-user platform and half of what you are adopting assumes a server. Every core capability
still works with the network cable unplugged: open the app, chat with a local model, read history,
prove a change, export a repro, read a bundle. **Local operation never requires login.** Source
code never leaves the machine without explicit, per-repo, opt-in consent — including through
LibreChat's telemetry, Langfuse integration, RUM, insights, and error reporting, every one of
which must be **off by default and provably inert**, not merely unconfigured.

- **Gate:** `python -m tempest.dev.egress_check --platform-tree --deny-all --airplane-mode-full-function`

### L33 — The document store is never SSPL, and never a second datastore for proofs.

Proof data — bundles, cassettes, observations, journals, the three indices — stays in SQLite,
owned by the engine, exactly as today. Platform data lives in the store §5.4 selects. **Two stores
is the accepted cost of L27**; a third is not, and moving proof data into the document store is
forbidden. Cross-store references are by opaque id only, never by join, and every one of them is
declared in `docs/MERGE-CONTRACT.md`.

- **Gate:** `python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store`

### L34 — Every process is supervised, and orphans are impossible.

The merged app runs the Rust host plus, at minimum: the Python engine, the Node API, the ts-sidecar,
the document store, language servers, the local model runner, and per-run sandbox containers.
Every one is a child of the Rust supervisor with process-group ownership, health checks,
exponential-backoff restart, and a teardown that survives `SIGKILL` of the parent. The existing
`orphan_check` gate extends to cover all of them.

- **Gate:** `uv run python -m tempest.dev.orphan_check --all-children --after-sigkill`

### L35 — Feature parity is measured, not asserted.

"Every LibreChat feature" is a testable claim and you will test it. `docs/FEATURES-V3.md` is a
machine-readable ledger with one row per LibreChat capability, each carrying its status
(`ADOPTED` / `IN_PROGRESS` / `NOT_STARTED`), its L30 relationship, its owning phase, and its
verifying test. Parity percentage is computed from the ledger and printed by the gate. **The
README publishes the number.** A feature is `ADOPTED` only when its verifying test runs green.

- **Gate:** `python -m tempest.dev.parity_ledger --require-100-at-ga --print-percentage`

### L36 — "Zero errors" is the seven zero-properties, plus five more, or it is marketing.

L15's seven properties (zero unhandled states, zero untyped boundaries, zero silent failures, zero
unbounded operations, zero data loss, zero regressions escape, published error budget) all still
bind, now across the platform tree. The convergence adds five:

8. **Zero untyped seams.** Every boundary between adopted code and Tempest code is generated from
   one schema and drift-gated. Five boundaries, one truth (§7).
9. **Zero orphaned processes.** L34, measured after `SIGKILL`.
10. **Zero unclassified features.** L30/L35, measured by the ledger.
11. **Zero unattributed adoptions.** Every copied or adapted file carries its notice at the moment
    of adoption; `license_check` gates it (§11).
12. **Zero mystery states in the merged UI.** Every view reachable from LibreChat's client
    implements loading, empty, error, partial, cancelled, stale, **and `UNPROVEN`** — the seventh
    is new and is a first-class state, never an error toast.

- **Gate:** the full `make verify-v3`, §9.

---

## 5. THE MANDATE — WHAT YOU ARE ACTUALLY BUILDING

### 5.1 The six rejections are overturned

`docs/PLATFORM-V2.md` carries a rejection table. **Owner decision 2026-08-21: all six are
overturned.** Because that document explicitly says overturning takes an ADR and not a drift, you
will write those ADRs — they are drafted in `docs/DECISIONS-V3-ADDENDUM.md` and must be committed
before the corresponding feature is built.

| Was rejected | New disposition | ADR | Constraint that survives |
|---|---|---|---|
| Image generation (GPT-Image, DALL·E, Flux, Stable Diffusion, MCP) | **ADOPT in full** | ADR-0063 | `PLATFORM`. Never renders in an evidence surface. Prompts and outputs are user data under L9. |
| Text-to-speech and speech-to-text | **ADOPT in full** | ADR-0065 | `PLATFORM`. Verdicts are never spoken as prose — a spoken "equivalent under budget" loses the qualifier that makes it honest. Evidence is read as evidence or not at all. |
| Agent marketplace | **ADOPT, with signing** | ADR-0066 | Community marketplace ships. Any agent, skill, or plugin requesting file-write, shell, or network capability is **signature-gated and capability-declared** before install. This is the one constraint retained from the v2 rejection, because the threat it named is real and the mitigation is cheap. |
| Chat as the primary surface | **ADOPT — chat is the primary surface** | ADR-0067 | The evidence surface is one keystroke away and is where proof lives. Chat leading does not mean proof hiding. |
| MongoDB | **ADOPT the data model, not the binary** | ADR-0068 | §5.4. Mongoose stays, `mongod` does not. |
| General-purpose assistant framing | **ADOPT** | ADR-0069 | Tempest is a general assistant that can prove code. The proof claim is never diluted into a general claim — "I checked" is not a verdict, and only the engine may say something stronger. |

Additionally adopted, never previously in scope: **code interpreter** (ADR-0070), **RAG / file
chat** (ADR-0071), **admin panel** (ADR-0072), **scheduled agent runs** (ADR-0073), **44-locale
i18n adopted wholesale rather than rebuilt** (ADR-0074).

### 5.2 The complete adoption list

Every item below ships. `docs/FEATURES-V3.md` carries the full ledger with per-feature tests; this
is the summary you should be able to recite.

**Providers and models.** Anthropic, OpenAI, Azure OpenAI, AWS Bedrock, Google, Vertex AI, the
OpenAI Responses API, and every OpenAI-compatible endpoint with no proxy — Ollama, groq, Mistral,
Cohere, together.ai, OpenRouter, Perplexity, DeepSeek, Qwen, Apple MLX, koboldcpp, Helicone,
ShuttleAI. Model specs, per-endpoint parameter controls, reasoning UI for chain-of-thought models,
mid-chat endpoint switching. *Tempest already has 16 providers over two wires (ADR-0040) — §5.5
resolves the two provider layers.*

**Agents.** No-code agent builder, the unified Tools marketplace, agent sharing to users and
groups, `SKILL.md` skill bundles (manual / automatic / always-on), agent plugins bundling skills
and MCP servers, subagents with isolated context windows, programmatic tool calling, per-tool
background and intent settings, agent run control (interrupt, steer mid-run, queue follow-ups,
reclaim and escalate pending steers), human-in-the-loop pause for input or tool approval,
generated activity-group headers and phase summaries, memory with optional per-agent isolation,
context-usage gauge, agent stream circuit breakers.

**Tools and execution.** Code interpreter across Python, Node/TS, Go, C/C++, Java, PHP, Rust,
Fortran with file upload/process/download; background code and shell execution; sandbox images
returned as viewable artifacts; MCP client with dynamic tool refresh, parsed response media types,
runtime OAuth recovery; custom actions from OpenAPI specs; web search with providers, scrapers,
and rerankers.

**Artifacts and generative UI.** React, HTML, and Mermaid rendered inline; fullscreen preview;
Mermaid export to SVG and PNG; `.potx` PowerPoint templates across upload, search, and code
execution; original Office file download from the artifact panel.

**Conversation.** Forking, branching, edit-and-resubmit, continue, presets (create/save/share),
prompts with user and group sharing, bookmarks and tags, full-text search across all messages and
conversations, virtualized search results, shared conversations with stable URLs and continue-as-
personal-copy, import from LibreChat / ChatGPT / Chatbot UI, export to markdown / JSON / text /
screenshot.

**Multimodal and files.** Image upload and analysis, file chat, RAG, OCR, document handling, S3 /
CloudFront-style media addressing adapted to local storage.

**Speech.** Speech-to-text and text-to-speech via OpenAI, Azure OpenAI, and ElevenLabs, with
automatic send and automatic playback.

**Images.** Text-to-image and image-to-image via GPT-Image-1, DALL·E 3/2, Stable Diffusion, Flux,
or any MCP image server.

**Platform.** Multi-user auth (OAuth2, LDAP, email) gating team features only; the browser-based
admin panel for users, groups, roles, and live config overrides; delegated config sections;
encrypted registered secrets; SSRF checks on speech, OCR, and web tools; moderation; token spend
tracking, balances, and quotas; Langfuse observability with encrypted connections and per-tenant
trace fan-out; resumable streams with multi-tab and multi-device sync; adaptive provider smoothing
and delta batching; configurable HTTP timeouts; scheduled runs; 44 locales.

**And every Tempest capability, undiminished.** F1–F16 as shipped, F5–F10 and F17–F21 as planned in
`docs/PLAN-V2.md` phases 24–32, the nine stages, the four verdicts, the tier ladder, the journal,
shadow worktrees, the four boundaries, and the CLI — which stays a first-class, fully offline
product that never requires the desktop app to exist.

### 5.3 The agent runtime reconciliation — the hardest decision in the merge

Both systems have a production agent runtime. **L29 says you ship one.** This is the decision, and
it is the one place where "LibreChat is the base" is deliberately overridden:

> **The Python orchestrator (`packages/engine/src/tempest/agent/`) is the runtime.**
> LibreChat's agent *surface* — builder, marketplace, skills, plugins, run control, HITL,
> activity groups, steering — is adopted in full and re-targeted onto it.

**Why**, recorded as ADR-0075 with this reasoning:

- ADR-0049's argument is unchanged and decisive: the turn loop's terminating condition is a proof,
  the prover is Python, and any other host has to call into Python on every turn.
- L16/L28 require the proof gate to be structurally unbypassable. That is achieved today by
  `ProvenChange` having no constructor without a bundle id and exactly one construction site.
  Reproducing that guarantee across a JS runtime doubles the attack surface for zero gain.
- Budget enforcement, the cost meter's single-lock ledger (ADR-0041), the shadow worktree manager,
  the journal, and subagent budget accounting are all Python and all correct.
- LibreChat's agent value is overwhelmingly in the **surface and the ergonomics**, not the loop.
  The builder, the marketplace, the run-control UX, the HITL forms, the activity-group summaries
  — that is the part that took years and the part users touch.

**The seam.** LibreChat's agent service (`api/server/services/Agents/`) is replaced by a thin
client over boundary E that speaks the same shapes to the client and delegates every turn to the
Python orchestrator. Their tool registry unifies with `agent_tools.rs` (boundary D), which stays
the root of truth for capability declarations and approval invariants — because that is where
`WriteScope` structurally cannot express a write to the user's working tree, and that property is
worth more than the convenience of two registries.

**What this costs, stated honestly.** It is the largest single item in the plan (phase C5), it
touches LibreChat's most actively developed subsystem, and it will make upstream merges in
`services/Agents/` painful forever. That cost is accepted and recorded. The alternative — two
runtimes — costs more, permanently, and produces a worse product.

### 5.4 The datastore decision

**Constraints, all binding at once:** LibreChat's entire data layer is Mongoose (L27 says do not
rewrite it) · `mongod` is SSPL (L33 says do not ship it) · the app is local-first and single-user
by default (L32) · idle RAM budget is 300 MB p50 / 450 MB p95 (L22) · proof data stays in SQLite
(L33).

**Decision (ADR-0068): FerretDB 2.x + embedded PostgreSQL + DocumentDB extension, as a supervised
sidecar, behind one seam — subject to a measured spike at phase C1.**

- All three components are permissively licensed: FerretDB Apache 2.0, DocumentDB MIT, PostgreSQL
  PostgreSQL Licence. No SSPL binary ships.
- LibreChat's `packages/data-schemas` is adopted **byte-for-byte**. Mongoose talks the wire
  protocol; it does not know or care what is answering. This is what makes L27 achievable.
- The connection is a Unix domain socket, never a TCP port.
- The store is a child of `supervisor.rs` under L34: health-checked, backoff-restarted, torn down
  with the process group.

**The spike is mandatory and it can overturn this.** Phase C1 measures cold launch to interactive,
idle RAM, idle CPU, and p95 query latency for the ten hottest LibreChat queries, on the 4-core /
16 GB reference profile. If any §10 budget is missed by more than 25%, the fallback engages:

> **Fallback (pre-approved, no new ADR needed to choose it — only to record the measurement):**
> keep the Mongoose *models* and *methods* as the public API, and implement a document-store
> adapter over the engine's existing SQLite with a BSON-ish document table plus expression indices.
> Higher port cost, permanently worse upstream mergeability for `data-schemas`, dramatically better
> resource profile. If you take this path, the delta ledger for `data-schemas` becomes the single
> most important file in `packages/platform/UPSTREAM.md`.

**Redis.** LibreChat uses it for cache, cluster coordination, and resumable-stream delta batching.
In single-user desktop mode none of those need a network service: adopt the interface, back it with
an in-process LRU plus the engine's SQLite for durability, and keep real Redis as a config option
for the unbuilt server mode (§3.1). Recorded in ADR-0068 §4.

### 5.5 The provider layer reconciliation

Tempest has `tempest/inference/` — 16 providers over two wires, stdlib-only, no vendor SDK, real
streaming cancellation, a single-lock cost meter, and three local runners (ADR-0040, ADR-0041).
LibreChat has its own multi-provider layer with broader model-spec metadata, per-endpoint parameter
UI, and reasoning-UI support.

**Decision (ADR-0076): one router, Python, in `tempest/inference/`.** LibreChat's provider
*configuration schema*, model-spec metadata, and parameter UI are adopted and mapped onto it. The
cost meter stays the single spend-enforcement point — **caps are enforced at the router, never in
the UI**, because a UI-enforced cap is not a cap. Adding a provider must not touch feature code in
either tree.

Complete `19.5b` as part of this: migrate `harness/llm.py` and `report/narrative.py` onto the
unified client and drop the `anthropic` SDK dependency. It is a small item that has been open since
Phase 19 and it blocks the claim that there is one model path.

---

## 6. THE MERGE CONTRACT

Full table in `docs/MERGE-CONTRACT.md`. The method is what matters here, and it is not optional.

**Before touching any LibreChat subsystem, assign it exactly one disposition and record it:**

| Disposition | Meaning | When |
|---|---|---|
| **VENDOR** | Copied into `packages/platform/` unmodified; integrated only at declared seams | Default. Anything with active upstream development. |
| **VENDOR+SEAM** | Vendored, plus a new `tempest/` subdirectory inside it holding integration code | Anything the proof engine must reach into. |
| **PORT** | Re-implemented in Tempest's stack because a law forbids adopting it as-is | Rare. Requires an ADR naming the law. |
| **REPLACE** | Tempest's existing implementation wins; LibreChat's surface re-targets onto it | Agent runtime (§5.3), provider router (§5.5), sandbox, keychain, signing, audit log, undo journal. |
| **BRIDGE** | Both survive behind one interface during a transition, with a dated removal plan | Strictly time-boxed. A bridge with no removal date is two implementations wearing a trenchcoat. |

**Rules that apply to every disposition:**

1. **Attribution at the moment of adoption**, never at release. `THIRD_PARTY_LICENSES.md` gains a
   row when the file lands, in the same commit. `license_check` already gates this and has 18 unit
   pins that each prove a *failure* on a violating tree — extend it to `packages/platform/**`.
2. **No brand assets.** Strip logos, wordmarks, favicons, colour tokens, and trade dress at the
   moment of vendoring, in the vendoring commit, so they are never in the tree.
3. **No dead imports, no vestigial config.** Vendored code that references a subsystem you replaced
   gets a seam, not a stub that silently no-ops.
4. **Their tests come with their code.** LibreChat's test suites for vendored subsystems run in
   `make verify-v3`. A vendored subsystem whose tests you did not bring is a subsystem you cannot
   claim works.
5. **One seam directory per package**, `packages/platform/<pkg>/tempest/`, so the delta between
   your tree and upstream is a `git diff` of known paths and nothing else.

---

## 7. FIVE BOUNDARIES, ONE TRUTH

L12 said three, v2 made it four, the merge makes it five. The mechanism is unchanged and
non-negotiable: **generation, not discipline.**

| | Boundary | Root of truth | Generator | Consumer |
|---|---|---|---|---|
| A | Python engine ↔ Rust host | Pydantic v2 models | JSON Schema → `typify` | `src-tauri/src/generated` |
| B | Rust host ↔ TS webview | Tauri commands/events | `tauri-specta` | `desktop/src/generated` |
| C | Python ↔ TS domain types | the same Pydantic models | `json-schema-to-typescript` | `desktop/src/generated` |
| D | Agent Tool Protocol | `src-tauri/src/agent_tools.rs` | `schemars` → 4 artifacts | model-facing, per provider |
| **E** | **Rust host ↔ Node platform API** | **`packages/shared-schema/platform.schema.json`** | **`quicktype`/`typify` → Rust + TS + JSDoc** | **`platform/*/tempest/generated`** |

**Boundary E rules:**

- Transport is **JSON-RPC 2.0 over a Unix domain socket** with length-prefixed framing. Never HTTP
  on a TCP port. Reuse `framing.rs` — it already does exactly this for boundary A.
- LibreChat is JavaScript, so TypeScript types are advisory at runtime. Therefore every message
  crossing E is **validated at the boundary in both directions**, in production and not only in
  dev, against the generated schema. A validation failure is a surfaced, diagnosable error with an
  ID (L15.3), never a swallowed exception.
- Domain values crossing E stay Pydantic-rooted (boundary C). Referenced, never redefined.
- Enums are exhaustively matched in Python (`assert_never`), Rust (`match`, no wildcard arm), and
  TypeScript (`switch` with a `never` guard). Adding a `ReasonCode` in Python must break the Rust
  build, the TS build, **and** boundary E's validator.

**The gate — five boundaries, still one command, no overrides, ever:**

```bash
make gen-contracts && git diff --exit-code
```

Wired into `predev`, `prebuild`, and CI as `contract-check`. A non-empty diff is a red build.

---

## 8. THE PHASES

Full detail with per-item gates in `docs/PLAN-V3.md`. Convergence phases are lettered **C0–C12** so
they do not collide with the still-live numbered phases 24–32.

| Phase | Scope | The gate that proves it |
|---|---|---|
| **C0** | Re-audit. Run every existing gate on the current tree, paste output. Establish the honest baseline before anything moves. | `make verify` exit 0 with pasted output; Phase-3 TS-execution gap and the other §2.1 open items written into `PLAN-V3.md` as real items |
| **C1** | Vendor LibreChat into `packages/platform/`. Strip brand assets. Attribution rows land in the same commit. **Datastore spike (§5.4) with measurements.** | `license_check --third-party-notices` green over the platform tree; `store_check`; spike numbers pasted against the §10 table; ADR-0068 records the measured choice |
| **C2** | Boundary E: schema, framing, generation, bidirectional validation, drift gate. Node API supervised under `supervisor.rs`, UDS only, no TCP. | `make gen-contracts && git diff --exit-code` with five boundaries; `orphan_check --all-children --after-sigkill`; a probe proving no TCP port is opened |
| **C3** | The merged shell. LibreChat's client mounts in the Tauri webview. One router, one store. Tempest's existing views absorbed. Auth optional; **airplane mode is fully functional**. | `egress_check --platform-tree --airplane-mode-full-function`; cold launch measured against §10; every route renders with zero console errors |
| **C4** | Provider router reconciliation (§5.5) + `19.5b`. One model path, one cost meter, caps at the router. | `provider_matrix --min-providers 16`; a cap test that starts 8 threads against a cap admitting 2 and gets exactly 2; `grep -r "anthropic" packages/engine` finds no SDK import |
| **C5** | **Agent runtime reconciliation (§5.3).** The largest item. LibreChat's agent surface re-targeted onto the Python orchestrator. One tool registry. | `runtime_check --single-orchestrator --single-tool-registry`; `agent_bench --tasks 50 --require-verdict-coverage 1.0` still 55/55 **through the new surface**; `gate_audit` enumerates every new path with a forge test each |
| **C6** | Datastore cutover complete. Every LibreChat model, method, and migration green against the selected store. Their test suites run in `make verify-v3`. | LibreChat's own data-layer suites green; migration up/down parity; `store_check` |
| **C7** | Conversation platform: forking, branching, edit-resubmit, presets→Proof Profiles (P7), prompts, bookmarks, search, sharing, import/export **with proof bundles attached** (P12). | `session_roundtrip --export-import --require-runnable-repros`; fork-and-compare-by-verdict working |
| **C8** | Tools and execution: code interpreter, custom actions, web search, MCP client refresh and OAuth recovery, scheduled runs, skills, plugins, subagents — all through the one runtime, all under the tier ladder. | `escape_suite` extended to the code interpreter, all tiers, three OSes; `redteam --injection` green including code-interpreter and MCP channels |
| **C9** | Artifacts and generative UI (P8) — React, HTML, Mermaid, fullscreen, SVG/PNG export, `.potx`, Office download — **plus behavioral artifacts**: call graphs, effect timelines, divergence tables, coverage maps, minimized-input trees. | artifacts render < 100 ms; sandbox escape suite covers the renderer; every artifact exportable into a run bundle |
| **C10** | The overturned features: image generation, TTS/STT, RAG and file chat, multimodal, memory, moderation, balances, Langfuse, insights, admin panel, marketplace **with capability signing**. | `feature_ledger --every-feature-classified`; marketplace signature gate proven by an adversarial unsigned-capability install attempt |
| **C11** | i18n across the merged surface. All 44 locales adopted; Tempest's verdict vocabulary and every `reason_code` explanation translatable. | `i18n_check --no-hardcoded-strings --pseudo-locale --rtl` over both trees |
| **C12** | Convergence hardening: performance campaign, craft campaign, red team, upstream merge rehearsal, parity ledger at 100%. | `make verify-v3` in full; `parity_ledger --require-100-at-ga`; `upstream_check`; a real upstream merge executed and green |

### 8.6 How C0–C12 interleave with phases 24–32

Phases 24–32 are not cancelled. They are the proof half of the product and cutting them turns this
into a chat app with a defensible README.

```
C0 → C1 → C2 → C3 → C4 → C5 ┬→ C6 → C7 → C8 → C9 → C10 → C11 → C12
                             │
                             └→ 24 (F9 self-validation, F10 cassette-to-suite)
                                25 (F7 de-slop, F8 dead code, F6 migration)
                                26 (F18 ambient watch, F17 fleet)
                                27 (F5 semantic merge, F19 debugger, F20 KB, F21 arena)
```

**Rule:** phases 24–27 may run in parallel with C6–C11 **only after C5 lands**, because every one
of them builds on the agent runtime and building on a runtime you are about to replace is how you
do the work twice. Phases 28 and 29 are **absorbed** — P6, P7, P8, P12, P13 land in C7/C9, and P10
and P14 land in C10/C11. Phases 30, 31, 32 merge into C12 and, per the v2 sequencing rule that has
not changed, **are never cut**.

---

## 9. VERIFICATION

```bash
make verify-v3
```

**A note on what exists.** The Makefile today has `verify` (composing `verify-python`, `verify-agent`,
`verify-node`, `verify-desktop`, `verify-contract`, `verify-grep-safe`), plus
`verify-linux-denominator`, `gen-contracts`, `perf-gate`, `bench`, `bench-editor`, `sync`, and
`ensure-sidecar`. **`make verify-v2` is not a target** — it is the accumulated definition-of-done
list in `docs/PLAN-V2.md`, and several of its commands are gates yet to be built. `verify-v3` is a
new target you create, composing the real `verify` with everything below, and it grows one gate at a
time as each phase makes that gate runnable.

`make verify-v3` = `make verify` + the v2 definition-of-done list as those gates come live + :

```bash
# ── contracts ───────────────────────────────────────────────────────────
make gen-contracts && git diff --exit-code              # FIVE boundaries, one truth
python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete

# ── the merge laws ──────────────────────────────────────────────────────
python -m tempest.dev.runtime_check   --single-orchestrator --single-tool-registry   # L29
python -m tempest.dev.gate_audit      --enumerate-paths --require-forge-test-per-path # L28
python -m tempest.dev.feature_ledger  --every-feature-classified --no-verdict-vocab-in-platform # L30
python -m tempest.dev.vocab_check     --reserved-verdicts --platform-tree            # L31
python -m tempest.dev.egress_check    --platform-tree --deny-all --airplane-mode-full-function # L32
python -m tempest.dev.store_check     --no-sspl-binaries --no-proof-data-in-document-store # L33
python -m tempest.dev.orphan_check    --all-children --after-sigkill                 # L34
python -m tempest.dev.parity_ledger   --require-100-at-ga --print-percentage         # L35
python -m tempest.dev.license_check   --third-party-notices --platform-tree          # L36.11

# ── the adopted tree's own tests ────────────────────────────────────────
pnpm --filter "./packages/platform/**" test
pnpm --filter "./packages/platform/**" typecheck

# ── the merged surface ──────────────────────────────────────────────────
pnpm test:e2e                                            # real API, seeded store, no mocked network
python -m tempest.dev.perf_suite --enforce-budgets       # §10, merged-app profile
python -m tempest.dev.redteam --injection --exfiltration --gate-subversion
```

**None of the eight new `tempest.dev` modules exist yet.** Writing each one is part of the phase
that needs it, exactly as the v2 plan handled its gate modules. A gate that has never run is a
claim. Do not add a command to this list before you have made it runnable and run it.

---

## 10. PERFORMANCE BUDGETS

The §5 v2 table still binds, unchanged, and CI still fails on a >10% regression. The merge adds
processes and therefore adds rows. Measured on 4-core / 16 GB against a 500k-LOC repo.

| Operation | p50 | p95 |
|---|---|---|
| *(all v2 rows unchanged — cold launch 800 ms/1.5 s, keystroke→render 8/16 ms, completion 120/300 ms, search 150/400 ms, agent first token 400 ms/1 s, incremental proof 5/15 s, full proof 25/60 s, diff 500 files 150/300 ms, idle CPU <0.5%/<1%)* | | |
| Cold launch → chat interactive **(merged app, all sidecars up)** | 1.2 s | 2.0 s |
| Conversation switch (1000-message history) | 80 ms | 200 ms |
| Message send → first token (local model) | 250 ms | 600 ms |
| Full-text search across 10k conversations | 120 ms | 300 ms |
| Artifact first render | 60 ms | 100 ms |
| Document-store p95 on the 10 hottest queries | 5 ms | 20 ms |
| Idle RAM, **all sidecars** | 550 MB | 800 MB |

**The idle-RAM row is the honest one.** The v2 budget was 300/450 MB for a Tauri host plus a Python
engine. A merged app running the Rust host, Python engine, Node API, ts-sidecar, and a document
store cannot hold that number, and pretending otherwise would guarantee a missed gate in C12
followed by a quiet re-baselining. 550/800 MB is the budget. If the C1 spike shows the FerretDB
path cannot hold *this* number either, §5.4's fallback engages — that is precisely what the number
is for.

**Mandatory techniques, unchanged from v2 and now applying to the platform tree too:** virtualize
every list and diff over 50 rows; incremental parse and index only; content-hash caching of
harnesses, cassettes, and adapters; all heavy work off the UI thread; React transitions with
`useDeferredValue` on every filter; streaming with backpressure; speculative prefetch of likely-next
views; SQLite in WAL with prepared statements and covering indices for every hot query.

---

## 11. SECURITY, THREATS, AND ATTRIBUTION

`docs/THREAT-MODEL-V2.md` binds. The merge widens the attack surface substantially and these are
the deltas you must handle. Every one gets a case in `redteam`.

| New surface | Threat | Required mitigation |
|---|---|---|
| Code interpreter | Arbitrary multi-language execution | Runs at the differential runner's tier ladder. No tier, no execution. Same containment, same escape suite, all three OSes. |
| Agent marketplace | Supply chain — this is the big one | Capability declaration + signature required before install for anything requesting file-write, shell, or network. Adversarial test: an unsigned capability-requesting agent must fail to install. |
| Image generation | Prompt and image exfiltration | Prompts and outputs are user data under L9. EXIF and geolocation stripped before any provider call, test-verified. |
| Speech | Audio exfiltration | Local-first STT path available; cloud STT is opt-in per provider with the consent surface L9 already requires. |
| RAG / file chat | Retrieved content as instruction | Already handled for web search (P9, `redteam --injection` 30/30). Extend the same treatment to RAG, file contents, and OCR output. **Every retrieved byte is attacker-controlled input, never instruction.** |
| Langfuse / RUM / insights / telemetry | Source code egress | Off by default and **provably inert**, not merely unconfigured. `egress_check` covers each independently. |
| Admin panel | Privilege escalation | Gates team features only. Never gates local operation. An admin cannot disable the proof gate — L28 is structural, not a permission. |
| Node API sidecar | Local privilege / lateral movement | UDS only, never TCP. Boundary E validated bidirectionally in production. Runs as the same user with no elevated capability. |
| Scheduled runs | Unattended agent action | Every scheduled run is journalled (L14), budgeted (L21), reversible (L20), and proof-gated (L28) identically to an interactive run. |

**Attribution mechanics, mechanical and gated:**

- `THIRD_PARTY_LICENSES.md` gains a row **in the same commit** the code lands. Not at release.
  Missing notices surface during enterprise procurement diligence, which is the worst possible
  moment to find them.
- Per-file header preserving `Copyright (c) 2026 LibreChat` and the MIT text on anything copied or
  closely adapted.
- The per-module derivation table records: source path, adopted commit SHA, disposition (§6),
  and modification summary.
- LibreChat's own `THIRD_PARTY_LICENSES` obligations for *its* dependencies travel with the
  vendored tree and are merged into ours.
- `rag_api` is a separate repository with its own licence — review it independently before
  adopting anything from it, and record the review.
- **No trademarks, no logos, no trade dress, no implication of endorsement.** The README's Credits
  section already does this correctly; keep it accurate as the adoption scope grows.

---

## 12. WORLD-CLASS IS A GATE, NOT AN ADJECTIVE

L26 and `docs/CRAFT.md` bind, and `docs/POLISH.md`'s 150 items are CI-enforced or checklist-verified
on three OSes. The bar is the best native desktop software, not the best web app. **"Looks fine" is
not a passing state.**

Specific to this merge:

- **One identity, not two.** LibreChat's client is adopted for its structure, its interaction
  design, and its completeness — then dressed entirely in Tempest's visual language. A user must
  never be able to tell where one codebase ends and the other begins. Two design systems in one
  window is the most visible possible way to look like a fork.
- **Never clone another vendor's chrome.** Adopt the principles that make great native software
  feel the way it does; express them in Tempest's own identity. This applies to LibreChat, to
  ChatGPT, and to Claude equally. (v2 failure mode 11, unchanged.)
- **Evidence is a first-class surface, one keystroke from anywhere.** Chat leads (ADR-0067); proof
  does not hide. A verdict must be reachable, legible, and beautiful from any message that produced
  a code change.
- **`UNPROVEN` is designed, not defaulted.** It is the single most important state in the product
  and the one every competitor lacks. It gets the double-bordered panel, the reason chips, and the
  actionable next step — in every locale.
- **Motion is interruptible.** Every animation interrupted at 50% settles cleanly.
  `pnpm test:motion-interrupt` is a gate.
- **CLS = 0** on every view, measured.
- **Accessibility is verified with recordings.** VoiceOver and NVDA, WCAG 2.2 AA, attached to the
  phase.
- **The screenshot test.** Any view, screenshotted alone, is legible and self-explanatory to a
  first-time viewer. If it needs you standing next to it, it is not done.

---

## 13. FAILURE MODES — RE-READ BEFORE EVERY PHASE

The v2 list of eleven still applies. These are the ones this merge creates.

1. **The frankenstein.** Two design systems, two routers, two stores, two agent loops, two
   provider layers. Every one of those is a specific law above; the failure mode is doing the merge
   without finishing the reconciliations first. **C4 and C5 come before features are built on top.**
2. **The proof feature becomes a tab.** Chat leads by decision (ADR-0067). If a week goes by where
   no proof-related work landed, the product is drifting into a LibreChat skin and you should say
   so out loud.
3. **Fork rot.** Six months in, upstream is 4,000 commits ahead and merging is impossible.
   L27 exists to prevent exactly this; `upstream_check` measures it; the quarterly merge rehearsal
   is not optional and C12 executes a real one.
4. **Proof-shaped features that do not prove.** A `PLATFORM` feature borrowing verdict language,
   verdict colours, or the confidence surface. L30 and L31, gated by `vocab_check`.
5. **Silent local-first erosion.** Adopted code assumes a server: an auth check here, a telemetry
   call there, a feature that spins forever offline. `egress_check --airplane-mode-full-function`
   runs every phase, not at the end.
6. **The datastore eats the schedule.** §5.4's spike is at C1 for exactly this reason. Measure
   early, decide on numbers, and take the fallback without ceremony if the numbers say so.
7. **Attribution debt.** Vendoring 200,000 lines and writing the notices "later." `license_check`
   gates the commit, not the release.
8. **Perf death by a thousand adopted features.** Budgets are enforced from C1, not C12. A feature
   that misses its budget does not ship; it gets fixed or cut.
9. **The agent learning to cheat the gate.** Unchanged and permanent: contract-weakening,
   test-deletion, and target-unreachability adversarial tests, now one per adopted path (L28).
10. **Adopting a feature without adopting its tests.** §6 rule 4. A vendored subsystem whose suite
    you did not bring is a subsystem you cannot claim works.
11. **Claiming "zero errors."** The user asked for zero errors. The honest form of that promise is
    L36's twelve properties, each gated. Saying "zero errors" without them is the one failure that
    makes every other claim in this repository worth less.

---

## 14. DEFINITION OF DONE

Tempest v3.0 ships when, and only when, all of the following have been executed with real output
attached:

- [ ] `make verify-v3` exit 0, complete, with pasted output.
- [ ] `parity_ledger --require-100-at-ga` at **100%** — every LibreChat capability adopted, each
      with a verifying test that ran green.
- [ ] Every Tempest capability F1–F21 shipped or explicitly deferred with an ADR that says why.
- [ ] Five boundaries generated and drift-gated by one command.
- [ ] One agent runtime, one tool registry, one provider router, one cost meter, one journal.
- [ ] Airplane mode: full local functionality, zero auth prompts, zero spinners, zero egress —
      **tested, not promised**, and the test output published as a sales artifact.
- [ ] Red team green: 50+ injection, 20+ exfiltration, 15+ gate-subversion, including the code
      interpreter, RAG, marketplace, and MCP channels.
- [ ] External security review completed before GA.
- [ ] All 150 `POLISH.md` items verified on macOS, Windows, and Linux with screenshots.
- [ ] a11y audit at WCAG 2.2 AA with VoiceOver and NVDA recordings attached.
- [ ] Every §10 budget met on the reference profile; public perf dashboard live.
- [ ] Tempest proves its own PRs with Tempest, gated in CI; the Tempest-on-Tempest proof rate
      published in the README (L24).
- [ ] One real upstream LibreChat merge executed and green (L27).
- [ ] `THIRD_PARTY_LICENSES.md` complete, `license_check` green, zero brand assets in the tree.
- [ ] 30-day dogfood with the crash-free session rate ≥ 99.9% and the agent turn failure rate
      ≤ 0.5% (L15.7).

---

## 15. YOUR FIRST ACTIONS

Do these in order. Do not skip to the interesting part.

1. **Read** `CLAUDE.md`, `docs/PLAN.md`, `docs/PLAN-V2.md`, `docs/PLATFORM-V2.md`,
   `docs/FEATURES-V2.md`, `docs/DECISIONS.md`, `docs/THREAT-MODEL-V2.md`, `THIRD_PARTY_LICENSES.md`.
   You are joining a project with 67 ADR entries running through ADR-0062 (five carry amendments)
   and a strong engineering culture. Inherit it.
2. **Run `make verify`** on the current tree and paste the output. This is C0 and it is the only
   honest starting point. If something is red that the docs say is green, that discovery is more
   valuable than any code you could write today.
3. **Commit the ADRs.** `docs/DECISIONS-V3-ADDENDUM.md` holds ADR-0063 … ADR-0076 in draft. Review
   each, sharpen the reasoning where you disagree, and land them into `docs/DECISIONS.md`. The six
   overturned rejections in `docs/PLATFORM-V2.md` get an amendment note pointing at their ADR —
   **do not delete the original rejection text.** A future contributor must be able to read what
   was rejected, why, and why that changed.
4. **Land `docs/PLAN-V3.md`, `docs/MERGE-CONTRACT.md`, and `docs/FEATURES-V3.md`** into the repo
   and wire `FEATURES-V3.md` into the parity ledger gate.
5. **Start C1.** Vendor. Attribute in the same commit. Strip brand assets in the same commit.
   Run the datastore spike and paste the numbers.

Then stop and report. One phase, one report, one owner review — the loop that produced 62 green
ADRs and is not being changed for this.

---

## 16. THE STANDARD

You are merging a 28,000-star platform that took years to build with a proof engine that does
something no product on the market does, into one desktop application, and the person who owns it
wants it to be the thing people open instead of ChatGPT.

That is achievable. It is achievable specifically because the hard part is already done twice: the
platform is finished and open, and the proof engine is finished and gated. What remains is
integration — and integration is where ambitious projects die, not from missing features but from
accumulated silent compromise. A skipped gate here, an unwritten ADR there, a "we'll fix the
attribution later," a re-baselined perf budget, a second agent loop that was only supposed to be
temporary.

The laws above exist because each one is a specific compromise that would look reasonable on the
day it was made and fatal a year later.

**Hold every gate. Write every ADR. Paste every output. Never say it works until you have watched
it work.**

That is the whole method, and it is the only reason the result will be worth using.
