/**
 * The risk indicator's honesty, and the two ways it shipped inert.
 *
 * These tests are deliberately built on the GENERATED types rather than on hand-written record
 * literals. The old suite constructed `{severity: "HIGH"}` objects and asserted the badge
 * escalated on them — a test of data the test itself invented, which passed for the whole life of
 * a feature whose escalation arm the wire could never reach (trap 43, in its purest form).
 */
import { describe, expect, it } from "vitest";

import { ESCALATION_TABLE, riskFor, riskLabel, type DivergenceRecord } from "./risk";

import type { Severity } from "../generated/bindings";

function record(over: Partial<DivergenceRecord> = {}): DivergenceRecord {
  return {
    divergence_id: 1,
    target_id: 1,
    run_id: 1,
    module: "billing",
    qualname: "calculateTotal",
    divergence_class: "RETURN_VALUE",
    severity: "NORMAL",
    detail: "return values differ",
    ...over,
  };
}

describe("riskFor", () => {
  it("renders a failed lookup as unmeasured, never as safe", () => {
    const risk = riskFor("calculateTotal", null);
    expect(risk.level).toBe("unmeasured");
    expect(risk.reason).toBe("no measurement available");
    expect(riskLabel(risk)).not.toContain("safe");
  });

  it("distinguishes 'we could not ask' from 'the engine has no record'", () => {
    // Both are unmeasured; the reason is the only thing that tells them apart, and a caller
    // that cannot tell them apart cannot report honestly.
    expect(riskFor("x", null).reason).not.toBe(riskFor("x", []).reason);
    expect(riskFor("x", []).reason).toBe("no recorded runs name this symbol");
    expect(riskFor("x", []).level).toBe("unmeasured");
  });

  it("escalates a HEADLINE divergence — the severity the wire actually carries", () => {
    // The defect this pins: the old set was {"HIGH","CRITICAL"}, neither of which
    // `tempest.model.Severity` has ever contained, so `high` was unreachable in production.
    const risk = riskFor("calculateTotal", [record({ severity: "HEADLINE" })]);
    expect(risk.level).toBe("high");
    expect(risk.divergences).toBe(1);
    expect(risk.reason).toBe("1 headline divergence recorded in billing.calculateTotal");
  });

  it("reports an ordinary divergence as elevated, not as high", () => {
    const risk = riskFor("calculateTotal", [record(), record({ divergence_id: 2 })]);
    expect(risk.level).toBe("elevated");
    expect(risk.reason).toBe("2 divergences recorded in billing.calculateTotal");
  });

  it("names the symbol it measured, so the badge cannot over-claim", () => {
    // A bare editor identifier can match more than one recorded symbol.
    const risk = riskFor("post", [
      record({ module: "ledger", qualname: "Ledger.post" }),
      record({ module: "mail", qualname: "Outbox.post", divergence_id: 2 }),
    ]);
    expect(risk.reason).toBe("2 divergences recorded in 2 symbols named post");
  });

  it("counts only the serious ones when both are present", () => {
    const risk = riskFor("calculateTotal", [
      record(),
      record({ divergence_id: 2, severity: "HEADLINE" }),
      record({ divergence_id: 3, severity: "LOW" }),
    ]);
    expect(risk.level).toBe("high");
    expect(risk.divergences).toBe(3);
    expect(risk.reason).toBe("1 headline divergence recorded in billing.calculateTotal");
  });

  it("escalates on every severity the engine can emit, and only those", () => {
    // `ESCALATION_TABLE` is a Record over the generated union, so this loop covers the WHOLE
    // vocabulary by construction: adding a variant in Python breaks the build, not this test.
    const expected: Record<Severity, "elevated" | "high"> = {
      LOW: "elevated",
      NORMAL: "elevated",
      HEADLINE: "high",
    };
    for (const [severity, level] of Object.entries(expected) as [Severity, string][]) {
      expect(riskFor("calculateTotal", [record({ severity })]).level, severity).toBe(level);
      expect(ESCALATION_TABLE[severity], severity).toBe(level === "high");
    }
  });
});

describe("riskLabel", () => {
  it("never renders absence as approval", () => {
    for (const risk of [riskFor("x", null), riskFor("x", [])]) {
      const label = riskLabel(risk);
      expect(label).toContain("unmeasured");
      expect(label).not.toContain("safe");
      expect(label).not.toContain("proved");
      expect(label).not.toContain("clean");
    }
  });

  it("says what it measured, not just that it is worried", () => {
    expect(riskLabel(riskFor("calculateTotal", [record({ severity: "HEADLINE" })]))).toBe(
      "⚠ high risk — 1 headline divergence recorded in billing.calculateTotal",
    );
    expect(riskLabel(riskFor("calculateTotal", [record()]))).toBe(
      "⚠ elevated — 1 divergence recorded in billing.calculateTotal",
    );
  });
});
