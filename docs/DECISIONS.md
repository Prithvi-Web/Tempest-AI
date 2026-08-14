# Architecture Decision Records

Append-only. Every deviation from `tempest-master-prompt` gets an entry **before** the deviating
code lands. Format: context → decision → consequences/risk.

---

## ADR-0001 — Record/replay determinism layer is a v1 requirement

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Differential execution is only meaningful under identical conditions (Law L3). Most
real-world changed code is impure: it reads clocks, RNGs, files, sockets, env, processes. Without
record/replay, Tempest would be limited to pure functions — a toy.

**Decision.** Build the cassette-based record/replay subsystem (master spec §4.4) as a first-class
v1 component: record once against base, replay both revisions from the identical cassette; value
divergence and effect divergence are both first-class findings; cassette miss = `DIVERGENT`;
un-interceptable surface = `UNPROVEN(UNINTERCEPTABLE_EFFECT)`.

**Risk (stated plainly).** This is the project's existential risk. Interception at module
boundaries can be bypassed (C extensions, cached references to originals, native addons), replay
ordering under concurrency is genuinely hard, and over-normalization can mask real divergence.
Mitigation: Phase 2 is gated on a 30-function real-world corpus — ≥24/30 byte-identical replays
across 5 consecutive runs, and the build **stops and reports** if the bar is missed. The corpus
runs before any dashboard work; we do not build UI on sand.

## ADR-0002 — Autonomous session: §16 "question list, then wait" answered by recorded defaults

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Master spec §16 says to produce a question list and wait. This build runs in an
autonomous session; the user is not available mid-run and instructed "make Tempest AI and store it
on GitHub".

**Decision.** The question list lives in `docs/QUESTIONS.md` with the default answer chosen for
each, cross-referenced to ADRs. The build proceeds on those defaults. The user can overturn any of
them later; each is isolated behind a small surface.

**Consequences.** No silent choices: anything §16-ambiguous is written down with its chosen answer.

## ADR-0003 — No container runtime on the dev machine: sandbox behavior

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Law L6 requires every execution of user code to run in a container (no network,
RO rootfs, limits, non-root). This development machine has **no Docker** (verified:
`docker NOT FOUND`), and installing Docker Desktop needs admin interaction.

**Decision.**
1. The sandbox module ships Docker-first: `DockerSandbox` implements L6 fully (network-none,
   read-only rootfs + scratch tmpfs, memory/pids/wall limits, non-root UID, seccomp profile in
   `docker/seccomp-tempest.json`). It is the only backend selectable for user repos. There is no
   flag to disable it.
2. On a machine without a usable container runtime, `tempest prove` against a user repo returns
   `UNPROVEN` with `reason_code=SANDBOX_UNAVAILABLE` and an actionable message. Never silently
   unsandboxed.
3. A `ProcessSandbox` (separate process, scrubbed env, rlimits, cwd jail) exists **only** for
   Tempest's own first-party test fixtures and corpus (trusted code we wrote), so the engine's
   gates can run on this machine. It is not reachable from the public CLI for arbitrary repos.
4. CI (GitHub Actions, Docker available) exercises the DockerSandbox path.

**Risk.** The Docker path gets less local exercise than the process path until a Docker-equipped
machine runs it; mitigated by making CI the enforcement point and keeping both backends behind one
`Sandbox` interface with a shared conformance test suite.

## ADR-0004 — Node 24 on the dev machine (spec pins Node 22)

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §5 pins Node 22. This machine has Node 24.16.0; installing a second Node
runtime adds drift risk for a non-coder-maintained machine.

**Decision.** `engines: { "node": ">=22" }` everywhere; CI matrix runs Node 22 so the pinned
version stays the enforced baseline; local dev uses Node 24.

**Consequences.** Any Node-24-only accidental usage is caught by CI on 22.

## ADR-0005 — GitHub publication via the user's GitHub Desktop flow

**Date:** 2026-08-13 · **Status:** accepted

**Context.** "Store it on GitHub" is part of the task. No `gh` CLI is installed, and this
non-interactive session cannot complete an OAuth device flow. The user's established workflow for
all prior projects is GitHub Desktop.

**Decision.** The repo is built with clean conventional commits on `main`, ready to publish.
Final handoff includes exact GitHub Desktop steps (Add Local Repository → Publish). Phase 6's
live-PR gate (which needs the repo on GitHub) runs after publication.

## ADR-0006 — Stage-3 synthesis: deterministic type-driven first, LLM optional

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §3 requires the CLI to work fully offline with zero backend, while §4-stage-3
puts an LLM in the harness-synthesis loop. Both cannot be unconditionally true at once.

**Decision.** `AdapterSynthesizer` is a strategy interface. Order: (1) `TypeDrivenSynthesizer` —
deterministic construction from type hints + usage inference; (2) `LLMSynthesizer` — used only when
`ANTHROPIC_API_KEY` is set (model: `claude-sonnet-5`), for targets the deterministic pass could not
harness. Both pass the identical validate-by-execution gate; acceptance is never based on reading
the code. The LLM never writes verdicts (Law: verdicts come from the runner).

**Consequences.** Offline runs lose only hard-to-construct targets (they surface as
`UNPROVEN(HARNESS_SYNTHESIS_FAILED)` — honest), and gain them back when a key is present.

## ADR-0007 — Auth in development: real wiring, dev-mode credentials

**Date:** 2026-08-13 · **Status:** accepted

**Context.** Spec §5 requires GitHub OAuth (Auth.js) + JWTs + CLI PATs. Registering a GitHub OAuth
app requires the user's GitHub account interaction and secrets this session cannot mint.

**Decision.** Implement the real auth surfaces (Auth.js GitHub provider, JWT issuance/validation,
PAT-style CLI tokens hashed at rest). Dev mode (`TEMPEST_DEV_AUTH=1` + compose defaults) enables a
deterministic local credential so the stack runs end-to-end without the OAuth app. Production
config requires the real GitHub OAuth env vars; missing vars fail loudly at boot, they do not fall
back to dev mode.

**Consequences.** The user must create the GitHub OAuth app before any real deployment; documented
in `docs/QUESTIONS.md` Q4.
