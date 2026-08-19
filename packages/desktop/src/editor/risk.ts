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
 * ## Two ways this shipped inert, and what stops each from recurring
 *
 * The Phase 20 review found that neither non-`unmeasured` level could EVER be reached, so the
 * badge was honest about absence by accident rather than by measurement:
 *
 * 1. **The escalation set named severities the wire does not carry.** It tested for
 *    `{"HIGH", "CRITICAL"}`; the engine's vocabulary is `LOW | NORMAL | HEADLINE`
 *    (`tempest.model.Severity`), and HEADLINE is exactly what a head-only crash records — the
 *    one thing this badge exists to shout about. The compiler could not see it because the
 *    severity arrived here as a `string`: `divergenceLookup` did `String(hit.severity)`, which
 *    widens a closed union into a type where any spelling is legal. The fix is not a better
 *    string — it is the GENERATED `Severity` type, so a set naming a value the wire cannot carry
 *    stops compiling.
 * 2. **The lookup asked a question the index cannot answer.** It called `searchDivergences`,
 *    whose FTS index covers `detail`, `base_summary` and `head_summary` — never `qualname`. See
 *    `divergenceLookup.ts`; the fix is a real by-symbol endpoint.
 *
 * Scope, stated: F11 names three inputs — historical divergence rates, low proof rates, and many
 * dependents. Only the FIRST is measurable today. Proof rate per symbol has no command behind it
 * yet, and dependents need the call graph that arrives in Phase 22 (F13). They are absent rather
 * than approximated: a risk score padded with guesses is worse than a narrower one that is true.
 */
import type { Severity, SymbolDivergence } from "../generated/bindings";

/** One recorded divergence, exactly as the engine reports it. Re-exported so the editor modules
 * name one type rather than a hand-written mirror of it (§9b). */
export type DivergenceRecord = SymbolDivergence;

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
  /** The count and the symbol that drove the level, so the badge can explain itself. */
  reason: string;
};

/**
 * Severities serious enough to escalate, as a `Record` over the WHOLE generated union.
 *
 * A `Set` of strings would have accepted `"HIGH"` — and did, for the life of 20.3e. A
 * `Record<Severity, ...>` must name every variant the wire can carry, so adding one to the
 * Python enum breaks this file until somebody decides what it means. That is the design working
 * (§9b), applied to a value rather than a shape.
 */
const ESCALATES: Record<Severity, boolean> = {
  LOW: false,
  NORMAL: false,
  // "headline (crash or contract break)" — `vocabulary.severityLabel`. The comparator assigns it
  // to a head-only CRASH and to HANG, which is the most serious thing Tempest can measure.
  HEADLINE: true,
};

/** Where the divergences were recorded, named precisely enough that the badge cannot over-claim. */
function attribution(symbol: string, recorded: readonly DivergenceRecord[]): string {
  const names = new Set(recorded.map((hit) => `${hit.module}.${hit.qualname}`));
  // `join("")` on a one-element set IS that element. Written this way rather than as
  // `[...names][0] ?? symbol` because `noUncheckedIndexedAccess` makes the index `string |
  // undefined`, and the `??` arm is then a branch that cannot be reached and cannot be tested —
  // a permanent hole in a 100% gate, defended by a fallback that would never run.
  if (names.size === 1) return [...names].join("");
  // A bare identifier can name more than one recorded symbol (two classes with a `post`). Saying
  // "recorded here" in that case would attribute one symbol's history to another.
  return `${names.size} symbols named ${symbol}`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Risk for `symbol`, from the divergences Tempest has actually recorded against it.
 *
 * `recorded` is what `divergencesForSymbol` returned — already selected BY SYMBOL in the engine,
 * so there is no client-side filtering left to get wrong. `null` means the lookup could not be
 * made at all, which is a different fact from an empty result and is reported as one.
 */
export function riskFor(symbol: string, recorded: DivergenceRecord[] | null): Risk {
  // A failed or absent lookup is NOT a clean bill of health.
  if (recorded === null) {
    return { level: "unmeasured", divergences: 0, reason: "no measurement available" };
  }
  if (recorded.length === 0) {
    return {
      level: "unmeasured",
      divergences: 0,
      // Deliberately not "looks fine": Tempest has never watched this symbol diverge, which is
      // a statement about Tempest's records, not about the symbol.
      reason: "no recorded runs name this symbol",
    };
  }
  const where = attribution(symbol, recorded);
  const serious = recorded.filter((hit) => ESCALATES[hit.severity]).length;
  if (serious > 0) {
    return {
      level: "high",
      divergences: recorded.length,
      reason: `${plural(serious, "headline divergence")} recorded in ${where}`,
    };
  }
  return {
    level: "elevated",
    divergences: recorded.length,
    reason: `${plural(recorded.length, "divergence")} recorded in ${where}`,
  };
}

/**
 * The symbol a suggestion NAMES, or null when it names none.
 *
 * The editor's completion is `prefix + text`. With the offline document source that is always an
 * identifier, so the first version looked up the concatenation directly — and that quietly made
 * the badge inert for exactly the users who configured a local model, because a model answers
 * with real code (`ulateTotal(items)`, or `    return total`) and `calc    return total` matches
 * no qualname that has ever existed. The badge then said "no recorded runs name this symbol"
 * about a symbol it had never asked after: a true sentence about the wrong question.
 *
 * The leading identifier of the concatenation IS the symbol being completed, for both sources.
 * When there is none — the suggestion starts with punctuation or whitespace — there is no symbol
 * to ask about, and that is reported as its own kind of absence rather than as an empty result.
 */
export function symbolNamedBy(prefix: string, text: string): string | null {
  const match = /^[A-Za-z_$][A-Za-z0-9_$]*/.exec(prefix + text);
  return match === null ? null : match[0];
}

/** A suggestion that names no symbol: unmeasured, and honest about WHY it is unmeasured. */
export function namesNoSymbol(): Risk {
  return {
    level: "unmeasured",
    divergences: 0,
    reason: "this suggestion does not name a symbol",
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

/** Exposed so a test can prove the escalation table covers the whole wire vocabulary. */
export const ESCALATION_TABLE: Readonly<Record<Severity, boolean>> = ESCALATES;
