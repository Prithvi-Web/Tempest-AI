# Tempest AI — The Three Numbers

> Phase 8+ master prompt §8: report all three in every status update. They are the company.
> Every figure below is a real measurement with its command; nothing is estimated.
> Last measured: 2026-08-13, commit `2358b97`, Apple Silicon macOS, Python 3.12.13.

## 1. Proof rate

**Definition:** of the changed symbols in a run, the fraction that reached a real verdict
(`DIVERGENT` or `EQUIVALENT_UNDER_BUDGET`) instead of `UNPROVEN`.

| Corpus | Measured | Command |
|---|---|---|
| pyfix fixture (12 seeded behavior changes + 12 no-op refactors; pure + impure-recordable) | **24/24 targets proven = 100%** | `TEMPEST_DEV=1 tempest prove --base base --head head --repo <pyfix> --max-inputs 40 --seed 0` |
| pyfix instance-method fixtures (c01–c03; AI constructor synthesis, ADR-0024) | **0/3 keyless (honest UNPROVEN + remediation) → 3/3 exercised with a key** — seeded changes DIVERGENT, no-op clean, offline cache rerun identical. Machinery-measured against a local Messages-API peer; the real-model number awaits an owner key (2.2) | `pytest packages/engine/tests/integration/test_llm_synthesis_pyfix.py` |
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

UNPROVEN reason distribution (the engine roadmap, as evidence):

| reason_code | count | example target | example detail |
|---|---|---|---|
| TARGET_UNREACHABLE | 112 | `benchmarks.specifiers.TimeSpecSuite._make_cold` | `TimeSpecSuite._make_cold` is an instance method — invoking it requires constructing `TimeSpecSuite( |
| HARNESS_SYNTHESIS_FAILED | 39 | `noxfile.tests` | could not introspect `noxfile.tests` — the module failed to import or the symbol does not exist in t |
| VALUE_UNSERIALIZABLE | 4 | `packaging.tags.platform_tags` | 0 of 1 inputs produced a comparable observation (1 unserializable) — e.g. base observation unreprese |
| NONDETERMINISTIC_BASE | 1 | `docs.conf.find_version` | base replay does not reproduce its own recording on input ('',) — determinism could not be reached ( |

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
