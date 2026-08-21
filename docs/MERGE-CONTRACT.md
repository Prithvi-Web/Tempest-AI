# The Merge Contract — subsystem-by-subsystem dispositions

> Normative. Source: `TEMPEST-V3-MASTER-PROMPT.md` §6. Legal record: `THIRD_PARTY_LICENSES.md`.
> Laws: `CLAUDE.md` L27–L36.
>
> **This file is the answer to "what do I do with this LibreChat directory?"** Every subsystem has
> exactly one disposition. If you are about to touch a LibreChat path that is not listed here, stop
> and add the row first — with an ADR if the disposition is `PORT` or `REPLACE`.

---

## The five dispositions

| | Meaning | Upstream mergeability | Requires ADR |
|---|---|---|---|
| **VENDOR** | Copied unmodified into `packages/platform/`; integrated only at declared seams | Full | No |
| **VENDOR+SEAM** | Vendored, plus `packages/platform/<pkg>/tempest/` holding integration code | High | No |
| **PORT** | Re-implemented in Tempest's stack because a law forbids adopting as-is | None | **Yes** |
| **REPLACE** | Tempest's implementation wins; LibreChat's surface re-targets onto it | None for that path | **Yes** |
| **BRIDGE** | Both survive behind one interface, with a dated removal plan | Temporary | **Yes**, with a removal date |

**Default is VENDOR.** Every deviation costs upstream mergeability, which L27 says is a shipped
feature. If you find yourself assigning `PORT` more than a handful of times, the architecture is
wrong, not LibreChat.

---

## Server tree — `api/` → `packages/platform/server/`

| LibreChat path | Disposition | Notes |
|---|---|---|
| `api/server/routes/**` | VENDOR | 35+ route modules. Untouched. Mounted behind boundary E instead of a TCP listener. |
| `api/server/controllers/**` | VENDOR | |
| `api/server/middleware/**` | VENDOR+SEAM | Auth middleware gains a seam: local single-user mode short-circuits to an implicit local principal. **Never** a bypass flag — a distinct code path with its own tests (L32). |
| `api/server/services/Agents/**` | **REPLACE** | ADR-0075. Thin client over boundary E to the Python orchestrator. The largest and most painful row in this table; accepted knowingly. |
| `api/server/services/ToolService.js`, `Tools/**` | **REPLACE** | Unifies with `agent_tools.rs` (boundary D). That file stays the root of truth for capability declarations and approval invariants. |
| `api/server/services/Endpoints/**` | **REPLACE** | ADR-0076. Config schema and model-spec metadata adopted; routing delegates to `tempest/inference/`. |
| `api/server/services/Files/**` | VENDOR+SEAM | Storage seam redirects S3/CloudFront addressing to local content-addressed storage; cloud remains a config option. |
| `api/server/services/Artifacts/**` | VENDOR+SEAM | Seam adds behavioral artifact types (call graphs, effect timelines, divergence tables, coverage maps, minimized-input trees) to the same renderer. |
| `api/server/services/MCP.js`, `initializeMCPs*` | BRIDGE → REPLACE by C8 | Tempest has a gated MCP client (ADR-0060). LibreChat has richer lifecycle (dynamic refresh, OAuth recovery, media-type parsing). Bridge during C8, converge on the Python client with LibreChat's lifecycle features ported. **Removal date: end of C8.** |
| `api/server/services/Runs/**`, `Threads/**` | VENDOR+SEAM | Run records gain a nullable `bundle_id` cross-store reference (L33: opaque id, never a join). |
| `api/server/services/Schedules/**` | VENDOR+SEAM | ADR-0073. Every scheduled run journalled, budgeted, reversible, proof-gated identically to an interactive run. |
| `api/server/services/Skills/**` | VENDOR+SEAM | Seam adds Proof Skills (P3): declared intent contracts, mutation floors, forbidden divergence classes — engine-enforced, not prompt text. |
| `api/server/services/AuthService.js`, `strategies/**` | VENDOR+SEAM | OAuth2 / LDAP / email adopted whole. Seam enforces L32: gates team features only, never local operation. |
| `api/server/services/Config/**` | VENDOR+SEAM | `librechat.yaml` adopted. Seam merges `tempest.toml` precedence (CLI flag > file > default) without a second config system. |
| `api/server/services/PermissionService.js`, `acl` | VENDOR | ACL adopted whole. **An admin cannot disable the proof gate** — L28 is structural, not a permission. |
| `api/models/**`, `api/db/**` | VENDOR | Mongoose access layer. Untouched — that is the point of §5.4. |
| `api/cache/**` | VENDOR+SEAM | Redis interface adopted; backed by in-process LRU + engine SQLite in desktop mode. Real Redis stays a config option. |
| `api/server/telemetry.js`, `otel/`, `rum`, `insights`, `langfuse` | VENDOR+SEAM | **Off by default and provably inert** (L32). Each gets an independent `egress_check` case. |

## Shared API package — `packages/api/` → `packages/platform/api/`

| Domain | Disposition | Notes |
|---|---|---|
| `agents/`, `flow/` | REPLACE (surface VENDOR) | Per ADR-0075. |
| `endpoints/`, `modelSpecs/` | REPLACE (schema VENDOR) | Per ADR-0076. |
| `mcp/` | BRIDGE → REPLACE by C8 | As above. |
| `artifacts/`, `html/` | VENDOR+SEAM | |
| `memory/` | VENDOR+SEAM | Per-agent isolation adopted. Memory is `PROOF_ADJACENT` — it may carry proof context, never write a verdict (L31). |
| `skills/`, `plugins/`, `apiKeys/` | VENDOR+SEAM | Marketplace installs gated by capability signing (ADR-0066). |
| `auth/`, `oauth/`, `acl/`, `admin/` | VENDOR | |
| `credentials.ts`, `crypto/` | **REPLACE** | Tempest's OS-keychain path wins (L18, `keychain.rs`). No plaintext key storage, ever, no exceptions for "just the dev build". |
| `files/`, `storage/`, `cdn/` | VENDOR+SEAM | Local content-addressed storage seam. |
| `conversations/`, `prompts/`, `projects/`, `favorites/`, `shared-links/` | VENDOR | |
| `stream/` | VENDOR+SEAM | Resumable streams (P2) adopted; seam checkpoints the **proof stage** so a killed turn resumes without re-proving what was already proven. |
| `schedules/` | VENDOR+SEAM | ADR-0073. |
| `cluster/` | VENDOR (dormant) | Server-mode only. Keep, do not maintain, do not let it drive a decision. |
| `insights/`, `telemetry.ts`, `langfuse/`, `rum/` | VENDOR+SEAM | Off by default, provably inert. |
| `middleware/`, `cache/`, `db/`, `app/`, `config/` | VENDOR | |

## Data layer — `packages/data-schemas/` → `packages/platform/data/`

| Path | Disposition | Notes |
|---|---|---|
| `models/`, `methods/`, `schema/`, `types/`, `admin/` | **VENDOR, byte-for-byte** | The entire §5.4 decision exists to make this row possible. Mongoose talks a wire protocol; it does not know what answers. |
| `migrations/` | VENDOR | Must run green against the selected store. Up/down parity test is a C6 gate. |
| *(fallback path only)* adapter over engine SQLite | PORT | Engages only if the C1 spike misses a §10 budget by >25%. If taken, this becomes the most important row in `UPSTREAM.md`'s delta ledger. |

## Client — `client/` → `packages/platform/client/`, mounted as the desktop webview

| Path | Disposition | Notes |
|---|---|---|
| `client/src/components/**` | VENDOR+SEAM | All ~30 domains adopted. Restyled into Tempest's identity in C3 via token substitution, **not** by rewriting components. |
| `client/src/components/ui/**` | VENDOR+SEAM | The design-token layer is the seam. One identity, not two (master prompt §12). |
| `client/src/store/**` | VENDOR | **Upstream already ships both Recoil 0.7 and Jotai 2.12.** Adopt both as they stand; do not "tidy" them into one during C3 — that is a large in-place edit to actively developed code for zero user benefit (L27). What C3 *does* forbid is a **third**: Tempest's existing view state migrates into the existing two, and the master prompt's "one store" rule means one *state layer*, not one library. If upstream consolidates later, take it from upstream. |
| `client/src/routes/**` | VENDOR+SEAM | One router. Tempest routes (Evidence, Composer, Editor, Runs, Divergence) added as first-class entries, not a nested app. |
| `client/src/data-provider/**` | VENDOR+SEAM | React-query bindings adopted; Tempest endpoints served through the same generated-client discipline (no raw `fetch` — ESLint enforced). |
| `client/src/locales/**` (44) | VENDOR | Adopted wholesale (ADR-0074). Tempest's verdict vocabulary and every `reason_code` explanation added as new keys — a verdict a user cannot read is not evidence. |
| `client/src/hooks/**`, `Providers/**`, `a11y/**`, `utils/**` | VENDOR | |
| `client/public/assets/**` | **STRIP** | Logos, wordmarks, favicons, brand imagery removed in the vendoring commit so they are never in the tree. MIT does not license trademarks. |
| Tempest `packages/desktop/src/views/**`, `editor/**`, `vocabulary.tsx` | **MERGE IN** | Absorbed into the platform client. `vocabulary.tsx` is the reserved-verdict rendering layer and is the enforcement point for L31. |

## Other trees

| Path | Disposition | Notes |
|---|---|---|
| `e2e/` | VENDOR | Their Playwright suite runs in `make verify-v3` (§6 rule 4). |
| `config/`, `search/`, `redis-config/`, `skill/` | VENDOR+SEAM | |
| `packages/data-provider/`, `packages/client/` | VENDOR | Shared contracts; consumed by both trees. |
| `rag_api` (separate repo) | **REVIEW FIRST** | Its own licence. Review independently, record the review, then decide. Do not vendor on the assumption it is MIT. |

---

## Declared cross-store references (L33)

Proof data lives in engine SQLite. Platform data lives in the document store. These are the **only**
permitted references between them, all by opaque id, never by join:

| From | Field | To | Nullable |
|---|---|---|---|
| platform `messages` | `tempest_bundle_id` | engine `bundles.id` | yes |
| platform `runs` | `tempest_run_id` | engine `runs.id` | yes |
| platform `agents` | `tempest_profile_id` | engine Proof Profiles | yes |
| platform `skills` | `tempest_contract_id` | engine `.tempest/contracts/` | yes |
| engine `journal` | `platform_conversation_id` | platform `conversations._id` | yes |

Adding a row here requires updating this table in the same commit. `store_check` reads it.

---

## The delta ledger

`packages/platform/UPSTREAM.md` carries:

1. The adopted upstream commit SHA and date.
2. The merge procedure (`make upstream-merge`) and the last rehearsal date.
3. **The inline-delta ledger**: every unavoidable edit inside vendored code that is *not* in a
   `tempest/` seam directory — path, reason, upstream issue link if one exists.

`upstream_check --max-inline-deltas 40 --ledger-complete` fails when the ledger is stale or the
count grows past the cap. The cap is deliberately uncomfortable: hitting it means you are editing
their code instead of building seams, which is the beginning of fork rot.
