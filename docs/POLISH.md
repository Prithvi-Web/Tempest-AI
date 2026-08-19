# Tempest AI — The Polish Checklist (120 items)

> Master prompt v2.0.0 §6. **Polish is not decoration. It is the absence of every rough edge,
> enumerated and eliminated.** Phase 29's gate is this list, verified item by item on macOS,
> Windows, and Linux, with screenshots, plus a green visual-regression suite.
>
> Verification columns: **M** macOS · **W** Windows · **L** Linux. An item is done only when
> all three are checked (or the item is marked platform-specific with a reason). Screenshots
> live in `docs/ui/polish/<item-number>-<platform>.png`.
>
> Items already satisfied by v1/desktop work are marked ✅ with their ADR; they are re-verified
> in Phase 29 rather than re-implemented.

---

## A. Design system (1–14)

| # | Item | M | W | L |
|---|---|---|---|---|
| 1 | Zero hardcoded colors anywhere — tokens only, enforced by a lint rule | ☐ | ☐ | ☐ |
| 2 | Zero hardcoded spacing values — one 8px scale, lint-enforced | ☐ | ☐ | ☐ |
| 3 | Zero hardcoded border radii — token scale only | ☐ | ☐ | ☐ |
| 4 | Zero hardcoded animation durations — token scale only | ☐ | ☐ | ☐ |
| 5 | One type scale, documented, no off-scale sizes in any view | ☐ | ☐ | ☐ |
| 6 | Dark theme audited view-by-view (not derived and hoped) | ☐ | ☐ | ☐ |
| 7 | Light theme audited view-by-view | ☐ | ☐ | ☐ |
| 8 | Theme switch is instant, with no flash of wrong theme on launch | ☐ | ☐ | ☐ |
| 9 | System-theme following, with an explicit override that persists | ☐ | ☐ | ☐ |
| 10 | Density modes (comfortable / compact) across every list and table | ☐ | ☐ | ☐ |
| 11 | Density preference persists across launches | ☐ | ☐ | ☐ |
| 12 | Icon set is one family at one optical size; no mixed-provenance icons | ☐ | ☐ | ☐ |
| 13 | Elevation/shadow scale is tokenized and used consistently | ☐ | ☐ | ☐ |
| 14 | Focus-ring style is one token, used everywhere, never removed | ☐ | ☐ | ☐ |

## B. Motion (15–24)

| # | Item | M | W | L |
|---|---|---|---|---|
| 15 | Every transition 120–200 ms | ☐ | ☐ | ☐ |
| 16 | One shared easing curve across the app | ☐ | ☐ | ☐ |
| 17 | Motion communicates state change only — zero decorative animation | ☐ | ☐ | ☐ |
| 18 | Full `prefers-reduced-motion` support ✅ (ADR-0031) — re-verified | ☐ | ☐ | ☐ |
| 19 | No spinner before 400 ms | ☐ | ☐ | ☐ |
| 20 | Skeletons match final layout exactly — zero shift on content arrival | ☐ | ☐ | ☐ |
| 21 | Cumulative layout shift measured at zero on every view | ☐ | ☐ | ☐ |
| 22 | View transitions never animate the whole page when a region changed | ☐ | ☐ | ☐ |
| 23 | Streaming agent output does not cause scroll jump or reflow thrash | ☐ | ☐ | ☐ |
| 24 | Long lists preserve scroll anchoring during background updates | ☐ | ☐ | ☐ |

## C. The six states, per data-bound component (25–38)

> L15.1: loading, empty, error, partial, cancelled, stale — designed and implemented for
> every data-bound component, enforced by a Storybook coverage check that fails CI.

| # | Item | M | W | L |
|---|---|---|---|---|
| 25 | Loading state for every data-bound component | ☐ | ☐ | ☐ |
| 26 | Empty state for every data-bound component | ☐ | ☐ | ☐ |
| 27 | Error state for every data-bound component | ☐ | ☐ | ☐ |
| 28 | Partial state (some targets proven, some not) | ☐ | ☐ | ☐ |
| 29 | Cancelled state (user stopped a run/agent turn) | ☐ | ☐ | ☐ |
| 30 | Stale state (data older than the underlying revision) | ☐ | ☐ | ☐ |
| 31 | Storybook coverage check fails CI on any missing state | ☐ | ☐ | ☐ |
| 32 | Every empty state teaches the next action (never a bare "no data") | ☐ | ☐ | ☐ |
| 33 | Every error state names the cause and offers a fix | ☐ | ☐ | ☐ |
| 34 | Every error state carries a copyable diagnostic ID (L15.3) | ☐ | ☐ | ☐ |
| 35 | `UNPROVEN` is a first-class state everywhere, never an error toast ✅ (v1 §9) | ☐ | ☐ | ☐ |
| 36 | `WEAK_EVIDENCE` (F9) rendered as its own state, not a footnote | ☐ | ☐ | ☐ |
| 37 | Offline state explicit and specific (L23) — never a spinner | ☐ | ☐ | ☐ |
| 38 | Budget-exhausted state distinct from failure (L15.4) | ☐ | ☐ | ☐ |

## D. Evidence vs narration (39–46) — L17, the product's core claim

| # | Item | M | W | L |
|---|---|---|---|---|
| 39 | Model narration visually unmistakable from computed evidence ✅ (ADR-0029) | ☐ | ☐ | ☐ |
| 40 | No model-authored text can appear in a verdict field, by construction | ☐ | ☐ | ☐ |
| 41 | Every verdict links to its stored bundle in one click | ☐ | ☐ | ☐ |
| 42 | Every behavioral-spec claim (F4) links to its supporting observations | ☐ | ☐ | ☐ |
| 43 | Every chat answer (F13) shows source spans and observation IDs | ☐ | ☐ | ☐ |
| 44 | Confidence/risk indicators show their computation, never a vibe | ☐ | ☐ | ☐ |
| 45 | The string "SAFE" appears nowhere in the product surface ✅ (L2, CI grep) | ☐ | ☐ | ☐ |
| 46 | Unproven agent changes carry the UNPROVEN label at equal prominence (L16) | ☐ | ☐ | ☐ |

## E. Interaction & keyboard (47–62)

| # | Item | M | W | L |
|---|---|---|---|---|
| 47 | Full keyboard navigation of every view ✅ (ADR-0031) — re-verified | ☐ | ☐ | ☐ |
| 48 | Discoverable command palette covering every action | ☐ | ☐ | ☐ |
| 49 | Every action has a shortcut and displays it in-place | ☐ | ☐ | ☐ |
| 50 | Shortcuts follow platform conventions (⌘ vs Ctrl) per OS | ☐ | ☐ | ☐ |
| 51 | Focus is explicit on route change, never lost ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 52 | Focus returns to the invoking control when a dialog closes | ☐ | ☐ | ☐ |
| 53 | Escape closes every transient surface, consistently | ☐ | ☐ | ☐ |
| 54 | Focus trap correct in every modal (no escape to background) | ☐ | ☐ | ☐ |
| 55 | Skip link to main content ✅ (ADR-0031) | ☐ | ☐ | ☐ |
| 56 | Optimistic UI with rollback on every mutation | ☐ | ☐ | ☐ |
| 57 | Undo for everything, one keystroke (L20) | ☐ | ☐ | ☐ |
| 58 | Redo where undo exists | ☐ | ☐ | ☐ |
| 59 | Multi-select on every list | ☐ | ☐ | ☐ |
| 60 | Bulk actions on every list that supports multi-select | ☐ | ☐ | ☐ |
| 61 | Every long operation is cancellable (L11) and cancellation is immediate | ☐ | ☐ | ☐ |
| 62 | Cancellation actually cancels upstream model requests, not just the UI | ☐ | ☐ | ☐ |

## F. Typography & data density (63–74)

| # | Item | M | W | L |
|---|---|---|---|---|
| 63 | Tabular numerals for every number | ☐ | ☐ | ☐ |
| 64 | Monospace for code and identifiers, everywhere | ☐ | ☐ | ☐ |
| 65 | Sensible truncation with hover-reveal of the full value | ☐ | ☐ | ☐ |
| 66 | Every table column sortable | ☐ | ☐ | ☐ |
| 67 | Every table filterable | ☐ | ☐ | ☐ |
| 68 | Columns resizable | ☐ | ☐ | ☐ |
| 69 | Column layout persists per view across launches | ☐ | ☐ | ☐ |
| 70 | Numbers aligned right; units consistent and labeled | ☐ | ☐ | ☐ |
| 71 | Timestamps show relative + absolute (hover or adjacent) | ☐ | ☐ | ☐ |
| 72 | Durations formatted consistently (never raw milliseconds in the UI) | ☐ | ☐ | ☐ |
| 73 | Long identifiers wrap or ellipsize without breaking layout | ☐ | ☐ | ☐ |
| 74 | Code and diff views use the editor's font settings, not their own | ☐ | ☐ | ☐ |

## G. Accessibility — WCAG 2.2 AA (75–90)

| # | Item | M | W | L |
|---|---|---|---|---|
| 75 | Full VoiceOver pass on every view (macOS) | ☐ | n/a | n/a |
| 76 | Full NVDA pass on every view (Windows) | n/a | ☐ | n/a |
| 77 | Orca smoke pass on every view (Linux) | n/a | n/a | ☐ |
| 78 | Visible focus rings meeting contrast requirements | ☐ | ☐ | ☐ |
| 79 | 200% zoom without breakage ✅ (ADR-0031) — re-verified | ☐ | ☐ | ☐ |
| 80 | 400% zoom / reflow to single column without horizontal scroll | ☐ | ☐ | ☐ |
| 81 | Text contrast ≥ 4.5:1 (normal), ≥ 3:1 (large) in both themes | ☐ | ☐ | ☐ |
| 82 | Non-text contrast ≥ 3:1 for controls and state indicators | ☐ | ☐ | ☐ |
| 83 | Verdicts never conveyed by color alone (icon + label) | ☐ | ☐ | ☐ |
| 84 | Live regions for streaming agent output ✅ (ADR-0031 aria-live) | ☐ | ☐ | ☐ |
| 85 | Live regions don't spam the screen reader (throttled, polite) | ☐ | ☐ | ☐ |
| 86 | All images/icons have accessible names or are properly hidden | ☐ | ☐ | ☐ |
| 87 | Form fields have labels, descriptions, and error associations | ☐ | ☐ | ☐ |
| 88 | Target size ≥ 24×24 CSS px (WCAG 2.2 §2.5.8) | ☐ | ☐ | ☐ |
| 89 | No keyboard trap anywhere, verified by automated crawl | ☐ | ☐ | ☐ |
| 90 | `a11y_audit --wcag 2.2 --level AA` green in CI | ☐ | ☐ | ☐ |

## H. Craft details (91–108)

| # | Item | M | W | L |
|---|---|---|---|---|
| 91 | Window size/position restored across launches | ☐ | ☐ | ☐ |
| 92 | Window state restored per display; sane on display disconnect | ☐ | ☐ | ☐ |
| 93 | Scroll position preserved per view | ☐ | ☐ | ☐ |
| 94 | Unsaved work never lost, including across a crash | ☐ | ☐ | ☐ |
| 95 | Editor buffers restored after force-quit | ☐ | ☐ | ☐ |
| 96 | Copy buttons everywhere, with confirmation feedback | ☐ | ☐ | ☐ |
| 97 | Every ID is selectable text | ☐ | ☐ | ☐ |
| 98 | Every error is copyable with a diagnostic bundle attached | ☐ | ☐ | ☐ |
| 99 | Native context menus (not custom divs) | ☐ | ☐ | ☐ |
| 100 | Proper drag-and-drop with valid/invalid drop affordances | ☐ | ☐ | ☐ |
| 101 | OS notifications on background agent completion | ☐ | ☐ | ☐ |
| 102 | Notifications are actionable (click → the relevant view) | ☐ | ☐ | ☐ |
| 103 | Dock/taskbar progress for long operations | ☐ | ☐ | ☐ |
| 104 | App menu bar complete and platform-correct | ☐ | ☐ | ☐ |
| 105 | External links open in the system browser, never in-app | ☐ | ☐ | ☐ |
| 106 | File paths clickable → reveal in Finder/Explorer/file manager | ☐ | ☐ | ☐ |
| 107 | Deep links / URL scheme into a specific run or divergence | ☐ | ☐ | ☐ |
| 108 | Quitting mid-run warns, and cancels cleanly (no orphans ✅ orphan_check) | ☐ | ☐ | ☐ |

## I. Cost, budgets & honesty surfaces (109–114) — L21

| # | Item | M | W | L |
|---|---|---|---|---|
| 109 | Live token + dollar meter visible during any model operation | ☐ | ☐ | ☐ |
| 110 | Pre-flight estimate before any operation over the user's threshold | ☐ | ☐ | ☐ |
| 111 | Hard caps per task, per session, per day — enforced, not advisory | ☐ | ☐ | ☐ |
| 112 | Prompt-cache hit rate shown so users see the savings | ☐ | ☐ | ☐ |
| 113 | Cost meter accurate to ±2% against provider-reported usage | ☐ | ☐ | ☐ |
| 114 | Reaching a cap is a designed state with a clear next action | ☐ | ☐ | ☐ |

## J. Verification of this checklist (115–120)

| # | Item | M | W | L |
|---|---|---|---|---|
| 115 | Automated visual regression: every view × both themes × 3 viewports | ☐ | ☐ | ☐ |
| 116 | Visual regression green in CI, with a reviewable diff artifact | ☐ | ☐ | ☐ |
| 117 | Screenshots captured for every item above, on all three OSes | ☐ | ☐ | ☐ |
| 118 | Perf budgets (§5) re-verified after the polish pass — polish cost nothing | ☐ | ☐ | ☐ |
| 119 | A fresh-install first-run walkthrough recorded on each OS | ☐ | ☐ | ☐ |
| 120 | This checklist re-run and re-signed at every subsequent release | ☐ | ☐ | ☐ |

---

**Gate (Phase 29):** all 120 items checked on all three OSes with screenshots committed,
`pnpm test:visual-regression` green, `python -m tempest.dev.a11y_audit --wcag 2.2 --level AA`
green. Paste the output; claimed-passing is failing.
