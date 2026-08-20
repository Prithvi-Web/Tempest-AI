# Tempest AI — The Six Numbers

> v2.0.0 master prompt §12: report all six in every status update. They are the company.
> Numbers 1–3 are the v1 three (Phase 8+ §8); numbers 4–6 are added by v2 and are
> **not yet measurable** — the features that produce them are Phases 21–24. They are listed
> here now, with their gate commands, so that "not measured" is visible rather than absent.
> Every figure below is a real measurement with its command; nothing is estimated.
> Each figure carries its own measurement date inline — they were taken on different days as
> each lever landed (proof rate re-measured 2026-08-16 after ADR-0027; TTFD 2026-08-17 with
> ADR-0032; the original baseline 2026-08-13 at commit `2358b97`). Machine for all of them:
> Apple Silicon macOS, Python 3.12.13.
> **Re-verified green at the v2 kickoff: 2026-08-18, commit `6debcec`** (`make verify` exit 0,
> 1038 passed, 100.00% coverage) — that run re-confirms the gates behind these numbers; it did
> not re-run the real-world corpus, which is unchanged since 2026-08-16.

| # | Number | Status today |
|---|---|---|
| 1 | Proof rate | **43%** real-world keyless (198 targets, 5 OSS repos), up from 34% after Phase 19a; 100% on the validation fixture |
| 2 | False divergence rate | **0** |
| 3 | Time-to-first-divergence | **6.4 s** demo (bar 90 s); real-repo TTFD still uninstrumented |
| 4 | Agent verdict coverage | **not measurable — no agent exists yet** (Phase 21; L16 target: 100%) |
| 5 | Agent task success rate | **not measurable yet** (Phase 21) |
| 6 | Mutation score | **not measurable yet** (Phase 24, F9) |

*(§§4–6 below state exactly what will measure them. Reporting a number we cannot measure
would violate L1 — evidence or silence — so they read "not measured", never "0" or "n/a".)*

## 1. Proof rate

**Definition:** of the changed symbols in a run, the fraction that reached a real verdict
(`DIVERGENT` or `EQUIVALENT_UNDER_BUDGET`) instead of `UNPROVEN`.

| Corpus | Measured | Command |
|---|---|---|
| pyfix fixture (12 seeded behavior changes + 12 no-op refactors; pure + impure-recordable) | **24/24 targets proven = 100%** | `TEMPEST_DEV=1 tempest prove --base base --head head --repo <pyfix> --max-inputs 40 --seed 0` |
| pyfix instance-method fixtures (c01–c03; AI constructor synthesis, ADR-0024) | **0/3 keyless (honest UNPROVEN + remediation) → 3/3 exercised with a key** — seeded changes DIVERGENT, no-op clean, offline cache rerun identical. Machinery-measured against a local Messages-API peer; the real-model number awaits an owner key (2.2) | `pytest packages/engine/tests/integration/test_llm_synthesis_pyfix.py` |
| tsfix fixture (TypeScript, wave 1 — 4 seeded changes incl. async, 1 no-op refactor, 1 shim-dependent no-op; ADR-0028) | **6/6 executable targets correct: 4 DIVERGENT + 2 EQUIVALENT, zero false divergences; unexported + fetch-touching honestly UNPROVEN** | `pytest packages/engine/tests/integration/test_prove_tsfix.py` |
| 30-function impure corpus (HTTP / fs / time-random) — record/replay stability, the proof-rate precondition for impure code | **30/30 stable ×20 consecutive replays** | `python -m tempest.dev.corpus_check --min-pass 24 --repeats 20` |

### The first real-world measurement (2026-08-16, HANDOFF-WORLD-CLASS 2.2, ADR-0025)

Five real open-source repos, real consecutive release pairs, T2 Seatbelt, keyless,
`max_inputs=30`, exact SHAs recorded. Command:
`TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.real_world corpus/real-world.toml`

| Repo | Base → Head | Tier | Targets | DIVERGENT | EQUIVALENT | UNPROVEN | ERROR | Proof rate |
|---|---|---|---|---|---|---|---|---|
| packaging | 26.2 `84a87ee42483` → 26.3 `929fd4b1410a` | T2 | 153 | 5 | 33 | 115 | 0 | 38/153 (25%) |
| semver | 3.0.0 `3a7680dc4362` → 3.0.4 `6adf8765f6e2` | T2 | 10 | 0 | 4 | 6 | 0 | 4/10 (40%) |
| humanize | 4.15.0 `2ddb5903cdc1` → 4.16.0 `3c577d765050` | T2 | 24 | 0 | 0 | 24 | 0 | 0/24 (0%) |
| more-itertools | v11.0.2 `247e15b3a489` → v11.1.0 `64be96ceb2a6` | T2 | 4 | 0 | 0 | 4 | 0 | 0/4 (0%) |
| python-slugify | v8.0.1 `58031becacdc` → v8.0.4 `f85f94885201` | T2 | 7 | 0 | 0 | 7 | 0 | 0/7 (0%) |
| **overall** |  |  | **198** | **5** | **37** | **156** | **0** | **42/198 (21%)** |

**Re-measured 2026-08-20 after Phase 19a (ADR-0048) — 34% → 43%, the second movement of the
corpus number:**

| Repo | Base → Head | Tier | Targets | DIVERGENT | EQUIVALENT | UNPROVEN | ERROR | Proof rate |
|---|---|---|---|---|---|---|---|---|
| packaging | 26.2 `84a87ee42483` → 26.3 `929fd4b1410a` | T2 | 153 | 5 | 50 | 98 | 0 | 55/153 (36%) |
| semver | 3.0.0 `3a7680dc4362` → 3.0.4 `6adf8765f6e2` | T2 | 10 | 0 | 4 | 6 | 0 | 4/10 (40%) |
| humanize | 4.15.0 `2ddb5903cdc1` → 4.16.0 `3c577d765050` | T2 | 24 | 4 | 17 | 3 | 0 | 21/24 (88%) |
| more-itertools | v11.0.2 `247e15b3a489` → v11.1.0 `64be96ceb2a6` | T2 | 4 | 0 | 0 | 4 | 0 | 0/4 (0%) |
| python-slugify | v8.0.1 `58031becacdc` → v8.0.4 `f85f94885201` | T2 | 7 | 1 | 5 | 1 | 0 | 6/7 (86%) |
| **overall** |  |  | **198** | **10** | **76** | **112** | **0** | **86/198 (43%)** |

**What moved, and what only looked like it moved.**

* **+18 targets proven, every one of them an instance method.** `TARGET_UNREACHABLE` fell from
  **112 to 94** and `EQUIVALENT` rose by 20 — the deterministic constructor rung now attempts
  plain classes, so a receiver it can build mechanically is proved with no key, no network and no
  money. packaging alone went 25% → 36%.
* **`DIVERGENT` fell from 12 to 10, and that is NOT this change.** Both losses are in humanize,
  on `naturalday` and `naturaldate` — date-relative functions, measured four days apart. The A/B
  that settles it: `typed.py` was temporarily reverted to its dataclass-only form and humanize
  re-measured **today**, giving `4 | 17 | 3` — identical to the new code. The recorded 6 belongs
  to 2026-08-16's calendar, not to a regression. (Same discipline as the cold-launch A/B in
  ADR-0047: when a number moves, revert the suspect and re-measure rather than reason about it.)
* **Nothing regressed.** Four repos improved or held; no repo lost a proven target.

**Still 43%, not 60%.** The standing rule stands: the engine still outranks feature work. The
distribution below remains the roadmap, and `TARGET_UNREACHABLE` at 94 is still the dominant
bucket by an order of magnitude — the residue is receivers whose `__init__` is unannotated, takes
a non-zero-valuable type, or rejects zero values at construction. Those are the cases the
key-gated rung exists for, and the cases a smarter deterministic rung could still take.

UNPROVEN reason distribution (the engine roadmap, as evidence):

| reason_code | count | example target | example detail |
|---|---|---|---|
| TARGET_UNREACHABLE | 112 | `benchmarks.specifiers.TimeSpecSuite._make_cold` | `TimeSpecSuite._make_cold` is an instance method — invoking it requires constructing `TimeSpecSuite( |
| HARNESS_SYNTHESIS_FAILED | 39 | `noxfile.tests` | could not introspect `noxfile.tests` — the module failed to import or the symbol does not exist in t |
| VALUE_UNSERIALIZABLE | 4 | `packaging.tags.platform_tags` | 0 of 1 inputs produced a comparable observation (1 unserializable) — e.g. base observation unreprese |
| NONDETERMINISTIC_BASE | 1 | `docs.conf.find_version` | base replay does not reproduce its own recording on input ('',) — determinism could not be reached ( |

**Re-measured 2026-08-16 evening after the engine-depth wave (ADR-0026 — static/class
methods pinned, typed-dataclass constructor synthesis, async execution): 42/198 = 21%,
UNCHANGED — and identically so, byte-for-byte (incidental re-proof of determinism).** Why,
verified against the bundles, not guessed: this corpus's 112 unreachable targets decompose
as 99 instance methods of PLAIN classes (the key-gated synthesis rung), 12 generators
(honestly out of scope), 1 closure — zero async / dataclass / static shapes among its
changed symbols. The new levers raise the capability CEILING (pyfix c04–c07 all prove
keyless: staticmethod, classmethod, typed dataclass via TYPE_SYNTHESIZED, async), but
THIS corpus's number moves only with a configured key (99 targets) and stage-2 env
reproduction (39 + humanize/slugify wholesale). Stated plainly instead of flattered.

**Re-measured 2026-08-16 night after stage-2 env reproduction (ADR-0027) — 21% → 34%,
the first real movement of the corpus number:**

| Repo | Base → Head | Tier | Targets | DIVERGENT | EQUIVALENT | UNPROVEN | ERROR | Proof rate |
|---|---|---|---|---|---|---|---|---|
| packaging | 26.2 `84a87ee42483` → 26.3 `929fd4b1410a` | T2 | 153 | 5 | 33 | 115 | 0 | 38/153 (25%) |
| semver | 3.0.0 `3a7680dc4362` → 3.0.4 `6adf8765f6e2` | T2 | 10 | 0 | 4 | 6 | 0 | 4/10 (40%) |
| humanize | 4.15.0 `2ddb5903cdc1` → 4.16.0 `3c577d765050` | T2 | 24 | 6 | 15 | 3 | 0 | 21/24 (88%) |
| more-itertools | v11.0.2 `247e15b3a489` → v11.1.0 `64be96ceb2a6` | T2 | 4 | 0 | 0 | 4 | 0 | 0/4 (0%) |
| python-slugify | v8.0.1 `58031becacdc` → v8.0.4 `f85f94885201` | T2 | 7 | 1 | 4 | 2 | 0 | 5/7 (71%) |
| **overall** |  |  | **198** | **12** | **56** | **130** | **0** | **68/198 (34%)** |

UNPROVEN reason distribution (the engine roadmap, as evidence):

| reason_code | count | example target | example detail |
|---|---|---|---|
| TARGET_UNREACHABLE | 112 | `benchmarks.specifiers.TimeSpecSuite._make_cold` | `TimeSpecSuite._make_cold` is an instance method — invoking it requires constructing `TimeSpecSuite( |
| HARNESS_SYNTHESIS_FAILED | 12 | `noxfile.tests` | could not introspect `noxfile.tests` — the module failed to import or the symbol does not exist in t |
| VALUE_UNSERIALIZABLE | 4 | `packaging.tags.platform_tags` | 0 of 1 inputs produced a comparable observation (1 unserializable) — e.g. base observation unreprese |
| NONDETERMINISTIC_BASE | 2 | `docs.conf.find_version` | base replay does not reproduce its own recording on input ('',) — determinism could not be reached ( |

humanize 0/24 → **21/24 (88%)** (the generated `_version.py` shim; 6 real divergences in a
real release pair) and python-slugify 0/7 → **5/7 (71%)** (setup.py AST metadata +
text-unidecode as a wheel + the T2 read-carve for the deps dir; 1 real divergence). The
residual 12 import failures are dev scripts (noxfile, docs conf) whose imports are not
`[project]` dependencies — out of scope, stated. The dominant remaining lever is unchanged
and key-gated: 112 plain-class instance methods (ADR-0024's rung, awaiting a configured
key). Measurement discipline note: the FIRST re-measure of this phase moved nothing —
because the fixes were hypotheses about humanize/slugify's failure modes that the bundles
then falsified (their real modes: a build-time-generated `_version.py`, a setup.py-only
repo, and a Seatbelt carve that denied the deps symlink target). Every fix landed only
after reproducing the exact import failure by hand. Verdicts over vibes, applied to
ourselves.

**Reading it honestly:** the 21% overall is the KEYLESS number on repos as-is (benchmarks,
noxfiles and docs scripts included — nothing was excluded to flatter the rate). The
distribution is the roadmap: the 112 instance-method targets are precisely what AI
constructor synthesis (ADR-0024) attacks once a user configures a key; the 39 import
failures are the stage-2 env-reproduction gap (the target package and its deps are not
installed in the sandbox); the 4 unserializable and 1 nondeterministic are comparison-layer
work. Per the master prompt: below ~60% real-world proof rate, ENGINE work outranks
feature work — these two levers are the engine work.

**Honest caveats, stated plainly:**
- 100% is measured on Tempest's own validation fixture — typed, importable, top-level functions.
  It is the engine's capability ceiling, not a real-world claim. Instance methods now reach
  verdicts through AI constructor synthesis (ADR-0024) **only when the user configures an
  Anthropic key**; keyless, they remain `UNPROVEN(TARGET_UNREACHABLE)` with remediation text
  naming the fix.
- On this machine, **user repos have a proof rate of 0% by design**: no Docker → every target is
  `UNPROVEN(SANDBOX_UNAVAILABLE)` (L6, ADR-0003). This is exactly the wall Phase 10's tiered
  sandboxing exists to remove; until T2 lands, the real-world proof rate on Docker-less machines
  is zero and no one should pretend otherwise.
- Changed TypeScript files are surfaced as `UNPROVEN(RECORD_REPLAY_UNAVAILABLE)` (never silently
  skipped, as of `2358b97`); the TS execution half (Phase 3) will move them into the numerator.
- The 60% bar in the master prompt applies to real-world code. The first real-world
  measurement (above, 2026-08-16) reads **21% keyless** — below the bar, so engine work
  (synthesis coverage of instance methods, stage-2 env reproduction) outranks feature work.
  The live-PR gate (`tempest-live.yml`) and the design-partner runs (Phase 18) keep this
  section current.

## 2. False divergence rate

**Measured: 0** — on the 12 seeded no-op refactors (parameter renames, comprehension↔loop,
formatting churn, equivalent expressions), zero `DIVERGENT` verdicts across every gate run,
re-verified on the run above (`false_divergences_on_noops=0`).

Structural defenses (not vibes): 3× fresh-process re-confirmation of every candidate divergence;
a base that disagrees with itself is `UNPROVEN(NONDETERMINISTIC_BASE)`, never a head bug; a
divergence that vanishes or drifts class on re-run is discarded as flaky; timing is never a
divergence signal.

## 3. Time-to-first-divergence

**Not yet instrumented** — the metric is defined as *install → first real divergence on the
user's own code* and belongs to the Phase 18 onboarding flow. It must not be conflated with raw
prove time. What is measurable today:

- Full pyfix run (24 targets, budget 40, incl. 31 minimized repro scripts): **105.3 s wall**.
- The Phase-7 measured slice: 5 pure targets at default budget 300: **3.9 s wall** (bar: <60 s).
- Desktop app cold start to healthy sidecar: **~2 s** (HANDOFF, live-verified).

Phase 18's gate instruments the real number end-to-end from a signed install.

**Measured 2026-08-17 (ADR-0032, the demo proof):** click → visible `DIVERGENT` in **6.4 s**
against a bar of 90 s, pinned by a timed E2E spec and an API test. The demo repo is real, not
staged — ordinary git repo, ordinary prove machinery, ordinary bundle (L4 extends to marketing).
This is the *bundled-demo* number; the **user's own code** number still awaits design-partner
installs, and the two must never be conflated.

---

## 4. Agent verdict coverage *(v2 number — not measurable yet)*

**Definition:** the percentage of agent-presented changes carrying a real verdict traceable to
a stored bundle. **Target: 100%. Anything less is L16 violated.**

**Status: no agent exists yet.** The Verdict Loop is Phase 21. Reporting any value today would
be a fabricated measurement (L1/L4).

**Will be measured by:** `python -m tempest.dev.agent_bench --tasks 50 --require-verdict-coverage 1.0`
plus the adversarial forge test that attempts to produce a "verified" label with no bundle.

## 5. Agent task success rate *(v2 number — not measurable yet)*

**Definition:** the percentage of agent tasks reaching intent-contract conformance without
human intervention.

**Status: not measurable** — depends on F1 (Phase 21) and F2 (intent contracts, Phase 21).

**Will be measured by:** the same 50-task `agent_bench`, cross-referenced with
`python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0` and
`python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats`.

## 6. Mutation score *(v2 number — not measurable yet)*

**Definition:** the median mutation score across `EQUIVALENT_UNDER_BUDGET` verdicts — i.e. of
faults deliberately injected into changed lines, the fraction the input search would have
caught. **This is the strength of the evidence**, and it is what makes an equivalence verdict
falsifiable rather than merely reassuring.

**Status: not measurable** — F9 (adversarial self-validation) is Phase 24. Note the honest
consequence: today's `EQUIVALENT_UNDER_BUDGET` verdicts state what was exercised (which is why
they are not "correct"), but they do **not** yet carry a measured sensitivity. Until F9 lands,
the report's own budget disclosure is the only evidence-strength signal, and it should be read
as such.

**Will be measured by:** `python -m tempest.dev.mutation_bench --report-scores`. Targets below a
configurable floor downgrade to the new `WEAK_EVIDENCE` verdict (an L2 vocabulary change
requiring its own ADR — see `docs/QUESTIONS.md`).

## Phase 11 performance envelope (measured 2026-08-14, this machine, `make bench`)

All five absolute targets pass with wide margin — `bench_guard: PASS (bench/bench.json, darwin)`:
cold launch (spawn → first stdio health) **0.297 s** (target <1.5 s) · first list page against
a 10,000-run store **1.06 ms** (<200 ms) · 5 MB observation detail **23.9 ms** (<400 ms) ·
idle **112.4 MB RSS** (<250 MB) / **0.0 % CPU** (<1 %). Guarded in CI (`bench` job, 4-core
ubuntu profile) with a 15 % regression bar per committed platform baseline. Soak (8-hour,
memory growth <10 %): **PASS — 937 proves in 480 min, 0 failures, growth −3.7 %** (memory
ended LOWER than baseline; `bench/soak.json`, 2026-08-14).

## Bundle determinism (supporting evidence for all three)

**Strengthened 2026-08-14:** determinism now extends to the zip CONTAINER itself — entry
timestamps pinned to the zip epoch and permissions to 0644, so a bundle's bytes are a pure
function of its content. Caught by Linux CI: delta sync hashes the container, and mtime leakage
made re-zipped identical content hash differently across a 2-second boundary (invisible on a
fast local machine). Pinned by `test_wire_bytes_are_wall_clock_independent`.


Two independent `tempest prove` runs of the same commit pair produce **byte-identical**
`targets.json` and all 31 repro scripts, and manifests identical except `created_at`
(timestamps are recorded, never compared). Nondeterminism in Tempest itself: **none observed**
(30/30 ×20 flake hunt, re-run fresh at `2358b97`).

---

## Derived metric (v2, platform) — cost per verified outcome

Not one of the six, but the number a VP of Engineering actually asks for, and one **no
competitor can compute**: dollars spent per *successfully proven* task, per model. It requires
both halves — P11's cost tracking and F21's proof-ranked outcomes — so it lands with Phase 27.

**Status: not measurable yet** (needs P11, Phase 19, and F21, Phase 27). Recorded here so it is
built as a first-class metric rather than reconstructed later from logs.

**Why it matters:** every competitor can report tokens spent. Only a system with a correctness
oracle can report tokens spent *per correct result* — which is the only form of the number that
supports a purchasing decision.
