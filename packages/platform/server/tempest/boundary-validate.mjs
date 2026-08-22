// Boundary E's production validator (PLAN-V3 C2). LibreChat is JavaScript, so TypeScript
// types are advisory at runtime — every message crossing the socket is therefore checked HERE,
// in production, both directions, against the generated contract sets. Dependency-free by
// design: the vendored platform tree carries no node_modules, and a validator that needs an
// install step is a validator that silently isn't there.
//
// The checks enforce platform.schema.json (additionalProperties: false everywhere — unknown
// keys are rejected, not ignored) PLUS two rules the schema states in prose because JSON
// Schema expresses them awkwardly for typify: a response carries exactly one of result/error,
// and a result must match ITS method's result shape (checkResult). A mismatch is a structured
// refusal with a reason, never a swallowed exception (L15.3).
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

const RESULT_SHAPES = {
  "platform.ping": (result) => {
    const extra = onlyKeys(result, ["ok", "pid", "protocol_version", "node_version"]);
    if (extra) return extra;
    if (result.ok !== true) return "ok must be true";
    if (!Number.isInteger(result.pid) || result.pid < 0) return "pid must be a non-negative int";
    if (typeof result.protocol_version !== "string") return "protocol_version must be a string";
    if (typeof result.node_version !== "string") return "node_version must be a string";
    return null;
  },
  "platform.describe": (result) => {
    const extra = onlyKeys(result, ["protocol_version", "methods"]);
    if (extra) return extra;
    if (typeof result.protocol_version !== "string") return "protocol_version must be a string";
    if (!Array.isArray(result.methods) || result.methods.some((m) => !PLATFORM_METHODS.includes(m))) {
      return "methods must be an array of known PlatformMethods";
    }
    return null;
  },
  "platform.shutdown": (result) => {
    const extra = onlyKeys(result, ["ok"]);
    if (extra) return extra;
    return result.ok === true ? null : "ok must be true";
  },
  "platform.http": (result) => {
    const extra = onlyKeys(result, ["status", "content_type", "body_base64"]);
    if (extra) return extra;
    if (!Number.isInteger(result.status) || result.status < 100 || result.status > 599) {
      return "status must be an HTTP status integer";
    }
    if (typeof result.content_type !== "string") return "content_type must be a string";
    if (typeof result.body_base64 !== "string") return "body_base64 must be a string";
    return null;
  },
};

/** Per-method result-shape validation — the outbound half beyond the envelope.
 * @returns {{ok: true}|{ok: false, why: string}} */
export function checkResult(method, result) {
  const shape = RESULT_SHAPES[method];
  if (!shape) return { ok: false, why: `no result shape known for ${method}` };
  const why = shape(result);
  return why ? { ok: false, why: `${method} result: ${why}` } : { ok: true };
}
