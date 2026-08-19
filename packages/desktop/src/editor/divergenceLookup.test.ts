/**
 * The measured lookup behind the risk badge (Phase 20.3e).
 *
 * The property under test is the distinction this product refuses to blur: an EMPTY result means
 * "the engine has no record of this symbol"; a FAILED call means "we do not know". Returning `[]`
 * for the second would let a broken lookup render as a clean history.
 */
import { describe, expect, it, vi } from "vitest";

import { LOOKUP_LIMIT, divergenceLookup } from "./divergenceLookup";

import type { SearchHit } from "../generated/bindings";

vi.mock("../generated/bindings", () => ({
  commands: { searchDivergences: vi.fn(async () => ({ status: "ok", data: { hits: [] } })) },
}));

/**
 * A wire hit. `severity` and `divergence_class` are generated ENUMS on the real boundary; this
 * lookup only forwards them as strings, so the cast keeps the test about the mapping rather than
 * about enum spelling — the enums themselves are pinned by the contract gate.
 */
const hit = (qualname: string, severity: string): SearchHit =>
  ({
    qualname,
    severity,
    divergence_class: "RETURN_VALUE",
    divergence_id: 1,
    module: "pkg",
    run_id: 1,
    snippet: "",
    target_id: 1,
  }) as unknown as SearchHit;

describe("divergenceLookup", () => {
  it("maps engine hits onto the shape risk.ts consumes", async () => {
    const lookup = divergenceLookup(async () => ({
      status: "ok",
      data: { hits: [hit("pkg.f", "HIGH")] },
    }));
    await expect(lookup("pkg.f")).resolves.toEqual([
      { qualname: "pkg.f", severity: "HIGH", divergence_class: "RETURN_VALUE" },
    ]);
  });

  it("passes the symbol and a bounded limit", async () => {
    const search = vi.fn(async () => ({ status: "ok", data: { hits: [] } }));
    await divergenceLookup(search)("pkg.calculateTotal");
    expect(search).toHaveBeenCalledWith("pkg.calculateTotal", LOOKUP_LIMIT);
  });

  it("returns an empty list when the engine genuinely has no record", async () => {
    const lookup = divergenceLookup(async () => ({ status: "ok", data: { hits: [] } }));
    await expect(lookup("pkg.f")).resolves.toEqual([]);
  });

  it("returns NULL — not an empty list — when the call errors", async () => {
    // The whole point: `[]` would render as "no divergences recorded", i.e. a clean history for
    // a symbol nobody managed to ask about.
    const lookup = divergenceLookup(async () => ({ status: "error" }));
    await expect(lookup("pkg.f")).resolves.toBeNull();
  });

  it("returns NULL when the call has no data", async () => {
    const lookup = divergenceLookup(async () => ({ status: "ok" }));
    await expect(lookup("pkg.f")).resolves.toBeNull();
  });

  it("returns NULL when the invoke throws", async () => {
    const lookup = divergenceLookup(async () => {
      throw new Error("ipc down");
    });
    await expect(lookup("pkg.f")).resolves.toBeNull();
  });

  it("uses the generated binding by default", async () => {
    const { commands } = await import("../generated/bindings");
    await expect(divergenceLookup()("pkg.f")).resolves.toEqual([]);
    expect(commands.searchDivergences).toHaveBeenCalledWith("pkg.f", LOOKUP_LIMIT);
  });
});
