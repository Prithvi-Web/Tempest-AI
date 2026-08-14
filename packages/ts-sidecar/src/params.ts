/** Structural validation of RPC params — invalid shapes fail fast with INVALID_PARAMS. */
import type { ChangedFile, SelectTargetsParams } from "./analyze.ts";
import type { ValuePoolsParams } from "./pools.ts";
import { INVALID_PARAMS, RpcError } from "./rpc.ts";

function asRecord(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RpcError(INVALID_PARAMS, `${what} must be an object`);
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, what: string): string {
  if (typeof value !== "string" || value === "") {
    throw new RpcError(INVALID_PARAMS, `${what} must be a non-empty string`);
  }
  return value;
}

function asChangedFile(value: unknown, what: string): ChangedFile {
  const record = asRecord(value, what);
  const lines = record["changedLines"];
  if (!Array.isArray(lines) || lines.some((n) => typeof n !== "number" || !Number.isInteger(n))) {
    throw new RpcError(INVALID_PARAMS, `${what}.changedLines must be an array of integers`);
  }
  return { path: asString(record["path"], `${what}.path`), changedLines: lines as number[] };
}

export function parseSelectTargetsParams(params: unknown): SelectTargetsParams {
  const record = asRecord(params, "params");
  const changedFiles = record["changedFiles"];
  if (!Array.isArray(changedFiles)) {
    throw new RpcError(INVALID_PARAMS, "params.changedFiles must be an array");
  }
  return {
    projectRoot: asString(record["projectRoot"], "params.projectRoot"),
    changedFiles: changedFiles.map((f, i) => asChangedFile(f, `params.changedFiles[${i}]`)),
  };
}

export function parseValuePoolsParams(params: unknown): ValuePoolsParams {
  const record = asRecord(params, "params");
  return {
    projectRoot: asString(record["projectRoot"], "params.projectRoot"),
    filePath: asString(record["filePath"], "params.filePath"),
    symbol: asString(record["symbol"], "params.symbol"),
  };
}
