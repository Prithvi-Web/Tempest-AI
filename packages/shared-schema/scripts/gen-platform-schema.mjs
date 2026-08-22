// Boundary E root of truth (master prompt §7, PLAN-V3 C2): the schema of every message
// crossing Rust host ↔ Node platform sidecar. Domain values stay Pydantic-rooted — the
// ReasonCode definition below is COPIED from domain-schema.json (itself generated from
// openapi.json, itself generated from Pydantic), never hand-written here. Adding a ReasonCode
// in Python therefore changes THIS document, the typify-generated Rust, and the generated
// Node schema module in the same `make gen-contracts` run — and an uncommitted regeneration
// is a red `verify-contract`. That is the enum-drift property the C2 gate proves.
//
// Outputs (both committed, both drift-gated):
//   packages/shared-schema/platform.schema.json                       (the contract)
//   packages/platform/server/tempest/generated/platform-schema.mjs    (the Node side's copy —
//     a declared seam path, dependency-free, consumed by the boundary endpoint's validator)
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const domain = JSON.parse(readFileSync(join(here, "..", "domain-schema.json"), "utf8"));

const reasonCode = domain.$defs.ReasonCode;
if (!reasonCode || !Array.isArray(reasonCode.enum)) {
  throw new Error("domain-schema.json carries no ReasonCode enum — boundary C moved; fix me");
}

// The C2 method set is the boundary's lifecycle. Service methods arrive with C5 (ADR-0075's
// thin client) and each lands here first — the schema leads, the code follows.
const PLATFORM_METHODS = ["platform.ping", "platform.describe", "platform.shutdown"];
const PROTOCOL_VERSION = "e1";

const sortDeep = (node) => {
  if (Array.isArray(node)) return node.map(sortDeep);
  if (node && typeof node === "object") {
    return Object.fromEntries(
      Object.keys(node)
        .sort()
        .map((key) => [key, sortDeep(node[key])]),
    );
  }
  return node;
};

const document = sortDeep({
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "TempestPlatformBoundary",
  description:
    "Boundary E (Rust host <-> Node platform sidecar), JSON-RPC 2.0 over a Unix domain " +
    "socket with Content-Length framing. Generated — do not edit; run `make gen-contracts`.",
  type: "object",
  additionalProperties: false,
  $defs: {
    ProtocolVersion: {
      type: "string",
      enum: [PROTOCOL_VERSION],
      description: "Bumped only by a commit that regenerates every consumer.",
    },
    PlatformMethod: {
      type: "string",
      enum: PLATFORM_METHODS,
      description: "Every method that may cross boundary E. C5 extends this list.",
    },
    // Pydantic-rooted (boundary C): copied verbatim from domain-schema.json by the generator.
    ReasonCode: reasonCode,
    PlatformRequest: {
      type: "object",
      additionalProperties: false,
      required: ["jsonrpc", "id", "method", "params"],
      properties: {
        jsonrpc: { type: "string", enum: ["2.0"] },
        id: { type: "integer", minimum: 0, maximum: 2147483647 },
        method: { $ref: "#/$defs/PlatformMethod" },
        params: { type: "object" },
      },
    },
    PlatformError: {
      type: "object",
      additionalProperties: false,
      required: ["code", "message", "diagnostic_id"],
      properties: {
        code: { type: "integer", minimum: -2147483648, maximum: 2147483647 },
        message: { type: "string" },
        diagnostic_id: {
          type: "string",
          description:
            "L15.3: every surfaced failure carries an id a human can quote and a log can find.",
        },
        reason_code: { $ref: "#/$defs/ReasonCode" },
        data: { type: "object" },
      },
    },
    PlatformResponse: {
      type: "object",
      additionalProperties: false,
      description:
        "Exactly ONE of result/error is present — stated in prose because a oneOf here " +
        "produces hostile typify output; boundary-validate.mjs enforces it at runtime, " +
        "both directions, in production.",
      required: ["jsonrpc", "id"],
      properties: {
        jsonrpc: { type: "string", enum: ["2.0"] },
        id: { type: "integer", minimum: 0, maximum: 2147483647 },
        result: { type: "object" },
        error: { $ref: "#/$defs/PlatformError" },
      },
    },
    PingResult: {
      type: "object",
      additionalProperties: false,
      required: ["ok", "pid", "protocol_version", "node_version"],
      properties: {
        ok: { type: "boolean", enum: [true] },
        pid: { type: "integer", minimum: 0, maximum: 2147483647 },
        protocol_version: { $ref: "#/$defs/ProtocolVersion" },
        node_version: { type: "string" },
      },
    },
    DescribeResult: {
      type: "object",
      additionalProperties: false,
      required: ["protocol_version", "methods"],
      properties: {
        protocol_version: { $ref: "#/$defs/ProtocolVersion" },
        methods: { type: "array", items: { $ref: "#/$defs/PlatformMethod" } },
      },
    },
    ShutdownResult: {
      type: "object",
      additionalProperties: false,
      required: ["ok"],
      properties: { ok: { type: "boolean", enum: [true] } },
    },
  },
});

const schemaTarget = join(here, "..", "platform.schema.json");
writeFileSync(schemaTarget, JSON.stringify(document, null, 2) + "\n");

const seamDir = join(here, "..", "..", "platform", "server", "tempest", "generated");
mkdirSync(seamDir, { recursive: true });
const moduleBody = `// Generated by gen-platform-schema.mjs — do not edit; run \`make gen-contracts\`.
// Boundary E's Node-side contract copy: the schema object plus the enum value sets the
// dependency-free validator in ../boundary.mjs enforces IN PRODUCTION, both directions.
export const PROTOCOL_VERSION = ${JSON.stringify(PROTOCOL_VERSION)};
export const PLATFORM_METHODS = Object.freeze(${JSON.stringify(PLATFORM_METHODS)});
export const REASON_CODES = Object.freeze(${JSON.stringify(reasonCode.enum)});
export const SCHEMA = Object.freeze(${JSON.stringify(document, null, 2)});
`;
writeFileSync(join(seamDir, "platform-schema.mjs"), moduleBody);

// The TS face of the same artifact (master prompt §7: "Rust + TS + JSDoc"): typed
// declarations for TS consumers (the C3 webview build), same values, zero duplication.
const dtsBody = `// Generated by gen-platform-schema.mjs — do not edit; run \`make gen-contracts\`.
export declare const PROTOCOL_VERSION: ${JSON.stringify(PROTOCOL_VERSION)};
export declare const PLATFORM_METHODS: readonly [${PLATFORM_METHODS.map((m) => JSON.stringify(m)).join(", ")}];
export declare const REASON_CODES: readonly [${reasonCode.enum.map((r) => JSON.stringify(r)).join(", ")}];
export declare const SCHEMA: Readonly<Record<string, unknown>>;
export type PlatformMethod = (typeof PLATFORM_METHODS)[number];
export type ReasonCode = (typeof REASON_CODES)[number];
`;
writeFileSync(join(seamDir, "platform-schema.d.mts"), dtsBody);

console.log(
  `gen-platform-schema: ${PLATFORM_METHODS.length} methods, ` +
    `${reasonCode.enum.length} reason codes -> platform.schema.json + seam module`,
);
