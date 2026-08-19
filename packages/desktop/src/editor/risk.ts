/**
 * Phase 20.3e (F11's twist) — the behavioural risk indicator.
 *
 * F11's completions are ordinary; this is what makes them Tempest's. A completion that names a
 * symbol Tempest has WATCHED DIVERGE is flagged, from measured runs — not from a heuristic, not
 * from a model's opinion, and not from how the code looks.
 *
 * THE MOST IMPORTANT RULE HERE IS WHAT ABSENCE MEANS. A symbol with no recorded divergences is
 * `unmeasured`, never `safe`. Tempest exists because "no evidence of a problem" and "evidence of
 * no problem" are different sentences, and an indicator that renders the first as the second
 * would be the product contradicting itself in its own editor (L7, and the whole reason
 * NOT-YET-MEASURED exists in the §5 table rather than a green tick).
 *
 * Scope, stated: F11 names three inputs — historical divergence rates, low proof rates, and many
 * dependents. Only the FIRST is measurable today. Proof rate per symbol has no command behind it
 * yet, and dependents need the call graph that arrives in Phase 22 (F13). They are absent rather
 * than approximated: a risk score padded with guesses is worse than a narrower one that is true.
 */

/** One recorded divergence, in the shape the generated `SearchHit` provides. */
export type DivergenceRecord = {
  qualname: string;
  severity: string;
  divergence_class: string;
};

/**
 * Deliberately has no "clean"/"proved" level.
 *
 * Nothing available today can establish that a symbol is behaviourally safe — that needs the
 * per-symbol proof rate F11 names, which has no command behind it yet. A level the product
 * cannot justify is aspirational surface, and this editor is the last place to put one: the
 * whole point of the indicator is that it reports what was measured.
 */
export type RiskLevel = "unmeasured" | "elevated" | "high";

export type Risk = {
  level: RiskLevel;
  /** How many recorded divergences name this symbol. */
  divergences: number;
  /** The count that drove the level, so the badge can explain itself rather than assert. */
  reason: string;
};

/** Severities that count as serious. Anything else contributes, but does not escalate alone. */
const SERIOUS = new Set(["HIGH", "CRITICAL"]);

/**
 * Risk for `qualname`, from the divergences Tempest has actually recorded.
 *
 * `searched` is the full result set for the query; entries naming other symbols are ignored
 * rather than counted, because a substring match on a search index is not evidence about this
 * symbol.
 */
export function riskFor(qualname: string, searched: DivergenceRecord[] | null): Risk {
  // A failed or absent lookup is NOT a clean bill of health.
  if (searched === null) {
    return { level: "unmeasured", divergences: 0, reason: "no measurement available" };
  }
  const mine = searched.filter((hit) => hit.qualname === qualname);
  if (mine.length === 0) {
    return {
      level: "unmeasured",
      divergences: 0,
      // Deliberately not "looks fine": Tempest has never watched this symbol diverge, which is
      // a statement about Tempest's records, not about the symbol.
      reason: "no recorded runs name this symbol",
    };
  }
  const serious = mine.filter((hit) => SERIOUS.has(hit.severity.toUpperCase())).length;
  if (serious > 0) {
    return {
      level: "high",
      divergences: mine.length,
      reason: `${serious} serious divergence${serious === 1 ? "" : "s"} recorded here`,
    };
  }
  return {
    level: "elevated",
    divergences: mine.length,
    reason: `${mine.length} divergence${mine.length === 1 ? "" : "s"} recorded here`,
  };
}

/** The short label the editor shows beside a suggestion. Never a bare colour. */
export function riskLabel(risk: Risk): string {
  switch (risk.level) {
    case "high":
      return `⚠ high risk — ${risk.reason}`;
    case "elevated":
      return `⚠ elevated — ${risk.reason}`;
    case "unmeasured":
      return `unmeasured — ${risk.reason}`;
  }
  // No `default` arm on purpose. Every level returns, so adding one to `RiskLevel` makes this
  // function fall through and violate its declared `string` return — the compiler enforces
  // exhaustiveness without a branch no test can reach. (Verified by adding a fourth level and
  // watching tsc reject it, rather than assuming.)
}
