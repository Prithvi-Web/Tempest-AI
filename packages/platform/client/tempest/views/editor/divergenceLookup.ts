/**
 * Phase 20.3e — the measured side of the risk indicator.
 *
 * Asks the engine what divergences it has RECORDED FOR A SYMBOL. Nothing here judges; `risk.ts`
 * does that, and it is unit-tested. This file exists to keep the Boundary B call in one place
 * and to make the failure mode explicit: a lookup that fails returns `null`, which `riskFor`
 * renders as "unmeasured". It must never return `[]` on failure — an empty result means "the
 * engine has no record", and a failed call means "we do not know", and this product does not let
 * those two blur into each other.
 *
 * **It used to ask the wrong question.** The first version called `searchDivergences`, which is
 * FREE-TEXT search over an FTS5 index built on `detail`, `base_summary` and `head_summary`.
 * `qualname` is not in that index — it is a JOINed output column — and every `detail` string the
 * comparator writes is value-shaped ("return values differ", "stdout differs", "base crashed
 * (exit 1), head returned"). So a search for `calculateTotal` could only hit if a VALUE happened
 * to contain that text, which it does not: the badge returned zero rows for symbols Tempest had
 * watched diverge and rendered "unmeasured — no recorded runs name this symbol". The feature was
 * inert, and it failed in the direction that looks exactly like the honest answer, which is why
 * no test and no gate caught it. `divergencesForSymbol` asks about `targets.qualname` directly.
 */
import { commands, type SymbolDivergences } from "../../../../../desktop/src/generated/bindings";

import type { DivergenceRecord } from "./risk";

/** How many hits to consider. The badge counts occurrences, so a cap bounds the claim it makes. */
export const LOOKUP_LIMIT = 50;

type BindingResult =
  | { status: "ok"; data: SymbolDivergences }
  | { status: "error"; error: unknown };

export function divergenceLookup(
  lookup: (symbol: string, limit: number) => Promise<BindingResult> = (symbol, limit) =>
    commands.divergencesForSymbol(symbol, limit),
): (symbol: string) => Promise<DivergenceRecord[] | null> {
  return async (symbol) => {
    try {
      const result = await lookup(symbol, LOOKUP_LIMIT);
      if (result.status !== "ok") return null;
      // The hits arrive already selected BY SYMBOL and already typed — no `String()` widening,
      // which is what let `risk.ts` compare against severities the wire cannot carry.
      return result.data.hits;
    } catch {
      // "We could not ask" is not "there is nothing".
      return null;
    }
  };
}
