# §16 Question List — genuinely ambiguous points, with the defaults this build chose

Per ADR-0002 (autonomous session), each question is answered with a recorded default instead of
blocking. Overturn any of these and the affected surface is small and isolated.

**Q1. Which LLM provider/key powers Stage-3 adapter synthesis, given the CLI must also run fully
offline?**
→ Default: deterministic type-driven synthesis always; Anthropic `claude-sonnet-5` used only when
the **end user** supplies their own `ANTHROPIC_API_KEY` (strict BYOK — the project owner never
pays for anyone's tokens; no key ships with Tempest). (ADR-0006)

**Q2. What happens on machines without Docker, given Law L6 forbids unsandboxed execution?**
→ Default: `UNPROVEN(SANDBOX_UNAVAILABLE)` for user repos; a process-isolation backend exists only
for Tempest's own trusted fixtures/corpus so gates can run here; CI enforces the Docker path.
(ADR-0003)

**Q3. GitHub repo name/visibility, and how does it get published without `gh` auth?**
→ Default: local repo `tempest`, published by the user via GitHub Desktop (their standing
workflow); visibility is the user's choice at publish time. Phase 6's live-PR gate runs
post-publication. (ADR-0005)

**Q4. GitHub OAuth app credentials for the dashboard — who registers them?**
→ Default: real Auth.js wiring with a loud dev-mode credential for local compose; the user
registers the OAuth app (Settings → Developer settings → OAuth Apps) before any deployment and
fills `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`. (ADR-0007)

**Q5. The 30-function Phase-2 corpus must be "drawn from real open-source repos" — vendored code or
referenced checkouts?**
→ Default: vendor small permissively-licensed (MIT/BSD/Apache) functions with per-file attribution
headers (repo, commit, license) into `corpus/impure/`, so the gate is hermetic and offline. GPL
code is excluded. (ADR to be appended when the corpus lands in Phase 2.)

**Q6. "Node 22" is pinned but the dev machine runs Node 24.**
→ Default: `engines >=22`, CI pins 22. (ADR-0004)

**Q7. §16 says "produce the docs, then wait" — wait for whom in an autonomous run?**
→ Default: don't block; record the answers here and proceed. (ADR-0002)

---

# v2.0.0 — the owner's decisions, and what is still open

## ANSWERED 2026-08-18 (owner) — these are now binding, not proposals

| # | Question | Owner's decision |
|---|---|---|
| — | The `v1.0.0` tag shipping `0.2.0` artifacts | **Retag as `v0.2.0`.** Done locally (annotated, on `6debcec`); the remote tag + release deletion needs the owner (no push credential — trap 13). |
| **QV8** | Scope doubled: fund all 14 phases or cut? | **Fund phases 19–27.** 28–32 are a later decision. |
| **QV9** | "Better than any other AI" vs the rejection table | **Build every feature in the master prompt, one at a time**, each landing flawless with a mini release. The rejection table stands — breadth comes from F1–F21 + P1–P14, not from becoming a general assistant. |
| — | Licence | **MIT, open source.** Copying LibreChat code is authorized (it is MIT too), with a section stating Tempest is based on LibreChat. Implemented in 19.1 + ADR-0038 amendment. |
| **QV3** | Is `packages/web` still a shipping product? | **Answered by the tree, not by opinion:** `git ls-files packages/web` returns **zero files** and `pnpm-workspace.yaml` lists only shared-schema, ts-sidecar, and desktop. The web app is already gone; only stale `node_modules` remain on disk. Desktop is the sole surface. `CLAUDE.md` §5's Next.js/Postgres rows are v1-era history. |

**Working agreement for the build-out:** one feature at a time; after each, a mini release and a
plain-English report naming the step we are on, so the work survives across sessions.

---

## STILL OPEN — needed before the phase that depends on them


QV3, QV8 and QV9 are answered above and removed from this list. The rest remain genuinely open,
each with a recommendation. **None of them blocks the current work** — each is needed only by
the phase named in it, so the build proceeds and these get answered as their phase approaches.

**QV1. The 60% proof-rate bar vs starting 21 features of feature work. (THE BIG ONE.)**
The v1 rule, recorded in `docs/METRICS.md`, is: *below ~60% real-world proof rate, ENGINE work
outranks feature work.* Today's measured real-world number is **34% keyless** (198 targets,
5 OSS repos). v2 is entirely feature work. This is a direct conflict between a standing recorded
rule and the new plan — and it is not academic: F1's whole promise is that the agent terminates
on a verdict, but at a 34% proof rate roughly two-thirds of the agent's changed symbols come back
`UNPROVEN`. That is *honest* (L16 requires the label) but it is a weak product: "I changed 9
things and could prove 3 of them."
→ **Recommendation:** insert a **Phase 19a — engine proof-rate wave** before the agent core,
targeting the two levers the bundles already name: the **112 plain-class instance-method targets**
(ADR-0024's key-gated constructor synthesis — needs QV2's key) and the residual
`HARNESS_SYNTHESIS_FAILED`. Re-measure `tempest.dev.real_world`; only then start Phase 21.
Alternative if the owner wants v2 velocity now: proceed, but publish agent verdict coverage
(number 4) next to proof rate from day one so the weakness is visible rather than hidden.

**QV2. Who pays for the model tokens the v2 gates consume, and can they run in CI?**
`make verify-v2` includes `agent_bench --tasks 50`, `intent_bench --tasks 40`,
`repair_bench` (up to 4 repair attempts each), `retrieval_bench --questions 40` and
`mutation_bench`. These are real model calls in the thousands. L18 says BYO keys and the
project owner never pays for anyone's tokens (Q1/ADR-0006) — but a gate that cannot run in CI
is a claim, not a fact (trap 37/ADR-0021-amendment). Options: (a) owner funds a CI key with a
hard monthly cap; (b) the benchmarks run against a **local model** in CI (cheap, reproducible,
but measures a weaker model than users will use); (c) benchmarks are local-only, run by the
owner on demand, and CI gates only the *machinery* against a fake Messages peer (today's
pattern for ADR-0024).
→ **Recommendation: (c) + (a)** — machinery gated in CI against the fake peer on every PR
(free, deterministic, catches regressions), plus a scheduled owner-run real-model measurement
whose numbers land in `METRICS.md`. Never let a keyless CI run *report* a real-model number.

**QV4. `WEAK_EVIDENCE` breaks L2's closed verdict vocabulary — verdict, or modifier?**
F9 adds `WEAK_EVIDENCE`, but L2 enumerates exactly four verdicts and v2 says v1 wins absent an
ADR. Two shapes: (a) a **fifth verdict** — breaks every exhaustive match in four languages
(the design working) but silently changes the meaning of every stored bundle, since bundles
written before F9 have no mutation score and must not be retro-labeled; or (b) an **evidence-
strength attribute on `EQUIVALENT_UNDER_BUDGET`** — no vocabulary change, bundles stay
comparable, and the UI can still show it at full prominence.
→ **Recommendation: (b)**, with the attribute displayed as loudly as a verdict. It keeps L2
intact, keeps historical bundles honest, and matches how the number actually behaves (it
qualifies an equivalence claim; it is not a fifth outcome). Needs an ADR either way.

**QV5. Windows and Linux desktop builds do not exist, but Phase 31 gates 150 craft items on
three OSes.** Today's release ships a macOS `.app` only; `tauri-driver` has no macOS/WKWebView
backend (ADR-0031 §5), so the built-app driver leg is already platform-blocked. Nothing in
Phases 19–32 schedules Windows/Linux desktop builds — and Phase 29 (P10 enterprise auth/LDAP)
targets exactly the buyers who run Windows. The revised craft bar makes this sharper, not
softer: `POLISH.md` now has explicitly Windows-only items (Mica, jump lists, NVDA) that no
amount of macOS work can satisfy.
→ **Recommendation:** add an explicit **Windows + Linux desktop phase before 29** — it also
unblocks the built-app E2E leg that macOS structurally cannot run, and it is a prerequisite for
P10 landing with anyone real. The alternative is to scope v2 to macOS and rewrite POLISH.md's
three-OS columns to one. **Pretending three OSes are covered when one is built is exactly the
kind of claim this product exists to refuse.**

**QV6. Is `tempest.dev.dogfood --prove-own-pr` (L24) achievable on this repo, and what rate is
publishable?** Tempest is a Python+Rust+TS monorepo; its own PRs frequently change Rust and
TS-in-Tauri code paths the engine cannot yet prove. A published Tempest-on-Tempest proof rate
that reads, say, 15% is honest but is also the number every visitor sees in the README.
→ **Recommendation:** publish it anyway, with the denominator broken out by language — a low,
explained number is on-brand and is exactly what "evidence, not opinion" costs. But the owner
should agree to that *before* Phase 30, not discover it at GA.

**QV7. F16's MCP server is "licensable separately" — does that imply a paid tier now?**
v1 has a license subsystem, but no pricing has been decided, and a licensing gate touches the
threat model (the server exposes `prove` to arbitrary callers).
→ **Recommendation:** ship the MCP server unlicensed and fully local in v2 (it is the best
distribution move — competitors' agents calling Tempest is the marketing), and defer any
license split to a post-GA commercial decision.

---

## New with the LibreChat adoption (QV8–QV12)

**QV10. P1 says 12+ providers; L18 says BYO keys only. Who pays to *test* 12 providers?**
This is QV2 (CI token funding) with a multiplier: `provider_matrix --min-providers 12` implies
credentials for twelve services. Most have free tiers; several do not.
→ **Recommendation:** the gate asserts **configurability and adapter correctness** against
recorded fixtures for all twelve (free, deterministic, runs in CI), plus a **live smoke test
against whichever providers the owner actually holds keys for**, reported honestly as "N of 12
verified live." A matrix that claims twelve live providers we never called would be exactly the
kind of unearned claim this project exists to refuse.

**QV11. P10 LDAP requires a directory server to test against.**
"LDAP against a real directory" is the gate. We have no directory, and standing one up is
infrastructure the owner would need to provide or fund.
→ **Recommendation:** gate against a containerized OpenLDAP with a seeded fixture directory
(real protocol, real bind, hermetic and free) and mark the "against a customer's real AD/LDAP"
leg as **owner-gated, unverified until a design partner supplies one** — stated in METRICS
rather than assumed. Note this also collides with QV5: Phase 29 is enterprise reach, but the
Windows desktop that most LDAP buyers run on still does not exist.

**QV12. Is chat a panel we build, or do we skip it?**
The rejection table says chat must never be the primary surface, and F13 (execution-grounded
codebase chat) is the sanctioned conversational surface. But P6 (branching), P3 (skills), and
P12 (export) are all described in conversational terms, which implies a real chat panel with
history, forking, and persistence.
→ **Recommendation:** build **one** conversational surface — F13's — and let P6/P3/P12 operate
on *agent runs*, not on a separate chat product. One surface, one history model, one export
format. Two would be the drift L25 warns about, and it would show up first as duplicated state
and second as a ChatGPT clone nobody asked for.
