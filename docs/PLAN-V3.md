# Tempest AI v3 — Convergence Phase Plan C0–C12

> Source: `TEMPEST-V3-MASTER-PROMPT.md` §8, normative. Laws: `CLAUDE.md` L1–L36.
> Dispositions: `docs/MERGE-CONTRACT.md`. Decisions: ADR-0063…ADR-0076. Ledger: `docs/FEATURES-V3.md`.
>
> **Execute in order, one item at a time, inline (no subagents — owner preference).** A phase is
> complete **only** when its gate commands have been run and their real output pasted into the
> session log, with the checkbox flipped in the same commit. **Claimed-passing is failing.**
> Stop after every phase for owner review. Rebuild and reinstall the app each phase.
>
> **Seven of the eight new `tempest.dev.*` gate modules do not exist yet; the eighth,
> `egress_check`, exists and lacks its `--platform-tree` extension** (verified at C0 against
> `tempest/dev/`). Writing each one is part of the phase that needs it. A gate that has never
> run is a claim, not a fact.

---

## Sequencing rules — violating these changes what product you are building

1. **C4 and C5 come before any feature is built on top of the runtime or the router.** Building on
   an implementation you are about to replace is how you do the work twice.
2. **C1's datastore spike is measured before C6 starts.** Deciding the store on architecture taste
   rather than numbers is how a schedule dies.
3. **Phases 24–27 may run in parallel with C6–C11 only after C5 lands.** Every one of them builds on
   the agent runtime.
4. **C12 is never cut.** A fast, unpolished world-class idea is not world-class. (Unchanged from the
   v2 rule protecting phases 30–31.)
5. **`egress_check --airplane-mode-full-function` runs every phase, not at the end.** Local-first
   erodes silently; it is never recovered in one pass at the end.

---

## Phase C0 — Re-audit: establish the honest baseline

Nothing moves until the current tree's real state is known. If something is red that the docs say is
green, that discovery is worth more than any code written today.

- [x] `make verify` on the current tree; paste full output. **Run 2026-08-21 on `a242dce`:
      `MAKE_EXIT=0` — "verify: all live steps green". pytest 1936 passed, TOTAL 9070 stmts
      0 miss / 2590 branch 0 partial = 100.00%; agent_bench 55/55 · intent_bench 54/54, 0 false
      INTENDED · repair_bench 22/28 (79%), 11/11 cheats refused · resume_test 15/15 ·
      subagent_bench 13/13 · retrieval_bench 40/40 + 15/15 grounded, p95 0.2 ms ·
      escape_suite exit 0 · redteam 35/35 · mcp_check 16/16 · mcp_client_check 11/11 ·
      compose_bench 11/11 · redaction 24/24 · license_check green · provider_matrix 16 ·
      vitest 27 + 86 · cargo 115 + 5 · Playwright E2E 51 passed · contract drift-free.
      Full log in the C0 session report.**
- [x] `make verify-linux-denominator`; paste output. **`DENOM_EXIT=0` — 1929 passed, 1 skipped,
      6 deselected; TOTAL 9070/0 + 2590/0 = 100.00%.**
- [x] `uv run python -m tempest.dev.parity --cli-vs-desktop`; paste output. **`PARITY_EXIT=0` —
      "byte-identical bundles (targets.json, 1 repro script(s), manifest minus created_at)";
      fixture verdicts {'clamp': 'DIVERGENT', 'total': 'EQUIVALENT_UNDER_BUDGET'}.**
- [x] `uv run python -m tempest.dev.orphan_check` (app installed to `/Applications`); paste
      output. **`ORPHAN_EXIT=0` — "zero sidecar processes survive SIGKILL of the host (cleared
      in 2.2s, bar 15s)".**
- [x] Write the §2.1 known-open items into this plan as real, numbered items rather than prose:
      Phase 3's TS **execution** half (Node worker, determinism shims, V8 precise coverage,
      type→fast-check compiler, TS corpora); the Claude-Code↔Tempest MCP demo recording (owner);
      ten real MCP servers with authorization-code OAuth (owner); item 19.5b.
      **Done — the known-open ledger below (KO-1…KO-4), including the measured KO-1 correction
      (wave 1 of TS execution SHIPPED in ADR-0028; wave 2 is what is open).**
- [x] Commit ADR-0063…ADR-0076 into `docs/DECISIONS.md`. Amend ADR-0038's refusal table with
      pointers — **do not delete the refusal text.** **Done — fourteen ADRs appended verbatim
      from the addendum; ADR-0038's table retained with a v3 pointer note.**
- [x] Land `docs/PLAN-V3.md`, `docs/MERGE-CONTRACT.md`, `docs/FEATURES-V3.md`; amend
      `docs/PLATFORM-V2.md` with the overturn pointers. **Done — plus
      `docs/TEMPEST-V3-MASTER-PROMPT.md` and `docs/DECISIONS-V3-ADDENDUM.md` landed so every
      cross-reference in the v3 doc set resolves inside the repo, and `CLAUDE.md` gained
      L27–L36 (which `MERGE-CONTRACT.md` and this file cite). Three read-only review lenses ran
      over the landing; all findings fixed (law-summary fidelity ×7, stale-§2.1 correction,
      LC row-id rename).**

**Gate:** every command above run with output pasted. No code written this phase.

### The known-open ledger (§2.1), as numbered items — written at C0, 2026-08-21

Measured against the tree at `a242dce`. Each item names its owner and the phase that closes it;
`docs/FEATURES-V3.md` T32–T35 are the same four items in ledger form.

- [ ] **KO-1 — TypeScript execution, wave 2** (= T32; scheduled C0 → 3-continuation per §8.6).
      **Correction, measured at C0:** master prompt §2.1 says "the Node execution worker and V8
      coverage are not [done]" — that predates ADR-0028 (2026-08-16). Wave 1 SHIPPED and is in
      `make verify`: `ts_worker.mjs` (Node execution worker), `ts_shims.mjs` (determinism shims:
      seeded `Math.random`/`Date`/`performance`/`crypto`), per-input V8 precise coverage with
      count-0 subtraction, `ts_dual.py` (the same comparator), tsfix corpus 8/8 keyless.
      **Actually open:** TS cassettes/recorded-IO, instance methods, `.tsx`, the T1(Docker) Node
      leg, the type→fast-check compiler, TS corpora growth. Blocks any parity claim that includes
      TypeScript proving beyond wave-1 scope.
- [ ] **KO-2 — Recorded Claude-Code ↔ Tempest MCP demo** (= T33). **Owner action** — no hermetic
      gate can assert it; `mcp_check` prints this itself.
- [ ] **KO-3 — Ten real MCP servers with authorization-code OAuth** (= T34). **Owner action.**
- [ ] **KO-4 — 19.5b, one model path** (= T35; closes in C4, ADR-0076 rider): migrate
      `harness/llm.py` and `report/narrative.py` onto `tempest/inference/` and drop the
      `anthropic` SDK. `grep -rn "^import anthropic\|from anthropic" packages/engine/src` finding
      no SDK import is part of C4's gate.

---

## Phase C1 — Vendor, attribute, and measure the store

- [x] Vendor LibreChat at a pinned commit into `packages/platform/{server,api,data,provider,client}`,
      preserving their directory structure (L27). **Done 2026-08-21, commit `ec1e9e0`: thirteen
      trees @ upstream `d602452c05ed767315a753264f02368c10f31e19` (the five named + client-pkg,
      e2e, config, search, otel, redis-config, skill, LICENSE — one SHA so the client and its
      shared package cannot skew), 4,194 files, ~50 MB. Zero whole-word `SAFE` in vendored
      .py/.ts/.tsx (CI grep unaffected); zero vendored .py (ruff/mypy scope unaffected);
      explicit pnpm/uv workspaces mean nothing vendored joins any build.**
- [x] **In the same commit:** strip every brand asset — logos, wordmarks, favicons, brand imagery,
      brand colour tokens — so they are never in the tree. MIT does not license trademarks.
      **Done in `ec1e9e0`: six own-brand files replaced in place with neutral generated
      placeholders (same filenames — references stay valid, upstream changes surface as merge
      conflicts); itemized in UPSTREAM.md. Gate grep zero. Text-level identity is C3's restyle;
      the client is not built or shipped before then. Provider logos retained (nominative use).**
- [x] **In the same commit:** `THIRD_PARTY_LICENSES.md` gains the derivation table rows (source path,
      adopted SHA, disposition, modification summary) and LibreChat's own dependency obligations are
      merged into ours. **Done in `ec1e9e0`: 13 rows @ `d602452c`; upstream MIT travels at
      `packages/platform/LICENSE`; upstream ships no third-party-licences file of its own —
      its dependency obligations are the manifests, which travel in the vendored trees.**
- [x] Extend `tempest.dev.license_check` to `packages/platform/**`, with unit pins that each prove a
      **failure** on a violating tree (the existing 18 pins are the pattern). **Done, commit
      `7dc41ca`: checks 6–9 (platform LICENSE, pinned UPSTREAM.md, boundary-aware derivation
      rows per vendored tree, brand assets by name AND bytes); 13 new pins; real-tree run:
      "zero missing notices", exit 0.**
- [x] Write `packages/platform/UPSTREAM.md`: adopted SHA, merge procedure, empty delta ledger.
      **Done in `ec1e9e0` (+ `01c4af2` writing the vendor-baseline SHA, which a commit cannot
      contain for itself): adopted SHA, tree mapping, merge procedure, brand-strip list, empty
      inline-delta ledger.**
- [x] Build `tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete`. **Done,
      `7dc41ca`: pinned origin + resolvable baseline required; drift = committed AND
      working-tree deltas under `packages/platform/**`; every non-seam/non-UPSTREAM.md delta
      must be a ledger row and every row a real delta (stale rows fail); 18 pins on real git
      repos. Real-tree run: "0 inline delta(s) against a cap of 40 … mergeability intact", exit 0.**
- [x] Build `tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store`.
      **Done, `7dc41ca`: no mongod/mongos/mongosh by stem, no SSPL licence text, no RUNTIME
      dep on the mongod downloader (devDependencies allowed — test tooling never ships), no
      pymongo/motor/mongoengine import in the engine, cross-store table declared; 18 pins.
      Real-tree run: "L33 holds", exit 0. All three gates + the brand grep now run as
      `make verify-convergence`, inside `make verify` and the CI python job (`9c5b246`).**
- [x] **The datastore spike (ADR-0068).** Stand up FerretDB 2.x + embedded PostgreSQL + DocumentDB
      on the 4-core/16 GB reference profile. Measure and paste: cold launch → interactive, idle RAM
      (all sidecars), idle CPU, and p95 for the ten hottest LibreChat queries. **Executed
      2026-08-21 with the decisive finding UPSTREAM of the latency table: the stack cannot be
      stood up on the shipping OS. DocumentDB ships Docker/K8s/DEB only (43 release assets,
      zero darwin; no Homebrew; source build's stated prerequisite is Docker), and this Mac has
      no Docker (`docker: command not found`) — nor may the app's own datastore REQUIRE a
      container runtime the containment law itself treats as optional (L6/ADR-0003). Fallback
      proxy measured instead: document-table-over-SQLite, 110k docs, five hot shapes, p95
      0.003–0.036 ms vs the §10 budget of 20 ms (~500× headroom, zero extra processes). Full
      record: ADR-0068 amendment.**
- [x] Record the measurement in ADR-0068. If any §10 budget is missed by >25%, engage the
      pre-approved fallback (Mongoose models/methods over an engine-SQLite document adapter) and
      record that instead. **No new ADR needed to take the fallback — only to record the numbers.**
      **Recorded — ADR-0068 amendment (2026-08-21): fallback ENGAGED. Mongoose models/methods
      stay the public API; the SQLite document adapter is built in C6; platform documents get
      their own SQLite file, never the proof store (L33 separation is logical, not vendor-based);
      FerretDB remains a config option for the unbuilt server mode on Linux.
      `docs/MERGE-CONTRACT.md` data-layer fallback row updated to ENGAGED.**

**Gate:**
```bash
python -m tempest.dev.license_check --third-party-notices --platform-tree
python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store
python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete
# spike numbers pasted against the §10 table; ADR-0068 amended with the measured choice
grep -ri "librechat" packages/platform/client/public packages/desktop/src --include='*.svg' --include='*.png'   # zero brand assets
```

---

## Phase C2 — Boundary E

- [x] `packages/shared-schema/platform.schema.json` — the root of truth for every message crossing
      Rust ↔ Node. Domain values reference boundary C's Pydantic-rooted types; they are never
      redefined. **Done 2026-08-21 (`1d06e7a` + review wave `91d…`). Mechanics note, stated
      exactly: the ReasonCode definition is COPIED from `domain-schema.json` by
      `gen-platform-schema.mjs` rather than `$ref`'d across files (typify needs a
      self-contained document) — single Pydantic source, mechanical ordered propagation inside
      one `gen-contracts` recipe, drift-gated; byte-equality of all three copies verified at
      review.**
- [x] Generation into Rust and TS, wired into `make gen-contracts`, landing inside the paths
      `verify-contract` already diffs. **Done: typify → `src-tauri/src/generated/platform.rs`
      (deny_unknown_fields throughout); the Node seam gets `platform-schema.mjs` (runtime
      consts) + `platform-schema.d.mts` (the TS face). Honesty note: the seam's generated dir
      was ADDED to `verify-contract`'s diff list — the plan's "already diffs" wording did not
      hold for the fifth boundary and the gate grew instead, disclosed in the commit.**
- [x] JSON-RPC 2.0 over a **Unix domain socket** (named pipe on Windows), length-prefixed framing —
      reuse `framing.rs`, which already does this for boundary A. **No TCP listener, ever.**
      **Done: `Transport::Unix` in supervisor.rs, `framing.rs` reused verbatim over the
      `UnixStream`; the Node decoder mirrors it and REJECTS what would desync (duplicate
      Content-Length, non-ASCII header bytes) — two wire-level pins. Socket in a private
      per-user 0700 subdir, pid-namespaced, dead-sibling sweep. Named pipe: no Windows desktop
      exists (QV5); `Transport::Unix` on non-unix returns an explicit Unavailable naming the
      deferral — recorded here so the clause is deferred, never dropped.**
- [x] **Bidirectional validation in production, not only in dev.** LibreChat is JavaScript, so TS
      types are advisory at runtime. A validation failure is a surfaced, diagnosable error with an
      ID (L15.3), never a swallowed exception. **Done: Node validates envelope AND per-method
      result shapes both directions in the shipped path (`boundary-validate.mjs`); proven at
      the wire by pins that inject a smuggled field and an unknown method and get -32600 +
      diagnostic_id. Rust: methods from the generated PlatformMethod enum, results parsed
      into deny_unknown_fields types, failures carry diagnostic ids.**
- [x] Node API supervised by `supervisor.rs` under L34: process-group ownership, health checks,
      exponential-backoff restart, teardown that survives `SIGKILL` of the parent. **Done —
      same monitor/backoff/sweep code path as the engine (500 ms → ×2 → 8 s cap, 60 s healthy
      reset); SIGKILL survival via the held-open stdin pipe + ppid watch; SIGKILL-respawn
      proven by a live test. At C2 the supervised child is the boundary's lifecycle endpoint —
      LibreChat services route through it at C5, by design (the schema leads).**
- [x] Extend `orphan_check` to `--all-children --after-sigkill`. **Done, then hardened by
      review: descendant tree re-snapshotted at kill time (caught a third process on its
      first run), pgrep scoped to OUR descendants (an unscoped match could have SIGKILLed a
      bystander), the port probe fails when lsof itself fails, and the socket assertion pairs
      through TEMPEST_PLATFORM_SOCKET rather than a duplicated constant. Run on the installed
      app: 3 descendants tracked, zero TCP listeners, zero survivors in 2.5 s / 15 s bar.**

**Gate:**
```bash
make gen-contracts && git diff --exit-code      # FIVE boundaries, one truth
uv run python -m tempest.dev.orphan_check --all-children --after-sigkill
# a port probe proving no TCP listener is opened by any child, on all three OSes
# an enum-drift probe: add a ReasonCode in Python → Rust build, TS build, AND boundary E
#   validator all fail. Paste all three failures, then revert.
```

**C2 gate outcomes (2026-08-21):** drift gate `FIVE_BOUNDARIES_DRIFT_FREE` (exit 0 after
regen, committed tree). Orphan gate: 3 descendants tracked, `port probe: zero TCP listeners
across the host and every descendant`, `zero descendant processes survive SIGKILL of the host
(cleared in 2.5s, bar 15s)` — plus an in-test lsof probe per run. **Three-OS honesty (QV5):
only the macOS desktop exists; the probe runs on macOS locally and ubuntu CI compiles the
suite — claiming three OSes would be exactly the kind of claim this product refuses.**
Enum-drift probe, all three failures observed live then reverted: Rust
`error[E0004]: non-exhaustive patterns: ReasonCode::EnumDriftProbe not covered`
(commands.rs:748, exit 101 under --all-targets, how CI compiles); TS
`vocabulary.tsx(67,24): error TS2345: '"ENUM_DRIFT_PROBE"' is not assignable to type 'never'`;
boundary E: seam-module diff → verify-contract exit 1 AND the live validator's
`{"ok":false,"why":"error.reason_code is not a known ReasonCode"}`.

---

## Phase C3 — The merged shell

- [x] LibreChat's React client mounts in the Tauri webview. **One router, one state layer, one
      design system.** Tempest's `packages/desktop/src/views/**` and `editor/**` are absorbed into
      it. (Upstream ships Recoil *and* Jotai; adopt both as they stand — do not consolidate
      actively-developed code for zero user benefit. Adding a **third** is what is forbidden.)
      **Done 2026-08-22 (`987684f` mount → `aadf3df` absorption, ADR-0077). ONE window, on by
      default, named Tempest AI: client dist + theme ship as bundled resources, the Node sidecar
      auto-spawns, and the scaffold second window is gone (`2c194f1`). The absorbed surface is a
      react-router subtree at `/tempest/*` in the `client/tempest/views` seam — ten views +
      editor + hooks ported to the client's own stack (Query v4, React 18), reached through
      exactly two inline deltas (route entry + nav link), both ledgered. The root fix that
      unblocked all of it: the bundle carried TWO Reacts (librechat-data-provider's query peer
      auto-resolved react@19 beside the client's 18) — pinned in pnpm-workspace.yaml
      (`858012b`); the handoff's chunk-order hypothesis was the symptom. Honesty note
      (ADR-0077): the legacy webview survived behind `TEMPEST_LEGACY_WINDOW=1` ONLY until the
      E2E suite re-targeted the platform surface — a dated bridge. **CLOSED 2026-08-22:
      the suite drives the platform surface (51/51 green, five consecutive runs across the
      branch and the merged tree), the legacy sources and the flag are deleted, and a
      failed platform start now opens `/__tempest-diagnostic` — see ADR-0077's completion
      note for the full evidence.**
- [x] `vocabulary.tsx` becomes the reserved-verdict rendering layer and the L31 enforcement point.
      **Done: the seam copy keeps every never-guard (a new Python variant still breaks the
      build) and is the only verdict renderer inside the client; `vocab_check` scans 4,056
      vendored files clean around it.**
- [x] Restyle into Tempest's identity via the design-token seam — **not** by rewriting components.
      A user must never be able to tell where one codebase ends and the other begins.
      **Done, with one real defect found and fixed (`2423351`): the seam re-declared the
      primitive gray ramp inverted under `html.dark` while upstream's `.dark` layer already
      inverts at the semantic level — the double inversion rendered a white chat pane in a dark
      shell. One ramp, two derivations; the dark block now carries polarity-true values only,
      plus `color-scheme` so native controls follow, plus a first-paint mode script at the
      protocol (the vendored client only sets `html.dark` from an effect).**
- [x] Auth becomes optional: local single-user mode short-circuits to an implicit local principal
      through a distinct code path with its own tests. **Never a bypass flag.**
      **Done (`987684f` seam; `a4211cc` + `b190021` the measured boot surface): the client
      boots authed with zero prompts against `local-api.mjs`'s ~30 endpoints, every shape read
      from the vendored provider types. Three traps that cost real renders: the client requests
      `/api/roles/USER` (uppercase) and reads `permissions[type][perm] === true` directly — an
      empty permissions object hides every gated nav section; a PRESENT-but-empty `interface`
      defeats the client's own defaults; `customFooter: ""` is what keeps the upstream wordmark
      off the shipped surface. Conversations/prompts/presets answer truthfully empty until
      their phases (C6/C7).**
- [x] Every telemetry surface (LibreChat telemetry, Langfuse, RUM, insights, error reporting) is off
      by default and **provably inert**, each with its own `egress_check` case.
      **Done (`0e8eada`): RUM, GTM, turnstile, Langfuse, OTel and the Sandpack bundler each
      carry a pinned gating pattern (a drift tripwire — upstream restructuring the gate fails
      the check and forces re-audit); the RUM bootstrap is pinned inert-by-construction; the
      seam's STARTUP_CONFIG is pinned to carry no telemetry key at all.**
- [x] Build `tempest.dev.egress_check --platform-tree --deny-all --airplane-mode-full-function`.
      **Done (`0e8eada`): 113 surfaces audited, 79 pins each proven to FAIL on a violating
      tree; the sidecar's import allowlist (node:net/fs/process + relatives only) proves it
      cannot express an outbound call; wired into `verify-convergence`. The L10 escape-suite
      leg keeps its original flags.**
- [x] Build `tempest.dev.vocab_check --reserved-verdicts --platform-tree`.
      **Done 2026-08-21 (`9039787`), in `verify-convergence` + CI since.**

**Gate:**
```bash
python -m tempest.dev.egress_check --platform-tree --deny-all --airplane-mode-full-function
python -m tempest.dev.vocab_check  --reserved-verdicts --platform-tree
python -m tempest.dev.perf_suite   --enforce-budgets     # cold launch, merged-app row
# every route renders with zero console errors; screenshots attached
```

**Gate outcomes (2026-08-22, pasted from the session log):**

- `egress_check`: *113 platform surfaces audited — every telemetry and egress surface off by
  default, the sidecar unable to express an outbound call, and the boot surface fully answered
  with the network unplugged (L32 holds)* — exit 0, and green again inside the full
  `make verify` below.
- `vocab_check`: *4056 vendored source files scanned — zero reserved verdict tokens, zero
  verdict-shaped field writes outside the seams (L31 holds)* — exit 0.
- **Merged-app cold launch** (the §10 row, measured by the new `make bench-merged` against the
  installed bundle, best-of-3 at HEAD): **0.575 s** against 1.2 s p50 / 2.0 s p95; earlier
  same-night launches sampled 0.611–0.673 s. The measurement point is the shell's first
  `/api/config` fetch — the webview up and asking for its world.
- **Console sweep**: the webview's console tap (every uncaught error, rejection, and
  console.error forwarded to host stderr) stayed at **zero lines** through boot and a full
  interactive pass — chat landing, every sidebar section, all six Tempest sub-views, Settings,
  and the sidebar toggle. Two real defects the sweep caught first are fixed and ledgered
  (`13896d2`). Screenshots taken at each step; the two-window scaffold is gone.
- `make verify` on this tree: **MAKE_EXIT=0** — pytest 2112 passed, 100.00% on 9,070
  statements + 2,590 branches; agent gates all green; cargo 115+8+5; vitest 27+86; desktop
  E2E 51 passed; all five convergence gates green (license, store, upstream 6/40 inline
  deltas, vocab, egress).

---

## Phase C4 — One provider router (ADR-0076)

- [x] LibreChat's provider configuration schema, model-spec metadata, per-endpoint parameter UI, and
      reasoning UI mapped onto `tempest/inference/`.
      **Done 2026-08-22 (`267350a` + `c2efc6b` + `5af38d1`), mechanics stated exactly: the engine's
      `GET /v1/platform/catalog` builds upstream's own `/api/endpoints` + `/api/models` shapes from
      the ONE registry, and the `tempest://` protocol answers the client from it — the selector the
      user sees IS the router the engine spends through. Model-spec metadata is ADOPTED from
      upstream's `defaultModels` tables at the vendored commit (anthropic 16 / OpenAI 22 / Gemini
      10, refreshed at upstream merges, never invented); metadata-less providers use upstream's own
      discovery mechanics — local runners probed live at loopback (keyless, offline-safe, L23),
      keyed remotes probed only when the user configured that key (the `verify_key` BYOK egress
      surface, L10; a hit-counting peer pins the ABSENCE of the keyless request). Parameter and
      reasoning UI light up from the client's own per-type tables (`custom`/`anthropic`) — zero
      client edits. Honest scope note: user-authored `librechat.yaml` custom-endpoint entries join
      when the real Config service lands (C6/C10); until then "adding a provider" is ADR-0076's own
      mechanism — one registry row, no feature code.**
- [x] Adaptive provider smoothing and delta batching adopted onto the single router.
      **Was deliberately open: its surface is the STREAMED chat turn, which arrives with the C5
      agent runtime — smoothing adopted before any stream exists would be decoration. Carried to
      C5. DISCHARGED there (ADR-0079 §7): a read-side, seq-preserving merge that coalesces
      adjacent text deltas for one step into a frame carrying the run's LAST seq, applied
      identically on the live and store-replay paths. LC06 is `ADOPTED` with its concatenation,
      cursor and no-hole pins. Ticked 2026-08-24 (ADR-0088) — the box had stayed open while the
      work it describes was finished and ledgered, which is the plan disagreeing with the
      ledger in the under-claiming direction.**
- [x] `credentials.ts` replaced by the OS keychain path (`keychain.rs`). No plaintext key storage,
      no exception for dev builds.
      **Done (`c2efc6b`/`5af38d1`): the protocol intercepts `/api/keys` and answers from the OS
      keychain — presence, storage, revocation — under accounts NAMED BY the provider's env var,
      so the host carries no registry copy and `engine_env` enumerates what exists at spawn
      (attribute-only search; values never in a response, error, or log). Upstream's exact wire
      shapes (`expiresAt: null` / literal `"never"` / bare 201/204), byte-matched after the live
      boot caught a guessed shape crashing the sidebar hook. The pre-C4 single-item install keeps
      answering for anthropic until any write migrates it. `credentials.ts` never enters the
      serving path — REPLACE, per the merge contract.**
- [x] Caps enforced at the router. Cost meter remains the single spend-enforcement point and still
      ships **no price list**. **Held and re-proven this phase — both gate tests named below ran
      green in this session's log and inside the full suite.**
- [x] **19.5b:** migrate `harness/llm.py` and `report/narrative.py` onto the unified client; drop the
      `anthropic` SDK dependency. **Done (`2e7715f`): both call sites one-to-one onto the stdlib
      client; `TEMPEST_SYNTHESIS_BASE_URL` stays the public knob, aliased onto the router's
      per-provider override, so all 19 fake-peer unit tests and 19 integration/API tests passed
      UNCHANGED. One disclosed behavior change: the SDK's retry is gone — a transient synthesis
      failure declines one attempt sooner into the same UNPROVEN terminal state. Open since
      Phase 19.**
- [x] Raise `provider_matrix` floor to `--min-providers 16`. **Done: module default + Makefile;
      the registry already held 16 — the gate now says so.**

**Gate:**
```bash
python -m tempest.dev.provider_matrix --min-providers 16
grep -rn "^import anthropic\|from anthropic" packages/engine/src && exit 1 || true
# cap test: 8 threads against a cap admitting 2 → exactly 2. Paste output.
# dollar cap with no user-supplied rate RAISES rather than passing. Paste output.
```

**Gate outcomes (2026-08-22, pasted from the session log):**

- `provider_matrix --min-providers 16`: *16 providers, every request path exercised against a
  real peer — adding a provider is one row, not one integration* — exit 0.
- SDK grep over `packages/engine/src`: **zero imports** (and `anthropic>=0.116` is gone from
  pyproject; the frozen sidecar was rebuilt without it).
- Cap test: `TestConcurrency::test_a_fleet_cannot_slip_two_charges_past_one_cap` — 8 threads
  against a cap admitting 2, `len(accepted) == 2` and `len(errors) == 6` — **PASSED**.
- Rate test: `TestAnUnevaluableLimitNeverPasses::test_a_dollar_cap_without_a_rate_raises_rather_
  than_passing` — `pytest.raises(RateUnknown, "cannot be evaluated")` — **PASSED**.
- The shipped binary's catalog, probed over its real stdio: 16 endpoints / 16 model lists / 16
  provider rows; anthropic first (16 adopted models, `claude-fable-5` leading), OpenAI 22,
  Gemini 10; locals and keyless remotes honestly empty. Full app boot with the bridge:
  **zero console errors, zero 404s**, merged cold launch 708 ms.

---

## Phase C5 — One agent runtime ⭐ THE LARGEST ITEM (ADR-0075)

This phase decides whether the merge produced one product or two. Budget for it accordingly, and do
not let anything else land while it is in flight.

- [x] `api/server/services/Agents/**` becomes a thin client, delegating every turn to the
      Python orchestrator, speaking unchanged shapes to the React client. *(Landed as the
      HOST's protocol seam over boundary A — the recorded ADR-0078 deviation; the vendored
      Express agent stack stays dormant, held by `runtime_check`.)*
- [x] Tool registries unify on `agent_tools.rs` (boundary D). `WriteScope` keeps its property that a
      write to the user's working tree is **unrepresentable**. *(Seven tools incl. `ask_user`;
      the builder's picker is a projection of the one manifest — e2e 23.)*
- [x] LibreChat's agent surface adopted and re-targeted: no-code builder, unified tools
      marketplace (builder side), skills (P3), subagents (P4), run control (interrupt, steer
      mid-run, queue follow-ups, reclaim pending steers), human-in-the-loop pause for input and
      tool approval, generated activity-group headers, context-usage gauge, stream circuit
      breakers. *(Named deferrals in ADR-0079: per-tool background/intent settings and the
      plugin marketplace install flow ride C8/C10; preempt-arm answers PREEMPT_UNSUPPORTED.)*
- [x] Build `tempest.dev.runtime_check --single-orchestrator --single-tool-registry`.
- [x] Build `tempest.dev.gate_audit --enumerate-paths --require-forge-test-per-path`: enumerate every
      code path by which agent-authored change reaches a user, and require a forge test per path.
      *(Six declared paths; the agent chat surface is the sixth, with its no-verdict forge.)*
- [x] `docs/MERGE-CONTRACT.md` and `UPSTREAM.md` updated with the `services/Agents/` delta.
- [x] **Local models, the owner's mandate** (ADR-0080 + its amendment): a curated
      free-and-permissive catalogue downloaded in-app with `Range:` resume and sha256
      verification, deletable, sizes and free space on screen before the spend; a supervised
      loopback model server, off by default; and the keyless turn's structured remedy wired to
      a "Get a local model" affordance. **T36 and T37 ADOPTED.** Two adversarial review waves
      over it: the second retrieved all four lenses (30 findings, 8 confirmed, 3 split), and
      what they found is the amendment — a P0 orphan window opened by the previous fix, a
      downloader that let the SERVER choose how many bytes reached the disk, a model server
      that could be told which executable to run by the webview, and four tests that could not
      fail. Driven end to end through the real panel by e2e spec 25, with the progress poll
      mutation-proven.
      **Placed where the owner asked, 24 Aug (ADR-0082/0083/0084).** The panel shipped inside
      the proof surface's own settings page, three clicks deep behind a surface that is a TOOL
      the assistant uses (ADR-0067) — so it moved into the app's ONE settings home beside the
      provider keys, with a Models entry on the main rail. The proof engine's settings joined
      the same dialog and the second settings page is gone; the proof surface became a
      full-width route so the window stopped carrying three columns of navigation; the agent
      builder gained the repository field that made a tool-bearing agent reachable from inside
      the app at all, and a blank-slate preset for an agent that knows how to use `prove`.
      A reasoning model's thinking became its own content channel (ADR-0081) — without it the
      catalogue's most-likely first click answers with an empty bubble — and a local model is
      shown by its NAME rather than by the absolute path llama.cpp reports, which was the
      user's home directory in a dropdown.

- [x] **The `created`-frame race is fixed, and a second route to the same symptom with it**
      (ADR-0089). A spinner that never stopped, from two independent mechanisms. The poller was
      started inside the POST handler at cursor 0, so the push carrying `created` was emitted
      before the webview had subscribed and was lost — and the replay page that still held it
      was then discarded by the overtaken-cursor retry. Fixed by ONE invariant enforced from
      both sides: the replay is the authority and the live feed begins strictly above the page
      it served. Reproduced deterministically first, and mutation-proven after. Separately,
      the host's 30-second circuit breaker emitted `status: "error"` with no events and the
      transport read only frames, so the breaker changed nothing — `readyState` stayed OPEN
      and the reconnect ladder never armed. That closes ADR-0079's last deferral.
- [x] **The ledger becomes an instrument** (ADR-0088, pulled forward from C10/C12). Build
      `tempest.dev.feature_ledger` (L30/L31/L36.3) and `tempest.dev.parity_ledger` (L35), wire
      both into `make verify`, and reconcile every disagreement they surface. First run against
      the real tree: 12 findings, including three rows claiming a LibreChat capability on a test
      that verifies a different one (LC11, LC34, LC52's unbuilt half) and two the ledger had
      UNDER-claimed (LC03, LC04). Parity is now published in the README — 16/78 = 20.5% — which
      L35 has required since it was written and had never once been satisfied.

**Gate:**
```bash
python -m tempest.dev.runtime_check --single-orchestrator --single-tool-registry
python -m tempest.dev.gate_audit    --enumerate-paths --require-forge-test-per-path
python -m tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform \
                                     --verifying-tests-resolve --no-unfinished-rows-in-closed-phases
python -m tempest.dev.parity_ledger  --print-percentage
./scripts/agent-gates.sh                                              # all four, through the NEW surface
python -m tempest.dev.agent_bench  --tasks 50 --require-verdict-coverage 1.0   # must still be 55/55
python -m tempest.dev.intent_bench --min-accuracy 0.90 --max-false-intended 0  # must still be 54/54, 0 false
python -m tempest.dev.repair_bench --min-success 0.60 --check-cheats
python -m tempest.dev.resume_test  --kill-mid-proof --sleep-mid-stream
```

**If `agent_bench` is not still 55/55 through the new surface, the merge broke the thing the product
is for. Fix it before anything else lands.**

---

## Phase C6 — Datastore cutover

> **Restructured 2026-08-25 (ADR-0090).** The five boxes below were written before anyone had
> run LibreChat's data layer, and the first of them ("every model, method and migration green")
> is a 90,889-line, 2,371-test target behind a store that does not exist yet. They are kept
> verbatim as the phase's definition of done and each is now backed by numbered sub-items that
> can be landed and gated one at a time. **Two of the original five could not survive contact
> with the tree and say so below, with the ADR that records why.**

- [ ] Every LibreChat model, method, and migration green against the store C1 selected.
- [ ] Migration up/down parity test.  ⚠️ **see C6.4 — no migration in the tree has a down path**
- [ ] Their data-layer test suites run inside `make verify-v3` (merge contract §6 rule 4).
- [ ] Redis interface backed by in-process LRU + engine SQLite; real Redis retained as config.
- [ ] The five declared cross-store references implemented as opaque ids; `store_check` reads the
      table in `MERGE-CONTRACT.md`.

### The measured shape of this phase (measured 2026-08-24/25)

Counted before any of it was planned, because "every model, method and migration" is a size, not
a sentence:

| | |
|---|---|
| vendored data layer | 90,889 LOC TypeScript, 282 source files |
| the gate | 66 spec files, **2,371 tests** — measured by running them, not counted from source (a static sweep says 2,252; 11 files use `it.each`) |
| of those | 44 boot a real `mongod`, 22 run in-process; 19 reach past Mongoose to the raw driver |
| query surface | **17** query + **12** update operators (`$bit` among them, only ever assigned dynamically; `$type`, `$all`, `$mod`, `$jsonSchema`, `$pop`, `$mul` used **zero** times) |
| aggregation surface | **11** stages, **18** expression operators, `$$ROOT` and `$let`; 22 `.aggregate()` call sites (that one figure counts specs; every other number in this table excludes them) |
| index surface | **235** declarations — 116 `schema.index()` + 119 field-level `index: true`; across both, 32 unique, 14 partial, 11 TTL, 6 sparse; **0** text, **0** collation (counted with comments stripped — upstream's prose about partial and TTL indexes inflates a naive grep) |
| runnable today | **yes, as of C6.0** — it was in none of `pnpm-workspace.yaml`, the lockfile or CI, and had never once been run in this repository |

### C6.0 — Join the data layer to the build and take the CONTROL measurement

Nothing after this is interpretable without it. A test that fails against the Tempest store and
also fails against real MongoDB has found nothing (trap 54: a differential check must ask both
sides under the same conditions).

- [x] `packages/platform/data` joins `pnpm-workspace.yaml`.
- [x] The phantom imports are resolved by **our** workspace metadata, never a vendored edit.
      Four files import packages their own manifest does not declare — `jest.globalSetup.mjs`
      wants `mongodb-memory-server-core`, `babel.config.cjs` wants `@babel/core`,
      `@babel/preset-env`, `@babel/preset-typescript` and
      `babel-plugin-replace-ts-export-assignment`, and the specs want `uuid` and `mongodb`.
      **`packageExtensions` is the wrong mechanism here and the reason is worth recording:**
      it has no `devDependencies` field, so every entry would become a RUNTIME dependency —
      and for `mongodb-memory-server-core` that is a runtime dependency able to fetch an SSPL
      `mongod`, which is exactly what `store_check --no-sspl-binaries` forbids. They are
      `publicHoistPattern` entries instead, which resolves the import while claiming nothing
      untrue about the graph. Every one was already in the store; nothing new is fetched.
      *(Two things learned the hard way and recorded so nobody pays twice: pnpm 11 reads these
      settings from `pnpm-workspace.yaml`, not `.npmrc` — writing them to `.npmrc` leaves
      `node_modules/.modules.yaml` recording `publicHoistPattern: []`; and changing the pattern
      forces a full `node_modules` relink, which pnpm refuses without a TTY.)*
- [x] `mongodb-memory-server`'s install-time download **denied** in `allowBuilds`, so no plain
      `pnpm install` and no CI run ever fetches an SSPL binary; `MONGOMS_VERSION` pinned to
      `8.2.6` so the control is a fixed point rather than whatever resolves today; and
      `MONGOMS_DOWNLOAD_DIR` forced outside the repository by `scripts/data-control.sh`, which
      **exits 2** if it resolves inside the tree.
      *(The guard's first version compared the RAW value with a shell `case`, and a string test
      is not a path test: `binaries`, `./mongo-bins`, `packages/../mongo-bins` and an absolute
      in-repo path all sailed past it — found by review, and each of the four now refuses. The
      value is resolved with `cd && pwd -P` first, so relative paths and symlinks are compared
      as real absolute paths.)*
- [x] **The gate that was supposed to be the backstop could not see the file.**
      `store_check`'s SSPL name check compared a filename stem against exactly
      `{mongod, mongos, mongosh}` — but `mongodb-memory-server` writes what it downloads as
      `mongod-<arch>-<distro>-<version>`, whose stem is `mongod-arm64-darwin-8`. A 147 MB SSPL
      server could sit in the tree — **committed** — under a gate printing "L33 holds", and a
      review demonstrated it by planting the real filename. The check now matches a server name
      followed by `-`/`_` or end-of-stem, in **both** name loops (tracked and walked, which
      compute the stem separately). Four new pins: the real darwin name, the real Windows name,
      a versioned `mongosh_2.3.1`, and `mongodump` + `mongodb-connection-string-url.js` which
      must still PASS — a gate that fails on those is untrustworthy in the other direction.
      The three failure pins are mutation-proven: reverted to exact equality, they fail; with
      the fix, 35/35 green. (The gate predates C6, but C6 is the phase that downloads a file
      with that exact name, so it is C6's to close.)
- [x] One override was needed and it is a layout adaptation, not a behaviour change:
      `tempest/jest.config.control.mjs` (a Tempest-owned seam file, so the vendored config stays
      byte-exact) adds `\.pnpm` to upstream's `transformIgnorePatterns` exception list.
      Upstream's regex is written for npm's FLAT `node_modules`; under pnpm the first
      `/node_modules/` segment is `.pnpm`, the negative lookahead succeeds there, and every
      ESM-only dependency is left untransformed — jest dies on `Cannot use import statement
      outside a module`. With `.pnpm` excepted, the second `/node_modules/` position — the one
      carrying the real package name — is the only decider, which is upstream's intent exactly.
- [x] **The control, run and reproducible** (`./scripts/data-control.sh`):
      ```
      Test Suites: 66 passed, 66 total
      Tests:       2371 passed, 2371 total
      Time:        55.242 s
      All files    |   77.84 |    73.82 |   82.83 |   78.02 |
      CONTROL_EXIT=0
      ```
      MongoDB `8.2.6` (`mongod-arm64-darwin-8.2.6`). **2,371 tests, not the 2,252 the static
      count predicted** — 11 files use `it.each`, so the run count is the higher one, and the
      run count is the one that matters. Coverage moves by ~0.04 points between runs; the
      control's claim is pass/fail, and it is not a coverage claim.
- [ ] **Record the command stream while the control runs.** The driver emits `commandStarted`
      for every operation it sends; a listener over the control run turns "what must the store
      implement?" from a reading exercise into a measurement — the exact command names, their
      option keys and their frequencies, taken from a real execution of 2,371 tests rather than
      inferred from source. This inventory, not a spec document, is what C6.1 builds against.
- [ ] `make verify` re-run in full afterwards — adding a workspace member re-resolves the whole
      lockfile and the hoist change relinked every `node_modules` in the tree, while the vendored
      client build chain is pinned by hand (React 18, axios 1.18.1, react-window 1.8.11). A green
      tree before is not a green tree after.

### C6.1 — `@tempest/docstore`: the store itself (ADR-0090)

A MongoDB-wire-protocol server on a Unix domain socket, backed by SQLite via `node:sqlite`.
Real, unmodified mongoose and the real native driver on the other side; **zero edits to
`packages/platform/data/`**, so its delta-ledger row stays empty.

- [ ] Wire layer: framing, `OP_MSG` (kind-0 and kind-1 sections) and `OP_QUERY`, the `hello`
      handshake, cursors (`getMore`, `killCursors`).
- [ ] Storage: documents in SQLite with a JSON mirror for expression indices, WAL, and a real
      schema stamp — trap 37, *every open verifies the live schema and repairs or refuses
      loudly*. Not inherited from a house convention, because there isn't one: of the tree's
      four SQLite openers, `index/store.py` (`meta.schema_version`) and `db/local_store.py`
      (`alembic_version` + a coded revision chain) stamp, and `agent/turnlog.py` and
      `platformstore.py` do not. C6 puts a **second writer** on platformstore's file, which is
      what turns its missing stamp from survivable into load-bearing (ADR-0090).
- [ ] Query engine: the 47 measured operators. Nothing speculative — an operator with no call
      site is not built.
- [ ] Update engine: update documents, array modifiers (`$each` with a negative `$slice`
      ring buffer is real and used 5 times), the positional `$`, `$bit`, and aggregation-pipeline
      updates (2 call sites).
- [ ] Aggregation engine: the 11 measured stages and their expression operators.
- [ ] Index catalogue: unique, partial, TTL and sparse, enforced by **SQLite's own constraint
      engine** — the C1 spike already showed a duplicate arriving at mongoose as a genuine
      `MongoServerError code=11000`.
- [ ] Explain: `EXPLAIN QUERY PLAN` translated into Mongo's vocabulary. **Truthful or absent —
      emitting `IXSCAN` because a test wants to see it is a fabricated execution result and L4
      forbids it** (ADR-0090).
- [ ] **Sessions with real isolation, not just the command path.** `methods/mcpAuthority.spec.ts`
      does not merely start a transaction — it asserts `startTransaction` was called with
      `{ readPreference: 'primary', readConcern: { level: 'snapshot' }, writeConcern:
      { w: 'majority' } }`, that a session was attached to 12 queries and 2 aggregations, that
      `read`/`readConcern` were never called per-query, and that `find` was issued 7 times with
      `singleBatch: true`. Snapshot isolation is the one to design for; SQLite gives it to a
      reader inside a WAL transaction, so the mapping is natural — but it has to be the real
      thing, because the test is checking that every read in the proof saw one consistent world.

**Gate — upstream's own conformance suite, with its teeth checked before it is trusted.**
LibreChat ships FerretDB/DocumentDB compat suites in `packages/platform/data/misc/`, driven by a
URI env var and documented as runnable *"against MongoDB (for parity)"* — which is very nearly
free conformance coverage for a non-Mongo backend. Three things had to be established before
that could be a gate, and the first is disqualifying on its own:

1. **It self-skips to green.** Ten of the eleven suites open with
   `const describeIfFerretDB = FERRETDB_URI ? describe : describe.skip`. Point it at nothing and
   jest reports success having executed no assertion — the exact shape of a gate that measures
   its own absence. **The gate must assert a minimum executed-test count**, not merely exit 0.
2. **It is not a pure URI swap.** `multiTenancy.ferretdb.spec.ts` shells out —
   `execSync("docker exec ${PG_CONTAINER} psql …")` — and asserts on FerretDB's *PostgreSQL
   catalog*, which is a fact about FerretDB's internals rather than about MongoDB behaviour.
   That suite, and `sharding.ferretdb.spec.ts`, are out of scope for the Tempest store and are
   excluded by name with the reason recorded, not silently.
3. **It has no control side.** The C6.0 control ran the 66 suites under `src/`; `misc/` is
   excluded by upstream's own `testPathIgnorePatterns`, so these have never run here against
   real MongoDB either. Per trap 54, the conformance suites get their own control run first —
   otherwise a red here cannot be told from a red anywhere.

```bash
# after the control side exists and the two FerretDB-internal suites are excluded by name
FERRETDB_URI="mongodb://<uds>/tempest_conformance" \
  npx jest --config misc/ferretdb/jest.ferretdb.config.mjs
# and the gate FAILS unless the executed-test count matches the control's
```

### C6.2 — The 66 suites against the Tempest store, measured against the control

- [ ] Their suites run against `@tempest/docstore` with **no vendored file edited**: a
      Tempest-owned jest config maps `mongodb-memory-server` to a shim that boots the store and
      returns its socket URI. The specs are byte-identical to upstream.
- [ ] Every difference from the C6.0 control is either fixed or recorded as a named, reasoned
      exception. **A suite that fails in both is not a finding; a suite that fails only here is.**
- [ ] **Report the store-backed number, not the headline one.** Of the 66 suites, 44 stand up a
      server and 22 run entirely in-process — 1,803 of the 2,252 static tests exercise the store
      and **449 pass no matter what answers the wire**. "2,371 green against @tempest/docstore"
      would therefore be true and misleading on the day the store could not serve a single query.
      The number that means something is the store-backed one, and it is the one to publish.
      *(1,803 + 449 = 2,252 is the static count; the run count is 2,371 because 11 files use
      `it.each`. The split is measured statically because the runtime split needs per-suite
      reporting the control does not emit — say which is which when quoting either.)*
- [ ] Their suites join `make verify-v3` (merge contract §6 rule 4) and the CI `node` job.

### C6.3 — Redis interface, backed by an in-process LRU + SQLite (ADR-0068 §4)

- [ ] The cache interface adopted; LRU + SQLite behind it; real Redis retained as config for the
      unbuilt server mode.

### C6.4 — Migrations, and the honest replacement for "up/down parity"

**The plan's gate cannot be satisfied as written, and this is the record of why.** The tree has
four migrations and **not one has a down path** — `down`, `reverse`, `rollback` and `revert`
appear nowhere in `src/migrations/`. `tenantIndexes.ts` drops **24** named indexes across 13
collections and, though `collection.indexes()` hands it the full specs, it records only their
*names* — never the key specs or options — so it is not reversible even in principle. Six further one-way migration scripts live in
`packages/platform/config/`. Authoring reverse paths would mean editing vendored business logic,
which L27 forbids and which would put the most schema-active package in the tree permanently off
upstream.

- [ ] Replace the up/down/up gate with the two properties that are true of these migrations and
      testable: **idempotence** (running a migration twice leaves the same state as running it
      once, which three of the four specs already assert) and **store-level round trip** (a
      snapshot of the document store taken before, restored after, is byte-identical), which is
      what a "down" was actually protecting.
- [ ] Record it as an ADR-0090 amendment or a new ADR — **not** by quietly rewriting the
      checkbox.

### C6.5 — The cross-store references grow teeth

- [ ] The five declared references implemented as opaque ids; `store_check` stops reading only
      the *declaration* in `MERGE-CONTRACT.md` and starts checking it against the live store —
      which is what its own docstring says C6 is for.

**Gate (the phase's own, with one correction).** The gate line this plan shipped with —
`pnpm --filter "./packages/platform/data/**" test` — could not run, for two reasons, and **C6.0
fixed one of them.** The filter selected nothing while the package was not a workspace member;
now that it is, `pnpm --filter "./packages/platform/data/**" list --depth -1` prints
`@librechat/data-schemas@0.0.68` and the glob is fine. What remains is the script: the package's
`test` is `jest --coverage --watch`, which never exits, so a gate invoking it would hang rather
than pass or fail.

**And `test:ci` — the obvious non-watching substitute, which an earlier draft of this line
recommended — does not work either.** Measured rather than assumed:

```
$ pnpm --filter "@librechat/data-schemas" test:ci
Test Suites: 7 failed, 59 passed, 66 total
Tests:       2115 passed, 2115 total
THEIR_GATE_EXIT=1        ● Test suite failed to run
                           SyntaxError: Cannot use import statement outside a module
```

Seven suites cannot load at all, because `test:ci` runs the **vendored** `jest.config.mjs`,
whose `transformIgnorePatterns` assumes npm's flat `node_modules` (see C6.0). The runnable form
is the Tempest-owned seam config, which is what `scripts/data-control.sh` invokes:

*(Two drafts of this paragraph were wrong before this one. The first claimed the `/**` glob
still matched nothing — checked with `pnpm --filter … exec true`, which prints nothing whether
it matches or not; a test that cannot fail is not a test, and a reviewer running `list` caught
it. The second recommended `test:ci` without running it. Trap 45 twice over: a guard's argument
is not a proof of the guard.)*
```bash
# their suites, green — via the seam config; `pnpm … test` watches and `test:ci` fails to load 7
( cd packages/platform/data && npx jest --config tempest/jest.config.control.mjs --ci )
python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store
python -m tempest.dev.perf_suite --enforce-budgets         # document-store p95 row
# migration idempotence + store round-trip, output pasted (C6.4)
```

---

## Phase C7 — The conversation platform (absorbs P6, P7, P12)

- [ ] Forking, branching, edit-and-resubmit, continue. **Combined with shadow worktrees**: fork an
      agent run at any turn and **compare branches by verdict** — not "which reply do I prefer" but
      *"branch A is EQUIVALENT_UNDER_BUDGET with a 0.94 mutation score; branch B is DIVERGENT on 2
      inputs."*
- [ ] **P7 Proof Profiles**: presets extended to carry model, input budget, float tolerance, required
      mutation floor, and sandbox tier. Resolve hierarchically by directory, hot-reload, display
      precedence on conflict.
- [ ] Prompts with user and group sharing; bookmarks and tags; full-text virtualized search across
      all messages and conversations; shared conversations with stable URLs and
      continue-as-personal-copy.
- [ ] Import from LibreChat / ChatGPT / Chatbot UI. Export to markdown / JSON / text / screenshot
      — **with proof bundles attached**, so an exported session re-imports on another machine with
      every repro still runnable.
- [ ] **A runner-path field for the local model server, read HOST-side.** `resolve_runner`
      resolves from `PATH` only. Wanted by anyone whose `llama-server` is not on `PATH` — a Nix
      profile, a manual build. Two constraints on how it may arrive, both learned the hard way
      (ADR-0080 amendment): the value comes from the host's own settings store (`runners.rs`,
      the way the editor runners already do) and **never as an IPC argument** — the command
      used to take the path from its caller, and its caller is the webview, so any script
      reaching `__TAURI_INVOKE` could name an arbitrary local executable for the host to run;
      and it is written down rather than referenced as though it existed, because an earlier
      draft of the panel read a `local_model_server` field that does not exist and the seam's
      typecheck gap meant nothing caught it.
- [ ] **Per-turn steer scoping, so a steer drained into a turn that then DIED is reclaimable.**
      `_converse` drains `steer_source()` into the transcript BEFORE the model call that carries
      it, and the client's chip flips to applied at that moment. If that call then fails — an
      abort, a provider outage, a cost cap — the instruction never reached a model that could act
      on it, yet it is gone from `pendingSteers` and absent from `unrecoveredSteers`. Today its
      TEXT survives visibly as a `steer` content part on the persisted message, so nothing the
      user typed is lost from the record; what is missing is the one-click reclaim. Doing it right
      needs per-TURN scoping (an accumulated applied-list would hand back steers earlier turns
      legitimately consumed), which is why the write-only `steers_applied` field was removed
      rather than given a reader that would have been wrong. Found by the C5 close-out review; the
      two verifiers split on severity and both agreed the text is preserved.
- [ ] Resumable streams (P2) extended: the **proof stage** is checkpointed so a killed turn resumes
      without re-proving what was already proven.

**Gate:**
```bash
python -m tempest.dev.session_roundtrip --export-import --require-runnable-repros
python -m tempest.dev.resume_test --kill-mid-proof --sleep-mid-stream
# fork from any turn; both branches independently proven; side-by-side verdict comparison;
#   merge a branch back. Screenshots + pasted verdicts.
# Proof Profile precedence displayed on conflict; hot-reload verified.
```

---

## Phase C8 — Tools and execution

- [ ] **Code interpreter** (ADR-0070): Python, Node/TS, Go, C/C++, Java, PHP, Rust, Fortran; file
      upload/process/download; background code and shell execution; sandbox images returned as
      viewable artifacts. **On Tempest's tier ladder — no tier, no execution.**
- [ ] **Cassette link**: a recording made in the interpreter is replayable by the differential
      runner. This is what moves the interpreter from `PROOF_ADJACENT` toward `PROOF_NATIVE`.
- [ ] **MCP convergence** (merge contract BRIDGE→REPLACE, removal date = end of this phase): port
      LibreChat's dynamic tool refresh, parsed response media types, and runtime OAuth recovery onto
      the Python client; retire the bridge.
- [ ] Custom actions from OpenAPI specs; web search with providers, scrapers, rerankers; skills;
      plugins; subagents; scheduled runs (ADR-0073).
- [ ] **RAG, file chat, OCR** (ADR-0071), local-by-default embeddings, PII scrubbing on by default
      with a preview of exactly what was scrubbed.
- [ ] Extend `redteam --injection` to RAG chunks, file contents, OCR output, and code-interpreter
      channels. **Every retrieved byte is attacker-controlled input, never instruction.**

**Gate:**
```bash
python -m tempest.dev.escape_suite --surface code-interpreter   # all tiers, three OSes
python -m tempest.dev.redteam --injection                        # incl. RAG, OCR, interpreter, MCP
python -m tempest.dev.mcp_client_check                           # bridge retired, one client
# a cassette recorded in the interpreter replayed by the differential runner. Paste output.
```

---

## Phase C9 — Artifacts, including behavioral artifacts (absorbs P8)

- [ ] React, HTML, and Mermaid rendered inline; fullscreen preview; Mermaid export to SVG and PNG;
      `.potx` templates across upload, search, and code execution; original Office file download.
- [ ] **Behavioral artifacts** in the same renderer: call graphs, effect-sequence timelines,
      divergence tables, coverage maps, minimized-input trees — inline and interactive. **This is how
      proof evidence stops being a wall of JSON.**
- [ ] Sandboxed renderer, strict CSP, no arbitrary network. Every artifact exportable into a run
      bundle.

**Gate:**
```bash
python -m tempest.dev.escape_suite --surface artifact-renderer
python -m tempest.dev.perf_suite --enforce-budgets         # artifact first render row
# every artifact type exports into a run bundle and re-renders from it. Paste output.
```

---

## Phase C10 — The overturned features + platform completion

- [ ] **Image generation** (ADR-0063): GPT-Image-1, DALL·E 3/2, Stable Diffusion, Flux, MCP image
      servers. EXIF and geolocation stripped before any provider call, test-verified.
- [ ] **Speech** (ADR-0065): STT and TTS via OpenAI, Azure OpenAI, ElevenLabs; automatic send and
      playback; local STT path available. **Verdicts are never spoken as prose.**
- [ ] **Marketplace** (ADR-0066): community agents, skills, plugins, discovery, group sharing —
      with capability declaration and **signature verification** required for anything requesting
      file-write, shell, or network.
- [ ] **Admin panel** (ADR-0072): users, groups, roles, live config overrides, delegated config
      sections, encrypted registered secrets. Gates team features only. **Cannot disable the proof
      gate.**
- [ ] Multi-user auth: OAuth2, LDAP, email. Moderation, token spend tracking, balances, quotas.
      Langfuse with encrypted connections and per-tenant fan-out — off by default.
- [ ] Multimodal input, memory with per-agent isolation, insights, SSRF checks on speech/OCR/web
      tools, configurable HTTP timeouts.
- [ ] Build `tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform`.

**Gate:**
```bash
python -m tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform
python -m tempest.dev.redteam --gate-subversion
# adversarial: an UNSIGNED capability-requesting agent must FAIL to install. Paste the refusal.
# adversarial: an admin attempting to disable the proof gate must find no such path. Paste.
# LDAP against a real directory; airplane mode = full local function, zero auth prompts.
# EXIF + geolocation stripped, test-verified. Paste.
```

---

## Phase C11 — i18n across the merged surface (ADR-0074)

- [ ] All 44 locales adopted wholesale; Tempest strings added as new keys in the same pipeline.
- [ ] Every verdict, every `reason_code` explanation, every `UNPROVEN` blocking reason translatable.
      **A verdict a user cannot read is not evidence.**
- [ ] Zero hardcoded user-facing strings, lint-enforced across both trees.
- [ ] Pseudo-locale for truncation and layout breakage; RTL verified, not assumed.
- [ ] Untranslated Tempest keys fall back to English with a visible dev marker, silent in production
      — never a raw key in front of a user.

**Gate:**
```bash
python -m tempest.dev.i18n_check --no-hardcoded-strings --pseudo-locale --rtl   # both trees
```

---

## Phase C12 — Convergence hardening + GA *(never cut)*

- [ ] **Performance campaign.** Every §10 budget met on the 4-core/16 GB profile against a 500k-LOC
      repo and a 10k-conversation history. CI perf gate on every PR. Public perf dashboard live.
- [ ] **Craft campaign.** All 150 `docs/POLISH.md` items verified on macOS, Windows, Linux with
      screenshots. Visual regression across every view × 2 themes × 3 viewports × 2 densities.
      Motion-interrupt suite: every animation interrupted at 50%, clean settle. **CLS = 0** on every
      view. a11y audit at WCAG 2.2 AA with VoiceOver and NVDA recordings attached. The screenshot
      test: any view legible and self-explanatory alone.
- [ ] **Red team.** 50+ injection, 20+ exfiltration, 15+ gate-subversion, covering the code
      interpreter, RAG, marketplace, MCP, and boundary E.
- [ ] **External security review** before GA.
- [ ] **Upstream merge rehearsal, executed for real.** `make upstream-merge && make verify-v3` green
      against a live upstream LibreChat commit. Not a dry run.
- [ ] **Parity ledger at 100%.** Every LibreChat capability `ADOPTED` with a verifying test that ran
      green. README publishes the number.
- [ ] **30-day dogfood.** Crash-free session rate ≥ 99.9%; agent turn failure rate ≤ 0.5%.
      Tempest proves its own PRs with Tempest, gated in CI; the Tempest-on-Tempest proof rate
      published in the README (L24).

**Gate:**
```bash
make verify-v3                                                    # complete, exit 0
python -m tempest.dev.parity_ledger --require-100-at-ga --print-percentage
python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete
python -m tempest.dev.redteam --injection --exfiltration --gate-subversion
python -m tempest.dev.perf_suite --enforce-budgets
python -m tempest.dev.a11y_audit --wcag 2.2 --level AA
python -m tempest.dev.dogfood --prove-own-pr
pnpm test:visual-regression --themes 2 --viewports 3 --densities 2
pnpm test:motion-interrupt
```

---

## Interleaving with phases 24–32

Phases 24–27 remain live in `docs/PLAN-V2.md` and are **the proof half of the product**. Cutting them
turns this into a chat app with a defensible README.

```
C0 → C1 → C2 → C3 → C4 → C5 ┬→ C6 → C7 → C8 → C9 → C10 → C11 → C12
                             │
                             └→ 24  F9 adversarial self-validation · F10 cassette-to-suite
                                25  F7 de-slop · F8 proven dead code · F6 migration agent
                                26  F18 ambient regression watch · F17 agent fleet
                                27  F5 semantic merge · F19 time-travel debugger ·
                                    F20 team KB · F21 model arena
```

- Phases 24–27 may run in parallel with C6–C11 **only after C5 lands.**
- Phases **28 and 29 are absorbed**: P6/P7/P12 → C7, P8/P13 → C9, P10 → C10, P14 → C11.
- Phases **30, 31, 32 merge into C12** and are never cut.
- Phase 3's TypeScript **execution** half is a C0 item and blocks any parity claim that includes
  TypeScript proving.

---

## New gate modules to be built, and where

| Module | Phase | Law |
|---|---|---|
| `upstream_check` | C1 | L27 |
| `store_check` | C1 | L33 |
| `egress_check --platform-tree` (extension) | C3 | L32 |
| `vocab_check` | C3 | L31 |
| `runtime_check` | C5 | L29 |
| `gate_audit` | C5 | L28 |
| `feature_ledger` | ~~C10~~ **C5** | L30 |
| `parity_ledger` | ~~C12~~ **C5** | L35 |

> **Both pulled forward to C5 on 2026-08-24 (ADR-0088).** `docs/FEATURES-V3.md` opens by
> calling itself machine-read and naming these two modules as its readers. Neither existed,
> so for five phases C5's completeness was asserted rather than measured — and the first run
> of `feature_ledger` against the real tree found the ledger wrong in both directions.
> Building the instrument at C10/C12 would have meant three more phases of unmeasured rows.

**Also not built yet — inherited from the v2 plan, and this plan uses them in gates.** Verified
absent from `tempest/dev/` on 2026-08-21: `mutation_bench`, `deadcode_trap`, `migration_bench`,
`session_roundtrip`, `i18n_check`, `a11y_audit`, `dogfood`. Each is built by the phase that first
needs it — `session_roundtrip` in C7, `i18n_check` in C11, `a11y_audit` and `dogfood` in C12, and
the remaining three in phases 24–25. **Writing the benchmark is part of the phase.** Do not paste a
gate command into a report before you have made it runnable and watched it run.

Plus extensions to existing modules: `license_check --platform-tree` (C1),
`orphan_check --all-children --after-sigkill` (C2), `provider_matrix --min-providers 16` (C4),
`escape_suite --surface code-interpreter|artifact-renderer` (C8, C9),
`redteam` new channels (C8, C10), `perf_suite` new rows (C1 onward),
`i18n_check` both trees (C11).
