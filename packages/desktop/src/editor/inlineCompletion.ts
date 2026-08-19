/**
 * Phase 20.3b (F11) — ghost text in CodeMirror 6, driven by `completionPolicy`.
 *
 * This file is the WIRING only: every decision about whether a suggestion is still valid lives
 * in `completionPolicy`, which is unit-tested to 100% because a race is the one thing an E2E
 * suite cannot pin reliably. What is pinned here, end to end, is that the ghost text appears,
 * that Tab takes it, and that typing makes it go away.
 *
 * "Without layout thrash" (F11's own wording) is why the suggestion is a widget decoration
 * rather than inserted text: nothing enters the document until the user accepts, so the line
 * never reflows on a suggestion arriving or being discarded.
 */
import { EditorState, StateEffect, StateField, type Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  WidgetType,
  keymap,
  type DecorationSet,
} from "@codemirror/view";

import { prefixAt } from "./documentSource";
import { riskFor, riskLabel, type DivergenceRecord, type Risk } from "./risk";
import {
  emptyMetrics,
  onAccept,
  onDismiss,
  onDocumentChanged,
  onRequest,
  onSuggestion,
  type Metrics,
  type PolicyState,
} from "./completionPolicy";

/** Produces a completion for the text before the cursor. Injected so tests need no model. */
export type CompletionSource = (context: {
  textBeforeCursor: string;
  textAfterCursor: string;
}) => Promise<string>;

const setPolicy = StateEffect.define<PolicyState>();
const setRisk = StateEffect.define<Risk | null>();

/**
 * What Tempest has recorded about a symbol. Injected so the editor works without an engine, and
 * so a test can force the states that matter — a lookup that FAILS must render "unmeasured",
 * never nothing, because a silent badge and a safe badge look identical to a reader.
 */
export type RiskLookup = (symbol: string) => Promise<DivergenceRecord[] | null>;

/** Shared metrics for the session. Read by the budget harness and the acceptance-rate readout. */
const sessionMetrics: Metrics = emptyMetrics();

export function completionMetrics(): Metrics {
  return sessionMetrics;
}

const riskField = StateField.define<Risk | null>({
  create: () => null,
  update(value, tr) {
    let next = value;
    for (const effect of tr.effects) {
      if (effect.is(setRisk)) next = effect.value;
      // A new suggestion invalidates the previous one's risk: showing the old badge beside new
      // text would attribute one symbol's history to another.
      if (effect.is(setPolicy)) next = null;
    }
    if (tr.docChanged) next = null;
    return next;
  },
});

class RiskBadge extends WidgetType {
  constructor(private readonly risk: Risk) {
    super();
  }

  override eq(other: RiskBadge): boolean {
    return other.risk.level === this.risk.level && other.risk.reason === this.risk.reason;
  }

  override toDOM(): HTMLElement {
    const span = document.createElement("span");
    span.className = `cm-risk-badge cm-risk-${this.risk.level}`;
    span.textContent = riskLabel(this.risk);
    span.setAttribute("data-testid", "risk-badge");
    span.setAttribute("data-risk-level", this.risk.level);
    return span;
  }

  override ignoreEvent(): boolean {
    return true;
  }
}

class GhostText extends WidgetType {
  constructor(private readonly text: string) {
    super();
  }

  override eq(other: GhostText): boolean {
    // Without this, CodeMirror rebuilds the widget on every state change and the caret flickers.
    return other.text === this.text;
  }

  override toDOM(): HTMLElement {
    const span = document.createElement("span");
    span.className = "cm-ghost-text";
    span.textContent = this.text;
    span.setAttribute("data-testid", "ghost-text");
    // Announced as a suggestion rather than as document content: a screen reader must not read
    // ghost text as if the file already contained it.
    span.setAttribute("aria-label", `Suggested: ${this.text}`);
    return span;
  }

  override ignoreEvent(): boolean {
    return true;
  }
}

const policyField = StateField.define<PolicyState>({
  create: () => ({ phase: "idle" }),
  update(value, tr) {
    let next = value;
    for (const effect of tr.effects) {
      if (effect.is(setPolicy)) next = effect.value;
    }
    // A document change invalidates whatever was in flight or on screen — the policy decides
    // which of those it is, and whether it counts as a rejection or a race.
    if (tr.docChanged) next = onDocumentChanged(next, sessionMetrics);
    return next;
  },
});

const ghostDecorations = EditorView.decorations.compute([policyField, riskField], (state) => {
  const policy = state.field(policyField);
  if (policy.phase !== "showing") return Decoration.none;
  const at = state.selection.main.head;
  const widgets = [Decoration.widget({ widget: new GhostText(policy.shown.text), side: 1 }).range(at)];
  const risk = state.field(riskField);
  if (risk !== null) {
    widgets.push(Decoration.widget({ widget: new RiskBadge(risk), side: 2 }).range(at));
  }
  return Decoration.set(widgets, true) as DecorationSet;
});

/** The extension. `source` is injected so the editor works with any producer — or none. */
export function inlineCompletion(source: CompletionSource, lookupRisk?: RiskLookup): Extension {
  let generation = 0;

  const request = (view: EditorView): boolean => {
    generation += 1;
    const mine = generation;
    const { state } = view;
    const head = state.selection.main.head;
    const { state: pendingState } = onRequest(
      state.field(policyField),
      sessionMetrics,
      performance.now(),
      mine,
    );
    view.dispatch({ effects: setPolicy.of(pendingState) });

    void source({
      textBeforeCursor: state.doc.sliceString(0, head),
      textAfterCursor: state.doc.sliceString(head),
    })
      .then((text) => {
        // The policy decides whether this answer is still the answer to the live question.
        const next = onSuggestion(
          view.state.field(policyField),
          sessionMetrics,
          performance.now(),
          mine,
          text,
        );
        view.dispatch({ effects: setPolicy.of(next) });
        if (next.phase !== "showing" || lookupRisk === undefined) return;

        // F11's twist: what has Tempest actually WATCHED this symbol do? The badge is attached
        // after the suggestion so a slow lookup never delays the completion itself — the §5
        // budget is about the text appearing, and evidence arriving a moment later is fine.
        const before = view.state.doc.sliceString(0, view.state.selection.main.head);
        const symbol = prefixAt(before) + text;
        void lookupRisk(symbol)
          .then((records) => {
            // Only if this suggestion is still the one on screen.
            const current = view.state.field(policyField);
            if (current.phase !== "showing" || current.shown.generation !== mine) return;
            view.dispatch({ effects: setRisk.of(riskFor(symbol, records)) });
          })
          .catch(() => {
            // A failed lookup is "unmeasured", never silence: a missing badge and a safe badge
            // are indistinguishable to a reader, and this product does not let those blur.
            const current = view.state.field(policyField);
            if (current.phase !== "showing" || current.shown.generation !== mine) return;
            view.dispatch({ effects: setRisk.of(riskFor(symbol, null)) });
          });
      })
      .catch(() => {
        // A source that fails is not a suggestion. It must not leave the editor pending
        // forever, which would make Tab do nothing with no explanation.
        view.dispatch({ effects: setPolicy.of({ phase: "idle" }) });
      });
    return true;
  };

  const accept = (view: EditorView): boolean => {
    const { state: next, insert } = onAccept(view.state.field(policyField), sessionMetrics);
    if (insert === null) return false; // let Tab do its ordinary job
    view.dispatch({
      changes: { from: view.state.selection.main.head, insert },
      selection: { anchor: view.state.selection.main.head + insert.length },
      effects: setPolicy.of(next),
    });
    return true;
  };

  const dismiss = (view: EditorView): boolean => {
    const policy = view.state.field(policyField);
    if (policy.phase === "idle") return false; // let Escape do its ordinary job
    view.dispatch({ effects: setPolicy.of(onDismiss(policy)) });
    return true;
  };

  return [
    policyField,
    riskField,
    ghostDecorations,
    keymap.of([
      { key: "F11", run: request, preventDefault: true },
      { key: "Tab", run: accept },
      { key: "Escape", run: dismiss },
    ]),
  ];
}

/** Exposed for the budget harness and the E2E specs; never used by product code. */
export function __resetCompletionMetricsForTests(): void {
  sessionMetrics.latencies.length = 0;
  sessionMetrics.shown = 0;
  sessionMetrics.accepted = 0;
  sessionMetrics.stale = 0;
}

export { EditorState };
