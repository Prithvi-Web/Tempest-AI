/**
 * Phase 20.3e — the measured side of the risk indicator.
 *
 * Asks the engine what divergences it has RECORDED for a symbol. Nothing here judges; `risk.ts`
 * does that, and it is unit-tested. This file exists to keep the Boundary B call in one place
 * and to make the failure mode explicit: a lookup that fails returns `null`, which `riskFor`
 * renders as "unmeasured". It must never return `[]` on failure — an empty result means "the
 * engine has no record", and a failed call means "we do not know", and this product does not let
 * those two blur into each other.
 */
import { commands, type SearchHit } from "../generated/bindings";

import type { DivergenceRecord } from "./risk";

/** How many hits to consider. The badge counts occurrences, so a cap bounds the claim it makes. */
export const LOOKUP_LIMIT = 50;

export function divergenceLookup(
  search: (q: string, limit: number) => Promise<{ status: string; data?: { hits: SearchHit[] } }> = (
    q,
    limit,
  ) => commands.searchDivergences(q, limit),
): (symbol: string) => Promise<DivergenceRecord[] | null> {
  return async (symbol) => {
    try {
      const result = await search(symbol, LOOKUP_LIMIT);
      if (result.status !== "ok" || result.data === undefined) return null;
      return result.data.hits.map((hit) => ({
        qualname: hit.qualname,
        severity: String(hit.severity),
        divergence_class: String(hit.divergence_class),
      }));
    } catch {
      // "We could not ask" is not "there is nothing".
      return null;
    }
  };
}
