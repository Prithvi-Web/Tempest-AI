# Phase 8 — Truth Audit

**Date:** 2026-08-13 · **Audited commit:** `95ac24f` · **Machine:** Apple Silicon macOS
(Darwin 25.5.0), Python 3.12.13, Node 24, pnpm 11.21, uv 0.12.4, **no Docker** (ADR-0003).

**Verdict up front:** the v1 foundation holds — determinism 30/30 across 20 consecutive replays,
zero false divergences, byte-identical bundles across independent runs, zero contract drift, and
the full verify suite green from a clean clone. The audit also found **three real honesty defects**
(none previously visible in any green gate), which were fixed test-first during this audit and are
part of the audited commit. The proof-rate picture is honest but narrow: 100% on the validation
fixture, **unmeasured on real-world code**, and 0% by design on Docker-less machines until
Phase 10 lands. Details and raw output below.

---

## 1. Clean-clone `make sync && make verify` (§0.1)

Fresh `git clone` into an empty directory outside the working tree; nothing reused but the pnpm
content-addressable store. Raw output (package-install listing elided; every check line real):

```
=== CLEAN CLONE @ 95ac24fba350facb960fbafe8d95964414edd37f ===
uv sync --all-packages                       # 51 packages, incl. tempest-engine + tempest-api
pnpm install --frozen-lockfile               # 170 packages, lockfile up to date — Done in 1.9s
uv run ruff check                            → All checks passed!
uv run ruff format --check                   → 126 files already formatted
uv run mypy --strict packages/engine/src packages/api/src
                                             → Success: no issues found in 72 source files
TEMPEST_DEV=1 uv run pytest packages/engine packages/api -q --cov --cov-fail-under=85
                                             → 400 passed, 1 warning in 150.42s
                                             → Required test coverage of 85% reached. Total: 88.28%
                                             # the 1 warning is FastAPI's own internal
                                             # StarletteDeprecationWarning (third-party, not ours)
uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
                                             → 30/30 stable across 5 consecutive replays
pnpm -r typecheck                            → Done ×4 (shared-schema, ts-sidecar, web, desktop)
pnpm -r test                                 → ts-sidecar: 27 passed (27)
pnpm --filter @tempest/web build             → ✓ Compiled successfully; 4 routes; zero warnings
pnpm gen:api && git diff --exit-code packages/shared-schema packages/web/src/generated
                                             → zero drift (byte-identical regeneration)
grep -rn -w 'SAFE' packages/                 → empty (the forbidden verdict string is absent)
── verify: all live steps green ──
VERIFY_EXIT=0
```

*(The full unabridged log for this run is reproducible by re-running the command block above from
any clean clone of this commit.)*

**The gate earned its keep during the audit itself:** the first clean-clone run (at `cf6e775`)
failed with a genuine `E501` on a line edited *after* the working-tree verify had already checked
that file — a race a working-tree run can never catch. Fixed in `95ac24f`; the re-run above is
green from scratch.

## 2. Determinism corpus, gate settings (§0.2)

```
$ uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
tempest corpus check: 30 impure functions x 5 replays
  STABLE   × 30 (10 HTTP-via-loopback, 10 filesystem, 10 time/random)
30/30 stable across 5 consecutive replays        # bar: ≥24 — exit 0
```

## 3. Full corpus ×20 + run-bundle diffs (§0.3)

Fresh 20-repeat flake hunt at the audited code state (full line-per-function log committed as
`docs/flake-hunt-20x.log`):

```
$ uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 20
tempest corpus check: 30 impure functions x 20 replays
30/30 stable across 20 consecutive replays
FLAKE_HUNT_EXIT=0
```

Bundle-level determinism, measured directly: two independent `tempest prove` runs over the same
commit pair (pyfix fixture, seed 0, budget 40):

```
EXIT_A=1 EXIT_B=1                                  # exit 1 = DIVERGENT, correct both times
bundle_diff: targets.json identical=True
             repros identical=True (31 scripts)
             manifest-(created_at) identical=True   # timestamps recorded, never compared
```

**Nondeterminism found in Tempest itself: none.**

## 4. Mechanical Law audits (§0.4)

| Check | Result |
|---|---|
| `grep -rn -w 'SAFE' packages/` | **empty** — also a standing CI/`make verify` step |
| Every divergence row has minimized input + repro | **Enforced in the DDL**, not policy: `divergences.minimized_args/minimized_kwargs/repro_filename/repro_script` are `NOT NULL` columns (`db/models.py:134-140`), proven by below-the-application inserts expecting `IntegrityError` (`test_ingest_constraints.py`) — plus the bundle writer refuses to write a divergence without evidence (`_check_integrity`) |
| Distinct `UNPROVEN` reason codes emitted (bar ≥5) | **8 of 8 enum variants have real emission sites with tests** — *after this audit's fixes*. Before them: 5 of 8; `VALUE_UNSERIALIZABLE`, `ENV_REPRODUCTION_FAILED`, `RECORD_REPLAY_UNAVAILABLE` were declared but unreachable (see §6, defects D1–D3) |
| `# type: ignore` / `as any` without justification | `as any`: **zero** in all TS packages. `type: ignore`: 21 occurrences, every one carries a specific error code plus an inline justification (trailing, or the line directly above where the line is at the 100-char width limit) |
| LLM response written into any verdict field | **Zero LLM code paths exist in the engine at all** — `grep -ri 'anthropic\|llm' packages/engine/src/` is empty. Verdicts are computed exclusively by the differential runner (`execute/dual.py`, `compare/compare.py`). The BYOK adapter-synthesis path (ADR-0006) is deliberately unwired until a key-bearing environment exists |

## 5. Proof rate, measured honestly (§0.5) — full numbers in `docs/METRICS.md`

- **pyfix fixture (24 changed symbols: 12 seeded bugs + 12 no-op refactors): 24/24 proven = 100%**
  — 12 `DIVERGENT` (all real, minimized, repro-scripted) + 12 `EQUIVALENT_UNDER_BUDGET`;
  **0 false divergences**; 105.3 s wall for the full run at gate budget.
- **What 100% does and does not mean:** it is the capability ceiling on typed, importable,
  top-level functions (pure + impure-recordable). Real-world code adds instance methods
  (`UNPROVEN(TARGET_UNREACHABLE)` today — no constructor synthesis), TS execution (Phase 3
  open), deeper HTTP stacks (`requests`/`httpx` → honest `UNINTERCEPTABLE_EFFECT`, ADR-0010).
- **On this machine, user repos have 0% proof rate by design** — no Docker means every user-repo
  target is `UNPROVEN(SANDBOX_UNAVAILABLE)` (L6/ADR-0003). This is the strongest argument in the
  entire Phase 8+ prompt for Phase 10's tiered sandboxing: on the machines Tempest will be sold
  for, sandbox availability *is* the proof rate.
- **Real-world proof rate is therefore UNMEASURED.** The §0.5 60% question cannot be answered
  truthfully from fixtures. It gets its first real data from the Phase 6 live-PR gate (blocked on
  the owner's GitHub publish) and the Phase 18 design-partner runs; `docs/METRICS.md` is the
  standing ledger and must be updated by both.

## 6. Defects found by this audit (all fixed test-first, in the audited commit)

**D1 — `EQUIVALENT_UNDER_BUDGET` over zero comparable inputs (L2 violation).** A target where
*every* input's comparison was `Unprovable` (unserializable return value, un-interceptable
surface, unstable replay, unconfirmable flake) was blessed `EQUIVALENT_UNDER_BUDGET` with
`equivalent_inputs=0` — in both the pure and impure prove loops. Nothing had been proven about
it. Fixed: a kind-aware `Unprovable` tally; zero-comparable targets now derive
`UNPROVEN` with the dominant reason (`VALUE_UNSERIALIZABLE` / `UNINTERCEPTABLE_EFFECT` /
`NONDETERMINISTIC_BASE`) and an exact "0 of N inputs produced a comparable observation"
detail. The impure stability-verify also no longer mislabels unserializable values as
`NONDETERMINISTIC_BASE`. Locked by three failing-first tests (`TestUnexercisedHonesty`).

**D2 — unknown ref crashed the CLI with a raw traceback.** `tempest prove --base nope` raised
`EnvReproError` straight through typer — neither the L2 vocabulary nor actionable. Fixed: the CLI
renders `UNPROVEN — ENV_REPRODUCTION_FAILED: git … failed: unknown revision 'nope'` and exits 2
(the config-error convention). The API path was already honest (it pre-validates refs →
`REF_NOT_FOUND` envelope). Locked by `TestCliEnvReproduction`.

**D3 — changed `.ts`/`.tsx` files vanished from runs (silent scope narrowing, §14.1 — "the
single worst failure mode").** The diff pathspec was `*.py`-only, so a mixed .py/.ts PR reported
only its Python half — the TS change was invisibly blessed by omission. Fixed: TS file changes now
produce per-file `UNPROVEN(RECORD_REPLAY_UNAVAILABLE)` records stating that TS execution lands
with Phase 3 and that the change is **not** being blessed. Locked by `test_prove_scope.py`.

Also fixed during the audit's error sweep: the web build's inferred-workspace-root warning
(pinned `outputFileTracingRoot`), and per-line justifications added to the remaining bare
`type: ignore`s.

## 7. Desktop shell reality check (vs the Phase 8+ contract)

What exists at `apps/desktop` (shipped before this audit): a working Tauri v2 shell, frozen
PyInstaller engine sidecar (23 MB, ~2 s to healthy), five views on the shared generated client,
in-app prove runs live-verified, kill-on-exit watchdog. Verified during this audit:
`cargo clippy --all-targets -- -D warnings` → clean; `cargo test` → 0 tests (none exist);
`tsc --noEmit` → clean (in `pnpm -r typecheck`).

Gaps against §3/§4 of the desktop prompt — **named, not hidden** (they are the Phase 9 checklist
in `docs/PLAN-DESKTOP.md`): HTTP-on-127.0.0.1 instead of stdio JSON-RPC (opens a localhost port);
no generated tri-boundary types (`typify`/`tauri-specta`); no crash-restart supervision; no
process-group ownership (SIGKILL orphan test); zero Rust tests; Next.js web package still present
(deletion is a Phase 9 gate item).

## 8. Ambiguities & contradictions the audit surfaced (§9 item 6)

1. **The Phase 8+ prompt assumes no desktop exists** ("Build `packages/desktop`…"). One already
   exists at `apps/desktop` and already made the prompt's own architectural choice (Tauri v2).
   Phase 9 is written as *evolve-in-place* (ADR-0011); confirm this reading.
2. **Deleting Next.js (Phase 9) vs v1's open web items** (SSE timeline, Playwright E2E,
   repo-settings view). ADR-0012 records that the desktop SPA supersedes them and the E2E
   obligation transfers to `pnpm --filter desktop test:e2e`. Confirm — otherwise the v1
   definition-of-done still requires web E2E that Phase 9 would delete.
3. **`docs/METRICS.md`'s §0.5 question cannot be answered yet:** real-world proof rate needs the
   live-PR gate (blocked on the owner's GitHub Desktop publish — ADR-0005) and design partners.
   The audit refuses to substitute fixture numbers for it.
4. **This machine cannot run several Phase 10/12 gate legs** (no Docker; single OS): the
   cross-OS escape matrix, egress namespace test, and clean-VM installs must run in CI or VMs —
   recorded per-phase in `PLAN-DESKTOP.md`, never silently skipped.
5. **Owner-only purchases** gate later phases and are marked [ASK ME] in `PLAN-DESKTOP.md`:
   Apple Developer ID + Windows EV certificate (Phase 12), Okta/Entra dev tenants (Phase 14),
   compliance platform + pen test (Phase 16).
6. **§0.4's "test DB" phrasing** is satisfied one level stronger than asked: evidence-completeness
   is a schema constraint (NOT NULL + writer refusal), so a violating row cannot exist to be
   sampled.

## 9. Recommendation

Proceed to Phase 9 **after the owner reviews this audit** (the prompt's own stop condition), with
two standing priorities carried forward: (a) Phase 10 tiered sandboxing is the existential phase —
on Docker-less machines it *is* the proof rate; (b) wire real-world proof-rate measurement into
the first live gates so `docs/METRICS.md` §1 stops saying "unmeasured" at the earliest possible
moment. The engine foundation is sound to build on: the risk is not the moat, it is the shell
around it.
