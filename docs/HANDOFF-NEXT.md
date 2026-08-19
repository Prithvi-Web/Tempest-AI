# HANDOFF-NEXT — the fresh session's single entry point (rewritten 2026-08-18, v2 kickoff)

**Read this FIRST, before any other doc.** It supersedes the "live state" sections of every
older handoff (they are history now). Then read, in order: `CLAUDE.md` (the Laws — now L1–L24
and the FOUR-boundary contract), `docs/QUESTIONS.md` **v2 section** (seven open questions the
owner must answer before Phase 19 starts), `docs/PLAN-V2.md` (phases 19–30),
`docs/FEATURES-V2.md` (the 21 features + gates), `docs/HANDOFF-PHASES.md` §2 (the DONE ledger —
do not redo anything there) and its traps, `docs/DECISIONS.md` (ADR-0001..0037).

**The owner is a non-coder.** Plain English, copy-paste commands, verify by running the real
app. **Subagents are FORBIDDEN** (owner, 15 Aug: "just build with one but go all out") —
single agent, maximum depth. **Stop after every phase** for review; rebuild and reinstall the
app to /Applications each phase. **The bar: 100% coverage, zero known defects, no red CI,
ever. Never claim "done" without pasting real gate output.**

---

## 1. Live state (2026-08-18, v1 audited green, v2 planned but NOT started)

- **v1 is green and released.** The full audit was re-run on `6debcec` at the v2 kickoff:
  `make verify` exit 0 — **1038 passed, 100.00% coverage** (5905 statements / 1678 branches,
  zero misses), 30/30 determinism corpus, escape suite fully contained, 24/24 planted secrets
  contained, four-boundary contract drift-free, 29 E2E passed (1 skipped = the opt-in
  `SCREENSHOTS=1` doc generator, not a behavior test). Raw output: the v2-kickoff check-in.
- **Everything is pushed.** `git log origin/main..HEAD` is empty. CI green on `main`.
- **The release shipped**, and it carries **one real defect: the tag is `v1.0.0` while every
  internal version string says `0.2.0`** — see §2, the first task.
- **v2 planning docs are written and committed** (this session): `PLAN-V2.md`,
  `FEATURES-V2.md`, `THREAT-MODEL-V2.md`, `POLISH.md`, `METRICS.md` (now six numbers),
  `CLAUDE.md` (L15–L24 + boundary D), ADR-0034..0037, and the seven open v2 questions.
- **No v2 code exists.** Phase 19 has not begun and **must not begin** until the owner has
  seen the audit and answered `docs/QUESTIONS.md` QV1–QV7 (master prompt §13: *"then stop
  and wait"*).

## 2. FIRST TASK: the v1.0.0 / 0.2.0 version mismatch

The published release is tagged **`v1.0.0`** ("v1.0.0 — versions unified") but ships
`tempest_engine-**0.2.0**-py3-none-any.whl`, and a user who installs it gets a binary whose
`tempest version` prints `0.2.0`. That is precisely the disagreement the ADR-0021 amendment
existed to eliminate ("the release tag, `tempest version`, the app's About, and the health
pill all now agree"). It is also a positioning claim: `v1.0.0` reads as GA, and GA is Phase 30.

**Do not "fix" this by editing anything until the owner chooses**, because the two repairs
are opposite:
- **(a) The tag was a slip** → delete the `v1.0.0` tag and release, re-tag `v0.2.0`. Cleanest
  truth, but rewrites a public release (fine — it has no known downloads yet).
- **(b) The owner meant 1.0** → bump every internal version string to `1.0.0`, regenerate the
  openapi contract (it embeds the version), rehearse every release job locally again
  (ADR-0021 amendment discipline), and re-cut the release.

Either way the gate is the same: tag, `tempest version`, About, and the health pill agree.

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

0. **The version mismatch** (§2) — owner decision, then execute.
1. **Answer QV1–QV7** (`docs/QUESTIONS.md` v2 section). QV1 is the load-bearing one: the
   standing rule says engine work outranks feature work below a 60% real-world proof rate,
   and the measured rate is **34%**. The recommendation on file is to insert a **Phase 19a
   engine proof-rate wave** (the 112 plain-class instance-method targets + residual harness
   synthesis failures) before the agent core, because F1's verdict loop is only as good as
   the proof rate underneath it.
2. **Phase 19** (v2 foundations) — only after 0 and 1. Gates in `docs/PLAN-V2.md`.
3. **Carried over from v1, still open:** Sigstore signing + a README demo GIF (ADR-0021 said
   signing "can be added later at zero cost" — it is still later); TS wave 2 (JS cassettes,
   constructor synthesis, ddmin for JS, node in the T1 Docker image, `.tsx`); the
   owner-gated real-model measurements (real synthesis + narrative quality with the owner's
   Anthropic key; rerun `tempest.dev.real_world`); motion polish beyond view transitions.
4. **Backlog (smaller):** `more-itertools`-class generators (materialization semantics),
   VALUE_UNSERIALIZABLE comparison-layer work, Linux T2 bubblewrap backend, parallel target
   proving, Phase 13 docker legs (compose/Postgres/Helm).

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
**39 a tag is a claim too** — `v1.0.0` shipping `0.2.0` artifacts got past a rehearsed release
workflow because the rehearsal proved the JOBS, never the NAME. Assert tag == version in the
release job itself.

## 7. Resume commands

```bash
cd "/Users/prithvivinay/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
git log origin/main..HEAD --oneline          # anything unpushed?
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify
make verify-linux-denominator
uv run python -m tempest.dev.parity --cli-vs-desktop
uv run python -m tempest.dev.orphan_check    # needs the app installed
```
