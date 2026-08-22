/**
 * Phase 20.3 (F11) — when to ask for a completion, which answer to believe, and what to record.
 *
 * Separated from the CodeMirror wiring on purpose: this is the part whose behaviour is decidable
 * without a live engine or a model, so it is unit-tested to 100% rather than left to the E2E
 * suite. What CodeMirror does with a suggestion is a rendering question; whether a suggestion is
 * still *valid* is a correctness question, and it is the one that bites.
 *
 * §5 budgets a completion at p50 120 ms / p95 300 ms. The latency recorded here is the number
 * that gate reads, so it is measured at the boundary the user actually experiences: the moment
 * the request is made to the moment a suggestion is eligible to be shown.
 */

/** A completion request in flight. `generation` is what makes a stale answer detectable. */
export type Pending = { generation: number; requestedAt: number };

/** What the editor should currently display. */
export type Shown = { text: string; generation: number };

export type PolicyState =
  | { phase: "idle" }
  | { phase: "pending"; pending: Pending }
  | { phase: "showing"; shown: Shown };

/** Instrumentation the §5 gate and the acceptance-rate metric read. */
export type Metrics = {
  /** One entry per suggestion that became eligible to show. */
  latencies: number[];
  shown: number;
  accepted: number;
  /** Answers discarded because the document moved on. Not failures — races. */
  stale: number;
};

export function emptyMetrics(): Metrics {
  return { latencies: [], shown: 0, accepted: 0, stale: 0 };
}

/**
 * The acceptance rate F11's gate requires to be "instrumented".
 *
 * Returns null rather than 0 when nothing has been shown: a rate over zero samples is not zero,
 * it is unknown, and reporting 0% acceptance for an editor nobody has used yet would be a number
 * that means nothing being read as a number that means something.
 */
export function acceptanceRate(metrics: Metrics): number | null {
  if (metrics.shown === 0) return null;
  return metrics.accepted / metrics.shown;
}

/**
 * Nearest-rank percentile — `ceil(pct/100 * n)` clamped into `[1, n]` — matching
 * `tempest.dev.perf_suite` so the two agree on what "p95" means.
 *
 * They did not. This side used `ceil`, the gate used `round(x + 0.5)`, and Python's banker's
 * rounding made them disagree whenever `pct/100 * n` is an integer; both now use `ceil`, and a
 * test below pins the exact vector where they differed.
 *
 * A percentile outside 0..100 answers null rather than throwing or clamping silently: it is a
 * caller error, and inventing a value for it would put a fabricated number into a gate. That was
 * also only half true — `Math.max(1, ...)` floored the rank, so `percentile(xs, -5)` returned
 * the SMALLEST sample, and the test asserting otherwise asserted the invented value in its own
 * "rather than inventing one" case.
 */
export function percentile(samples: number[], pct: number): number | null {
  if (pct < 0 || pct > 100) return null;
  const ordered = [...samples].sort((a, b) => a - b);
  const rank = Math.min(ordered.length, Math.max(1, Math.ceil((pct / 100) * ordered.length)));
  // No separate empty-samples guard: over an empty list `rank` clamps to 0 and the index is
  // out of range, so this `??` IS the empty case rather than an arm nothing can reach. Written
  // with the guard as well, `noUncheckedIndexedAccess` still demands the `??` and then no input
  // can reach it — a permanent hole in a 100% gate, defended by a fallback that never runs.
  return ordered[rank - 1] ?? null;
}

/** A document edit invalidates anything in flight or on screen. */
export function onDocumentChanged(state: PolicyState, metrics: Metrics): PolicyState {
  if (state.phase === "showing") {
    // Shown-then-typed is a rejection: the user saw it and kept typing.
    return { phase: "idle" };
  }
  if (state.phase === "pending") {
    // The answer still in flight is now about a document that no longer exists.
    metrics.stale += 1;
    return { phase: "idle" };
  }
  return state;
}

/** F11, or an automatic trigger. Returns the new state and the generation to tag the request. */
export function onRequest(
  state: PolicyState,
  metrics: Metrics,
  now: number,
  nextGeneration: number,
): { state: PolicyState; request: Pending } {
  if (state.phase === "pending") {
    // Superseding an in-flight request: the older answer must never win.
    metrics.stale += 1;
  }
  const request: Pending = { generation: nextGeneration, requestedAt: now };
  return { state: { phase: "pending", pending: request }, request };
}

/**
 * An answer arrived. It is believed ONLY if it is the answer to the question currently being
 * asked — the same rule the LSP multiplexer applies to response ids, and for the same reason: a
 * stale answer is not a slow answer, it is a wrong one.
 */
export function onSuggestion(
  state: PolicyState,
  metrics: Metrics,
  now: number,
  generation: number,
  text: string,
): PolicyState {
  if (state.phase !== "pending" || state.pending.generation !== generation) {
    metrics.stale += 1;
    return state;
  }
  // An empty suggestion is not a suggestion. Showing one would put an invisible "accept me"
  // affordance under Tab.
  if (text.length === 0) {
    return { phase: "idle" };
  }
  metrics.latencies.push(now - state.pending.requestedAt);
  metrics.shown += 1;
  return { phase: "showing", shown: { text, generation } };
}

/** Tab. Returns the text to insert, or null when there is nothing to accept. */
export function onAccept(state: PolicyState, metrics: Metrics): { state: PolicyState; insert: string | null } {
  if (state.phase !== "showing") return { state, insert: null };
  metrics.accepted += 1;
  return { state: { phase: "idle" }, insert: state.shown.text };
}

/** Escape, blur, or a cursor move. Never counts as acceptance. */
export function onDismiss(state: PolicyState): PolicyState {
  return state.phase === "idle" ? state : { phase: "idle" };
}
