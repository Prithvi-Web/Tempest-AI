# HANDOFF-NEXT — the fresh session's single entry point (rewritten 2026-08-20;
# **19, 19a, 20 and 21 COMPLETE — all four Phase 21 gates green, wired into `make verify`.
# §0 is the only thing to read before touching anything**)

## 0a. Tree state at hand-off (2026-08-20, second session)

* **The previous session's two commits were LOST from the branch and recovered from the working
  tree.** `git reflog` shows `72faec5` (Phase 19a + 21) and `dff9f5a` (its handoff note) landing
  at 10:33, and `HEAD` back at `62cc180` afterwards with every one of their changes sitting
  uncommitted. Nothing was lost — `git diff dff9f5a` shows no deletions, only this session's
  additions — but the handoff that said *"`72faec5` is committed and UNPUSHED. Working tree
  clean"* was describing a branch state that no longer existed. **Check `git status` before
  believing any sentence about what is committed**, including this one.
* **The owner pushes via GitHub Desktop (trap 13).** If a push seems to have "not happened", look
  at the reflog before re-doing work: this is what a reset looks like from the inside.
* **`main` moved once, mid-session, with no reflog entry to explain it** — from `62cc180` (where
  it sat when this session started) back to `dff9f5a`, while the working tree stayed exactly as it
  was. GitHub Desktop is open on this repository and is the likeliest author. The outcome was the
  one wanted, and every changed file was still one this session had authored (`git diff
  --name-only` checked), but **read `git rev-parse HEAD` before reasoning about what is committed
  rather than trusting a note like this one.** A branch can move underneath you here.

---

## 0. START HERE — Phase 21 is COMPLETE. The §0 defect is fixed and all four gates are green

**`python -m tempest.dev.repair_bench` exits 0.** The cheat it used to miscount is refused, and
`collateral-damage-repaired` — the false positive the reverted-symbol excuse exists to prevent —
is still green.

```
repair_bench: 22/28 genuine repairs succeeded (79%; required 60%)
repair_bench: 11/11 dishonest outcomes correctly refused (cheats miscounted as success: 0)
```

**What the fix was, and why that one** (ADR-0051). Option (1) from the three that were on the
table: **a repair is only a repair if the changed code still loads**, checked by executing the
import in the engine's sandbox. No static rule can separate `import math` from
`import no_such_module_xyz`; both parse. Option (3) would have re-broken
`collateral-damage-repaired`; option (2) would not have fixed F3 on its own, because the new
module-level target would be UNPROVEN, which carries no divergence, so `judge` would still have
seen a clean bundle.

The probe is **differential**, which it was not in its first version: a module that fails to
import at head is only evidence against the agent if it imported at the BASELINE. A repository
with an unfetched dependency or an already-broken file would otherwise have produced a cheat
accusation for something the agent never touched. That correction came from the review, not from
the author.

**The half of the problem the old §0 did not mention.** The RATE was red too — 4/7 = 57% against
a 60% bar — and with the 15-task corpus it could never have gone green, because three of the seven
rate rows were tasks designed to fail. 4/7 was the ceiling. The corpus is now **55 tasks**, which
`agent_bench --tasks 50` required anyway.

### The four Phase 21 gates, and where they run

```bash
cd "/Users/prithvivinay/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
./scripts/agent-gates.sh          # all four; also wired into `make verify` as `verify-agent`
```

`agent_bench --tasks 50` · `intent_bench` · `repair_bench` · `resume_test --kill-mid-proof
--sleep-mid-stream`. The first three share one corpus and run concurrently; `resume_test` runs
alone afterwards because both of its claims are about wall-clock.

### What P2 does now

`run_task` consumes `plan_resume`. A restarted process re-attaches to the SAME shadow worktree at
the SAME baseline, replays the recorded conversation instead of paying the model again, re-proves,
and REFUSES to silently redo a task that already finished. `resume_test` proves it by `SIGKILL`ing
a real child the moment the durable log says it entered the proof.

**That gate found a real defect on its first run** (ADR-0052): `envrepro.materialize` reused a
cached git worktree whenever the DIRECTORY existed, so a killed process poisoned the cache
permanently and every later run in that repository died on a file that was not there.

### Two things this phase deliberately left OPEN, and they are not hidden

1. **`run_command` is refused.** It used to call `subprocess.run(argv, cwd=shadow)` — the user's
   uid, environment, network and whole filesystem, with only the working directory set — while
   the tool manifest declared `writes: shadow_worktree` and `touches_network: false`. That is a
   Law violation (L19) and a false claim in a contract. It now refuses, naming the law and F14.
   **Phase 23's F14 (the sandboxed agent terminal, with the escape suite extended to cover it) is
   what re-enables it.** Do not re-enable it any other way.
2. **Nothing serialises two processes resuming the same task id.** They would attach the same
   shadow and interleave. One engine sidecar runs today so it cannot currently happen; the agent
   fleet (F17, Phase 26) is when it can, and that is when it must be closed.

---

## 0b. SETTLED (history) — the red `desktop` job on `070f046` did not reproduce

**Nothing to do here. Do not re-run it, do not pin the runner, do not re-read the old evidence
table.** This section is kept because the *reasoning* is reusable, not because the item is open.

`ci / desktop` failed on run `32315935235` (`070f046`) inside the first minute of its first cargo
command — `quote`, `proc-macro2` and `serde_core` build scripts exiting **126**, *"cannot execute
binary file"*: an architecture mismatch on the runner, not a compile error.

It was settled without the owner clicking anything, by an experiment **stronger than the re-run
that was planned**. `3860c23` (a documentation commit) was pushed on top of `070f046`, and CI ran
on it: **run `32317420375`, 7 of 7 green**, `desktop` included — step 10
`cargo clippy --workspace --all-targets -- -D warnings`, the exact step that had exited 101,
**passed**, as did `cargo test --workspace`, `typecheck` and the E2E leg.

The reason that is decisive, and checkable in one command each:

| Claim | Command | Result |
|---|---|---|
| `3860c23` touches only `docs/` | `git diff --name-only 070f046 3860c23` | `docs/DECISIONS.md`, `docs/HANDOFF-NEXT.md` |
| every non-`docs` tree object is **identical** | `git ls-tree <c> \| grep -v docs \| git hash-object --stdin` | `0b33d572…` on **both** commits |
| a **different** runner ran it | job `runner_name` | `1000000612` vs the failing `1000000607` |

Identical source bytes + a fresh runner + green = transient infrastructure fault. A re-run replays
a job inside the original run's context; a new push gets a new allocation and a new checkout, so
this answered the question the re-run was meant to answer, with a stronger control.

**No code change and no CI change was made.** `runs-on` is unpinned and `-D warnings` is untouched:
pinning a runner to work around a fault that happened once and did not recur on identical bytes
would trade a real cross-arch signal for the look of stability (v2 failure mode 2). The evidence
for pinning is a **second** occurrence.

**Recurrence signature — recognise it in one look:** a `macos-latest` job dying inside the first
minute of its first cargo command, `exit 126` + `cannot execute binary file`, from *dependency*
build scripts, before any Tempest code compiles. If that happens again it IS reproducible, and the
fix is to **pin the host** — `runs-on: macos-14` — and only that. **Not** `targets:` on
`dtolnay/rust-toolchain`: `targets:` installs cross-compilation stdlibs affecting
`target/<triple>/`, while a build script is always compiled for and run on the **host** triple and
lands in `target/debug/build/<crate>-<hash>/build-script-build` — the exact path in the failing
log, and `target/` here holds only `debug/`, `release/`, `tmp/`, no triple directory at all. An
earlier draft of this section offered `targets:` as an equal alternative; it would have looked
like diligence and changed nothing.

**Still open, and NOT settled by the above** — `actions/setup-node@v4`,
`actions/upload-artifact@v4` and `astral-sh/setup-uv@v6` target Node 20 and are *"being forced to
run on Node.js 24"*. The runner is absorbing a deprecation for us; when it stops, the affected
jobs go red for a reason unrelated to Tempest. **The scope, counted rather than estimated:
5 of the 7 jobs** — `desktop` (all three), `python` / `bench` / `contract-check` (two each),
`node` (one); `forbidden-verdict-grep` and `compose-validate` use only `actions/checkout@v5`
(already Node 24) and are unaffected. It is **10 `uses:` lines in `ci.yml` and 16 across all
workflows**, not three. Queued in §4, deliberately not fixed in the session that found it — a
workflow edit is only verifiable by a CI run, and that session must not leave an unverified
workflow behind. Recorded in ADR-0046's closing section.



**Read this FIRST, before any other doc.** It supersedes the "live state" sections of every
older handoff (they are history now). Then read, in order: `CLAUDE.md` (the Laws — now L1–**L26**
and the FOUR-boundary contract), `docs/QUESTIONS.md` **v2 section** (the owner's binding
decisions first, then the questions still open), `docs/PLAN-V2.md` (phases **19–32**, with the
Phase 19 step ledger),
`docs/FEATURES-V2.md` (the 21 proof-native features + gates), `docs/PLATFORM-V2.md` (the 14
foundations adopted from LibreChat **and the rejection table — read the rejections, they are
load-bearing**), `docs/CRAFT.md` + `docs/POLISH.md` (the craft bar, 150 items),
`THIRD_PARTY_LICENSES.md`, `docs/HANDOFF-PHASES.md` §2 (the DONE ledger — do not redo anything
there) and its traps, `docs/DECISIONS.md` (ADR-0001..**0044** — 0034–0044 are all v2).

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

## 1. Live state (2026-08-19 — **Phase 19 complete; Phase 20's steps all landed; three things
still open before Phase 20 can be CALLED complete — read §1a**)

- **Everything through `2a0a998` is pushed and CI-green** (all seven jobs): Phase 19 including
  the trap-44 fix (`191c91e`), and Phase 20.1 + 20.1b (`f1b3502`, `43fbb25`, `31a40cc`,
  `453075b`, `2a0a998`). Check reality rather than this sentence, which ages the moment anything
  lands: `git rev-parse --short HEAD origin/main` and `git log origin/main..HEAD`.
- **Phase 20 is COMPLETE (2026-08-19, ADR-0046).** 20.1 editor surface · 20.1b budgets armed ·
  20.2 LSP multiplexer + handshake + hover dispatch · 20.3a completion policy · 20.3b ghost text
  + offline source · 20.3c completion budget + input storm · 20.3d local model runner + fallback
  · 20.3e behavioural risk indicator · **20.4a–d the review's confirmed fixes** · **20.5 the
  hover tooltip that makes `lsp_hover` reachable** · **20.6 the runners' settings surface**.
  **All twelve Phase 20 commits are PUSHED, and the phase is CI-CONFIRMED.** Everything through
  `30f970a` was CI-green 7/7; `070f046` came back 6/7 with `desktop` red; and `3860c23` — whose
  non-`docs` tree object is the *same hash* as `070f046`'s — came back **7/7 green** on a fresh
  runner (run `32317420375`). §0 has the full reasoning; the item is closed, not deferred.
- **Test counts after the ADR-0047 bench-conditions work (2026-08-20)**: pytest **1329** at
  100.00% (`MAKE_EXIT=0`, "all live steps green") · Linux denominator **1323**, 6 deselected,
  100.00% (`LINUX_EXIT=0`) · cargo **115** in the workspace + **5** devtools (untouched — no
  `.rs` changed this session) · vitest **86** desktop + **27** ts-sidecar · Playwright
  **48 passed** · `parity --cli-vs-desktop` byte-identical · `ruff format --check` clean
  repo-wide (281 files) · `mypy --strict` clean on 130 files, both platform views.
  Phase 20 handed off at pytest **1273**; the delta is this session's tests.
  **`make perf-gate`: `PERF_GATE_EXIT=0` — green for the first time (ADR-0047).**
- **The §5 editor budgets were MET when last measured**: open file p50 15.4 ms (bar 40),
  keystroke p50 1.3 ms (bar 8), completion p50 4.1 ms (bar 120), all three p95s inside their
  bars. The input-storm test (900 keys at 15/s, zero drops, order-exact) passes. Those were
  Phase 20's stated exit gate.
  **The live count is now 3 of 13, not 6, and nothing regressed.** `bench/editor-metrics.json`
  predates HEAD, so the staleness guard discarded it exactly as designed and the three editor rows
  read NOT-YET-MEASURED — the honest state for "the surface exists and nobody re-ran the
  measurement". `make bench-editor` restores them, after which the count returns to 6 of 13. Do
  **not** read the drop as a regression, and do not quote "6 of 13" without re-running the
  measurement that earns it.
- **Phase 20.1 + 20.1b are DONE** (ADR-0045). CodeMirror 6 behind `pathguard` — one enforcement
  point the Phase 21 orchestrator reuses; the editor is reachable from a proved target; the §5
  editor budgets are ARMED, so `perf_suite` reports **5 of 13** measurable (open file p50
  15.6 ms, keystroke p50 1.3 ms, BOTH p95s enforced because the leg emits raw samples). Local
  `make verify`: `MAKE_EXIT=0`, **1260 passed / 100.00%**, 37 E2E specs.
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
  `CLAUDE.md` (L1–**L26** + the four-boundary contract), ADR-0034..**0044**.
- **The final local `make verify` on `5717c41` came back GREEN after the defect fixes:**
  `MAKE_EXIT=0` — **1243 passed, 100.00% coverage**, ruff clean, `mypy --strict` clean on 130
  source files (both platform views), escape suite fully contained, redaction 24/24,
  `license_check` zero missing notices, `provider_matrix` 16 providers with every request path
  exercised, vitest 20+27, cargo 25+5, E2E 29 passed, four-boundary contract drift-free.
- **CI on `5717c41` came back RED, and the local green did not travel** (ADR-0044, trap 44).
  One test failed on the fresh checkout — `test_perf_suite.py::TestCli::
  test_the_real_repo_bench_file_is_evaluated`, `AssertionError: the repo ships a committed
  bench.json` — while the *same run* reported 100.00% coverage and 1235 other tests passing.
  The repo does **not** ship `bench/bench.json`: it is gitignored machine-local measurement
  output, and the test passed on the author's Mac only because a generated copy sat in the tree.
  **Fixed** by pointing the test at `bench/baseline-darwin.json` (which the repo does ship) and
  asserting the path is *in the committed tree* (`git cat-file -e HEAD:<path>` — NOT
  `git ls-files`, which answers about the index). Exactly one instance of this defect; the
  gitignored artifacts other tests read are all produced by an explicit CI step.

## 2. WHERE WE ARE: **19, 19a, 20, 21 and 22 are COMPLETE.** Phase 23 is the next feature work.

### Phase 22 in one paragraph (ADR-0054)

Three indices in one SQLite file at `.tempest/index/index.sqlite3` — structural (`ast`, incremental
by content digest, call edges resolved only when unambiguous), lexical/vector (identifier tokens +
character trigrams, BM25 over an inverted index — a real vector space with a dependency-free
embedding, described as what it is), and **execution** (the observation store the master prompt
assumed existed and did not: behaviour classes with counts and two representatives each, built by
running the generator with no head revision, without touching `prove.py`). One query planner over
all three, routing mechanically rather than by asking a model (L17), and **every statement carries
the source spans and observation ids it came from or is not written**. F4's spec synthesis is the
same discipline as a type: `Claim` refuses to exist with an empty citation list.

```
retrieval_bench: 40/40 questions answered, cited and correct
retrieval_bench: 15/15 source-impossible questions grounded in execution
retrieval_bench: retrieval p50 0.1 ms, p95 0.2 ms (bar 400 ms)
```

**The latency figure is on a FOUR-FILE fixture and the gate says so itself.** §5's bar is a
500k-LOC repository. That measurement has not been taken and is not claimed.

**QV1 is ANSWERED (owner, 2026-08-20): ENGINE FIRST.** Phase 19a followed immediately and the
proof rate is **re-measured at 43%**, up from 34% (ADR-0048, METRICS.md). Still under the 60% bar,
so the standing rule still puts engine work ahead of feature work — the remaining
`TARGET_UNREACHABLE` bucket is 94 and is still the dominant one by an order of magnitude.

### Phase 21, piece by piece

| Piece | State |
|---|---|
| Tool dispatch (boundary D enforcement) | **DONE** — `agent/tools.py`; `run_command` REFUSES, see §0 |
| Structured tool calling, BOTH wires | **DONE** — `inference/client.py`, real loopback peers |
| **F1** turn loop → verdict, L16 by construction | **DONE** — `agent/orchestrator.py` |
| **F2** intent contracts + classification | **DONE** — `agent/contracts.py`, wired into the loop |
| **F3** proof-guided repair | **DONE** — the load probe closed the §0 defect (ADR-0051) |
| **P2** durable/resumable turns | **DONE** — `run_task` consumes `plan_resume`; ADR-0053 |
| `agent_bench --tasks 50` | **GREEN** — 55/55, each verdict checked against its stored bundle |
| `intent_bench` | **GREEN** — 54/54, zero false INTENDED, any mismatch now fails |
| `repair_bench` | **GREEN** — 22/28 (79%), 11/11 cheats refused, 0 miscounted |
| `resume_test --kill-mid-proof --sleep-mid-stream` | **GREEN** — 15/15 |

All four run inside `make verify` as `verify-agent` (`scripts/agent-gates.sh`).

**The owner's decisions (2026-08-18) are binding and recorded in `docs/QUESTIONS.md`:**
retag as `v0.2.0`; **fund phases 19–27**; build every master-prompt feature **one at a time**,
each landing flawless with a **mini release** and a plain-English report naming the step;
licence is **MIT** and copying LibreChat code is authorized with attribution.

**19.1 DONE** (`2a88d91`) — MIT `LICENSE` + the `license_check` gate + LibreChat credits
(ADR-0038 amendment). **19.2 DONE** (`37e9027`) — boundary D, the Agent Tool Protocol:
`src-tauri/src/agent_tools.rs` is the root, `make gen-contracts` emits four committed artifacts
via `export_agent_tools`, and the existing `verify-contract` diff already covers where they
land — so four boundaries share one gate.

**19.3 DONE** (`80ad33a`) — the shadow worktree, `tempest/agent/shadow.py`. It lives in the
**engine, not Rust** (ADR-0036 amendment records why). Baseline via `git stash create` so the
agent edits what the user actually sees without their tree being touched; a snapshot is a real
commit so `prove(baseline, shadow)` needs no engine change; acceptance is all-or-nothing with
journalled pre-images. 38 tests on real repos, 100% coverage, no pragmas.

**19.4 DONE** (`6301d66`) — the agent journal, `tempest/agent/journal.py` (ADR-0039).
Append-only JSONL + pre-images, durable across restart, `undo_last()` LIFO with out-of-order
undo refused by reason. `shadow.accept` was refactored to write through it, so there is **one
journal and one reversal path**. The Phase 19 gate *"undo restores any state"* is met by a
12-seed randomised property test.

**19.5 DONE** (`53a3efb`) — P1, the model layer at `tempest/inference/` (ADR-0040).
**16 providers via two wires** (Anthropic Messages + OpenAI Chat Completions, which every
OpenAI-compatible endpoint speaks), stdlib-only, no vendor SDK, **no per-provider branch
anywhere** — proven by a test that invents a provider absent from the registry file. Real
streaming cancellation. `provider_matrix --min-providers 12` is in `make verify`, runs
**offline**, and exercises all 16 request paths against real loopback peers.

Phase 20 closed on 2026-08-19 with ADR-0046: 20.1 editor surface · 20.1b budgets armed ·
20.2 LSP multiplexer · 20.3a–e F11 · **20.4a–d the review fixes** · **20.5 hover reachable** ·
**20.6 the runners' settings surface**. The phase's own exit gate (every §5 editor budget met
plus the input-storm test) was already met at hand-off; what was missing was the review, the way
in, and a way to configure it. All three are done. Read §1a for what is CARRIED.

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

**All seven steps landed** (they were pushed at `5717c41`; the trap-44 fix on top is newer —
confirm with `git log origin/main..HEAD`):

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

### 1b. The last local `make verify` was RED for an INFRASTRUCTURE reason — re-run it clean

`make verify` on `05eb5c9` ended `MAKE_EXIT=2`, and the reason is not a defect:

```
1262 passed, 3 warnings in 618.43s
FAIL Required test coverage of 100.0% not reached. Total coverage: 0.00%
Couldn't use data file '.../.coverage': no such table: tracer
```

**Zero tests failed.** The `.coverage` SQLite database was left 0 bytes, so the report could not
be generated and the gate failed at 0.00% — a corrupt measurement, not a measured failure. The
empty file was deleted at hand-off (it would have poisoned the next run too), so a fresh
`make verify` is all that is needed. Do NOT read that 0.00% as a coverage regression, and do not
"fix" anything on the strength of it: re-run first, then believe the number.

Watch for it recurring. If it does, the cause is worth finding rather than deleting — a coverage
database that empties itself mid-run is exactly the kind of thing that would eventually report a
FALSE 100% instead of a false 0%, and only one of those two is self-announcing.

### 1a. PHASE 20 IS COMPLETE — what closed it, and what is CARRIED (not missing)

The three things this section used to list as blocking are done. Read the carried items before
assuming anything about measurement.

**0. THE FIXES WERE REVIEWED TOO, and that found eighteen more defects** (`f577f7d`, `23f4e9f`).
The 20.4–20.6 commits were new code with fresh tests, 100% coverage and green gates — the exact
state 20.2/20.3 were in when eleven lenses found 37 defects in them. Six lenses over the fixes,
56 agents, **18 confirmed unanimously**. Four were REGRESSIONS the fixes introduced (`trim()`
deleting the indentation that IS a FIM answer; `model_spec` splitting an env var that names a
whole program; a `LIKE` whose case behaviour is a dialect property; a risk badge that went inert
as soon as a model was configured). One was a FLAKE that had already passed two full `make
verify` runs. And `#[tauri::command(async)]` on a synchronous fn turned out to move the stall to
a tokio worker rather than remove it — starving every other async command, including the Settings
screen that is the user's only way to clear a bad language-server command.

**Trap 48: the review of a fix is not optional because the fix was careful.**

**1. The Phase 20 review RAN** (ADR-0046). Eleven read-only lenses over 20.2/20.3, every finding
adversarially verified by two refute-by-default verifiers: **138 agents, 63 findings judged, 126
verdicts, 37 confirmed unanimously.** It found, among others, that language servers were orphaned
on every quit (`tao` exits via `process::exit`, so no `Drop` of managed state ever runs, and
`shutdown_all` had zero production callers); that `Running::kill` could block forever on a
`join()` whose EOF never came, holding the multiplexer's mutex on the Tauri command thread; that
a server-initiated JSON-RPC request bearing our id was returned as our answer; that a legal
`-32601` killed the server while bring-up probed with `workspace/symbol`; that `lsp_hover`'s
containment was three lexical checks under a comment claiming parity with `pathguard`; that
`local_completion` and `lsp_hover` ran on the MAIN THREAD; and that the behavioural risk
indicator could never fire, in two independent ways that both rendered as the honest answer.
All fixed. Two of them were settled by running a probe rather than by reading.

**2. `lsp_hover` IS REACHABLE** (`d72c66d`). A CodeMirror hover tooltip calls it; the decision of
which outcomes are ordinary is a separate 100%-covered module; contents render as text, never
markup. Five E2E specs, the first of which asserts only that the command is issued at all.

**3. BOTH RUNNERS HAVE A SETTINGS SURFACE** (`af58163`, `runners.rs`). Language servers and the
local model are configured in Settings, with the environment still winning and saying so, and
with whether the program can be FOUND stated rather than left to a silent failure.

#### CARRIED — true today, and none of it is a defect being hidden

- ~~**The cold-launch baseline needs one `make bench` on an idle machine.**~~ **CLOSED 2026-08-20
  — `make perf-gate` is GREEN** (`PERF_GATE_EXIT=0`, "every measurable budget met"). Measured
  `cold_launch_s = 0.3248` (three samples: 0.326 / 0.326 / 0.325) against the 0.2968 baseline =
  **+9.43%, inside the 10% bar**, and 0.475 s inside the 0.8 s absolute budget. Full record and
  caveats in **ADR-0047**.
  **It was NOT closed by getting an idle machine — the machine could not be made idle, and that is
  now a measured fact.** With TreeMap and Chrome closed, load decayed to a floor of 0.24–0.30/cpu
  and stopped: `WindowServer` ~41% and `Claude Helper` ~14% are the Claude desktop app drawing the
  session that is asking for the measurement. **On this Mac, with a session open, the 0.20 quiet
  bar is unreachable.** That floor is exactly why three sessions recorded the same hypothesis and
  none could test it, and it was invisible until `bench` started recording load.
  It closed because the **one-sided rule** makes an idle machine unnecessary for a PASS: 0.3248 s
  was taken at 0.256/cpu, over the bar, so it is an *upper bound*, and an upper bound of +9.43%
  against a 10% bar proves there is no regression a fortiori. Two things stay true and are not
  hidden: it passed by only **0.57 points**, and the baseline still records no conditions of its
  own, so this is still a comparison against a reference of unknown provenance — which the gate
  prints on every run and which stops being true the first time a baseline is taken with this
  instrumentation.
  **Never re-baseline under load** (v2 failure mode 2) — and note this did not need to.
- **`perf-gate` runs in NO CI job.** The Makefile used to claim it "belongs to the perf flow and
  the CI bench job"; `grep -rn "perf_suite\|perf-gate" .github/` is empty and the comment now
  says so. Arming it in CI needs a committed `bench/baseline-linux.json` (without one the
  regression bar prints PENDING and never binds) and a decision about cold_launch above.
- **The §5 editor numbers are a claim about ONE laptop.** They come from
  `bench/editor-metrics.json`, which is gitignored and written only by `make bench-editor`
  (tagged `@bench`, grep-inverted out of `test:e2e`). `perf_suite` now counts three states
  separately — MEASURED / armed-but-NOT-YET-MEASURED / NOT-YET-MEASURABLE — instead of calling
  every unmeasured row "not measurable", which was false for the three armed editor rows.
- **The E2E harness has no Rust host.** The open-file and completion spans therefore EXCLUDE
  `pathguard` and Tauri IPC and INCLUDE an HTTP hop to a node bridge. Confirmed by the review and
  stated in the spec; closing it needs a harness that drives a real bundled app.
- **Nothing GATES the CSP.** It ships (`b11d533`) and is correct for what the app does today, but
  the only build in which tauri enforces it is a bundled one CI never produces, and the E2E suite
  runs against a vite origin with no CSP header. A build-time assertion that the bundled
  `index.html` carries the policy is the cheap first step.
- **The orphan gate covers the SIDECAR only.** `tempest.dev.orphan_check` detects survivors with
  `pgrep -f tempest-server`, so it cannot see a leaked language server — which is exactly why
  the Phase 20 review's orphan finding went unnoticed by a gate that had been green for months.
  The language-server sweep is instead proved in Rust, by
  `killing_a_server_reaps_the_grandchildren_it_spawned` against a real shim subprocess, with
  `sweep_on_exit` as the production caller. Extending `orphan_check` to configure a fake server
  and drive one hover before the SIGKILL would close the gap properly; it is not built.
- **`update_editor_runners` chooses a binary this host later spawns.** Nothing routes model
  output into settings today and the CSP forbids injected script; that is the whole mitigation,
  and it is written down (ADR-0046) rather than assumed.

### FIRST TASK for the next session — the CI confirmation is DONE; measurement is what is left

1. ~~Confirm CI on the Phase 20 tip.~~ **DONE 2026-08-20 — §0.** Run `32317420375` on `3860c23`
   is **7/7 green**, on source bytes identical to `070f046`. Phase 20 is CI-confirmed. Do not
   re-run `make verify` to "check" this: a local green is evidence about one machine (trap 44),
   and the question was always about the repository.
   For when you *do* need the local gates, the commands and the trap-40 rule are in §7:
   ```bash
   TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify > /tmp/verify.log 2>&1; echo "MAKE_EXIT=$?" >> /tmp/verify.log
   grep -E "^MAKE_EXIT=" /tmp/verify.log      # read THIS line, never the task notification
   ```
   Reading CI needs no auth on this public repo, and no `gh` (it is not installed here). **Quote
   the URL** — `?` is a zsh glob character and `NOMATCH` is on, so the unquoted form dies with
   `zsh: no matches found` before curl ever starts (an earlier draft of this very block printed
   it unquoted, three lines above its own warning that this shell is zsh):
   ```bash
   curl -s 'https://api.github.com/repos/Prithvi-Web/Tempest-AI/actions/runs?per_page=10'
   ```
   `.../runs/<id>/jobs` gives per-job and per-STEP conclusions — which is how the failing step was
   identified without log access. Job *logs* are 403 without a token;
   `check-runs/<id>/annotations` is public and carries the failing line (trap 12).
   **Two things will bite you, both paid for on 2026-08-20 — see trap 49:**
   *(a)* pipe `curl` straight into the parser. **Never `echo "$json" | …`** — this shell is zsh,
   whose builtin `echo` expands `\n`, turning the escaped newline inside a JSON *string* into a
   real control character and producing a bogus `Invalid control character` at a position that
   drifts between polls. `printf '%s'` is the safe form.
   *(b)* unauthenticated GitHub API is **60 requests/hour by IP**. Two concurrent 20-second
   pollers exhaust it in ten minutes and then every call returns a 403 body that parses as JSON
   and contains none of the fields you asked for. Poll **once**, at 60 s or slower, and check
   `x-ratelimit-remaining` before believing a surprising answer.
2. **Read §1a's CARRIED list before measuring anything**, then take the cold-launch bench on an
   idle machine and start Phase 21 (answer QV1 first — §4.4).

### The one thing deliberately left RED — do not "fix" it by re-baselining

`make perf-gate` still fails, on cold launch alone (re-measured 2026-08-19 after Phase 20):
```
PERF-GATE cold_launch: 0.3309s regressed 11.5% over baseline 0.2968s (bar 10%)
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

0. ~~**Confirm CI is green on the Phase 20 tip.**~~ **DONE 2026-08-20** — run `32317420375` on
   `3860c23`, **7/7 green**, on a tree whose non-`docs` object hash is identical to `070f046`'s.
   Trap 44 is satisfied the way it demands: by a fresh-checkout run of the repository, not by a
   local green. See §0.
0a. **The Node 20 deprecation.** `actions/setup-node@v4`, `actions/upload-artifact@v4` and
   `astral-sh/setup-uv@v6` target Node 20 and are *"being forced to run on Node.js 24"*. Nothing
   is red today because the runner absorbs it; when it stops, the affected jobs go red for a
   reason that has nothing to do with this code. **Counted, not estimated** (an earlier draft of
   this bullet said "every job" and "three `uses:` lines"; both were false and a review caught
   them):
   ```bash
   awk '/^  [a-zA-Z0-9_-]+:$/{j=$1} /uses:/{print j, $NF}' .github/workflows/ci.yml
   grep -cE 'uses: (actions/setup-node@v4|actions/upload-artifact@v4|astral-sh/setup-uv@v6)' .github/workflows/ci.yml
   ```
   **5 of the 7 jobs** are affected — `desktop` uses all three, `python` / `bench` /
   `contract-check` two each, `node` one — and `forbidden-verdict-grep` and `compose-validate`
   use only `actions/checkout@v5`, which is already Node 24, so they cannot carry the warning and
   cannot go red from it. The bump is **10 `uses:` lines in `ci.yml`, 16 across all workflows**
   (`release.yml` holds the other 6). A session that changes three lines will believe it closed
   this and the next run will still warn.
   A workflow edit is **only verifiable by a CI run**, so it must be made by a session that can
   then watch the run it caused, and must not be bundled into a push whose other content it could
   mask. Do it as its own commit, first thing, and watch it.
1. **Settle the cold-launch perf signal** — `make bench` on an idle machine (NO Claude session
   running; that is why it is still open), then `make perf-gate`. Never re-baseline to make it
   green. Then consider arming `perf-gate` in CI, which needs a committed
   `bench/baseline-linux.json` first.
2. **Gate the CSP.** It ships and is correct for what the app does, and nothing executes under
   it: `grep -rni csp` over the app, the specs and the workflows returns zero hits, and tauri
   applies the policy only in a bundled build CI never produces. A build-time assertion that the
   bundled `index.html` carries it is the cheap first step; running one smoke spec against a
   built app is the real one.
2a. **Queued by the Phase 20.1 review (ADR-0045) — the first two are DONE; read the correction:**
   - ~~No CI job runs the E2E suite.~~ **DONE in `b11d533`**: the CI desktop job installs a
     chromium and runs the same `test:e2e` script `make verify` does, with `set -o pipefail`
     before the `tee` (trap 18). This bullet still said the opposite two commits after that
     landed, and the Phase 20 review confirmed it as a live documentation defect — the handoff
     that is the project's own answer to "is this done?" answered no about work that was done.
     Corrected 2026-08-19.
   - ~~`tauri.conf.json` ships `security.csp: null`.~~ **DONE in `b11d533`**: it ships a full
     policy (`default-src 'self'` … `frame-ancestors 'none'`). Same correction, same date.
     **What is still true and is NOT done:** nothing GATES the CSP. `grep -rni csp` over
     `packages/desktop/src`, `e2e`, `.github` and every test returns zero hits; the E2E suite runs
     against the vite dev server, which sends no CSP header, in Chromium — while the app ships on
     WKWebView, and tauri applies `security.csp` only for the `tauri://localhost` protocol, i.e.
     only in a bundled build that CI never produces. So the policy is a config file nobody has
     executed under. That is the real open item; see §4.
   - **The cold-launch baseline** needs one `make bench` on a genuinely quiet machine (every
     measurement on 19 Aug was taken with ~25–30% background load from a Claude session). The A/B
     settled the cause: the BASELINE COMMIT ITSELF benches at 0.3316 today — environment drift
     (+11.7%), not code (+4.3%, inside the bar). Do NOT re-baseline under load. **Still open on
     2026-08-19 after Phase 20: it could not be taken, because that session WAS the load.**
     `make perf-gate` reports `cold_launch 0.3309s regressed 11.5% over baseline 0.2968s`; the
     absolute budget is met with wide margin (0.33 s against a 0.8 s p50).
2b. **Queued by the trap-44 review (ADR-0044) — none of these are done:**
   - **A repo-wide gate for the trap-44 class.** Today only `test_perf_suite.py` proves the file
     it reads is committed; nothing stops the next test from using bare `Path.is_file()` on a repo
     path. A mechanical check (every non-`tmp_path` repo path a test reads must be in HEAD, or be
     produced by a named CI step) would gate the class instead of the instance.
   - **`test_prove_scope.py:41-52`** gates *which assertion runs* on gitignored
     `node_modules/ts-morph`: `DIVERGENT` when present, `UNPROVEN` when not. It never fails, it
     silently downgrades — the strong assertion can evaporate with nothing turning red.
   - **`tempest.dev.bench` emits only aggregates.** Emitting raw `samples` turns three p95 budgets
     from NOT-YET-MEASURED into enforced (also listed in §2).
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
44 a test that reads a repo file must assert the file is COMMITTED (in HEAD, not the index), not merely present — local green is measured in a tree full of untracked build output, CI in a fresh checkout (§12) ·
45 a guard's ARGUMENT is not a proof of the guard — write the bypass and RUN it; a hard link defeated a credential denylist whose own prose explained why it could not (§13) ·
**46 a REVIEW agent that reads the tree AFTER you have fixed it judges the FIX, not the defect —
verification and repair must not overlap on the same file (§14) ·
47 a GATE can measure the wrong thing and report green about something it never looked at; when a
corrected ruler goes red, the ruler was the bug (§15) ·
48 THE REVIEW OF A FIX IS NOT OPTIONAL BECAUSE THE FIX WAS CAREFUL — six lenses over the Phase 20
fix wave found 18 more defects, four of them regressions the fixes themselves introduced, in code
written by an author who had just read 37 findings about the same modules (§16) ·
49 A DIAGNOSIS YOU DID NOT RUN IS A GUESS, AND A GUESS IN A DOC IS A FALSE CLAIM — a plausible,
wrong cause was written into this handoff as fact and caught only by running the command it
recommended; the real cause was zsh's `echo` expanding `\n` inside JSON (§17) ·
50 A SOURCE FILE CREATED DURING A COVERAGE RUN IS MEASURED AT 0% AND ITS TESTS ARE NEVER
COLLECTED — the run then fails the 100% gate for a reason that is an artifact of the edit, not a
fact about the code (§18) ·
51 A NEW CHECK IN A DIFFERENTIAL PRODUCT MUST ASK "DID THIS CHANGE IT", NOT "IS THIS TRUE NOW" —
the load probe's first version reported every module that failed to import, which in any repo with
an unfetched dependency is a cheat accusation for a file the agent never touched (§19) ·
52 A CRASH WINDOW ONE LINE WIDE CAN CLOSE A RESOURCE PERMANENTLY — two in this wave, both between
creating something and recording that it exists, and both left a directory `create` would not
overwrite and `attach` would not adopt (§20) ·
53 A COMMITTED CONTRACT CAN CLAIM CONTAINMENT THE CODE DOES NOT PROVIDE — `run_command`'s manifest
declared `writes: shadow_worktree, touches_network: false` over a bare `subprocess.run`, and 51
passing tests all asserted that it WORKED (§21)** ·
39 a tag is a claim too** — `v1.0.0` shipping `0.2.0` artifacts got past a rehearsed release
workflow because the rehearsal proved the JOBS, never the NAME. Assert tag == version in the
release job itself.

## 6b. The Phase 21 gates — how to run them, and what each currently says

```bash
cd "/Users/prithvivinay/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.agent_bench   # EXIT 0
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.intent_bench  # EXIT 0
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.repair_bench  # EXIT 1 — §0
```

Each takes 1-3 minutes: every task is a real git repo, a real shadow worktree and a real
differential proof. The only fake is the MODEL — a loopback peer scripted to make a fixed
sequence of edits, including the misbehaving ones a real model cannot be asked to perform
reliably (L4: the fake is the model, never the execution).

The corpus is `tempest/dev/_agent_corpus.py`, 15 tasks. Its composition is a choice and is stated
in the module: repairable and deliberately-unrepairable tasks are both present, so the keyless
repair RATE is a property of those scripts rather than of any model. A real-model number is an
owner-run measurement (QV2) and a keyless run may never report one.

**`--tasks N` is a REQUIREMENT, not a target.** Asking for more tasks than the corpus holds exits
2 with the shortfall named, rather than quietly reporting a rate over a smaller set (trap 44).

## 7. Resume commands

```bash
cd "/Users/prithvivinay/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

git log origin/main..HEAD --oneline          # what is NOT yet pushed (do not assume empty)

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

---

## 12. Trap 44 — a test that reads a repo file must assert the file is COMMITTED

Phase 19 was handed off as complete on a green local `make verify` while CI on the same commit was
still running. CI came back **failure**. The single failing test asserted *"the repo ships a
committed bench.json"* — a false statement. `bench/bench.json` is gitignored: it is what
`make bench` writes on **your** machine. The repo ships `bench/baseline-darwin.json`.

The test was green locally for a reason that does not travel: a generated file happened to be in
the working tree. Coverage was **100.00% in the same run that failed**, because the defect was not
in a line of code — it was in a claim about the *repository*, which no coverage number ranges over.

**How to apply.**
1. Any test that reaches outside `tmp_path` into the repo asserts something about the repo.
   Prove it with `git cat-file -e HEAD:<repo-relative-path>` at the point of use —
   `Path.is_file()` answers a question about your laptop, not about the project.
   `test_perf_suite.py::_is_committed` is the ready-made helper.
   **Not `git ls-files`** — that reports the INDEX, so a `git add`ed-but-uncommitted file answers
   "tracked" while a fresh checkout still lacks it. That is this same trap one step later, and the
   first draft of the fix had it.
2. The real question is **not** "is it gitignored" but **"does a CI step produce it on a fresh
   checkout?"** `node_modules/` is gitignored too, and `pnpm install --frozen-lockfile` produces
   it; nothing produces `bench.json`.
3. Assert what the gate actually *did*, not that it ran. The first fix asserted
   `"of 13 §5 budgets" in out`, which reads identically when the gate evaluates **nothing** —
   `0 of 13` contains that substring. Assert the count.
4. To reproduce a "CI-only" failure of this class locally, move the untracked artifact aside and
   re-run — the fresh-checkout condition is usually one `mv` away, not a Docker image.
5. **A local `make verify` is evidence about this machine; "Phase N is complete" is a claim about
   the repository.** Do not write the second on the strength of the first. Wait for CI.

**How the fix was verified.** The old assertion was watched failing with `bench.json` moved aside
(byte-identical to CI's message); the new one was watched passing in that same state; the guard was
proved load-bearing by showing `bench.json` reports `exists_on_disk=True, committed=False`; and the
HEAD-based form was checked against a depth-1 shallow clone in detached HEAD, which is what
`actions/checkout` produces.

**Known remaining instances of the PATTERN (not defects today, but the shape to watch).**
- `test_prove_scope.py:41-52` gates *which assertion runs* on gitignored
  `node_modules/ts-morph` existing: `DIVERGENT` when present, `UNPROVEN` when not. It never fails,
  it silently downgrades. CI installs the dependency so the strong arm does run there.
- `test_license_check.py:138` and the corpus fixture loaders use bare `Path.is_file()` on repo
  paths. Those files are committed, so the tests are right today.
- **No repo-wide mechanical gate for this class exists.** The fix pins the instance and its own
  file; it does not stop a new test elsewhere from using bare `is_file()`. That gate is queued in
  §4, not built — do not read "the class is pinned" anywhere; it is not.

---

## 13. Trap 45 — a guard's ARGUMENT is not a proof of the guard

`pathguard` decides whether bytes may leave the disk. Its doc comment named the attack it
defeated — "a symlink named `notes.txt` pointing at `.env` passes every lexical check ever
written" — and explained that the denylist is therefore applied twice, to the requested path and
again to the resolved one. The prose was persuasive, correct as far as it went, and stopped the
reader (its author) from looking further.

A hard link is that attack with the target removed. It IS the file: two directory entries, one
inode, nothing to follow, and `canonicalize("notes.txt")` answers `"notes.txt"`, so both
applications of the denylist see an innocent name. A ten-line probe against the real function
printed

    LEAKED SECRET VIA HARDLINK: "SECRET=hunter2"

and a verifier reproduced it for all three denylist mechanisms (`.env` by segment, `.ssh/id_rsa`
by segment, `server.pem` by suffix) while the symlink control was correctly refused — proving the
defence covered symlinks only. Every line of the module had run. This is trap 43 in security
clothes.

**How to apply.**
1. **Write the bypass and run it.** For any rule that decides whether data escapes, a probe
   against the actual function is the cheapest real check there is. It found in one minute what
   careful reading had missed for hours. Build it in a throwaway dir; delete it after.
2. **When a rule cannot see a case, change the KIND of rule.** The fix was not a longer denylist:
   no name-based rule can ever see a hard link. It is a different question — a file with more
   than one name cannot be judged by the name it was requested under, so it is refused.
3. **Enumerate states for the MEDIUM, not the feature.** For a filesystem guard the standing list
   is: symlink · **hard link** · directory symlink · `.git` as a FILE (a worktree — Tempest's own
   agent shadows are worktrees) and as a directory · case-folded spellings on a case-insensitive
   filesystem · a file that grows between stat and read · a path resolving to a file other than
   the one it names.
4. A doc comment explaining why something is safe is a **claim**, and this project treats claims
   as deliverables (trap 39). Test it like one.


---

## 14. Trap 46 — a verifier that reads the tree after the fix judges the FIX, not the defect

The Phase 20 review ran 138 agents over ~75 minutes. Repairs on `lsp.rs` began before the
verification pass finished, and several verifiers then read the ALREADY-FIXED module and refuted
findings on that basis. One wrote, in good faith and in detail, that the finding "reviews a
superseded revision, not the shipped code" and attributed the fix to `05eb5c9` — a commit that
does not contain it, because the fix was uncommitted in the working tree at that moment.

The tell is in the tally: `Multiplexer::drop never runs at app exit` appears in the CONFIRMED
column (2/2 from one lens) *and* in the REFUTED column (from another lens whose verifiers ran
later). So do the pathguard-parity, `didChange`, whitespace and unbounded-servers findings —
every item that had been repaired in between.

**How to apply.**
1. **Do not edit a file while a verifier is still reading it.** Verification and repair are two
   phases, not one; overlapping them destroys the signal you paid for.
2. If they do overlap, the FINDER's verdict is the authoritative one — finders all ran against a
   pristine `origin/main`. Re-check any refutation against `git show HEAD:<file>` before
   accepting it.
3. A refutation that describes code you just wrote is evidence your fix is complete, which is
   worth having — but it is NOT evidence the defect was imaginary. Record both readings.

---

## 15. Trap 47 — a gate can be measuring the wrong thing entirely

Three of Phase 20's gates reported green about something they never looked at:

- **The contrast gate** scored every span against `getComputedStyle(host).backgroundColor`, no
  matter what surface the element actually sits on. The gutter and the risk badge live on
  `--surface-sunken` and were judged against `--surface`; a badge at a real **4.30:1** measured
  as a passing **5.07:1**. It also enumerated `.cm-line span` only, so F11's ghost text and risk
  badge did not exist when the probe ran.
- **The input storm** typed 900 keys "with inline completion live" and never pressed F11, the
  extension's only trigger, so `policyField` stayed idle for the whole run.
- **`perf_suite`'s summary** called MEASURED rows "measurable" and every other row
  NOT-YET-MEASURABLE, collapsing the two states the module exists to keep apart.

Each was fixed by correcting the RULER, and two of them then went red on real defects — ghost
text at 3.48:1, and a storm whose document tail read "…no recorded runs name this symbol"
because its own text extraction counted a widget as typed text.

**How to apply.** When a gate is green, ask what it would have to see to go red, and then check
that it can see it. A cheap version: break the thing on purpose and confirm the gate notices. If
correcting a gate makes it fail, the gate was the defect and the failure is the first honest
measurement you have had.


---

## 16. Trap 48 — the review of a fix is not optional because the fix was careful

The Phase 20 review found 37 confirmed defects in 20.2/20.3. The fix wave that answered it was
written deliberately, test-first, with 100% coverage and green gates — and was then reviewed the
same way, on the reasoning that this is *precisely* the state the reviewed code had been in.
Six lenses, 56 agents, **18 confirmed unanimously.**

What that second pass caught that the first could not:

1. **A fix that only appeared to work.** `#[tauri::command(async)]` on a synchronous fn spawns
   the future on tokio's multi-thread runtime and the sync body blocks a WORKER. The stall was
   moved off the main thread and onto the runtime, where it could starve every other async
   command — including the Settings screen, the only way to clear the bad command that caused it.
   The doc comment written with the fix argued only about the main thread and was persuasive.
2. **Regressions introduced BY the fixes** — four of them. A `trim()` that refused whitespace
   answers also deleted the leading indentation that IS a mid-token completion. A settings parser
   split an env var that had always named a whole program. A `LIKE` made a lookup answer
   differently on SQLite and Postgres. A symbol derivation correct for the offline source made
   the risk badge inert for anyone with a model configured.
3. **A flake that had already passed two full `make verify` runs** — env-var tests serialising
   their setters but not their readers, failing 2 runs in 6.
4. **Claims, again.** In a fix wave whose entire subject was untrue claims, three new untrue
   claims: a test that timed out during the handshake and never reached the write it names, an
   `assert 3 + 3 + 7 == 13` the interpreter folds before the test runs, and a doc describing a
   `default: never` arm the function deliberately does not have.

**How to apply.** Budget the review of a fix wave as part of the fix wave, not as an optional
extra if time allows. The author of a fix has just read a list of everything that was wrong with
the old code, which is the worst possible preparation for seeing what is wrong with the new. And
run it *before* declaring the phase done — every one of these was found after a green
`make verify` and would otherwise have shipped under a completion claim.


---

## 17. Trap 49 — a diagnosis you did not run is a guess, and a guess in a doc is a false claim

This trap was written twice and was wrong both times, which is the best evidence for it.

A CI-polling loop kept dying with `json.decoder.JSONDecodeError: Invalid control character at:
line 81 column 97 (char 4047)`, at a position that drifted between polls (4047, then 4050). The
cause written into this handoff, in the same commit that settled §0, was: *"commit messages carry
raw newlines and the strict decoder dies on them — parse with `json.load(f, strict=False)`."*

That sentence is plausible, it explains the symptom, it names a real Python flag, and **it is
wrong**. It was caught within the minute, by running the very command it recommended: the payload
parsed fine under `strict=True`, so the claim refuted itself.

**The actual cause is the shell.** The failing loop did `R=$(curl -s …)` then `echo "$R" | python3`.
A concurrent loop that piped `curl … | python3` directly never failed once, on the same endpoint,
at the same moment — the tell that the difference was in the plumbing, not the payload. **This
shell is zsh, and zsh's builtin `echo` expands backslash escapes by default** (bash's does not).
GitHub sends a commit message as the two characters `\` `n` inside a JSON string, which is valid;
zsh's `echo` turns them into one real newline, which is a control character inside a string
literal, which is not. Reproduced in three lines:

    $ printf '%s' '{"message":"docs: line one\n\nline two"}' > good.json
    $ python3 -c "import json; json.load(open('good.json'))"        # OK
    $ R=$(cat good.json); echo "$R" | python3 -c "import json,sys; json.load(sys.stdin)"
    JSONDecodeError: Invalid control character at: line 1 column 27 (char 26)
    $ printf '%s' "$R" | python3 -c "import json,sys; json.load(sys.stdin)"   # OK

**How to apply.**
1. **Run the diagnosis before you write it down.** This project treats a claim as a deliverable
   (trap 39) and a doc comment as a claim (trap 45). A *cause* is a claim too, and the cost of
   testing one is usually a single command. The near-miss here is the point: it happened in a
   session whose entire first task was settling a false-looking failure, written by an author who
   had just read traps 39, 44, 45 and 48.
2. **When two callers of the same thing disagree, the difference is the evidence.** One loop
   worked and one did not, against the same URL in the same minute. That fact alone excluded every
   payload-based explanation, and it was visible before any hypothesis was formed.
3. **`echo` is not portable and this machine is zsh.** Never `echo "$json"`. Pipe the producer
   straight into the consumer, or use `printf '%s'`. The same expansion silently mangles Windows
   paths, regexes and anything else carrying a backslash.
4. **A drifting error offset tells you nothing. Do not read it as a clue.** This bullet
   originally said the opposite — *"a drifting error position means the input is being rewritten,
   not that the input is corrupt"* — and **that was false, and was itself an un-run diagnosis
   written into the section whose entire subject is un-run diagnoses.** A review caught it; three
   lines disprove it. A genuinely corrupt payload that nothing rewrites drifts too, as soon as any
   preceding field changes length. **Run this — it is the whole refutation, and unlike the first
   draft of this block it is output someone actually produced:**

   ```bash
   python3 -c "
   import json
   for pad in ('', 'xxxxx', 'xxxxxxxxxx'):
       try: json.loads('{\"' + pad + 'k\":\"a\",\"m\":\"one' + chr(10) + 'TWO\"}')
       except json.JSONDecodeError as e: print(e)
   "
   Invalid control character at: line 1 column 18 (char 17)
   Invalid control character at: line 1 column 23 (char 22)
   Invalid control character at: line 1 column 28 (char 27)
   ```

   The `try/except` is load-bearing and its absence is the defect the review caught: the first
   draft of this bullet pasted the same three lines under a bare `json.loads` in a loop, which
   raises on the *first* iteration and can only ever print one error and a traceback. The
   arithmetic was right and the transcript was fiction — **an un-run snippet offered as the proof
   that an un-run diagnosis is wrong**, inside the trap about un-run diagnoses. Third time in one
   session. If this section ever prints output again, run it first.

   And a live Actions run list *guarantees* drift whatever the cause — durations tick, statuses go
   queued→in_progress→completed, the run count changes. So the offset moved for reasons that
   exclude nothing, and the rule built on it would have sent the next reader hunting upstream of a
   parser that was fine. **The thing that actually localised the bug was the difference between
   two callers (point 2), not the offset.**
5. Unrelated but paid for in the same ten minutes: the unauthenticated GitHub API allows **60
   requests/hour per IP**. Two concurrent 20-second pollers exhausted it, after which every call
   returned a 403 whose body is *valid JSON* carrying `message` and `documentation_url` and none
   of the fields being read — a rate limit that looks exactly like a schema change. Check
   `x-ratelimit-remaining` before believing a surprising answer.


---

## 18. Trap 50 — a source file created during a coverage run is measured at 0%

`make verify` came back `MAKE_EXIT=2` with **1466 passed** and *"Required test coverage of 100.0%
not reached. Total coverage: 99.01%"*. The named file was `agent/repair.py`, at **0%, lines
36-194** — a module whose tests were sitting right there and passing.

**They were written while the run was in flight.** pytest collects once, at startup; a test file
that appears afterwards is never collected. `coverage`, meanwhile, walks the *source tree* at
report time, finds the new module, and correctly reports that nothing executed it. So the run
fails for a reason that is entirely an artifact of the edit — the code is fine, the tests are
fine, and the number is real but meaningless.

The reasoning that produced it was: *"editing docs during a verify is safe, and a NEW file is
safe too, because nothing imports it yet."* The first half is true. The second is not, and the
difference is that coverage is a claim about the whole tree rather than about the files under
test.

**How to apply.**
1. **Do not create files in `packages/*/src` while a coverage run is going.** Docs are fine; new
   source is not. A new test file is merely useless (uncollected); a new *source* file actively
   fails the run.
2. When a coverage gate names a file at exactly **0%**, check its mtime against the run's start
   before reading it as a defect. 0% is the signature of "never imported", and "did not exist at
   collection time" is the cheapest explanation.
3. The general form is the one trap 46 already states about verifiers: **do not mutate the tree
   something is measuring.** That trap was about review agents; this is the same rule for the
   coverage gate, which is just a slower measurement of the same tree.
4. The fix is to re-run, not to add a pragma. There was never anything wrong with the module.


---

## 19. Trap 51 — a new check in a differential product must be differential

The load probe answers "does this module import?". Its first version reported every changed file
that failed, and `judge` called that a cheat.

In a repository with a dependency nobody fetched — or a file that was already broken when the user
opened the editor, or a package that needs an installed extra — that is an accusation about
something the agent never touched. The agent's change is innocent and the loop says it moved the
goalposts.

The fix is one the product already knew: **ask whether the change caused it.** A module that fails
at head is only evidence if it imported at the baseline. The probe now re-checks a failure against
the baseline tree and reports only what *stopped* loading.

**How to apply.** Every new check in this codebase inherits a question: absolute, or differential?
The answer is almost always differential, because the product's entire claim is about the delta.
An absolute check is right only when the property must hold unconditionally *and* the user could
not have been living with a violation of it already. Ask which one you are writing, and write the
answer in the docstring — the first version of this one did not, which is why nobody noticed.

---

## 20. Trap 52 — a crash window one line wide can close a resource forever

Two in one wave, and the same shape both times:

```python
shadow = create(repo, task_id)  # ← killed here
log.checkpoint(task_id, STARTED, ...)
```

```python
_git(repo, "worktree", "add", ..., path)  # ← or here
_write_meta(repo, slug, baseline=sha)
```

Afterwards the directory exists and the record does not. `attach` will not adopt a shadow whose
baseline was never written; `create` will not overwrite a directory that already exists. So the
task id is finished — not for this run, but for every run, until somebody deletes the directory by
hand. A user would experience it as "that task never works any more".

**How to apply.**
1. **After any "create the thing, then record the thing" pair, ask what the state between them
   looks like from a restart.** If the answer is "indistinguishable from a state we refuse", it is
   a wedge.
2. **Wreckage under your own directory is yours to reclaim.** A worktree under
   `.tempest/agent/worktrees/` with no metadata beside it was written by this code and interrupted;
   nothing else writes there, and the fact that was never recorded is exactly the fact that would
   have made it worth keeping.
3. The general form is idempotent creation: a function that can be called twice and leaves one
   resource is a function a crash cannot corner.

---

## 21. Trap 53 — a committed contract can claim containment the code does not provide

`agent-tools.json` — generated from Rust, committed, diffed by `verify-contract`, and shown to the
model — declared `run_command` as `writes: "shadow_worktree"`, `touches_network: false`. The
implementation was:

```python
subprocess.run(argv, cwd=self.root, capture_output=True, text=True, timeout=timeout)
```

The user's uid. The user's environment. The user's network. The user's whole filesystem. The only
thing the shadow constrained was the working directory. L19 says agent commands run at the same
isolation tier as differential runners; this ran at no tier at all.

**It had 100% coverage and 51 passing tests, and every test that touched it asserted that the
command WORKED** — that `echo hi` printed `hi`, that `ls` saw the shadow's files. A test suite can
be complete about behaviour and silent about capability.

**How to apply.**
1. **A generated contract is a claim, and a claim is a deliverable (trap 39).** When a manifest
   says a tool writes only X or touches no network, something must make that true. Grep for the
   fields — `writes`, `touches_network`, `destructive` — and ask, per tool, what enforces each one.
2. **Grant-gating is not containment.** `prompt_once_per_project` means the user approved the
   capability, not that the capability is bounded. Approval and isolation answer different
   questions.
3. **When the capability cannot yet be contained, refuse it and say why.** The tool stays in the
   manifest (boundary D requires the handler set and the tool set to match), the handler raises a
   refusal naming the law and the feature that will close it, and the tests assert the refusal.
   That is a smaller product and a true one.
