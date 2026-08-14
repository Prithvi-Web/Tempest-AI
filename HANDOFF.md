# HANDOFF — read me first

**What this is:** Tempest AI, a behavioral proof agent — it *executes* diffs (base vs head under
identical deterministic conditions) and reports divergences with minimized, runnable evidence.
Built from `tempest-master-prompt.md` (the v1 contract) on 2026-08-13; the desktop/enterprise
era is governed additionally by the Phase 8+ master prompt (Laws L8–L14 + tri-boundary contract,
both now in `CLAUDE.md`). Phase status with REAL gate outputs: v1 in `docs/PLAN.md`, desktop in
`docs/PLAN-DESKTOP.md`; the Phase 8 truth audit is `docs/AUDIT-PHASE8.md`; the three company
numbers live in `docs/METRICS.md`; every deviation is an ADR in `docs/DECISIONS.md`.

## Status at a glance (2026-08-13)

| Phase | Status | Gate evidence |
|---|---|---|
| 0 Skeleton | ✅ | `make verify` green from clean clone; live browser smoke test |
| 1 Pure-fn differential (Py) | ✅ | pyfix: **12/12 caught, 0 false positives**, minimized repros; 3.9 s for a 5-target PR (target <60 s) |
| 2 Determinism layer | ✅ | corpus_check: **30/30 stable ×5** (bar ≥24); flake hunt **30/30 ×20** (`docs/flake-hunt-20x.log`) |
| 3 TypeScript | 🔶 analysis sidecar ✅ (27+6 tests); execution half open | Node worker + TS shims + corpora remain |
| 4 API + persistence | ✅ core | 33 tests incl. Hypothesis round-trip gate; arq/SSE/MinIO/auth open |
| 5 Web dashboard | ✅ views (live-verified in browser) | Playwright E2E + SSE timeline + repo-settings open |
| 6 CI integration | ✅ code | live-PR gate needs GitHub publish (ADR-0005); selftest workflow rehearses it |
| — Desktop app | ✅ Tempest.app (Phase 9 architecture) installed to /Applications: stdio JSON-RPC sidecar (zero listening sockets, verified), supervised process group, typed tri-boundary contracts | rebuild: ./packages/desktop/build-server.sh then pnpm tauri build (in packages/desktop) |
| 7 Hardening | 🔶 | flake hunt ✅, schema-migration tests ✅, `SANDBOX_REVIEW.md` ✅ (container leg needs a Docker machine), perf ✅ 3.9 s |
| **8 Truth Audit** | ✅ 2026-08-13 | `docs/AUDIT-PHASE8.md` — clean-clone verify green, 30/30×20 fresh, byte-identical bundle diffs, 8/8 reason codes emittable, **3 honesty defects found & fixed test-first** (blessed-with-zero-comparable-inputs, EnvRepro traceback, silent .ts skip); proof rate: fixture 100%, real-world unmeasured (stated plainly) — see `docs/PLAN-DESKTOP.md`, ADR-0011..0013, `docs/METRICS.md` |
| **9 Desktop Shell Migration** | ✅ core 2026-08-14 (owner said go) | `packages/desktop`: stdio JSON-RPC Boundary A (no TCP anywhere, `lsof`-verified), typify + tauri-specta generated tri-boundary types with drift gate, owned-pgroup supervisor w/ crash restart, five views on typed bindings, **Next.js web package deleted** (ADR-0014). Gates: contract zero-drift · Rust 10/10 · roundtrip **10000/10000** · cli-vs-desktop parity **byte-identical** (gate caught + fixed a real frozen-runtime generation bug) · SIGKILL orphan **2.7 s**. Open: desktop Playwright E2E, clean-VM leg |

## Run it

```bash
make sync                      # uv + pnpm install
make verify                    # every live gate incl. the 30-fn determinism corpus
TEMPEST_DEV=1 uv run tempest prove --base <ref> --head <ref> --repo <path>
uv run tempest ci-comment --bundle <bundle-dir>        # GFM PR comment
uv run python -m tempest.dev.corpus_check --min-pass 24 --repeats 5
uv run python corpus/fixtures/pyfix/make_fixture.py /tmp/pyfix   # the Phase 1 fixture repo
```

## Traps (standalone — don't relearn these)

1. **No Docker on this machine.** User repos → `UNPROVEN(SANDBOX_UNAVAILABLE)` by design (Law
   L6, ADR-0003). First-party fixtures run via ProcessSandbox ONLY with the repo marker file +
   `TEMPEST_DEV=1` (ADR-0008). Never weaken this.
2. **The worker is stdlib-only** (`execute/_worker.py`): it runs where tempest isn't installed;
   `canonical.py` and `_shims.py` are copied into scratch beside it. Anything it imports must
   stay stdlib.
3. **Shims must install BEFORE target import** (from-import binding capture) — the import
   session rides in every cassette under `"import"`. Shim-internal machinery must never touch
   the ledger (`_internal()` passthrough).
4. **The string S‑A‑F‑E must never appear in product surfaces** (Law L2) — CI greps for it.
5. **PLAN.md checkboxes flip only with real gate output pasted.** Claimed-passing is failing.
6. **`git diff --exit-code` on generated files** (shared-schema, web/src/generated) is a CI
   gate — always run `pnpm gen:api` after touching API schemas and commit the outputs.
7. **BYOK guarantee:** no API key ships anywhere; the optional LLM synthesis path activates only
   on the end user's own `ANTHROPIC_API_KEY` (ADR-0006). The owner never pays for runs.
8. Coverage bar is 85%; `determinism/*` is temporarily omitted from measurement while Phase 2/3
   iterate (its behavior is pinned by execution tests) — remove the omit when things settle.

## Publish to GitHub (owner's step — GitHub Desktop)

1. Open GitHub Desktop → File → **Add Local Repository** → choose `Desktop/Claude Code/tempest`.
2. **Publish repository** (pick the visibility you want).
3. After publish: open a PR with any seeded change to run `tempest-selftest.yml` — that is the
   Phase 6 live gate.
