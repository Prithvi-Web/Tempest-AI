/**
 * Newline-delimited JSON-RPC 2.0 framing + dispatch. The Python core speaks this over stdio.
 * Analysis methods (ts-morph target selection, type→arbitrary compilation) register here in Phase 3.
 */

export interface RpcRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: string;
  params?: unknown;
}

export interface RpcSuccess {
  jsonrpc: "2.0";
  id: number | string;
  result: unknown;
}

export interface RpcFailure {
  jsonrpc: "2.0";
  id: number | string | null;
  error: { code: number; message: string };
}

export type RpcResponse = RpcSuccess | RpcFailure;

export type MethodHandler = (params: unknown) => unknown | Promise<unknown>;

export const PARSE_ERROR = -32700;
export const INVALID_REQUEST = -32600;
export const METHOD_NOT_FOUND = -32601;
export const INVALID_PARAMS = -32602;
export const INTERNAL_ERROR = -32603;

/** Throw from a handler to control the JSON-RPC error code (e.g. INVALID_PARAMS). */
export class RpcError extends Error {
  // no TS parameter properties here — the sidecar runs under Node's strip-only mode,
  // which rejects non-erasable syntax
  readonly code: number;

  constructor(code: number, message: string) {
    super(message);
    this.name = "RpcError";
    this.code = code;
  }
}

export class Dispatcher {
  private readonly methods = new Map<string, MethodHandler>();

  register(method: string, handler: MethodHandler): void {
    this.methods.set(method, handler);
  }

  /** Handle one newline-delimited frame; always returns a serializable response. */
  async dispatch(line: string): Promise<RpcResponse> {
    let req: RpcRequest;
    try {
      req = JSON.parse(line) as RpcRequest;
    } catch {
      return { jsonrpc: "2.0", id: null, error: { code: PARSE_ERROR, message: "parse error" } };
    }
    if (req.jsonrpc !== "2.0" || typeof req.method !== "string" || req.id === undefined) {
      return {
        jsonrpc: "2.0",
        id: null,
        error: { code: INVALID_REQUEST, message: "invalid request" },
      };
    }
    const handler = this.methods.get(req.method);
    if (!handler) {
      return {
        jsonrpc: "2.0",
        id: req.id,
        error: { code: METHOD_NOT_FOUND, message: `method not found: ${req.method}` },
      };
    }
    try {
      return { jsonrpc: "2.0", id: req.id, result: await handler(req.params) };
    } catch (err) {
      const code = err instanceof RpcError ? err.code : INTERNAL_ERROR;
      const message = err instanceof Error ? err.message : String(err);
      return { jsonrpc: "2.0", id: req.id, error: { code, message } };
    }
  }
}
