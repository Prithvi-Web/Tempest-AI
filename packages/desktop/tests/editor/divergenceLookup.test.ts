/**
 * The lookup's ONE job beyond calling a command: never let a failure look like an empty result.
 */
import { describe, expect, it } from "vitest";

import { LOOKUP_LIMIT, divergenceLookup } from "../../../platform/client/tempest/views/editor/divergenceLookup";

import type { SymbolDivergence, SymbolDivergences } from "../../src/generated/bindings";

function hit(over: Partial<SymbolDivergence> = {}): SymbolDivergence {
  return {
    divergence_id: 1,
    target_id: 1,
    run_id: 7,
    module: "billing",
    qualname: "calculateTotal",
    divergence_class: "RETURN_VALUE",
    severity: "HEADLINE",
    detail: "return values differ",
    ...over,
  };
}

function ok(hits: SymbolDivergence[]): { status: "ok"; data: SymbolDivergences } {
  return { status: "ok", data: { symbol: "calculateTotal", hits } };
}

describe("divergenceLookup", () => {
  it("asks the by-symbol endpoint, with the cap it documents", async () => {
    const asked: Array<[string, number]> = [];
    const lookup = divergenceLookup(async (symbol, limit) => {
      asked.push([symbol, limit]);
      return ok([hit()]);
    });
    const records = await lookup("calculateTotal");
    expect(asked).toEqual([["calculateTotal", LOOKUP_LIMIT]]);
    expect(records).toEqual([hit()]);
  });

  it("passes the severity through UNWIDENED", async () => {
    // `String(hit.severity)` is what defeated the compiler last time: it turned a closed union
    // into `string`, and a comparison against a value the wire cannot carry then type-checked.
    const lookup = divergenceLookup(async () => ok([hit({ severity: "HEADLINE" })]));
    const records = await lookup("calculateTotal");
    expect(records?.[0]?.severity).toBe("HEADLINE");
  });

  it("answers null — not [] — when the command reports an error", async () => {
    const lookup = divergenceLookup(async () => ({ status: "error", error: { code: -1 } }));
    expect(await lookup("calculateTotal")).toBeNull();
  });

  it("answers null — not [] — when the call throws", async () => {
    const lookup = divergenceLookup(async () => {
      throw new Error("the bridge is down");
    });
    expect(await lookup("calculateTotal")).toBeNull();
  });

  it("answers null when there is no host to ask — the default caller, exercised", async () => {
    // Called with no injected lookup, so the real generated binding runs. Under vitest there is
    // no Tauri IPC, so it throws — and the contract is that a lookup which cannot be MADE is
    // null, never []. This is the arm the coverage gate named, and it is worth a test rather
    // than a pragma: it is exactly the state of a webview whose host has gone away.
    expect(await divergenceLookup()("calculateTotal")).toBeNull();
  });

  it("answers [] when the engine genuinely has no record", async () => {
    const lookup = divergenceLookup(async () => ok([]));
    expect(await lookup("neverProved")).toEqual([]);
  });
});
