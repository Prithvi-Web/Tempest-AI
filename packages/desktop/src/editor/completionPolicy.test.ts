/**
 * F11 completion policy (Phase 20.3a).
 *
 * States enumerated before the tests, because this module exists to survive races: idle · a
 * request in flight · a suggestion on screen · an answer that arrives after the document moved ·
 * an answer to a superseded request · an empty answer · accept with nothing shown · dismiss with
 * nothing shown · shown-then-typed · two requests in flight at once.
 *
 * The rule that matters most is the same one the LSP multiplexer enforces on response ids: a
 * stale answer is not a slow answer, it is a WRONG one, and believing it puts text on screen
 * that describes a document the user no longer has.
 */
import { describe, expect, it } from "vitest";

import {
  acceptanceRate,
  emptyMetrics,
  onAccept,
  onDismiss,
  onDocumentChanged,
  onRequest,
  onSuggestion,
  percentile,
  type PolicyState,
} from "./completionPolicy";

const IDLE: PolicyState = { phase: "idle" };

describe("the happy path", () => {
  it("requests, receives, shows, and accepts", () => {
    const m = emptyMetrics();
    const { state: pending, request } = onRequest(IDLE, m, 1_000, 1);
    expect(pending.phase).toBe("pending");
    expect(request.generation).toBe(1);

    const showing = onSuggestion(pending, m, 1_090, 1, "return x + 1");
    expect(showing).toEqual({ phase: "showing", shown: { text: "return x + 1", generation: 1 } });
    expect(m.latencies).toEqual([90]);
    expect(m.shown).toBe(1);

    const { state, insert } = onAccept(showing, m);
    expect(insert).toBe("return x + 1");
    expect(state).toEqual(IDLE);
    expect(m.accepted).toBe(1);
    expect(acceptanceRate(m)).toBe(1);
  });
});

describe("staleness — the reason this module exists", () => {
  it("ignores an answer to a request the document has moved past", () => {
    const m = emptyMetrics();
    const { state: pending } = onRequest(IDLE, m, 0, 1);
    const afterEdit = onDocumentChanged(pending, m);
    expect(afterEdit).toEqual(IDLE);

    const late = onSuggestion(afterEdit, m, 200, 1, "stale text");
    expect(late, "a late answer must not appear on a document it does not describe").toEqual(IDLE);
    expect(m.shown).toBe(0);
    expect(m.latencies).toEqual([]);
    expect(m.stale).toBe(2); // once for the edit, once for the answer that arrived anyway
  });

  it("ignores an answer to a SUPERSEDED request when a newer one is in flight", () => {
    const m = emptyMetrics();
    const { state: first } = onRequest(IDLE, m, 0, 1);
    const { state: second } = onRequest(first, m, 10, 2);
    expect(m.stale).toBe(1);

    const wrong = onSuggestion(second, m, 50, 1, "answer to the OLD question");
    expect(wrong.phase, "generation 1 must not satisfy generation 2").toBe("pending");
    expect(m.shown).toBe(0);

    const right = onSuggestion(second, m, 60, 2, "answer to the new one");
    expect(right).toEqual({ phase: "showing", shown: { text: "answer to the new one", generation: 2 } });
    expect(m.latencies).toEqual([50]);
  });
});

describe("degenerate inputs", () => {
  it("treats an empty suggestion as no suggestion", () => {
    // Showing one would put an invisible "accept me" affordance under Tab.
    const m = emptyMetrics();
    const { state: pending } = onRequest(IDLE, m, 0, 1);
    expect(onSuggestion(pending, m, 10, 1, "")).toEqual(IDLE);
    expect(m.shown).toBe(0);
    expect(m.latencies).toEqual([]);
  });

  it("accepting with nothing shown inserts nothing and counts nothing", () => {
    const m = emptyMetrics();
    expect(onAccept(IDLE, m)).toEqual({ state: IDLE, insert: null });
    const { state: pending } = onRequest(IDLE, m, 0, 1);
    expect(onAccept(pending, m).insert).toBeNull();
    expect(m.accepted).toBe(0);
  });

  it("dismissing is safe from every state and never counts as acceptance", () => {
    const m = emptyMetrics();
    expect(onDismiss(IDLE)).toEqual(IDLE);
    const { state: pending } = onRequest(IDLE, m, 0, 1);
    expect(onDismiss(pending)).toEqual(IDLE);
    const showing = onSuggestion(pending, m, 10, 1, "x");
    expect(onDismiss(showing)).toEqual(IDLE);
    expect(m.accepted).toBe(0);
    expect(acceptanceRate(m)).toBe(0);
  });

  it("typing while a suggestion is shown is a rejection, not a race", () => {
    const m = emptyMetrics();
    const { state: pending } = onRequest(IDLE, m, 0, 1);
    const showing = onSuggestion(pending, m, 10, 1, "x");
    expect(onDocumentChanged(showing, m)).toEqual(IDLE);
    expect(m.stale, "the user saw it and kept typing — that is a rejection, not a stale answer").toBe(0);
    expect(m.accepted).toBe(0);
  });

  it("an edit while idle changes nothing", () => {
    const m = emptyMetrics();
    expect(onDocumentChanged(IDLE, m)).toEqual(IDLE);
    expect(m.stale).toBe(0);
  });
});

describe("instrumentation the §5 gate reads", () => {
  it("reports an unknown acceptance rate rather than 0% before anything is shown", () => {
    // 0/0 is not 0. Reporting 0% for an editor nobody has used would be a number that means
    // nothing being read as a number that means something.
    expect(acceptanceRate(emptyMetrics())).toBeNull();
  });

  it("computes percentiles by nearest rank, matching perf_suite", () => {
    expect(percentile([], 50)).toBeNull();
    expect(percentile([10], 50)).toBe(10);
    expect(percentile([10, 20, 30, 40], 50)).toBe(20);
    expect(percentile([10, 20, 30, 40], 95)).toBe(40);
    expect(percentile([40, 10, 30, 20], 25)).toBe(10);
  });

  it("answers null for a percentile outside 0..100 rather than inventing one", () => {
    // A caller error must not become a fabricated number inside a §5 gate.
    expect(percentile([10, 20], 200)).toBeNull();
    expect(percentile([10, 20], -5)).toBe(10);
  });
});
