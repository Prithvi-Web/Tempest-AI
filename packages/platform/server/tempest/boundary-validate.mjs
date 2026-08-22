// Boundary E's production validator (PLAN-V3 C2). LibreChat is JavaScript, so TypeScript
// types are advisory at runtime — every message crossing the socket is therefore checked HERE,
// in production, both directions, against the generated contract sets. Dependency-free by
// design: the vendored platform tree carries no node_modules, and a validator that needs an
// install step is a validator that silently isn't there.
//
// The checks mirror platform.schema.json exactly (additionalProperties: false everywhere —
// unknown keys are rejected, not ignored). A mismatch is a structured refusal with a reason,
// never a swallowed exception (L15.3).
import { PLATFORM_METHODS, REASON_CODES } from "./generated/platform-schema.mjs";

const INT32_MAX = 2147483647;
const INT32_MIN = -2147483648;

const isPlainObject = (value) =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isId = (value) => Number.isInteger(value) && value >= 0 && value <= INT32_MAX;

const onlyKeys = (value, allowed) => {
  const extra = Object.keys(value).filter((key) => !allowed.includes(key));
  return extra.length === 0 ? null : `unknown field(s): ${extra.join(", ")}`;
};

/** @returns {{ok: true}|{ok: false, why: string}} */
export function checkRequest(value) {
  if (!isPlainObject(value)) return { ok: false, why: "request is not an object" };
  const extra = onlyKeys(value, ["jsonrpc", "id", "method", "params"]);
  if (extra) return { ok: false, why: extra };
  if (value.jsonrpc !== "2.0") return { ok: false, why: "jsonrpc must be the string '2.0'" };
  if (!isId(value.id)) return { ok: false, why: "id must be an integer in [0, 2^31)" };
  if (typeof value.method !== "string" || !PLATFORM_METHODS.includes(value.method)) {
    return { ok: false, why: `method must be one of: ${PLATFORM_METHODS.join(", ")}` };
  }
  if (!isPlainObject(value.params)) return { ok: false, why: "params must be an object" };
  return { ok: true };
}

/** @returns {{ok: true}|{ok: false, why: string}} */
export function checkResponse(value) {
  if (!isPlainObject(value)) return { ok: false, why: "response is not an object" };
  const extra = onlyKeys(value, ["jsonrpc", "id", "result", "error"]);
  if (extra) return { ok: false, why: extra };
  if (value.jsonrpc !== "2.0") return { ok: false, why: "jsonrpc must be the string '2.0'" };
  if (!isId(value.id)) return { ok: false, why: "id must be an integer in [0, 2^31)" };
  const hasResult = "result" in value;
  const hasError = "error" in value;
  if (hasResult === hasError) {
    return { ok: false, why: "exactly one of result/error must be present" };
  }
  if (hasResult && !isPlainObject(value.result)) {
    return { ok: false, why: "result must be an object" };
  }
  if (hasError) {
    const error = value.error;
    if (!isPlainObject(error)) return { ok: false, why: "error must be an object" };
    const extraErr = onlyKeys(error, ["code", "message", "diagnostic_id", "reason_code", "data"]);
    if (extraErr) return { ok: false, why: `error carries ${extraErr}` };
    if (!Number.isInteger(error.code) || error.code < INT32_MIN || error.code > INT32_MAX) {
      return { ok: false, why: "error.code must be an int32" };
    }
    if (typeof error.message !== "string") {
      return { ok: false, why: "error.message must be a string" };
    }
    if (typeof error.diagnostic_id !== "string" || error.diagnostic_id.length === 0) {
      return { ok: false, why: "error.diagnostic_id is required (L15.3)" };
    }
    if ("reason_code" in error && !REASON_CODES.includes(error.reason_code)) {
      return { ok: false, why: "error.reason_code is not a known ReasonCode" };
    }
    if ("data" in error && !isPlainObject(error.data)) {
      return { ok: false, why: "error.data must be an object" };
    }
  }
  return { ok: true };
}
