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

Six files carrying LibreChat's own visual identity were **replaced in place** (same filenames,
so upstream references — e.g. `AuthLayout.tsx`, `index.html` — stay valid and every future
upstream change to these files surfaces as a merge conflict to resolve by keeping ours). At C1
they became neutral placeholders; the identity pass (commit `aa565ee`) re-cut every one from
the Tempest storm-glass mark (`packages/desktop/app-icon.svg`):

| File (under `packages/platform/client/public/assets/`) | Action |
|---|---|
| `logo.svg` | replaced — the Tempest mark (bolt on a navy squircle) |
| `favicon-16x16.png` | replaced — Tempest mark 16×16 |
| `favicon-32x32.png` | replaced — Tempest mark 32×32 |
| `apple-touch-icon-180x180.png` | replaced — Tempest mark 180×180 |
| `icon-192x192.png` | replaced — Tempest mark 192×192 |
| `maskable-icon.png` | replaced — Tempest mark 512×512 |

Third-party **provider** logos (openai.svg, mistral.png, …) are other vendors' marks used
nominatively to label providers; they are not LibreChat trade dress and are retained unmodified.
**Text-level identity** (the `<title>LibreChat</title>` and description in `client/index.html`,
in-UI product-name strings) is deliberately deferred to C3's identity restyle, where every
name surface is replaced as one reviewed pass — the client is not built, bundled, or shipped
before C3, so no LibreChat-branded surface can reach a user in the interim.

## Inline-delta ledger

Every in-place edit to vendored code that is **not** inside a `packages/platform/*/tempest/`
seam directory. Cap enforced by `upstream_check --max-inline-deltas 40`. Hitting the cap means
seams are being skipped — stop. (The six brand-asset files were invisible here while their
placeholder bytes matched the vendor baseline; the identity pass made them real divergences,
so they carry rows like any other in-place edit.)

| Path | Reason | Upstream issue |
|---|---|---|
| `packages/platform/client/public/assets/logo.svg` | brand identity: the Tempest mark replaces upstream's logo (trademarks are not MIT-licensed); every upstream change resolves as keep-ours | — |
| `packages/platform/client/public/assets/favicon-16x16.png` | brand identity, as above | — |
| `packages/platform/client/public/assets/favicon-32x32.png` | brand identity, as above | — |
| `packages/platform/client/public/assets/apple-touch-icon-180x180.png` | brand identity, as above | — |
| `packages/platform/client/public/assets/icon-192x192.png` | brand identity, as above | — |
| `packages/platform/client/public/assets/maskable-icon.png` | brand identity, as above | — |
| `packages/platform/provider/tsdown.config.mjs` | upstream requires the monorepo ROOT package.json (deliberately not vendored) for `__LIBRECHAT_VERSION__`; retargeted to `../client/package.json`, which tracks the same upstream release (v0.8.8-rc1 at adoption — verify at every upstream merge) | — |
| `packages/platform/client/tailwind.config.cjs` | the C1 tree mapping renames upstream `packages/client` → `client-pkg`; three sibling-relative requires/globs retargeted | — |
| `packages/platform/client/tsconfig.json` | same rename: two include entries retargeted to `../client-pkg` | — |
| `packages/platform/client/src/routes/index.tsx` | C3 absorption: one lazy loader + one `tempest/*` route entry mounting the seam subtree (`client/tempest/views`) — the router's entire knowledge of the absorbed proof surface | — |
| `packages/platform/client/src/hooks/Nav/useUnifiedSidebarLinks.ts` | C3 absorption: one nav link (`Tempest`, insights-link pattern) reaching the seam subtree. Extended by ADR-0082 with a second: **Models**, which opens the app's one settings home on its Models tab — the owner's "download local models on the vertical navigation bar". Both titles are real locale keys as of that ADR | — |
| `packages/platform/client/src/components/UnifiedSidebar/ExpandedPanel.tsx` | upstream defect: `onClick={toggleClick}` hands the pointer event to `onCollapse(afterSlide?)`, and `useSidebarToggle` calls it on every non-'slide' (desktop) path — uncaught TypeError per collapse click; wrapped zero-arg | worth filing upstream |
| `packages/platform/client/src/components/UnifiedSidebar/ExpandedPanel.tsx` | brand identity: one `<img>` (the Tempest mark, `/assets/logo.svg`) at the rail's top — upstream ships no brand slot in this rail and the seam CSS cannot add an accessible image; second delta in this file, kept beside the zero-arg fix | — |
| `packages/platform/client/src/components/UnifiedSidebar/__tests__/ExpandedPanel.spec.tsx` | the unit pin for the brand-mark delta above (alt text, served src, draggable=false); joins `make verify-v3` when the vendored client suites are wired at C6 — until then the enforced pin is e2e spec 21 | — |
| `packages/platform/client/src/hooks/SSE/useResumableSSE.ts` | C5 (ADR-0078): one import + one constructor indirection — inside the desktop app the SSE transport is the boundary-B seam (`tempest/stream/TempestSSE`, interface-identical to sse.js, gated on the host-injected marker); the harness and server mode keep sse.js untouched. The tempest:// protocol cannot stream (wry's one-shot responder), so this is the client's entire knowledge of the app transport | — |
| `packages/platform/client/src/components/Chat/Messages/Content/Part.tsx` | C5 (ADR-0080 §8): one import + one branch — an in-band error part may carry a machine-readable `remedy`, and the only one that exists offers the local-model way out of a keyless turn. Both the narrowing (`hasLocalModelRemedy`, `unknown` in) and the affordance live in the seam, so this file gains no knowledge of the shape; the alternative was the client matching on the error PROSE, which breaks whenever the prose improves | — |
| `packages/platform/client/src/locales/en/translation.json` | ADR-0082 (one settings home): 16 `com_tempest_*` keys — the two new tabs, their six sections, their seven entries, and a real key for the rail's Tempest link (`NavLink.title` is `TranslationKeys`, and the raw string there had been an invisible type error since C3). Inserted in the file's own alphabetical order as a contiguous block, so an upstream key added anywhere else merges without touching ours. The other 43 locales fall back to English until C11 | — |
| `packages/platform/client/src/components/Nav/Settings/types.ts` | ADR-0082: the settings dialog is registry-driven, which is the extension point this needed — one `import`, `SettingsTab` widened by the seam's `TempestSettingsTab`, `SectionId` widened by six literals, and `...TEMPEST_SETTINGS_TABS` APPENDED to `TABS` (appended, so an upstream tab inserted mid-list merges without touching our row) | — |
| `packages/platform/client/src/components/Nav/Settings/registry.tsx` | ADR-0082: one import and `...TEMPEST_SETTINGS_ENTRIES` appended to `registry`; plus the three provider-key entries re-addressed from the Data tab to the Models tab (two fields each, their components untouched) so local models and API keys are one decision in one place — the owner's requirement. The now-empty `apiKeys` section is deliberately LEFT in the Data tab's meta: `Content.tsx` renders nothing for an empty section, and removing it would silently swallow an entry upstream adds there later | — |
| `packages/platform/client/src/components/Nav/Settings/Dialog.tsx` | ADR-0082: one import and a four-line effect — the dialog's active tab honours a request from the seam, so the rail, the proof surface and the keyless-turn remedy can open the home ON A TAB. An effect rather than a `useState` initializer because the request can arrive while the dialog is already open | — |
| `packages/platform/client/src/components/Nav/AccountSettings.tsx` | ADR-0082: one import and the dialog's open state ORed with the seam's request (and cleared on close). Upstream owns that state in a local `useState` here, so nothing outside this component could ask for settings at all; two lines here beat threading a prop through three components | — |
| `packages/platform/provider/src/schemas.ts` | ADR-0083: one field in `defaultAgentFormValues` (`tempest_repo`). It has to be in the DEFAULTS and not only on the type — `AgentSelect`'s repopulate-on-edit filters incoming agent fields through `new Set(Object.keys(defaultAgentFormValues))`, so a field missing here renders empty over a stored value and the next save erases it (mutation-proven) | — |
| `packages/platform/client/src/common/agents-types.ts` | ADR-0083: `tempest_repo?: string \| null` on `AgentForm` — the repository a tool-bearing agent's tools work in | — |
| `packages/platform/client/src/components/SidePanel/Agents/AgentPanel.tsx` | ADR-0083: `tempest_repo` destructured and carried in `composeAgentUpdatePayload`. That composer is a WHITELIST, so a field the form holds and it does not name is dropped silently on every save — invisible from the form alone (mutation-proven) | — |
| `packages/platform/client/src/components/SidePanel/Agents/AgentConfig.tsx` | ADR-0083: two imports and two elements — the seam's `RepositoryField`, rendered directly under the tools because it is the thing they act on, and `ProofAgentPreset`, a blank-slate shortcut that renders nothing once the person has made any decision of their own | — |
| `packages/platform/client/src/components/UnifiedSidebar/UnifiedSidebar.tsx` | ADR-0084: one import and a generalised boolean — upstream already collapses the conversations panel on `/insights` because that route owns the width, and the proof surface owns it the same way. Without this the window carried THREE nav columns in the proof surface (icon rail · "Projects / Chats" · the proof surface's own sidebar) and the middle one applied to nothing on screen. `routeActiveId` is lifted out of the two inline ternaries at the same time | — |
| `packages/platform/client/src/components/UnifiedSidebar/ExpandedPanel.tsx` | ADR-0084: the rail's active entry follows the ROUTE on a full-width route, not the panel's own active section — standing in the proof surface used to highlight "Chats". Fourth delta in this file, beside the zero-arg collapse fix and the brand mark | — |
