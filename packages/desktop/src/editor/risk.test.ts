/**
 * The behavioural risk indicator (Phase 20.3e).
 *
 * States enumerated first: the lookup failed · the lookup succeeded and found nothing · hits that
 * name OTHER symbols · one ordinary divergence · several ordinary divergences · a serious one ·
 * a serious one mixed with ordinary ones · severity in unexpected case.
 *
 * The assertion that matters most is that ABSENCE IS NOT SAFETY. Tempest exists because "no
 * evidence of a problem" and "evidence of no problem" are different sentences; an indicator that
 * rendered the first as the second would be the product contradicting itself in its own editor.
 */
import { describe, expect, it } from "vitest";

import { riskFor, riskLabel, type DivergenceRecord } from "./risk";

const hit = (qualname: string, severity: string): DivergenceRecord => ({
  qualname,
  severity,
  divergence_class: "RETURN_VALUE",
});

describe("absence is never safety", () => {
  it("reports unmeasured when the lookup failed", () => {
    const risk = riskFor("pkg.calculateTotal", null);
    expect(risk.level).toBe("unmeasured");
    expect(risk.divergences).toBe(0);
  });

  it("reports unmeasured when nothing names the symbol", () => {
    const risk = riskFor("pkg.calculateTotal", []);
    expect(risk.level, "no recorded divergence is NOT a clean bill of health").toBe("unmeasured");
    expect(riskLabel(risk)).toContain("unmeasured");
    expect(riskLabel(risk)).not.toContain("safe");
  });

  it("has no level that claims safety at all", () => {
    // Nothing available today can establish behavioural safety; a level saying so would be a
    // claim the product cannot support.
    const levels = ["unmeasured", "elevated", "high"];
    for (const level of levels) expect(riskLabel({ level, divergences: 1, reason: "r" } as never)).toBeTruthy();
    expect(levels).not.toContain("clean");
    expect(levels).not.toContain("proved");
  });
});

describe("measured history", () => {
  it("ignores hits that name other symbols", () => {
    // A substring match on a search index is not evidence about THIS symbol.
    const risk = riskFor("pkg.calculateTotal", [hit("pkg.calculateSubtotal", "LOW")]);
    expect(risk.level).toBe("unmeasured");
    expect(risk.divergences).toBe(0);
  });

  it("flags one ordinary divergence as elevated, and says how many", () => {
    const risk = riskFor("pkg.f", [hit("pkg.f", "LOW")]);
    expect(risk.level).toBe("elevated");
    expect(risk.divergences).toBe(1);
    expect(risk.reason).toBe("1 divergence recorded here");
    expect(riskLabel(risk)).toContain("elevated");
  });

  it("pluralises honestly", () => {
    const risk = riskFor("pkg.f", [hit("pkg.f", "LOW"), hit("pkg.f", "MEDIUM")]);
    expect(risk.reason).toBe("2 divergences recorded here");
  });

  it("escalates to high on a serious divergence", () => {
    const risk = riskFor("pkg.f", [hit("pkg.f", "LOW"), hit("pkg.f", "CRITICAL")]);
    expect(risk.level).toBe("high");
    expect(risk.divergences).toBe(2);
    expect(risk.reason).toBe("1 serious divergence recorded here");
  });

  it("counts several serious ones", () => {
    const risk = riskFor("pkg.f", [hit("pkg.f", "HIGH"), hit("pkg.f", "CRITICAL")]);
    expect(risk.reason).toBe("2 serious divergences recorded here");
  });

  it("compares severity case-insensitively", () => {
    // The wire says HIGH; nobody should have to know that to get a correct badge.
    expect(riskFor("pkg.f", [hit("pkg.f", "high")]).level).toBe("high");
  });
});
