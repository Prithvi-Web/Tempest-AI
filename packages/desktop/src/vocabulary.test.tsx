/**
 * Exhaustive-enum renders (CLAUDE.md §9, HANDOFF-WORLD-CLASS §1.1).
 *
 * Two nets, one truth. COMPILE-time: every switch in vocabulary.tsx carries a `never` guard,
 * so a new Python enum variant breaks `tsc` the moment the bindings regenerate. RUN-time
 * (this file): the variant lists are read from the GENERATED domain schema — the same
 * document typify and the Rust build consume — and every function and chip component is
 * driven over every variant. The lists asserted below are the schema's, so this suite fails
 * loudly if the schema and the handwritten expectations ever disagree.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import domainSchema from "../../shared-schema/domain-schema.json";
import type {
  DivergenceClass,
  Lang,
  ReasonCode,
  RunStatus,
  Severity,
  TargetClassification,
  Verdict,
} from "./generated/bindings";
import {
  ClassificationChip,
  VerdictChip,
  classificationHint,
  divergenceClassLabel,
  langLabel,
  reasonHint,
  runStatusLabel,
  severityLabel,
  verdictHint,
} from "./vocabulary";

afterEach(cleanup);

function variants(name: string): string[] {
  const defs = (domainSchema as { $defs: Record<string, { enum?: string[] }> }).$defs;
  const found = defs[name]?.enum;
  if (!found || found.length === 0) throw new Error(`schema has no enum ${name}`);
  return found;
}

describe("every enum variant has non-empty copy (schema-driven)", () => {
  it("Verdict", () => {
    for (const v of variants("Verdict")) {
      expect(verdictHint(v as Verdict).length).toBeGreaterThan(20);
    }
  });

  it("ReasonCode — every reason is actionable, not just named", () => {
    for (const v of variants("ReasonCode")) {
      expect(reasonHint(v as ReasonCode).length).toBeGreaterThan(30);
    }
  });

  it("DivergenceClass", () => {
    for (const v of variants("DivergenceClass")) {
      expect(divergenceClassLabel(v as DivergenceClass).length).toBeGreaterThan(5);
    }
  });

  it("Severity", () => {
    for (const v of variants("Severity")) {
      expect(severityLabel(v as Severity).length).toBeGreaterThan(2);
    }
  });

  it("TargetClassification", () => {
    for (const v of variants("TargetClassification")) {
      expect(classificationHint(v as TargetClassification).length).toBeGreaterThan(10);
    }
  });

  it("RunStatus", () => {
    for (const v of variants("RunStatus")) {
      expect(runStatusLabel(v as RunStatus).length).toBeGreaterThan(3);
    }
  });

  it("Lang", () => {
    for (const v of variants("Lang")) {
      expect(langLabel(v as Lang).length).toBeGreaterThan(3);
    }
  });
});

describe("chip components render every variant", () => {
  it("VerdictChip: variant text, verdict-colored class, honest tooltip", () => {
    for (const v of variants("Verdict")) {
      const { getByText, unmount } = render(<VerdictChip verdict={v as Verdict} />);
      const chip = getByText(v);
      expect(chip.className).toBe(`chip ${v}`);
      expect(chip.getAttribute("title")).toBe(verdictHint(v as Verdict));
      unmount();
    }
  });

  it("ClassificationChip: neutral chip, explanation in the tooltip", () => {
    for (const v of variants("TargetClassification")) {
      const { getByText, unmount } = render(
        <ClassificationChip classification={v as TargetClassification} />,
      );
      const chip = getByText(v);
      expect(chip.className).toBe("chip neutral");
      expect(chip.getAttribute("title")).toBe(classificationHint(v as TargetClassification));
      unmount();
    }
  });
});

describe("L2 in the copy itself", () => {
  it("equivalent-under-budget never claims correctness", () => {
    expect(verdictHint("EQUIVALENT_UNDER_BUDGET")).toContain("not a proof of correctness");
  });

  it("cancellation claims no verdict", () => {
    expect(runStatusLabel("CANCELLED")).toContain("no verdict");
  });

  it("every unhandled guard is a loud crash, never a silent fallback", () => {
    // The cast simulates the one state this can occur in: a stale bundle carrying a variant
    // this build does not know. The UI must crash into its error boundary, not invent copy —
    // and EVERY switch carries the guard, so every function is driven into it here.
    const bogus = "SOMETHING_NEW";
    expect(() => verdictHint(bogus as Verdict)).toThrowError(/unhandled enum variant/);
    expect(() => reasonHint(bogus as ReasonCode)).toThrowError(/unhandled enum variant/);
    expect(() => divergenceClassLabel(bogus as DivergenceClass)).toThrowError(
      /unhandled enum variant/,
    );
    expect(() => severityLabel(bogus as Severity)).toThrowError(/unhandled enum variant/);
    expect(() => classificationHint(bogus as TargetClassification)).toThrowError(
      /unhandled enum variant/,
    );
    expect(() => runStatusLabel(bogus as RunStatus)).toThrowError(/unhandled enum variant/);
    expect(() => langLabel(bogus as Lang)).toThrowError(/unhandled enum variant/);
  });
});
