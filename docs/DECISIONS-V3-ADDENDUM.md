# DECISIONS — v3 Convergence addendum (ADR-0063 … ADR-0076)

> **LANDED 2026-08-21 (Phase C0).** Every ADR below has been committed into
> `docs/DECISIONS.md`, which is the authoritative record; this file is retained because the
> master prompt and the C-phase docs reference it by name. If the two ever disagree,
> `docs/DECISIONS.md` wins.


> **Drafted for review and commit into `docs/DECISIONS.md` — that commit has happened; see the
> LANDED note above.** Format matches the existing 62 ADRs.
> Six of these overturn refusals recorded in ADR-0038. Per that ADR's own instruction — *"overturning
> any refusal above takes an ADR, not a drift"* — each one below engages with the original reason
> rather than ignoring it. **Do not delete ADR-0038's refusal table.** Amend it with a pointer.

---

## ADR-0063 — Image generation adopted (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Overturns:** ADR-0038 refusal 1 · **Law:** L30

**Context.** ADR-0038 refused image generation on the grounds that it has "zero proof story, zero
relationship to code correctness" and is "the clearest single signal that a product has lost its
thesis." That reasoning was correct **for the product ADR-0038 described** — a proof workbench whose
primary surface is the editor and the evidence view.

The v3 mandate changes the product. Tempest is now the application a person opens instead of
ChatGPT: a complete general assistant that can also prove code. Under that mandate the refusal's
premise no longer holds, because the thesis is no longer "only things that serve a proof belong in
the product." It is "everything belongs in the product, and the proof is what makes the coding part
trustworthy."

**Decision.** Adopt image generation in full — GPT-Image-1, DALL·E 3/2, Stable Diffusion, Flux, and
any MCP image server — classified `PLATFORM` under L30.

**The refusal's real content is preserved as a constraint, not discarded.** ADR-0038 was protecting
against a specific failure: features that *imply* verification they cannot deliver. L30 and L31 now
carry that protection explicitly and generally. Image generation:

- never renders inside an evidence surface;
- never borrows the verdict vocabulary, verdict colours, or verdict typography;
- is declared `PLATFORM` in `docs/FEATURES-V3.md`, and the ledger gate proves the declaration.

**Consequences.** Prompts and generated images are user data under L9 — they do not leave the
machine except through a provider the user configured, with the consent surface L9 already requires.
EXIF and geolocation are stripped from any image before it reaches a provider, test-verified.
The honest cost of this ADR is surface area: a category of feature now exists that no gate can
relate to the thesis. L30's classification requirement is what keeps that cost visible instead of
letting it accumulate silently.

---

## ADR-0064 — LibreChat is the base; the product is a desktop app; server mode is retained unbuilt (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Supersedes:** ADR-0038's "cannot be vendored" premise

**Context.** ADR-0038 concluded that LibreChat's code "cannot be vendored into this stack" and set
the strategy to *adopt the capability, re-implement it in our stack*. Fourteen foundations were
planned that way; P1, P2, P3, P4, P5, P9 and P11 shipped that way and are green.

Two things changed. First, the owner's requirement is now **every** LibreChat feature, not fourteen
— and re-implementing an entire mature platform is a multi-year project that would be permanently
behind upstream. Second, measured against the actual constraint, the "cannot be vendored" claim was
about the *deployment shape* (multi-user web service vs. local desktop app), not about the code.
A Tauri host can supervise a Node child process; it already supervises a Python one.

**Decision.** LibreChat is vendored into `packages/platform/` and becomes the base of the
application. **The shipped product is a desktop application, not a website.** Concretely:

- The Rust host remains the application: window, lifecycle, signing, keychain, sandbox tiers, audit
  log, undo journal, and ownership of every child process.
- LibreChat's Node/Express API runs as a supervised sidecar on a **Unix domain socket**, never a TCP
  port — a listening port fails enterprise security review and the threat model already says so.
- LibreChat's React client becomes the primary webview. Tempest's existing views are absorbed into
  it: one router, one store, one design system.

**Server mode is retained, unbuilt.** Because `packages/platform/server/` is LibreChat's real API,
LibreChat's multi-user web deployment remains runnable against a real Postgres. We keep that
capability, do not maintain it, and **do not let it drive a single architectural decision.** It is
a free option, not a product.

**Consequences.** L27 (upstream mergeability is a shipped feature) exists because of this ADR and is
the constraint that makes it survivable. The seven already-shipped P-features are re-examined in C4
and C5: where Tempest's re-implementation is better (provider router, agent runtime, keychain,
sandbox), it wins and LibreChat's surface re-targets onto it; where LibreChat's is better or richer
(MCP lifecycle, model-spec metadata, resumable-stream ergonomics), theirs wins and ours retires.
Neither outcome is embarrassing; shipping both would be.

---

## ADR-0065 — Speech in and out adopted (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Overturns:** ADR-0038 refusal 2 · **Law:** L30, L31

**Context.** ADR-0038 refused TTS on the grounds that "nobody listens to code," while conceding that
speech-to-text input "is defensible later." Under the general-assistant mandate (ADR-0069) the
premise is wrong twice over: most of what a general assistant produces is not code, and hands-free
use is a real accessibility and mobility requirement, not a novelty.

**Decision.** Adopt speech-to-text and text-to-speech in full — OpenAI, Azure OpenAI, ElevenLabs —
with automatic send and automatic playback. Classified `PLATFORM`.

**One constraint is retained and it is not stylistic.** **Verdicts are never spoken as prose.**
"Equivalent under budget" read aloud loses the qualifier that makes it honest; a listener hears
"it's fine." Evidence is read as evidence — on screen, with the reason chips and the coverage
numbers — or it is not delivered at all. TTS may narrate model explanation text (L17 narration),
never engine output fields (L31).

**Consequences.** A local STT path is available so that hands-free operation does not require
egress (L32). Cloud STT is opt-in per provider. Audio is user data under L9.

---

## ADR-0066 — Agent marketplace adopted, with mandatory capability signing (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Overturns:** ADR-0038 refusal 3, **partially**

**Context.** ADR-0038 refused an open marketplace because "for a tool with file-write and shell
access, an open marketplace is a supply-chain attack surface aimed directly at the most
security-sensitive customers," and replaced it with a signed, curated, org-scoped registry.

**That threat is real and has not changed.** It is the one refusal in ADR-0038 whose reasoning
survives the change of product mandate intact — the mandate changed what the product is *for*, not
what an unsigned shell-capable plugin can do to a user's machine.

**Decision.** Adopt LibreChat's marketplace — community agents, skills, plugins, discovery,
collaborative sharing to users and groups — **with one non-negotiable gate**:

> Any agent, skill, or plugin that requests `file-write`, `shell`, or `network` capability must
> declare that capability explicitly and be **signature-verified** before installation.

Capability-free items (prompt-only agents, instruction bundles with no tool access) install freely.
The declaration is machine-checked against what the item can actually reach, not taken on trust from
its manifest.

**Consequences.** This is a partial overturn and it is stated as one. The bazaar ships; the
unsigned-shell-access hole does not. The adversarial test — an unsigned, capability-requesting agent
must fail to install — is permanent and lives in `redteam --gate-subversion`. Curated org-scoped
registries remain available for enterprises that want a narrower surface; they are now a policy
setting rather than the only mode.

---

## ADR-0067 — Chat is the primary surface (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Overturns:** ADR-0038 refusal 4 · **Law:** L30, L31

**Context.** ADR-0038 refused chat-as-primary because "our primary surface is the editor and the
evidence view. Chat is a panel. Inverting that makes a ChatGPT clone with a proof feature." v2
failure mode 9 names this as the specific risk of the LibreChat adoption.

The owner's mandate is that people use Tempest **instead of** ChatGPT. That is not achievable with
chat as a panel: the first thirty seconds of the product decide whether anyone stays, and for a
general assistant those thirty seconds are a conversation.

**Decision.** Chat is the primary surface. The evidence surface is **one keystroke from anywhere**
and is where proof lives.

**The refusal's fear is answered structurally, not by reassurance.** "A ChatGPT clone with a proof
feature" is a product where the proof engine is optional decoration. That is prevented by mechanisms
that do not depend on which pane opens first:

- L28 — every path by which agent-authored code reaches the user is proof-gated, structurally,
  with a forge test per path;
- L31 — no adopted subsystem may write a verdict, and the vocabulary lint proves it;
- L35 — the parity ledger tracks proof features at the same rigour as platform features;
- the failure-mode check in the master prompt §13.2: *a week with no proof-related work landed means
  the product is drifting, and you say so out loud.*

**Consequences.** v2 failure mode 9 is not deleted — it is upgraded from "do not do this" to "this
is now the design; here are the four mechanisms that keep it from becoming the failure." A future
contributor reading only the failure-mode list must find this ADR from it.

---

## ADR-0068 — The document store: Mongo's data model, never Mongo's binary (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted, **pending the C1 spike measurement** · **Overturns:**
ADR-0038 refusal 5 · **Law:** L27, L33

**Context.** ADR-0038 refused MongoDB with "SQLite local, Postgres server. A third datastore buys
nothing." Under ADR-0064, LibreChat's entire data layer — `packages/data-schemas`, every model,
method, and migration — is vendored, and it is Mongoose from top to bottom. Rewriting it would
destroy L27's upstream mergeability for the single most schema-active package in the tree.

Four constraints bind simultaneously:

1. LibreChat's data layer is Mongoose and must not be rewritten (L27).
2. **MongoDB Community Server is SSPL** — declared not an open-source licence by the OSI in 2021,
   and encumbered for redistribution inside a product. Verified 2026-08-21.
3. The app is local-first and single-user by default (L32); idle RAM budget is bounded (L22).
4. Proof data — bundles, cassettes, observations, journals, indices — stays in SQLite (L33).

**Decision.** Adopt Mongo's **data model and wire protocol**; ship none of Mongo's binaries.

- **FerretDB 2.x** (Apache 2.0) + **PostgreSQL** (PostgreSQL Licence) + Microsoft's **DocumentDB**
  extension (MIT), as a supervised sidecar under `supervisor.rs` (L34), on a Unix domain socket.
- `packages/platform/data/` is vendored **byte-for-byte**. Mongoose talks a wire protocol; it does
  not know what is answering. That is the entire point of this decision.
- Proof data stays in engine SQLite. **Two stores is the accepted cost of L27; a third is not**, and
  moving proof data into the document store is forbidden. Cross-store references are opaque ids
  only, declared in `docs/MERGE-CONTRACT.md`, never joins.

**The spike is mandatory and can overturn this ADR without a new one.** Phase C1 measures cold
launch to interactive, idle RAM, idle CPU, and p95 latency on the ten hottest LibreChat queries,
on the 4-core / 16 GB reference profile. If any budget in master prompt §10 is missed by more than
25%, the pre-approved fallback engages: keep Mongoose's *models* and *methods* as the public API and
implement a document-store adapter over engine SQLite (document table + expression indices). Taking
the fallback requires only that the measurement be recorded here — not a new decision.

**§4 — Redis.** LibreChat uses Redis for cache, cluster coordination, and resumable-stream delta
batching. None of the three needs a network service in single-user desktop mode. Adopt the
interface; back it with an in-process LRU plus engine SQLite for durability; keep real Redis as a
config option for the unbuilt server mode (ADR-0064).

**Consequences.** Three extra processes at idle, reflected honestly in the revised §10 budget
(550 MB p50 idle rather than v2's 300 MB). Pretending the old number survives a merged app would
guarantee a missed gate in C12 followed by a quiet re-baselining, which is the exact failure L22
exists to prevent.

---

## ADR-0069 — General-purpose assistant framing adopted (overturns ADR-0038) (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Overturns:** ADR-0038 refusal 6 · **Law:** L30, L31

**Context.** ADR-0038 refused general-assistant framing: *"'Do anything' is the opposite of 'prove
this.' Every general capability dilutes the one sentence that sells this product."* The concern is
about **positioning dilution**, and it is a real risk.

**Decision.** Tempest is a general-purpose assistant that can prove code.

**The dilution risk is answered by separating two claims that ADR-0038 treated as one.** The
positioning sentence is not "Tempest only does verifiable things." It is:

> Every other assistant tells you it is done. Tempest shows you the evidence — or tells you,
> honestly, that it could not get any.

That sentence survives generality completely. It is a claim about **what happens when Tempest writes
code**, not a claim about the boundaries of what Tempest will discuss. A user asking for a poem does
not weaken it. A user asking for a refactor and getting "verified" without a bundle destroys it —
which is L28, and L28 is structural.

**The constraint that carries the refusal's real content:** the proof claim is never diluted into a
general claim. **"I checked" is not a verdict.** Only the engine may say something stronger than
narration, and L31's reserved vocabulary plus the `vocab_check` lint make that mechanical rather
than editorial.

**Consequences.** Marketing and in-product copy must hold two registers precisely: confident and
general about capability, exact and narrow about proof. Copy review is added to the C12 craft
campaign, because this is the one failure that no automated gate can catch.

---

## ADR-0070 — Code interpreter adopted (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L19, L28, L30

**Context.** Not previously in scope. LibreChat ships sandboxed execution across Python, Node/TS,
Go, C/C++, Java, PHP, Rust, and Fortran with file upload, processing, and download.

**Decision.** Adopt in full, classified `PROOF_ADJACENT`.

**It runs on Tempest's tier ladder, not beside it.** Tempest already has a containment story that
has been audited, escape-tested on three OSes, and gated (`escape_suite`, F14's agent terminal,
27/27 contained). Running a second, parallel execution sandbox would mean two containment
implementations, two audit surfaces, and two ways to be wrong. **No tier, no execution.** The
existing rule holds unchanged: no container runtime → the operation is refused with a reason code,
never silently unsandboxed.

**The proof relationship is real and worth naming.** Code the interpreter executes is code whose
behaviour can be recorded, and a cassette recorded in the interpreter is a cassette the differential
runner can replay. That link is built in C8; until it is, the feature is honestly `PROOF_ADJACENT`
and not `PROOF_NATIVE`.

**Consequences.** `escape_suite` gains a `--surface code-interpreter` leg covering all tiers and all
three OSes. Background execution and stateful sessions inherit L15.4's budget-and-cancellation
requirement without exception.

---

## ADR-0071 — RAG, file chat, and OCR adopted; retrieved bytes are hostile (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L9, L30 · **Threat model:** T1/T6

**Context.** Not previously in scope, and a substantial category: document upload, chunking,
embedding, retrieval, OCR, and chat-with-files across every endpoint.

**Decision.** Adopt in full, classified `PROOF_ADJACENT`.

**Every retrieved byte is attacker-controlled input, never instruction.** This is not a new rule —
P9 established it for web search and `redteam --injection` proves it at 30/30 with the model
scripted as ALREADY CAPTURED. C8 extends the identical treatment to RAG chunks, file contents, and
OCR output. A document that says "ignore your instructions" is a document, not an instruction.

**Local-first is load-bearing here.** Embeddings and the vector index are computed and stored
locally by default (the engine already has a local, deterministic, dependency-free embedding path
from Phase 22). A cloud embedding provider is opt-in per repository with the L9 consent surface.
`rag_api` is a **separate repository with its own licence** — review independently and record the
review before adopting anything from it.

**Consequences.** The C1 storage budget accounts for a local vector index. PII scrubbing at import
is on by default with a preview of exactly what was scrubbed, reusing F10's scrubber and its
planted-secret tests.

---

## ADR-0072 — Admin panel adopted; it cannot disable the proof gate (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L28, L32

**Decision.** Adopt LibreChat's browser-based admin panel in full — users, groups, roles, live
config overrides, delegated config sections, encrypted registered secrets — classified `PLATFORM`.

**Two invariants, both structural:**

1. **The admin panel gates team features only.** It never gates local operation. Airplane mode gives
   full local functionality with zero auth prompts (L32), and that is a tested gate, not a policy.
2. **An administrator cannot disable the proof gate.** L28 is enforced by `ProvenChange` having no
   constructor without a bundle id, not by a permission check. There is no role, no config key, and
   no override that produces a verified label without a bundle. If a reviewer can imagine such a
   path, that is a P0 and a forge test.

**Consequences.** The panel's config surface merges with `tempest.toml` precedence (CLI flag > file
> default) rather than introducing a second configuration system. Every privileged action taken
through the panel is audit-logged under L14 to the append-only tamper-evident local log, regardless
of whether enterprise features are enabled.

---

## ADR-0073 — Scheduled agent runs adopted (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L14, L20, L21, L28

**Decision.** Adopt LibreChat's schedules — unattended, recurring agent runs — classified
`PROOF_ADJACENT`.

**An unattended run is subject to every law an interactive run is, without softening.** Journalled
(L14), budgeted with hard caps at the router (L21), reversible by one keystroke including multi-file
edits (L20), and proof-gated (L28). The temptation this feature creates is a "trusted" fast path for
runs nobody is watching, on the grounds that nobody is there to read the verdict. That reasoning is
exactly backwards: **an unwatched run is the one that most needs a verdict waiting when someone
returns.**

**Consequences.** Scheduled runs that produce `DIVERGENT` or `UNPROVEN` surface as first-class
notifications with the evidence attached, never as a silent log line. Budget exhaustion mid-schedule
pauses the schedule and reports; it does not silently skip.

---

## ADR-0074 — i18n adopted wholesale: 44 locales, and the verdict vocabulary is translatable (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Supersedes:** P14's "adopt the structure" plan

**Context.** P14 planned to adopt LibreChat's i18n *structure* and ship English plus four locales.
Under ADR-0064 the client is vendored, and 44 fully translated locale directories come with it.
Re-deriving four from scratch when 44 already exist and are maintained upstream is pure loss.

**Decision.** Adopt all 44 locales wholesale. Tempest's strings are added as new keys in the same
pipeline, so upstream translation work continues to flow in under L27.

**The strings that matter most are ours.** Every `reason_code` explanation, every verdict, and every
`UNPROVEN` blocking reason must be translatable — **a verdict a user cannot read is not evidence.**
Zero hardcoded user-facing strings, lint-enforced across both trees. Pseudo-locale catches
truncation and layout breakage; RTL layout is verified, not assumed.

**Consequences.** `i18n_check --no-hardcoded-strings --pseudo-locale --rtl` runs over
`packages/platform/**` and `packages/desktop/**` together. Untranslated Tempest keys fall back to
English with a visible marker in development and a silent fallback in production — never a raw key
in front of a user.

---

## ADR-0075 — One agent runtime: the Python orchestrator wins, LibreChat's surface is adopted (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L29 · **Builds on:** ADR-0049

**Context.** Both systems ship a production agent runtime. LibreChat's is mature and has a superb
surface: no-code builder, unified tools marketplace, skills, plugins, subagents, run control
(interrupt, steer mid-run, queue follow-ups, reclaim and escalate pending steers), human-in-the-loop
pause for input and tool approval, generated activity-group headers, phase summaries, context-usage
gauge, stream circuit breakers. Tempest's is proof-terminated and gated: `agent_bench` 55/55,
`intent_bench` 54/54 with zero false-intended, `repair_bench` 22/28 and 11/11 cheat-refusals,
`resume_test` 15/15.

L29 says ship one. This is the decision, and it is the one place where "LibreChat is the base"
(ADR-0064) is deliberately overridden.

**Decision.** **The Python orchestrator (`tempest/agent/`) is the runtime.** LibreChat's agent
*surface* is adopted in full and re-targeted onto it.

**Why the override:**

- ADR-0049's argument is unchanged and decisive: the turn loop's terminating condition is a proof,
  the prover is Python, and any other host must call into Python on every turn.
- L16/L28 require the proof gate to be structurally unbypassable. Today that is achieved by
  `ProvenChange` having no constructor without a bundle id and exactly one construction site.
  Reproducing that guarantee inside a second runtime doubles the attack surface for no gain.
- Budget enforcement, the single-lock cost ledger (ADR-0041), the shadow-worktree manager
  (ADR-0036), the journal and one-keystroke undo (ADR-0039), and subagent budget accounting
  (ADR-0059) are all Python, all correct, and all gated.
- LibreChat's agent value is overwhelmingly in the **surface and ergonomics**, not the loop. That is
  the part that took years and the part users touch, and it is adopted entirely.

**The seam.** `api/server/services/Agents/**` becomes a thin client over boundary E that speaks the
same shapes to the React client and delegates every turn to the Python orchestrator. Tool registries
unify on `agent_tools.rs` (boundary D), which stays the root of truth for capability declarations
and approval invariants — because that is where `WriteScope` **structurally cannot express** a write
to the user's working tree, and an unrepresentable state cannot be reached by a bug.

**Consequences, stated honestly.** This is the largest item in the plan (phase C5) and it touches
LibreChat's most actively developed subsystem, which makes upstream merges in `services/Agents/`
painful permanently. That cost is accepted and recorded in `UPSTREAM.md`'s delta ledger. The
alternative — two runtimes, two tool registries, two budget meters, two cancellation stories — costs
more, forever, and produces a worse product. C5's gate re-runs `agent_bench --tasks 50
--require-verdict-coverage 1.0` **through the new surface**: if the number is not still 55/55, the
merge broke the thing the product is for.

---

## ADR-0076 — One provider router: `tempest/inference/`, with LibreChat's configuration schema (2026-08-21)

**Date:** 2026-08-21 · **Status:** accepted · **Law:** L18, L21, L29 · **Builds on:** ADR-0040, ADR-0041

**Context.** Tempest has 16 providers over two wires (Anthropic Messages, OpenAI Chat Completions),
stdlib-only, no vendor SDK, no per-provider branch, with real streaming cancellation proven by an
observed broken pipe, and a cost meter whose caps and ledger append **under one lock** (a test starts
8 threads against a cap admitting 2 and gets exactly 2). LibreChat has broader model-spec metadata,
richer per-endpoint parameter UI, reasoning-UI support, and adaptive provider smoothing.

**Decision.** One router: `tempest/inference/`. LibreChat's provider **configuration schema**,
model-spec metadata, parameter UI, and reasoning-UI support are adopted and mapped onto it.

- **Caps are enforced at the router, never in the UI.** A UI-enforced cap is not a cap.
- The cost meter remains the single spend-enforcement point and continues to ship **no price list**:
  tokens measured from the provider's own usage, dollars only from a rate the user supplies, and a
  dollar cap with no rate **raises** rather than passing.
- Keys live in the OS keychain (`keychain.rs`), never plaintext, never synced (L18). LibreChat's
  `credentials.ts` path is replaced, not bridged — see `MERGE-CONTRACT.md`.
- Adding a provider must not touch feature code in either tree.

**Rider — closing 19.5b.** Migrate `harness/llm.py` and `report/narrative.py` onto the unified
client and drop the `anthropic` SDK dependency. This has been open since Phase 19 and it blocks the
claim that there is one model path. `grep -r "anthropic" packages/engine` finding no SDK import is
part of C4's gate.

**Consequences.** `provider_matrix` raises its floor from `--min-providers 12` to `--min-providers 16`
and gains LibreChat's endpoints. Where LibreChat supports a provider Tempest does not, it is added
as configuration, not code. Where Tempest's two-wire abstraction cannot express a LibreChat endpoint,
that is an ADR, not a special case.
