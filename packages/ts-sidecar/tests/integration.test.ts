/** Dispatcher-level integration: the exact newline-JSON frames the Python core sends/receives. */
import { afterEach, describe, expect, it } from "vitest";

import { buildDispatcher } from "../src/index.ts";
import { INVALID_PARAMS } from "../src/rpc.ts";
import { cleanupProjects, makeProject } from "./helpers.ts";

afterEach(cleanupProjects);

interface Frame {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string };
}

/** One full frame round-trip: serialized request line in, serialized response line back out. */
async function roundTrip(method: string, params: unknown, id: number): Promise<Frame> {
  const line = JSON.stringify({ jsonrpc: "2.0", id, method, params });
  const response = await buildDispatcher().dispatch(line);
  return JSON.parse(JSON.stringify(response)) as Frame;
}

describe("dispatcher integration", () => {
  it("serves selectTargets over a real on-disk project", async () => {
    const root = makeProject({
      "src/mod.ts": [
        "export function add(a: number, b: number): number {",
        "  return a + b;",
        "}",
        "function hidden(a: number): number {",
        "  return a - 1;",
        "}",
      ].join("\n"),
    });
    const frame = await roundTrip(
      "selectTargets",
      { projectRoot: root, changedFiles: [{ path: "src/mod.ts", changedLines: [2, 5] }] },
      7,
    );
    expect(frame.id).toBe(7);
    expect(frame.error).toBeUndefined();
    const { targets } = frame.result as {
      targets: { symbol: string; classification: string; reasonDetail?: string }[];
    };
    expect(targets.map((t) => [t.symbol, t.classification])).toEqual([
      ["add", "PURE_CANDIDATE"],
      ["hidden", "UNREACHABLE"],
    ]);
    expect(targets[1]?.reasonDetail).toContain("not exported; cannot be imported in isolation");
  });

  it("serves valuePools and the frame survives JSON serialization (specials stay strings)", async () => {
    const root = makeProject({
      "src/mod.ts": "export function half(n: number): number { return n / 2; }",
    });
    const frame = await roundTrip(
      "valuePools",
      { projectRoot: root, filePath: "src/mod.ts", symbol: "half" },
      8,
    );
    expect(frame.error).toBeUndefined();
    const { parameters } = frame.result as {
      parameters: { values: unknown[]; specials: string[] }[];
    };
    expect(parameters[0]?.values).toContain(2147483647);
    expect(parameters[0]?.specials).toEqual(["NaN", "Infinity", "-Infinity"]);
  });

  it("rejects malformed params with INVALID_PARAMS, not a crash", async () => {
    const missing = await roundTrip("selectTargets", { changedFiles: [] }, 9);
    expect(missing.error?.code).toBe(INVALID_PARAMS);
    expect(missing.error?.message).toContain("projectRoot");

    const badLines = await roundTrip(
      "selectTargets",
      { projectRoot: "/tmp", changedFiles: [{ path: "x.ts", changedLines: ["1"] }] },
      10,
    );
    expect(badLines.error?.code).toBe(INVALID_PARAMS);

    const badPools = await roundTrip("valuePools", { projectRoot: "/tmp" }, 11);
    expect(badPools.error?.code).toBe(INVALID_PARAMS);
  });
});
