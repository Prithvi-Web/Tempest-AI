/**
 * Dev-mode deep validation at Boundary B (CLAUDE.md §9b, HANDOFF-WORLD-CLASS §1.3).
 *
 * serde on the Rust side already rejects shape drift (code -2); this is the SECOND net, in
 * the webview: every command result is validated against the generated JSON Schema
 * (`packages/shared-schema/domain-schema.json` — the same document typify and
 * json-schema-to-typescript consume), so a generator regression or a hand-edited binding
 * fails loudly the moment it produces a value, not three views later.
 *
 * Dev builds only: hooks.ts imports this module dynamically behind `import.meta.env.DEV`,
 * so production bundles carry neither ajv nor the schema. The E2E suite runs against the
 * dev server, which makes every one of its command calls a live contract check — and the
 * console-clean gate turns any violation into a failed suite.
 */
import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import domainSchema from "../../shared-schema/domain-schema.json";

// Same construction as scripts/roundtrip-validate.mjs — one validator config, two nets.
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats.default(ajv);
ajv.addSchema(domainSchema, "domain");

const def = (name: string): object => ({ $ref: `domain#/$defs/${name}` });

const AI_KEY_STATUS: object = {
  type: "object",
  required: ["configured", "last4"],
  properties: {
    configured: { type: "boolean" },
    last4: { type: ["string", "null"] },
  },
};
const listOf = (name: string): object => ({ type: "array", items: def(name) });

/** Command → result schema. `getDivergenceRepro` is the one transport-level type defined in
 * the Rust host (commands.rs `ReproSource`), not a domain object — validated inline. */
const RESULT_SCHEMAS: Record<string, object> = {
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
  // Host-level type (commands.rs AiKeyStatus, like ReproSource): {configured, last4} is ALL
  // the webview may ever learn about the stored key (L9).
  aiKeyStatus: AI_KEY_STATUS,
  setAiKey: AI_KEY_STATUS,
  clearAiKey: AI_KEY_STATUS,
  searchDivergences: def("SearchResults"),
  cancelRun: def("CancelAccepted"),
  listLogRecords: listOf("LogRecordOut"),
  getSettings: def("SettingsOut"),
  updateSettings: def("SettingsOut"),
  testAiKey: def("AiKeyTestResult"),
  syncPush: def("SyncReport"),
  exportDiagnostics: def("DiagnosticBundle"),
  // Host-side action with no payload: the contract IS "nothing came back".
  revealInDataDir: { type: "null" },
  getWatchStatus: def("WatchStatus"),
  startWatch: def("WatchStatus"),
  stopWatch: def("WatchStatus"),
};

const compiled = new Map<string, ValidateFunction>();

export function assertValidCommandResult(command: string, data: unknown): void {
  const schema = RESULT_SCHEMAS[command];
  if (schema === undefined) {
    throw new Error(`devValidate: no result schema registered for command ${command}`);
  }
  let validate = compiled.get(command);
  if (validate === undefined) {
    validate = ajv.compile(schema);
    compiled.set(command, validate);
  }
  if (!validate(data)) {
    const detail = ajv.errorsText(validate.errors, { dataVar: command });
    // Loud on both channels: the console (fails the E2E console-clean gate) and the caller
    // (the view lands in its error state instead of rendering off-contract data).
    console.error(`Boundary B contract violation: ${detail}`);
    throw new Error(`Boundary B contract violation: ${detail}`);
  }
}

declare global {
  interface Window {
    /** Dev-only hook so the E2E suite can prove the net actually catches (07-spec). */
    __TEMPEST_DEV_VALIDATE__?: typeof assertValidCommandResult;
  }
}

window.__TEMPEST_DEV_VALIDATE__ = assertValidCommandResult;
