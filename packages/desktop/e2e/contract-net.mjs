/**
 * Boundary B deep validation, relocated into the bridge (ADR-0077 / CLAUDE.md §9b).
 *
 * The legacy webview carried this net itself (src/devValidate.ts, behind import.meta.env.DEV):
 * every command result checked against the generated domain schema, so a generator regression
 * fails the moment it produces a value. The platform client's seam copy deliberately dropped
 * ajv from the page (see tempest/views/hooks.ts) — so the net moves HERE, to the harness
 * process that already stands between the page and the engine. Same schema document, same
 * validator configuration (scripts/roundtrip-validate.mjs), same two-net design: serde in the
 * Rust host is the first net, this is the second, and every E2E command call runs through it.
 *
 * On a violation the reply becomes an in-band engine-shaped error (`{code, kind:"contract",
 * message}` — the shim rethrows it, typedError turns it into `{status:"error"}`, the view
 * lands in its error state instead of rendering off-contract data) AND the violation is
 * appended to a ledger the 07 spec reads over `/admin/contract-ledger`.
 *
 * `corruptNext(operation)` scripts ONE corruption: the next reply for that operation is
 * replaced with an off-contract value before validation. That is the 07 spec's probe — the
 * proof that the net catches, not merely runs.
 *
 * ajv is loaded via createRequire from this package's node_modules (the bridge itself stays
 * dependency-free; ajv is already a desktop devDependency for the legacy net).
 */

import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { Ajv2020 } = require("ajv/dist/2020.js");
const addFormats = require("ajv-formats");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const domainSchema = require(
  path.resolve(HERE, "..", "..", "shared-schema", "domain-schema.json"),
);

// Same construction as devValidate.ts and scripts/roundtrip-validate.mjs — one validator
// config, one truth.
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats.default ? addFormats.default(ajv) : addFormats(ajv);
ajv.addSchema(domainSchema, "domain");

const def = (name) => ({ $ref: `domain#/$defs/${name}` });
const listOf = (name) => ({ type: "array", items: def(name) });

/**
 * Operation → result schema, transcribed from src/devValidate.ts RESULT_SCHEMAS with two
 * mechanical differences: keys are ENGINE OPERATION names (the bridge validates replies, and
 * `list_log_records` maps to the operation `listLogs`), and the host-only commands the bridge
 * never carries (ai_key_*, reveal_in_data_dir, local_completion, lsp_hover, editor runners,
 * read_project_file) have no row — the shim answers those without an engine behind them.
 * `getDivergenceRepro` stays the one transport-level type defined in the Rust host.
 */
const RESULT_SCHEMAS = {
  getHealth: def("HealthResponse"),
  listRuns: def("Page_RunSummary_"),
  getRun: def("RunDetail"),
  listRunEvents: listOf("RunEventOut"),
  getTarget: def("TargetDetail"),
  getDivergence: def("DivergenceDetail"),
  getDivergenceRepro: {
    type: "object",
    required: ["content_type", "text"],
    properties: { content_type: { type: "string" }, text: { type: "string" } },
  },
  startLocalProve: def("RunCreated"),
  composeChange: def("ComposeView"),
  cancelRun: def("CancelAccepted"),
  searchDivergences: def("SearchResults"),
  divergencesForSymbol: def("SymbolDivergences"),
  listLogs: listOf("LogRecordOut"),
  getSettings: def("SettingsOut"),
  updateSettings: def("SettingsOut"),
  testAiKey: def("AiKeyTestResult"),
  syncPush: def("SyncReport"),
  exportDiagnostics: def("DiagnosticBundle"),
  getWatchStatus: def("WatchStatus"),
  startWatch: def("WatchStatus"),
  stopWatch: def("WatchStatus"),
  reportUiError: def("UiErrorRecorded"),
  startDemoProve: def("RunCreated"),
};

const compiled = new Map();

/** Violations recorded since bridge boot, oldest first — the 07 spec's evidence. */
export const ledger = [];

let corruption = null; // operation name whose NEXT reply gets corrupted, or null

export function corruptNext(operation) {
  corruption = operation;
}

/**
 * Validate one engine reply. Returns `{ok: true, data}` (data possibly corrupted when
 * scripted — which then fails validation by construction) or `{ok: false, failure}` where
 * failure is the engine-shaped error the shim rethrows.
 *
 * An operation with no registered schema is itself a contract violation: the legacy net
 * threw on unknown commands, and a bridge command added without a schema row would otherwise
 * silently opt out of the net.
 */
export function checkContract(operation, data) {
  if (corruption === operation) {
    corruption = null;
    // Off-contract for every registered schema: objects miss their required fields, arrays
    // fail the type, and the corruption is unmistakable in the ajv detail.
    data = { __corrupted_by_e2e__: true };
  }
  const schema = RESULT_SCHEMAS[operation];
  if (schema === undefined) {
    const failure = {
      code: -32097,
      kind: "contract",
      message: `Boundary B contract violation: no result schema registered for ${operation}`,
    };
    ledger.push({ operation, detail: failure.message, at: new Date().toISOString() });
    return { ok: false, failure };
  }
  let validate = compiled.get(operation);
  if (validate === undefined) {
    validate = ajv.compile(schema);
    compiled.set(operation, validate);
  }
  if (!validate(data)) {
    const detail = ajv.errorsText(validate.errors, { dataVar: operation });
    const failure = {
      code: -32097,
      kind: "contract",
      message: `Boundary B contract violation: ${detail}`,
    };
    ledger.push({ operation, detail, at: new Date().toISOString() });
    return { ok: false, failure };
  }
  return { ok: true, data };
}
