# HANDOFF-NEXT — the fresh session's single entry point (written 2026-08-17)

**Read this FIRST, before any other doc.** It supersedes the "Part 0 / live state" sections
of every older handoff (they are history now). Then read, in order: `CLAUDE.md` (the Laws),
`docs/HANDOFF-PHASES.md` §2 (the DONE ledger — do not redo anything there) and its traps,
`docs/HANDOFF-WORLD-CLASS.md` (the roadmap, mostly struck through now), `docs/DECISIONS.md`
(ADR-0001..0029 — every deviation lives there).

**The owner is a non-coder.** Plain English, copy-paste commands, verify by running the
real app. **Subagents are FORBIDDEN** (owner, 15 Aug: "just build with one but go all
out") — single agent, maximum depth. **Stop after every phase** for review; rebuild and
reinstall the app to /Applications each phase. **The bar: 100% coverage, zero known
defects, no red CI, ever. Never claim "done" without pasting real gate output.**

---

## 1. Live state (as of this handoff's final commit)

- **Every feature-sized item in the world-class roadmap is BUILT and gated**: AI harness
  synthesis (ADR-0024), monorepo roots + live-PR gate + the real-world measurement
  (ADR-0025, 21%), engine depth (ADR-0026), stage-2 env reproduction (ADR-0027, 21%→34%),
  TypeScript execution wave 1 (ADR-0028, bilingual), watch mode + AI narratives
  (ADR-0029, bundle schema v3). The DONE ledger with gate numbers: `HANDOFF-PHASES.md` §2.
- **Unpushed:** commit `502dcff` — the trap-35 CI fix (see §2, THE most important context
  for the next session) — plus this handoff's own commit. The owner pushes via GitHub
  Desktop (no CLI credential — trap 13).
- **The app in /Applications** is current with everything through ADR-0029 + the trap-35
  engine fix (rebuilt/installed at this handoff's close — the check-in message has the
  timestamp and orphan-check output).
- **The demo branch `tempest-live-demo`** (seeded change for the first live-PR evidence
  comment) exists locally and may already be pushed; if the owner never opened that PR,
  it still works any time: push branch → open PR → Tempest comments → close PR, never merge.

## 2. FIRST TASK: confirm CI green after the owner pushes (trap 35)

The first Linux CI run of TS execution failed ALL TS tests:
`RangeError: WebAssembly.Instance(): Out of memory` at import. Root cause (ADR-0028
amendment): `_set_child_limits` sets `RLIMIT_AS = 2 GiB` on Linux only; V8/Wasm (node's
type stripper) RESERVES multi-GiB virtual address space up front. macOS never enforces
AS → invisible to every local run AND `verify-linux-denominator` (kernel semantics, not
test selection — same class as trap 22). The fix in `502dcff`:
`sandbox.popen(..., v8=True)` → `_set_child_limits_v8` (keeps CPU/core/nproc, drops AS)
across Process/Seatbelt/Docker; the worker carries `--max-old-space-size=256`
(JS containment = V8 heap cap + CPU rlimit + batch wall budget + group kill). The cap's
delivery into the worker is pinned end-to-end (`TestV8Containment`).

**After the owner pushes:** watch the `ci / python` job. If STILL red, the failure rows are
in the check-run **annotations** (the only publicly readable channel — trap 12). Diagnose
from the exact error, reproduce the semantics locally if possible, fix test-first, record
the lesson as trap 36. Never bypass, never lower a gate.

## 3. Frontend ↔ backend: what is guaranteed, and the ONE way to keep it

The integration is protected by generation + gates, not discipline. When you touch ANY
shape, this is the entire law:

1. **One source of truth:** Pydantic models in `packages/api/src/tempest_api/schemas/`
   (+ enums in `packages/engine/src/tempest/model.py`). Never hand-write a TS/Rust type.
2. **Regenerate + commit BEFORE `make verify`:** `make gen-contracts` regenerates
   `packages/shared-schema/*` + `packages/desktop/src/generated/bindings.ts` +
   `packages/desktop/src-tauri/src/generated/domain.rs`; the drift gate diffs the
   committed tree, so uncommitted regen = red `verify-contract`.
3. **Adding an enum variant** must break Rust/TS until handled — that is the design
   working. Check `commands.rs` enum-discipline tests; the UI mostly renders enum strings
   directly (no `never`-guard switches on TargetClassification — 1.1 hardening adds them).
4. **A new DB-backed field is THREE places** (trap 34): `alembic/versions/000N.py` +
   `local_store._FORWARD_STEPS` (keyed by the PRIOR revision) + `REVISION_CHAIN`. The
   migration tests catch any miss — trust them.
5. **Behavior, not just shapes:** the desktop E2E suite (14 tests, real vite UI × real
   stdio sidecar, console-clean gate) runs inside `make verify` (`verify-desktop`). The
   RunProgress push events, dev-mode ajv validation (Boundary B), and the labeled
   AI-narrative panel are all covered there or in component pins.
6. **Every phase ends with the app chain** so the shipped app IS the verified code:
   `./packages/desktop/build-server.sh` → parity → `pnpm tauri build` → ditto to
   /Applications → `orphan_check`. Engine data files (e.g. the `.mjs` execution pair)
   must be in `tempest-server.spec` datas — parity's pure-Python fixture CANNOT detect a
   missing JS asset (trap 32); verify presence in the frozen archive TOC.

## 4. Remaining work, in recommended order (each is one phase with its gate)

1. ~~**Part 3 UI remainder** — Settings groups + Test key + the watch live feed~~
   **DONE 2026-08-17 late (ADR-0030, commit `c189bcd`)**: `settings.json` with
   environment > file > default and every forced field NAMED to the user; Sync/Storage/
   Privacy groups over real config; "Test key" on the sanctioned egress surface; a Watch
   destination whose commits become ORDINARY runs (feed = a query over the `watch.commit`
   ledger mark). Screenshots refreshed in `docs/ui/` (now 16, incl. watch light/dark).
   **Still open from Part 3: motion polish beyond view transitions, and the accessibility
   pass (VoiceOver, keyboard, 200% zoom).**
2. ~~**1.1 hardening**~~ **DONE 2026-08-17 night (ADR-0031)**: enum vocabulary with
   never-guards + schema-driven vitest renders; `reportUiError` end to end (production
   redaction → obslog → LOGS view); desktop logic coverage gate (100%/100% vocabulary +
   router, in `pnpm -r test`). The BUILT-app driver leg is PLATFORM-BLOCKED (tauri-driver
   has no macOS/WKWebView backend) — ADR-0031 §5 names the compensating gates; a Linux CI
   leg can adopt it when the Linux desktop ships. Also DONE: **§3.3 accessibility**
   (skip link, focus-to-title, aria-live status, reduced-motion, 200% zoom — 5 E2E specs)
   and **Phase 18 onboarding** (ADR-0032: "Try a demo proof", click → DIVERGENT in 6.4 s,
   bar 90 s).
3. **2.6 Distribution**: the owner pushes tag `v0.2.0` → `release.yml` fires (wheel +
   unsigned .app + SHA256SUMS + install-check). Watch its first run; then Sigstore
   signing and a README demo GIF (the in-app demo now exists — a GIF of IT is the asset).
4. **TS wave 2** (ADR-0028's stated scope): JS record/replay cassettes, methods via
   constructor synthesis, ddmin for JS inputs, node in the T1 Docker image, `.tsx`.
5. **Owner-gated measurements**: real-model synthesis + narrative quality with the
   owner's Anthropic key in Settings; rerun `tempest.dev.real_world` (the 112
   instance-method targets are the biggest remaining keyless→keyed jump from 34%).
6. **Backlog (smaller)**: `more-itertools`-class generators (materialization semantics),
   VALUE_UNSERIALIZABLE comparison-layer work, Linux T2 bubblewrap backend, parallel
   target proving, Phase 13 docker legs (compose/Postgres/Helm).

## 5. The per-phase loop that produced 29 green ADRs (do not improvise a new one)

```
pick ONE phase → failing tests first (TDD; hermetic: fake Messages peer, local wheels,
  real git repos, REAL execution always — L4)
→ implement; ruff + mypy --strict as you go
→ uv run ruff format --check .          # REPO-WIDE (trap 28 — corpus/ too)
→ commit (regen contracts first if shapes changed)
→ make verify        # detached w/ monitor; ~10 min; expect the 100% gate to name arms —
                     # pin each named arm with a REAL test, amend, rerun
→ make verify-linux-denominator
→ ./packages/desktop/build-server.sh → parity --cli-vs-desktop → pnpm tauri build
  → rm -rf /Applications/Tempest.app && ditto ... → orphan_check
  (ALL direct gate invocations: TEMPEST_NO_POWER_PAUSE=1 — trap 17)
→ ADR + HANDOFF-PHASES row + METRICS if a number moved → memory
→ plain-English check-in WITH pasted gate output → owner pushes → confirm CI
```

Environment: uv+pnpm at `~/.local/bin`, cargo at `~/.cargo/bin`; Playwright pinned
`~1.61.0` (matching the cached browser — `playwright install` HANGS on this Mac);
coverage iterating: `--no-cov`; the authoritative coverage run must be exclusive.

## 6. Traps index (paid-for lessons — full text in HANDOFF-PHASES / memory)

13 owner pushes via GitHub Desktop only · 17 TEMPEST_NO_POWER_PAUSE=1 on direct gates ·
18 pipefail · 19 planted secrets letter-segmented · 22 ubuntu runners have live Docker
(runtime-arc divergence CI-only) · 23 conftest scrubs real ANTHROPIC_API_KEY ·
24 double-covered branches hide dead arms · 25 the L2 grep matches TEST SOURCE (assemble
"SA"+"FE") · 26 revisions predating a config can't self-describe · 27 the worker's
settrace window is invisible to coverage (use the sys.monitoring recorder) · 28 repo-wide
format before verify · 29 Seatbelt carve vs symlink targets · 30 reproduce the exact
failure by hand before coding the fix · 31 V8 precise-coverage repeat deltas are empty ·
32 frozen .mjs are spec datas; parity can't see them · 33 node needs the explicit
strip-types flag + warning suppression · 34 a DB field is three places ·
35 V8 cannot run under RLIMIT_AS (heap cap instead; macOS never enforces AS) ·
36 the line right after a greenlet crossing is mis-attributed by coverage — restructure
into a sync helper, never pragma the block · 37 a schema stamp is a claim, not a fact —
every open verifies the live schema and repairs or refuses loudly.

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
