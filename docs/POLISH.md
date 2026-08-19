# Tempest AI — The Craft Checklist (150 items)

> Master prompt v2.0.0 §6, and **L26: craft is a gate.** The principles behind these items are
> in `docs/CRAFT.md`; this file is the verification instrument. **Polish is not decoration. It
> is the absence of every rough edge, enumerated and eliminated.**
>
> Phase 31's gate is this list, verified item by item on **macOS, Windows, and Linux**, with
> screenshots, plus green visual-regression, motion-interrupt, and a11y suites.
>
> Columns: **M** macOS · **W** Windows · **L** Linux. An item is done only when all three are
> checked, or it is marked platform-specific with a stated reason. Screenshots live in
> `docs/ui/polish/<item>-<platform>.png`.
>
> Items already satisfied by v1/desktop work are marked ✅ with their ADR; Phase 31 **re-verifies**
> them rather than re-implementing them.

---

## A. Design system (1–16)

| # | Item | M | W | L |
|---|---|---|---|---|
| 1 | Zero hardcoded colors anywhere — tokens only, lint-enforced | ☐ | ☐ | ☐ |
| 2 | Zero hardcoded spacing — 4pt base grid, 8pt layout rhythm, lint-enforced | ☐ | ☐ | ☐ |
| 3 | Zero hardcoded border radii — token scale only | ☐ | ☐ | ☐ |
| 4 | Zero hardcoded durations — token scale only | ☐ | ☐ | ☐ |
| 5 | Zero hardcoded shadows — elevation tokens only | ☐ | ☐ | ☐ |
| 6 | **Exactly six** type sizes; no ad-hoc values anywhere | ☐ | ☐ | ☐ |
| 7 | Exactly three font weights | ☐ | ☐ | ☐ |
| 8 | Semantic color layer over primitives; components never reference primitives | ☐ | ☐ | ☐ |
| 9 | Dark theme audited view-by-view (not derived and hoped) | ☐ | ☐ | ☐ |
| 10 | Light theme audited view-by-view | ☐ | ☐ | ☐ |
| 11 | Theme switch instant, no flash of wrong theme on launch | ☐ | ☐ | ☐ |
| 12 | System-appearance following, with a persisted explicit override | ☐ | ☐ | ☐ |
| 13 | System accent-color followed where the OS exposes it | ☐ | ☐ | ☐ |
| 14 | Density modes (comfortable/compact) across every list and table | ☐ | ☐ | ☐ |
| 15 | Density preference persists across launches | ☐ | ☐ | ☐ |
| 16 | One icon family at one optical size; no mixed-provenance icons | ☐ | ☐ | ☐ |

## B. Deference — the interface yields to the content (17–24)

| # | Item | M | W | L |
|---|---|---|---|---|
| 17 | **A screenshot of any view is ~90% content** — measured, not eyeballed | ☐ | ☐ | ☐ |
| 18 | No decorative gradients anywhere | ☐ | ☐ | ☐ |
| 19 | No card-within-card nesting | ☐ | ☐ | ☐ |
| 20 | No border that isn't doing work; no shadow that isn't communicating elevation | ☐ | ☐ | ☐ |
| 21 | Color used for **meaning** (verdict, severity, diff semantics), not decoration | ☐ | ☐ | ☐ |
| 22 | Verdict colors are the strongest in the palette; nothing decorative competes | ☐ | ☐ | ☐ |
| 23 | Chrome recedes when content is dense (no fixed furniture stealing rows) | ☐ | ☐ | ☐ |
| 24 | Evidence views print/export cleanly with no chrome artifacts | ☐ | ☐ | ☐ |

## C. Motion & physicality (25–38)

| # | Item | M | W | L |
|---|---|---|---|---|
| 25 | Micro-interactions 100–150 ms | ☐ | ☐ | ☐ |
| 26 | View transitions 200–300 ms | ☐ | ☐ | ☐ |
| 27 | **Direct manipulation uses spring physics**, not eased durations | ☐ | ☐ | ☐ |
| 28 | Spring constants live in tokens (stiffness ~200, damping ~26), not inline | ☐ | ☐ | ☐ |
| 29 | One shared curve for all non-spring transitions | ☐ | ☐ | ☐ |
| 30 | **Every animation interruptible mid-flight**, settling cleanly | ☐ | ☐ | ☐ |
| 31 | `pnpm test:motion-interrupt` interrupts each animation at 50% and asserts clean settle | ☐ | ☐ | ☐ |
| 32 | Nothing bounces decoratively; motion only communicates state change | ☐ | ☐ | ☐ |
| 33 | Full `prefers-reduced-motion` — motion removed, **meaning retained** ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 34 | No spinner before 400 ms | ☐ | ☐ | ☐ |
| 35 | Skeletons match final layout exactly — zero shift on arrival | ☐ | ☐ | ☐ |
| 36 | **CLS = 0 on every view**, measured in CI | ☐ | ☐ | ☐ |
| 37 | Streaming agent output renders progressively without reflow or scroll jump | ☐ | ☐ | ☐ |
| 38 | Long lists keep scroll anchoring during background updates | ☐ | ☐ | ☐ |

## D. Depth & platform materials (39–44)

| # | Item | M | W | L |
|---|---|---|---|---|
| 39 | Sheets over content; popovers anchored to their trigger | ☐ | ☐ | ☐ |
| 40 | Inspectors **push** rather than overlay | ☐ | ☐ | ☐ |
| 41 | macOS vibrancy via `backdrop-filter` where supported | ☐ | n/a | n/a |
| 42 | Windows 11 Mica where supported | n/a | ☐ | n/a |
| 43 | Solid fallback is **also beautiful**, never a degraded afterthought | ☐ | ☐ | ☐ |
| 44 | Z-order is meaningful and consistent; nothing floats without reason | ☐ | ☐ | ☐ |

## E. The six states, per data-bound component (45–58)

| # | Item | M | W | L |
|---|---|---|---|---|
| 45 | Loading state for every data-bound component | ☐ | ☐ | ☐ |
| 46 | Empty state for every data-bound component | ☐ | ☐ | ☐ |
| 47 | Error state for every data-bound component | ☐ | ☐ | ☐ |
| 48 | Partial state (some targets proven, some not) | ☐ | ☐ | ☐ |
| 49 | Cancelled state (user stopped a run or agent turn) | ☐ | ☐ | ☐ |
| 50 | Stale state (data older than the underlying revision) | ☐ | ☐ | ☐ |
| 51 | Storybook coverage check fails CI on any missing state | ☐ | ☐ | ☐ |
| 52 | Every empty state teaches the next action | ☐ | ☐ | ☐ |
| 53 | Every error names the cause **and** the fix | ☐ | ☐ | ☐ |
| 54 | Every error carries a copyable diagnostic ID (L15.3) | ☐ | ☐ | ☐ |
| 55 | `UNPROVEN` is first-class everywhere, never an error toast ✅ (v1 §9) | ☐ | ☐ | ☐ |
| 56 | `WEAK_EVIDENCE` (F9) rendered as its own state, not a footnote | ☐ | ☐ | ☐ |
| 57 | Offline state explicit and specific (L23) — never a spinner | ☐ | ☐ | ☐ |
| 58 | Budget/cap-reached is a designed state with a next action, not a failure | ☐ | ☐ | ☐ |

## F. Evidence vs narration (59–68) — L17, the product's core claim

| # | Item | M | W | L |
|---|---|---|---|---|
| 59 | Model narration visually unmistakable from computed evidence ✅ (ADR-0029) | ☐ | ☐ | ☐ |
| 60 | No model-authored text can reach a verdict field, by construction | ☐ | ☐ | ☐ |
| 61 | Every verdict links to its stored bundle in one click | ☐ | ☐ | ☐ |
| 62 | Every behavioral-spec claim (F4) links to supporting observations | ☐ | ☐ | ☐ |
| 63 | Every chat answer (F13) shows source spans **and** observation IDs | ☐ | ☐ | ☐ |
| 64 | Confidence/risk indicators show their computation, never a vibe | ☐ | ☐ | ☐ |
| 65 | The string "SAFE" appears nowhere in the product surface ✅ (L2, CI grep) | ☐ | ☐ | ☐ |
| 66 | Unproven agent changes carry the UNPROVEN label at equal prominence (L16) | ☐ | ☐ | ☐ |
| 67 | Behavioral artifacts (P8) are evidence-rendered, exportable to the bundle | ☐ | ☐ | ☐ |
| 68 | Branch comparison (P6) shows verdicts side by side, never "which looks better" | ☐ | ☐ | ☐ |

## G. Keyboard & interaction (69–86)

| # | Item | M | W | L |
|---|---|---|---|---|
| 69 | Full keyboard navigation of every view ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 70 | Command palette reaches **every** action | ☐ | ☐ | ☐ |
| 71 | Every action has a shortcut and the UI teaches it in place | ☐ | ☐ | ☐ |
| 72 | Shortcuts follow platform conventions (⌘ vs Ctrl) per OS | ☐ | ☐ | ☐ |
| 73 | Full keyboard navigation of **tables** | ☐ | ☐ | ☐ |
| 74 | Full keyboard navigation of **diffs**, hunk by hunk | ☐ | ☐ | ☐ |
| 75 | **Vim mode** in the editor | ☐ | ☐ | ☐ |
| 76 | Focus explicit on route change, never lost ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 77 | Focus returns to the invoking control when a dialog closes | ☐ | ☐ | ☐ |
| 78 | Escape closes every transient surface, consistently | ☐ | ☐ | ☐ |
| 79 | Correct focus trap in every modal | ☐ | ☐ | ☐ |
| 80 | Skip link to main content ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 81 | Optimistic UI with silent rollback on every mutation | ☐ | ☐ | ☐ |
| 82 | Undo for everything, one keystroke (L20), incl. multi-file agent edits | ☐ | ☐ | ☐ |
| 83 | Redo wherever undo exists | ☐ | ☐ | ☐ |
| 84 | Multi-select on every list | ☐ | ☐ | ☐ |
| 85 | Bulk actions wherever multi-select exists | ☐ | ☐ | ☐ |
| 86 | Every long operation cancellable (L11); cancellation is immediate and real | ☐ | ☐ | ☐ |

## H. Typography & data density (87–98)

| # | Item | M | W | L |
|---|---|---|---|---|
| 87 | System font stack per platform (SF / Segoe UI Variable / Inter fallback) | ☐ | ☐ | ☐ |
| 88 | Tabular numerals for every number — no jitter while streaming | ☐ | ☐ | ☐ |
| 89 | Monospace for code and identifiers everywhere | ☐ | ☐ | ☐ |
| 90 | Code ligatures **off by default** (they obscure operators) | ☐ | ☐ | ☐ |
| 91 | Optical alignment, not merely mathematical | ☐ | ☐ | ☐ |
| 92 | Truncation with hover-reveal — never a mystery ellipsis | ☐ | ☐ | ☐ |
| 93 | Every table column sortable | ☐ | ☐ | ☐ |
| 94 | Every table filterable | ☐ | ☐ | ☐ |
| 95 | Columns resizable, and the layout persists per view | ☐ | ☐ | ☐ |
| 96 | Numbers right-aligned; units consistent and labeled | ☐ | ☐ | ☐ |
| 97 | Timestamps show relative **and** absolute | ☐ | ☐ | ☐ |
| 98 | Durations formatted consistently — never raw milliseconds in the UI | ☐ | ☐ | ☐ |

## I. Native platform integration (99–114)

| # | Item | M | W | L |
|---|---|---|---|---|
| 99 | Real menu bar, correct platform conventions | ☐ | ☐ | ☐ |
| 100 | Native context menus (not custom divs) | ☐ | ☐ | ☐ |
| 101 | Native window controls / traffic lights, correctly inset | ☐ | ☐ | ☐ |
| 102 | Full-screen behavior correct | ☐ | ☐ | ☐ |
| 103 | Stage Manager behavior correct | ☐ | n/a | n/a |
| 104 | Drag-and-drop **to** Finder/Explorer | ☐ | ☐ | ☐ |
| 105 | Drag-and-drop **from** Finder/Explorer | ☐ | ☐ | ☐ |
| 106 | Quick Look integration for bundles/repros | ☐ | n/a | n/a |
| 107 | Jump lists | n/a | ☐ | n/a |
| 108 | Dock/taskbar badge for background agent progress | ☐ | ☐ | ☐ |
| 109 | Real OS notifications, **with actions** | ☐ | ☐ | ☐ |
| 110 | Notifications are actionable — click lands on the relevant view | ☐ | ☐ | ☐ |
| 111 | Window size/position restored across launches, per display | ☐ | ☐ | ☐ |
| 112 | Scroll position preserved per view across launches | ☐ | ☐ | ☐ |
| 113 | External links open in the system browser, never in-app | ☐ | ☐ | ☐ |
| 114 | File paths clickable → reveal in Finder/Explorer/file manager | ☐ | ☐ | ☐ |

## J. Accessibility — WCAG 2.2 AA min, AAA body (115–130)

| # | Item | M | W | L |
|---|---|---|---|---|
| 115 | Full VoiceOver pass on every view, **recording attached** | ☐ | n/a | n/a |
| 116 | Full NVDA pass on every view, **recording attached** | n/a | ☐ | n/a |
| 117 | Orca smoke pass on every view | n/a | n/a | ☐ |
| 118 | Body text contrast meets **AAA** | ☐ | ☐ | ☐ |
| 119 | All other text meets AA (4.5:1 / 3:1 large) in both themes | ☐ | ☐ | ☐ |
| 120 | Non-text contrast ≥ 3:1 for controls and state indicators | ☐ | ☐ | ☐ |
| 121 | Focus rings meet contrast **on every background** | ☐ | ☐ | ☐ |
| 122 | Verdicts never conveyed by color alone (icon + label) | ☐ | ☐ | ☐ |
| 123 | 200% zoom without breakage ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 124 | 400% zoom / reflow to one column, no horizontal scroll | ☐ | ☐ | ☐ |
| 125 | Live regions for streaming agent output ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 126 | Live regions throttled/polite — the stream is experienced, not spammed | ☐ | ☐ | ☐ |
| 127 | All images/icons have accessible names or are properly hidden | ☐ | ☐ | ☐ |
| 128 | Form fields have labels, descriptions, and error associations | ☐ | ☐ | ☐ |
| 129 | Target size ≥ 24×24 CSS px (WCAG 2.2 §2.5.8) | ☐ | ☐ | ☐ |
| 130 | Full operation with **no mouse**, verified end to end; no keyboard trap | ☐ | ☐ | ☐ |

## K. Internationalization (131–136) — P14

| # | Item | M | W | L |
|---|---|---|---|---|
| 131 | Zero hardcoded user-facing strings, lint-enforced | ☐ | ☐ | ☐ |
| 132 | **Verdict vocabulary and `reason_code` explanations translatable** — the strings that matter most | ☐ | ☐ | ☐ |
| 133 | Every error message translatable | ☐ | ☐ | ☐ |
| 134 | Pseudo-locale run catches truncation and layout breakage | ☐ | ☐ | ☐ |
| 135 | RTL layout verified end to end | ☐ | ☐ | ☐ |
| 136 | Numbers, dates, and currency locale-formatted (tabular figures preserved) | ☐ | ☐ | ☐ |

## L. Cost & honesty surfaces (137–142) — L21, P11

| # | Item | M | W | L |
|---|---|---|---|---|
| 137 | Live token + dollar meter during any model operation | ☐ | ☐ | ☐ |
| 138 | Pre-flight estimate before any operation over the user's threshold | ☐ | ☐ | ☐ |
| 139 | Hard caps enforced **at the router, not the UI** | ☐ | ☐ | ☐ |
| 140 | Prompt-cache hit rate shown so users see the savings | ☐ | ☐ | ☐ |
| 141 | Cost meter accurate to ±2% against provider billing | ☐ | ☐ | ☐ |
| 142 | **Cost-per-verified-outcome** surfaced per model (P11 × F21) | ☐ | ☐ | ☐ |

## M. Durability — nothing is ever lost (143–147)

| # | Item | M | W | L |
|---|---|---|---|---|
| 143 | Unsaved work survives a crash | ☐ | ☐ | ☐ |
| 144 | Editor buffers restored after force-quit | ☐ | ☐ | ☐ |
| 145 | Agent turn resumes after kill mid-proof, zero lost work (P2) | ☐ | ☐ | ☐ |
| 146 | Copy buttons everywhere with confirmation; every identifier selectable | ☐ | ☐ | ☐ |
| 147 | Every error copyable with a diagnostic bundle attached | ☐ | ☐ | ☐ |

## N. Verification of this checklist (148–150)

| # | Item | M | W | L |
|---|---|---|---|---|
| 148 | Visual regression: every view × 2 themes × 3 viewports × 2 densities, green in CI | ☐ | ☐ | ☐ |
| 149 | Screenshots captured for every item above, on all three OSes | ☐ | ☐ | ☐ |
| 150 | **The screenshot test** — a static screenshot of any view is legible and self-explanatory to someone who has never used Tempest. If it needs narration, redesign it. | ☐ | ☐ | ☐ |

---

**Gate (Phase 31):** all 150 items checked on all three OSes with screenshots committed;
`pnpm test:visual-regression --themes 2 --viewports 3 --densities 2` green;
`pnpm test:motion-interrupt` green; CLS = 0 measured on every view;
`python -m tempest.dev.a11y_audit --wcag 2.2 --level AA` green with VoiceOver and NVDA
recordings attached. **Paste the output; claimed-passing is failing.**

**Re-run and re-sign this checklist at every subsequent release.** Craft regresses silently.
