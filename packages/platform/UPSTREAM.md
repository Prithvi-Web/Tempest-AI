# UPSTREAM — the LibreChat vendoring ledger

> Machine-read by `python -m tempest.dev.upstream_check` (L27). This file is the single record of
> what was adopted, from where, and every deliberate delta between this tree and upstream. It is
> itself exempt from the drift check, as are the `packages/platform/*/tempest/` seam directories.

- **Upstream repository:** https://github.com/danny-avila/LibreChat
- **Upstream licence:** MIT (`packages/platform/LICENSE`, vendored verbatim from the adopted commit)
- **Adopted commit:** d602452c05ed767315a753264f02368c10f31e19
- **Adopted date:** 2026-08-21 (upstream commit of the same day: "🪪 fix: Support MCP Server Titles With Hyphens (#15094)")
- **Vendor baseline:** ec1e9e05830d22caebb4dc77e4861f74db051272 — the vendoring commit in THIS repository, against which
  `upstream_check` diffs `packages/platform/**`. It moves only on a vendoring or upstream-merge
  commit.

## Tree mapping (upstream path → this repository)

Directory structure and module boundaries are preserved *within* each tree (L27); the top-level
names follow the master prompt §3.2. `packages/platform/client-pkg/` is upstream's
`packages/client` (their shared UI package) — vendored at the same commit because
`client/` imports it, and skew between the two halves of one client would be a merge hazard.

| Upstream path | Vendored path | Disposition (docs/MERGE-CONTRACT.md) |
|---|---|---|
| `api/` | `packages/platform/server/` | per-subsystem rows, "Server tree" |
| `packages/api/` | `packages/platform/api/` | per-domain rows, "Shared API package" |
| `packages/data-schemas/` | `packages/platform/data/` | VENDOR, byte-for-byte |
| `packages/data-provider/` | `packages/platform/provider/` | VENDOR |
| `client/` | `packages/platform/client/` | VENDOR+SEAM (restyle is C3, via tokens) |
| `packages/client/` | `packages/platform/client-pkg/` | VENDOR ("Other trees": shared contracts) |
| `e2e/` | `packages/platform/e2e/` | VENDOR (suite joins `make verify-v3` from C6) |
| `config/` | `packages/platform/config/` | VENDOR+SEAM |
| `search/` | `packages/platform/search/` | VENDOR+SEAM |
| `otel/` | `packages/platform/otel/` | VENDOR+SEAM (off by default, provably inert — L32) |
| `redis-config/` | `packages/platform/redis-config/` | VENDOR+SEAM |
| `skill/` | `packages/platform/skill/` | VENDOR+SEAM |
| `LICENSE` | `packages/platform/LICENSE` | travels with the vendored work |

**Deliberately not vendored** (no MERGE-CONTRACT row; fetchable at the adopted SHA if a later
phase needs them): `helm/` (server-mode deployment), `scripts/`, `utils/` (their repo tooling),
`src/` (an upstream OIDC integration test stub), root docker/compose files, root README/docs.
`rag_api` is a separate repository and is NOT adopted (review-first rule, MERGE-CONTRACT).

## Merge procedure (`make upstream-merge`)

Quarterly, gated, rehearsed for real in C12 (L27). Last executed: never (first vendoring).

1. `git -C <scratch> clone https://github.com/danny-avila/LibreChat && git checkout <new-sha>`
2. For each row of the tree mapping: three-way merge upstream `<old-sha>..<new-sha>` onto the
   vendored path (`git diff <old-sha> <new-sha> -- <upstream path>` applied with `git apply
   --3way` after path rewriting, or a `git subtree`-style pull once wired into the Makefile).
3. Re-apply the brand-asset strip list below to any re-introduced brand file.
4. Update **Adopted commit** above; the merge commit becomes the new **Vendor baseline**.
5. `make verify-v3` (until it exists: `make verify` + the C-phase gates that are live).

## Brand-asset strip (performed in the vendoring commit — MIT does not license trademarks)

Six files carrying LibreChat's own visual identity were **replaced in place with neutral
Tempest-placeholder images** (same filenames, so upstream references — e.g. `AuthLayout.tsx`,
`index.html` — stay valid and every future upstream change to these files surfaces as a merge
conflict to resolve by keeping ours):

| File (under `packages/platform/client/public/assets/`) | Action |
|---|---|
| `logo.svg` | replaced — neutral placeholder mark |
| `favicon-16x16.png` | replaced — neutral 16×16 |
| `favicon-32x32.png` | replaced — neutral 32×32 |
| `apple-touch-icon-180x180.png` | replaced — neutral 180×180 |
| `icon-192x192.png` | replaced — neutral 192×192 |
| `maskable-icon.png` | replaced — neutral 512×512 |

Third-party **provider** logos (openai.svg, mistral.png, …) are other vendors' marks used
nominatively to label providers; they are not LibreChat trade dress and are retained unmodified.
**Text-level identity** (the `<title>LibreChat</title>` and description in `client/index.html`,
in-UI product-name strings) is deliberately deferred to C3's identity restyle, where every
name surface is replaced as one reviewed pass — the client is not built, bundled, or shipped
before C3, so no LibreChat-branded surface can reach a user in the interim.

## Inline-delta ledger

Every in-place edit to vendored code that is **not** inside a `packages/platform/*/tempest/`
seam directory and not a row of the brand-asset strip above. Cap enforced by
`upstream_check --max-inline-deltas 40`. Hitting the cap means seams are being skipped — stop.

| Path | Reason | Upstream issue |
|---|---|---|
| *(none)* | — | — |
