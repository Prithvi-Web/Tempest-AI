import { describe, expect, it } from "vitest";

import { buildDispatcher } from "../src/index.js";
import { Dispatcher, INTERNAL_ERROR, METHOD_NOT_FOUND, PARSE_ERROR } from "../src/rpc.js";

describe("JSON-RPC dispatcher", () => {
  it("answers ping with sidecar identity", async () => {
    const resp = await buildDispatcher().dispatch(
      JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
    );
    expect(resp).toEqual({
      jsonrpc: "2.0",
      id: 1,
      result: { pong: true, sidecar: "@tempest/ts-sidecar", version: "0.1.0" },
    });
  });

  it("rejects malformed JSON with PARSE_ERROR", async () => {
    const resp = await new Dispatcher().dispatch("{nope");
    expect(resp).toMatchObject({ error: { code: PARSE_ERROR } });
  });

  it("rejects unknown methods with METHOD_NOT_FOUND and echoes the id", async () => {
    const resp = await new Dispatcher().dispatch(
      JSON.stringify({ jsonrpc: "2.0", id: "abc", method: "nope" }),
    );
    expect(resp).toMatchObject({ id: "abc", error: { code: METHOD_NOT_FOUND } });
  });

  it("maps handler exceptions to INTERNAL_ERROR without crashing the loop", async () => {
    const d = new Dispatcher();
    d.register("boom", () => {
      throw new Error("kaput");
    });
    const resp = await d.dispatch(JSON.stringify({ jsonrpc: "2.0", id: 2, method: "boom" }));
    expect(resp).toMatchObject({ id: 2, error: { code: INTERNAL_ERROR, message: "kaput" } });
  });

  it("passes params through to the handler", async () => {
    const d = new Dispatcher();
    d.register("echo", (params) => params);
    const resp = await d.dispatch(
      JSON.stringify({ jsonrpc: "2.0", id: 3, method: "echo", params: { a: [1, 2] } }),
    );
    expect(resp).toMatchObject({ id: 3, result: { a: [1, 2] } });
  });
});
