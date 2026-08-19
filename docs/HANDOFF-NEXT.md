# HANDOFF-NEXT — the fresh session's single entry point (rewritten 2026-08-19, Phase 19 complete)

**Read this FIRST, before any other doc.** It supersedes the "live state" sections of every
older handoff (they are history now). Then read, in order: `CLAUDE.md` (the Laws — now L1–**L26**
and the FOUR-boundary contract), `docs/QUESTIONS.md` **v2 section** (the owner's binding
decisions first, then the questions still open), `docs/PLAN-V2.md` (phases **19–32**, with the
Phase 19 step ledger),
`docs/FEATURES-V2.md` (the 21 proof-native features + gates), `docs/PLATFORM-V2.md` (the 14
foundations adopted from LibreChat **and the rejection table — read the rejections, they are
load-bearing**), `docs/CRAFT.md` + `docs/POLISH.md` (the craft bar, 150 items),
`THIRD_PARTY_LICENSES.md`, `docs/HANDOFF-PHASES.md` §2 (the DONE ledger — do not redo anything
there) and its traps, `docs/DECISIONS.md` (ADR-0001..**0043** — 0034–0043 are all v2).

**The owner is a non-coder.** Plain English, copy-paste commands, verify by running the real app.

**Multi-agent workflows are ALLOWED, capped at TEN subagents** (owner, 18 Aug: *"you can start
using a multi agent workflow to optimize everything and make it completely flawless"*, then
*"don't use more than 10 subagents but make sure it is errorless"*). This reverses the 15 Aug
"no subagents" rule. **Use them to REVIEW, not to author**: write each feature single-threaded in
one coherent voice, then fan out to independent lenses (correctness, security/Laws, test quality)
whose findings are **adversarially verified before being reported or acted on**. That is not
ceremony — on Phase 19 it found five real defects in code with 100% coverage and a green
`make verify` (ADR-0043, trap 43). **Reviewers get read-only instructions explicitly** (trap 42).

**Build one feature at a time**, each landing flawless with its own gate output and a
plain-English check-in naming the step, so the work survives across sessions.

**The bar: 100% coverage, zero known defects, no red CI, ever. Never claim "done" without
pasting real gate output** — and never weaken a gate to make it pass (v2 failure mode 2).

---

## 1. Live state (2026-08-19 — **Phase 19 COMPLETE and pushed**; Phase 20 next)

- **Everything is pushed.** `origin/main == HEAD == 5717c41`. Fifteen commits landed this
  session (`72dd048`…`5717c41`).
- **v1 remains green.** The audit at the v2 kickoff: `make verify` exit 0, 1038 passed /
  100.00%; corpus 30/30 ×20; parity byte-identical; orphan 2.1 s; `bench_guard: PASS`. The suite
  has since grown to **1162+ tests, still 100.00%** on both denominators.
- **The release is correct.** Tag `v0.2.0` (the old mis-named `v1.0.0` is gone), shipping
  `tempest_engine-0.2.0` artifacts — tag, artifacts, `tempest version`, About and health pill all
  agree. Trap 39 recorded the lesson: a tag is a claim too.
- **Licence: MIT.** The repo previously had **no LICENSE file at all** (published = all rights
  reserved by default). Fixed in 19.1, with `license_check` in `make verify` so attribution is
  mechanical rather than remembered. Copying LibreChat code is authorised; Tempest credits it in
  the README and `THIRD_PARTY_LICENSES.md`.
- **v2 planning docs are complete**: `PLAN-V2.md` (phases 19–32), `FEATURES-V2.md` (F1–F21),
  `PLATFORM-V2.md` (P1–P14 **and the rejection table — read the rejections**), `CRAFT.md`,
  `POLISH.md` (150 items), `THREAT-MODEL-V2.md`, `METRICS.md` (six numbers),
  `CLAUDE.md` (L1–**L26** + the four-boundary contract), ADR-0034..**0043**.
- **Two verifications were still in flight at hand-off** and are the next session's first task:
  the final local `make verify` on `5717c41`, and CI on the same commit.

## 2. WHERE WE ARE: **Phase 19 is COMPLETE (19.1–19.7 + the review fixes). Phase 20 is next.**

**The owner's decisions (2026-08-18) are binding and recorded in `docs/QUESTIONS.md`:**
retag as `v0.2.0`; **fund phases 19–27**; build every master-prompt feature **one at a time**,
each landing flawless with a **mini release** and a plain-English report naming the step;
licence is **MIT** and copying LibreChat code is authorized with attribution.

**19.1 DONE** (`2a88d91`) — MIT `LICENSE` + the `license_check` gate + LibreChat credits
(ADR-0038 amendment). **19.2 DONE** (`37e9027`) — boundary D, the Agent Tool Protocol:
`src-tauri/src/agent_tools.rs` is the root, `make gen-contracts` emits four committed artifacts
via `export_agent_tools`, and the existing `verify-contract` diff already covers where they
land — so four boundaries share one gate. **Contract only; dispatch is Phase 21.**

**19.3 DONE** (`80ad33a`) — the shadow worktree, `tempest/agent/shadow.py`. It lives in the
**engine, not Rust** (ADR-0036 amendment records why). Baseline via `git stash create` so the
agent edits what the user actually sees without their tree being touched; a snapshot is a real
commit so `prove(baseline, shadow)` needs no engine change; acceptance is all-or-nothing with
journalled pre-images. 38 tests on real repos, 100% coverage, no pragmas.

**19.4 DONE** (`6301d66`) — the agent journal, `tempest/agent/journal.py` (ADR-0039).
Append-only JSONL + pre-images, durable across restart, `undo_last()` LIFO with out-of-order
undo refused by reason. `shadow.accept` was refactored to write through it, so there is **one
journal and one reversal path** (and shadow.py's last `pragma: no cover` is gone). The Phase 19
gate *"undo restores any state"* is met by a 12-seed randomised property test.

**19.5 DONE** (`53a3efb`) — P1, the model layer at `tempest/inference/` (ADR-0040).
**16 providers via two wires** (Anthropic Messages + OpenAI Chat Completions, which every
OpenAI-compatible endpoint speaks), stdlib-only, no vendor SDK, **no per-provider branch
anywhere** — proven by a test that invents a provider absent from the registry file. Real
streaming cancellation (the peer observes a broken pipe, so the connection genuinely dies).
`provider_matrix --min-providers 12` is in `make verify`, runs **offline**, and exercises all
16 request paths against real loopback peers.

**All seven steps landed and are PUSHED** (`origin/main == 5717c41`):

| Step | What | Commit |
|---|---|---|
| 19.1 | MIT `LICENSE` + `license_check` gate (the repo had **no licence at all**) | `2a88d91` |
| 19.2 | Boundary D — the Agent Tool Protocol, drift-gated | `37e9027` |
| 19.3 | Shadow worktree (L19) | `80ad33a` |
| 19.4 | Agent journal + one-keystroke undo (L20) | `6301d66` |
| 19.5 | P1 — 16 providers, two wires (`tempest/inference/`) | `53a3efb` |
| 19.6 | Cost meter — caps at the router (`inference/cost.py`) | `076c42d` |
| 19.7 | §5 budgets as a gate (`dev/perf_suite.py`, `make perf-gate`) | `6cc3acb` |
| fixes | **5 defects found by the review workflow**, all test-first | `5717c41` |

### FIRST TASK for the next session — verify, then choose

1. **Re-run the gates on a quiet machine** (the previous session's final `make verify` was still
   in flight at hand-off, and CI on `5717c41` was `in_progress`):
   ```bash
   TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify   # expect MAKE_EXIT=0
   make verify-linux-denominator
   ```
   **Read the logged exit line, never the task notification (trap 40).**
2. **Confirm CI is green on `5717c41`** — that run contains the five defect fixes and had not
   finished at hand-off.
3. **Settle the one deliberately-failing gate** (below), then start Phase 20.

### The one thing deliberately left RED — do not "fix" it by re-baselining

`make perf-gate` currently fails:
```
PERF-GATE cold_launch: 0.3375s regressed 13.7% over baseline 0.2968s (bar 10%)
```
The **absolute** budget is met with wide margin (0.34 s against a 0.8 s p50); what trips is §5's
10% regression bar. `bench/bench.json` was captured while the machine was busy running an audit,
so this is probably load, not drift — but that is a hypothesis, and the way to settle it is
`make bench` on an idle machine, then either the number returns (nothing was wrong) or it does
not (a real regression to chase). **Re-baselining to make it green is v2 failure mode 2** and is
forbidden.

### Phase 20 — the editor surface (the actual next feature work)

- CodeMirror 6 editor in the webview (**ADR-0034 already measured Monaco out**: CM6 with JS+Python
  is 545 KB minified / 181 KB gzipped vs Monaco's 4.43 MB / 1.09 MB — 8.1× and 6.2× smaller).
- **LSP multiplexer in Rust** — language servers never live in the webview.
- **F11** inline completion + next-edit prediction, local-model capable, with the behavioural
  risk indicator wired to measured divergence/proof-rate data.
- Exit gate: every §5 editor budget met (open file p50 40 ms, keystroke→render p50 8 ms,
  completion p50 120 ms / p95 300 ms) + the input-storm test (15 keys/s × 60 s, zero drops).
- **`perf_suite` already encodes those budgets** as `NOT-YET-MEASURABLE (Phase 20)`; Phase 20
  turns them on, which is the honest definition of its exit gate.

### Also queued, with names

- **19.5b** — migrate `harness/llm.py` + `report/narrative.py` onto `tempest/inference/`, dropping
  the `anthropic` SDK so there is ONE model path. Deliberately deferred: proven paths, and the
  frozen sidecar spec references the SDK.
- **Bench samples** — `tempest.dev.bench` already collects raw samples but stores only
  aggregates (and `min()` for cold launch). Emitting `samples` turns three p95 budgets from
  `NOT-YET-MEASURED` into enforced. Cheap, additive, high value.
- **Open questions** (`docs/QUESTIONS.md`): QV1 (34% proof rate vs the 60% engine-first rule —
  decide before Phase 21), QV2/QV10 (who funds live model gates), QV4 (`WEAK_EVIDENCE` as a fifth
  verdict or an attribute — recommend attribute), QV5 (**no Windows/Linux desktop exists** but
  Phase 31 gates 150 craft items on three OSes), QV6, QV7, QV11, QV12.

### The retag: what the owner does (I have no push credential — trap 13)

The local tag is already correct: **annotated `v0.2.0` on `6debcec`**, and local `v1.0.0` is
deleted. The remote still carries the wrong one, and deleting a published release needs the web
UI. In order:

1. **Delete the release**: github.com/Prithvi-Web/Tempest-AI → Releases → `v1.0.0` → Delete.
2. **Delete the remote tag**: on the same Releases page the tag survives deletion of the release
   — Tags → `v1.0.0` → Delete. (Or in GitHub Desktop: History → the tag → Delete Tag → Push.)
3. **Push the new tag**: GitHub Desktop → Push origin (tags ride along), or from a terminal
   where you are authenticated: `git push origin v0.2.0`.
4. `release.yml` fires on the new tag and rebuilds the same 0.2.0 artifacts under the right
   name. **Watch that run** — it is the first release run since the package-name fix.

**Trap 39 stands as the lesson:** a tag is a claim too. The rehearsal proved the *jobs* and
never the *name*. When `release.yml` is next touched, assert `tag == __version__` inside the
workflow so this cannot recur.

## 3. Frontend ↔ backend: what is guaranteed, and the ONE way to keep it

Unchanged from the previous handoff, plus a fourth boundary. The integration is protected by
generation + gates, not discipline. When you touch ANY shape:

1. **One source of truth:** Pydantic models in `packages/api/src/tempest_api/schemas/`
   (+ enums in `packages/engine/src/tempest/model.py`). Never hand-write a TS/Rust type.
   **v2 adds boundary D** (Agent Tool Protocol, ADR-0035), whose root is a Rust trait +
   `schemars` — because the orchestrator owns dispatch and capability enforcement, and the
   enforcement point and the schema must not be able to disagree.
2. **Regenerate + commit BEFORE `make verify`:** `make gen-contracts` (note: the v2 master
   prompt writes `gen:contracts`; the real target is `gen-contracts`). The drift gate diffs
   the committed tree, so uncommitted regen = red `verify-contract`.
3. **Adding an enum variant** must break Rust/TS until handled — that is the design working.
4. **A new DB-backed field is THREE places** (trap 34): `alembic/versions/000N.py` +
   `local_store._FORWARD_STEPS` (keyed by the PRIOR revision) + `REVISION_CHAIN`.
5. **Behavior, not just shapes:** the desktop E2E suite (30 specs, real vite UI × real stdio
   sidecar, console-clean gate) runs inside `make verify`.
6. **Every phase ends with the app chain** so the shipped app IS the verified code:
   `./packages/desktop/build-server.sh` → parity → `pnpm tauri build` → ditto to
   /Applications → `orphan_check`. Engine data files must be in `tempest-server.spec` datas —
   parity's pure-Python fixture CANNOT detect a missing JS asset (trap 32).

## 4. Remaining work, in recommended order

0. **Verify** (§2 first task): `make verify` + `make verify-linux-denominator` on a quiet
   machine, and confirm CI green on `5717c41`.
1. **Settle the cold-launch perf signal** — `make bench` on an idle machine, then `make
   perf-gate`. Never re-baseline to make it green.
2. **Phase 20** — the editor surface (CodeMirror 6 + Rust LSP multiplexer + F11). Details in §2.
3. **19.5b** — one model path: migrate `harness/llm.py` + `report/narrative.py` onto
   `tempest/inference/` and drop the `anthropic` SDK.
4. **Answer QV1 before Phase 21** — the standing rule says engine work outranks feature work
   below a 60% real-world proof rate, and the measured rate is **34%**. At 34%, F1's agent
   honestly reports UNPROVEN on ~2/3 of what it changes. The recommendation on file is a
   **Phase 19a engine proof-rate wave** (the 112 plain-class instance-method targets, key-gated,
   plus residual harness-synthesis failures) before the agent core.
5. **Carried from v1**: Sigstore signing + a README demo GIF; TS wave 2 (JS cassettes, methods,
   ddmin for JS, node in the T1 image, `.tsx`); owner-key real-model measurements.

## 5. The per-phase loop that produced 33 green ADRs (do not improvise a new one)

```
pick ONE phase → failing tests first (TDD; hermetic: fake Messages peer, local wheels,
  real git repos, REAL execution always — L4)
→ implement; ruff + mypy --strict as you go
→ uv run ruff format --check .          # REPO-WIDE (trap 28 — corpus/ too)
→ commit (regen contracts first if shapes changed)
→ make verify        # detached w/ monitor; ~15 min; expect the 100% gate to name arms —
                     # pin each named arm with a REAL test, amend, rerun
→ make verify-linux-denominator
→ ./packages/desktop/build-server.sh → parity --cli-vs-desktop → pnpm tauri build
  → rm -rf /Applications/Tempest.app && ditto ... → orphan_check
  (ALL direct gate invocations: TEMPEST_NO_POWER_PAUSE=1 — trap 17)
→ ADR + HANDOFF-PHASES row + METRICS if a number moved → memory
→ plain-English check-in WITH pasted gate output → owner pushes → confirm CI
```

Environment: uv+pnpm at `~/.local/bin`, cargo at `~/.cargo/bin`; Playwright pinned `~1.61.0`
(matching the cached browser — `playwright install` HANGS on this Mac); coverage iterating:
`--no-cov`; the authoritative coverage run must be exclusive.

## 6. Traps index (paid-for lessons — full text in HANDOFF-PHASES / memory)

13 owner pushes via GitHub Desktop only · 17 TEMPEST_NO_POWER_PAUSE=1 on direct gates ·
18 pipefail · 19 planted secrets letter-segmented · 22 ubuntu runners have live Docker
(runtime-arc divergence CI-only) · 23 conftest scrubs real ANTHROPIC_API_KEY ·
24 double-covered branches hide dead arms · 25 the L2 grep matches TEST SOURCE (assemble
"SA"+"FE") · 26 revisions predating a config can't self-describe · 27 the worker's settrace
window is invisible to coverage (use the sys.monitoring recorder) · 28 repo-wide format
before verify · 29 Seatbelt carve vs symlink targets · 30 reproduce the exact failure by hand
before coding the fix · 31 V8 precise-coverage repeat deltas are empty · 32 frozen .mjs are
spec datas; parity can't see them · 33 node needs the explicit strip-types flag + warning
suppression · 34 a DB field is three places · 35 V8 cannot run under RLIMIT_AS (heap cap
instead; macOS never enforces AS) · 36 the line right after a greenlet crossing is
mis-attributed by coverage — restructure into a sync helper, never pragma the block ·
37 a schema stamp is a claim, not a fact — every open verifies the live schema and repairs or
refuses loudly · 38 a stage can be green and dead (mining skipped its own `.tempest` worktree
root) — additive stages need one end-to-end bug only they can find ·
**40 a task notification's exit code is the WRAPPER's, not make's — read the logged exit line
(§8) · 41 a scratch-package rehearsal proves LOGIC, never a NAME collision (§9) · 42 a REVIEW
agent that mutates the shared tree races your commits — reviewers are read-only (§10) ·
43 100% coverage proves which LINES ran, not which STATES were considered (§11) ·
39 a tag is a claim too** — `v1.0.0` shipping `0.2.0` artifacts got past a rehearsed release
workflow because the rehearsal proved the JOBS, never the NAME. Assert tag == version in the
release job itself.

## 7. Resume commands

```bash
cd "/Users/prithvivinay/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

git log origin/main..HEAD --oneline          # expect empty (all pushed at 5717c41)

# Run detached with a GREPPABLE exit marker — a task notification reports the WRAPPER's
# status, not make's, so never trust it (trap 40).
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify > /tmp/verify.log 2>&1; echo "MAKE_EXIT=$?" >> /tmp/verify.log
grep -E "^MAKE_EXIT=" /tmp/verify.log        # 0 = green

make verify-linux-denominator                # the Linux coverage denominator (traps 15/21/22)
uv run python -m tempest.dev.parity --cli-vs-desktop
uv run python -m tempest.dev.orphan_check    # needs the app installed

# The Phase 19 gates, individually:
uv run python -m tempest.dev.license_check --third-party-notices
uv run python -m tempest.dev.provider_matrix --min-providers 12
make bench && make perf-gate                 # perf-gate is currently RED on cold launch (§2)
```

**Never edit a `.py` file while a coverage run is in flight** — an unimported new module counts
as 0% and the run reports a false total. Draft new modules in a scratch directory and move them
in afterwards (that technique is how 19.4–19.6 were built safely), but remember it cannot prove
a module NAME is free (trap 41).

---

## 8. Trap 40 — a task notification's exit code is the WRAPPER's, not the command's

Backgrounded gate runs here end with `; echo "EXIT CODE: $?" >> log`. The harness reports the
**wrapper's** status, which is the `echo`'s — always 0. On 2026-08-18 that made a `make verify`
run whose real exit was **2** arrive as "completed (exit code 0)".

**Always read the logged exit line, never the notification.** That time the failure was benign
(`verify-contract` diffs the COMMITTED tree and a licence edit was still uncommitted — the
documented "commit before verify" rule, §3.2). But a session that trusts the notification will
eventually paste a green claim over a red gate, which is the one thing this product exists not
to do. Prefer a distinctive marker (`MAKE_EXIT=$?`) so the real code is greppable.

---

## 9. Trap 41 — a scratch-package rehearsal cannot prove a NAME is free

19.5's model layer was first written as `tempest/model/`. `tempest/model.py` **already existed**
(the domain enums: `Verdict`, `ReasonCode`, `Stage`), so the new package silently *shadowed* it
and broke imports in 25 files. It had passed 33 tests in an isolated scratch package minutes
earlier — because that package had no `tempest/model.py`. `mypy --strict` found it in one run
inside the real tree; renamed to `tempest/inference/`.

**The rehearsal technique is still right** (drafting outside the repo is how these steps stay
safe during a coverage run) — but it proves *logic*, never *collisions*. Before adopting a new
top-level module name, check the tree it will live in: `ls packages/engine/src/tempest/`.

---

## 10. Trap 42 — a REVIEW agent that mutates the shared tree races your commits

The Phase-19 review workflow (4 lenses, ADR-0041 era) included a test-quality lens asked to
determine *"would this test still pass if the behaviour it names were broken?"*. The honest way
to answer that is mutation testing — so the agent **edited `agent/shadow.py` in the real working
tree**, moved the conflict check out of pre-validation, ran the tests, and restored the file.
Correct technique, correct result, and it left no trace.

But it ran **concurrently with the main agent committing 19.6**. For roughly a minute
`git status` showed a semantic change nobody had authored. Committing with `git add -A` in that
window would have silently shipped a mutation that contradicts ADR-0036 (validate the whole
changeset before a byte is written) — and the tests would still have passed, because the
journal's rollback masks it.

**Rules, learned the cheap way:**
1. **Review agents get read-only instructions, explicitly** — the verifier prompts said "do NOT
   edit any file"; the reviewer prompts did not, and that gap is the whole story.
2. A lens that genuinely needs to mutate code gets `isolation: 'worktree'` so it mutates its own
   copy.
3. **Never `git add -A`** while a workflow is running; stage the exact paths you authored
   (which is what saved this commit).
4. If `git status` shows a change you did not write, **stop and diff it** before anything else.

---

## 11. Trap 43 — 100% coverage proves which LINES ran, not which STATES were considered

The Phase-19 review workflow found five real defects in code that had 100% line **and** branch
coverage, no pragmas, and a green `make verify`. Every arm had been executed — just never in the
state that mattered:

| Defect | The state nobody set up |
|---|---|
| Untracked files poisoned the baseline | a repo with **one ordinary untracked file** |
| `list_shadows()` rebuilt the wrong baseline | a shadow **snapshotted, then reloaded** |
| Conflict compare wrong both ways | a file whose content **begins with whitespace** |
| API key leaked on redirect | a server that answers with **302** |

The most instructive one was a *test*: it set up the exact precondition for the worst bug and
then stopped one assertion short — it checked the file arrived, and never called the function
that would have failed.

**How to apply.** When a module's behaviour depends on external state — a git tree, a network
peer, the filesystem, the clock — write the state list down before the tests and cover it
deliberately. For git-backed code the standing list is: clean tree · uncommitted tracked edit ·
**untracked file** · gitignored file · file deleted by the user · **after a snapshot/restart** ·
content with leading/trailing whitespace · path with spaces · empty repo with no commits.
A green 100% gate is precisely the thing that makes you stop looking, so look before you see it.
