# Tempest AI — Interface Craft (L26)

> Source: v2.0.0 master prompt §6, normative. The item-by-item verification list is
> `docs/POLISH.md` (150 items). Phase 31 is the craft campaign; **it is never cut.**

**The bar, stated precisely.** Tempest should feel like software Apple would ship — **not
software that *looks* like Apple's.** Do not clone macOS chrome, copy Apple's icons, or imitate
their trade dress; that is both legally unwise and creatively bankrupt, and users can always
tell (failure mode 11). Instead adopt the **principles** that make that software feel the way it
does, then express them in Tempest's own visual identity.

**Why this is a law and not a preference.** Tempest's product claim is that evidence beats
opinion. An interface that is cluttered, janky, or ambiguous *hides evidence* — it converts a
proof into a wall of JSON nobody reads. Craft here is not decoration on top of the thesis; it is
the delivery mechanism for it. That is why L26 makes it a gate.

---

## The four principles, and what each demands here

### 1. Deference — the interface yields to the content

The content is **code and evidence**. Chrome recedes. No decorative gradients, no unnecessary
borders, no card-within-card nesting, no shadows that don't communicate elevation.

Color is used almost exclusively for **meaning** — verdict states, divergence severity, diff
semantics — and almost never for decoration. **A screenshot of Tempest should be ~90% content.**

*The Tempest-specific consequence:* `DIVERGENT`, `EQUIVALENT_UNDER_BUDGET`, `UNPROVEN`,
`WEAK_EVIDENCE`, and `ERROR` own the strongest colors in the palette. If a decorative element
competes with a verdict for attention, the decorative element is wrong.

### 2. Clarity — legibility at every size, always

- **Exactly six type sizes.** No ad-hoc values, ever.
- **Optical alignment, not merely mathematical.**
- Contrast **exceeding AA**, targeting **AAA for body text**.
- **Every icon paired with a label or a tooltip.** Icon-only UI is a memory tax on the user.
- **Tabular figures** for all numbers, so columns align and do not jitter while streaming.

*The Tempest-specific consequence:* a verdict must be readable and unambiguous at a glance, in
both themes, at 200% zoom, by someone who has never used the product. See the screenshot test.

### 3. Depth — hierarchy through layering and motion, not ornament

Real z-axis meaning: sheets over content, popovers anchored to their trigger, inspectors that
**push rather than overlay**. Use platform materials — `backdrop-filter` vibrancy on macOS,
Mica on Windows 11 where the OS supports it — with a solid fallback that is **also beautiful,
never a degraded afterthought.**

### 4. Physicality — motion obeys physics, not timing functions

**This is the single largest gap between good web UI and great native UI.**

Use **spring physics** for anything the user directly manipulates (panels, sheets, drag,
reorder). Springs are interruptible and land naturally; eased durations feel mechanical the
moment a user interrupts them. Reserve fixed-duration easing for **non-interactive transitions
only**.

**Nothing bounces for fun.** Every animation is interruptible mid-flight; a user who changes
their mind is never made to wait for an animation to finish.

---

## Concrete specification

### Design tokens
Tokens only — **no hardcoded color, spacing, radius, duration, or shadow anywhere**,
lint-enforced. 4pt base grid with an 8pt rhythm for layout. Six type sizes, three weights.
A **semantic** color layer on top of a primitive palette; components reference semantics only,
never primitives.

### Typography
System font stack first (SF on Apple, Segoe UI Variable on Windows, Inter as the cross-platform
fallback) so text renders with native hinting and feels at home. A single high-quality monospace
for code with **ligatures off by default** — ligatures obscure operators, which matters
enormously in a tool about behavior. Tabular numerals everywhere numbers appear.

### Motion budget
| Class | Spec |
|---|---|
| Micro-interactions | 100–150 ms |
| View transitions | 200–300 ms |
| Direct manipulation | **springs** (stiffness ~200, damping ~26, tuned by feel then locked in tokens) |
| Non-spring transitions | one shared curve |

Full `prefers-reduced-motion` support that **removes motion without removing meaning** —
reduced-motion users still get the state change, just instantly.

### Loading and latency choreography
No spinner before 400 ms. Skeletons match final layout **exactly**, so nothing shifts on
arrival. Streaming content renders progressively without reflow. **Zero cumulative layout shift,
measured in CI.** Optimistic UI on every mutation with silent rollback.

### The six states
Every data-bound component implements **loading, empty, error, partial, cancelled, stale**
(L15.1). Empty states teach the next action. Error states name the cause, the diagnostic ID, and
the fix. A Storybook coverage check fails CI on any missing state.

### Native platform integration
*The thing that separates a desktop app from a website in a window.* Real menu bar with correct
platform conventions. Native context menus. Native traffic lights and window controls, correctly
inset. Full-screen and Stage Manager behavior. Drag-and-drop to and from Finder/Explorer. Quick
Look on macOS. Jump lists on Windows. Dock/taskbar badge for background agent progress. Real OS
notifications with actions. System appearance and accent-color following. Window state handed
off across launches, including scroll position per view.

### Keyboard-first
A command palette that reaches **every** action. Every action has a shortcut, and the UI teaches
it. Explicit focus management that never drops focus on navigation. Full keyboard navigation of
tables and diffs. **Vim mode** in the editor, for the population that will refuse the product
without it.

### Data density
Density modes (comfortable / compact) — this is a tool used eight hours a day. Sortable,
filterable, resizable, **persistent** columns. Multi-select with bulk actions on every list.
Truncation with hover-reveal, never a mystery ellipsis.

### Accessibility — a craft requirement, not a compliance chore
WCAG 2.2 AA minimum, **AAA for body text**. Full VoiceOver and NVDA passes on every view. **Live
regions for streaming agent output**, so screen-reader users experience the stream rather than a
wall of text at the end. Focus rings meeting contrast on every background. 200% zoom without
breakage. Full keyboard operation with no mouse, verified end to end.

### The small things that compound into "flawless"
Unsaved work survives a crash. Copy buttons everywhere, with confirmation. Every identifier
selectable. Every error copyable with a diagnostic bundle attached. Undo for everything (L20),
including multi-file agent edits. Window state, panel sizes, and sort orders persist. **Nothing
ever silently discards user input.**

---

## Gate (Phase 31)

- [ ] `docs/POLISH.md` — **150 items**, verified item by item on **macOS, Windows, and Linux**,
      with screenshots attached.
- [ ] `pnpm test:visual-regression --themes 2 --viewports 3 --densities 2` — every view ×
      both themes × three viewports × both density modes.
- [ ] `pnpm test:motion-interrupt` — **every animation interruptible**, verified by interrupting
      each at 50% progress and asserting a clean settle.
- [ ] **CLS = 0** on every view, measured.
- [ ] `python -m tempest.dev.a11y_audit --wcag 2.2 --level AA` — passed, with VoiceOver and NVDA
      recordings attached.
- [ ] **The screenshot test:** a static screenshot of any view must be legible and
      self-explanatory to someone who has never used Tempest. **If it needs narration, redesign
      it.** This is the hardest item here and the one that most reliably finds real problems —
      it is a design review with a pass/fail, not a vibe.
