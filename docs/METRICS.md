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
| 30-function impure corpus (HTTP / fs / time-random) — record/replay stability, the proof-rate precondition for impure code | **30/30 stable ×20 consecutive replays** | `python -m tempest.dev.corpus_check --min-pass 24 --repeats 20` |

**Honest caveats, stated plainly:**
- 100% is measured on Tempest's own validation fixture — typed, importable, top-level functions.
  It is the engine's capability ceiling, not a real-world claim. The micro-repo CLI test shows the
  honest boundary: an instance method is `UNPROVEN(TARGET_UNREACHABLE)` today (no constructor
  synthesis yet).
- On this machine, **user repos have a proof rate of 0% by design**: no Docker → every target is
  `UNPROVEN(SANDBOX_UNAVAILABLE)` (L6, ADR-0003). This is exactly the wall Phase 10's tiered
  sandboxing exists to remove; until T2 lands, the real-world proof rate on Docker-less machines
  is zero and no one should pretend otherwise.
- Changed TypeScript files are surfaced as `UNPROVEN(RECORD_REPLAY_UNAVAILABLE)` (never silently
  skipped, as of `2358b97`); the TS execution half (Phase 3) will move them into the numerator.
- The 60% bar in the master prompt applies to real-world code. First real-world measurement
  arrives with the Phase 6 live-PR gate (after GitHub publish) and the design-partner runs
  (Phase 18); both must update this file.

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
memory growth <10 %): 2-minute validation run PASS at **−4.87 %** growth; the 8-hour result
lands in `bench/soak.json`.

## Bundle determinism (supporting evidence for all three)

Two independent `tempest prove` runs of the same commit pair produce **byte-identical**
`targets.json` and all 31 repro scripts, and manifests identical except `created_at`
(timestamps are recorded, never compared). Nondeterminism in Tempest itself: **none observed**
(30/30 ×20 flake hunt, re-run fresh at `2358b97`).
