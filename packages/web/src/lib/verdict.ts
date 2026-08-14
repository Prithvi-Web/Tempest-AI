/**
 * Exhaustive helpers over the generated enum unions (CLAUDE.md §9).
 *
 * Every union here is imported from the generated schema — never restated. Every switch ends in
 * an `assertNever` guard, so adding a variant to a Python enum breaks this file's typecheck
 * until the UI handles it. That is desired.
 */
import type { components } from "@tempest/shared-schema/types";

type Schemas = components["schemas"];

export type Verdict = Schemas["Verdict"];
export type DivergenceClass = Schemas["DivergenceClass"];
export type ReasonCode = Schemas["ReasonCode"];
export type Severity = Schemas["Severity"];
export type TargetClassification = Schemas["TargetClassification"];
export type RunStatus = Schemas["RunStatus"];
export type Lang = Schemas["Lang"];
export type ErrorCode = Schemas["ErrorCode"];
export type ErrorEnvelope = Schemas["ErrorEnvelope"];

export function assertNever(value: never): never {
  throw new Error(`unhandled enum variant: ${String(value)}`);
}

/* ---------------------------------------------------------------- Verdict */

/** Exhaustive record — a new Python `Verdict` variant fails this object literal. */
const VERDICT_ORDER: Record<Verdict, number> = {
  DIVERGENT: 0,
  EQUIVALENT_UNDER_BUDGET: 1,
  UNPROVEN: 2,
  ERROR: 3,
};

export const ALL_VERDICTS = (Object.keys(VERDICT_ORDER) as Verdict[]).sort(
  (a, b) => VERDICT_ORDER[a] - VERDICT_ORDER[b],
);

export function parseVerdict(value: string | null | undefined): Verdict | undefined {
  return ALL_VERDICTS.find((v) => v === value);
}

export function verdictChipClass(verdict: Verdict): string {
  switch (verdict) {
    case "DIVERGENT":
      return "border-divergent text-divergent";
    case "EQUIVALENT_UNDER_BUDGET":
      return "border-equivalent text-equivalent";
    case "UNPROVEN":
      return "border-unproven text-unproven";
    case "ERROR":
      return "border-error text-error";
    default:
      return assertNever(verdict);
  }
}

/** One honest sentence per verdict (Law L2 — the four words above are the whole vocabulary). */
export function verdictNote(verdict: Verdict): string {
  switch (verdict) {
    case "DIVERGENT":
      return "at least one input produced differing observable behavior — evidence attached";
    case "EQUIVALENT_UNDER_BUDGET":
      return "identical behavior across the exercised inputs; this is not “correct”, only equivalent under budget";
    case "UNPROVEN":
      return "could not be exercised under controlled conditions — not blessed";
    case "ERROR":
      return "Tempest itself failed — the verdict is about Tempest, not the change";
    default:
      return assertNever(verdict);
  }
}

/* ------------------------------------------------------- DivergenceClass */

export function divergenceClassNote(cls: DivergenceClass): string {
  switch (cls) {
    case "RETURN_VALUE":
      return "return values differ";
    case "EXCEPTION_TYPE":
      return "raised exception types differ";
    case "EXCEPTION_MESSAGE":
      return "exception messages differ";
    case "EFFECT_SEQUENCE":
      return "order of observed effects differs";
    case "EFFECT_ARGUMENTS":
      return "an observed effect was called with different arguments";
    case "CASSETTE_MISS":
      return "head performed an effect the base recording never made";
    case "CRASH":
      return "one side crashed";
    case "HANG":
      return "one side exceeded the time budget";
    case "OUTPUT_STREAM":
      return "stdout/stderr output differs";
    default:
      return assertNever(cls);
  }
}

/* ------------------------------------------------------------ ReasonCode */

/** Generic next step per blocking reason. The per-target `reason_detail` is the specific one. */
export function reasonCodeHint(code: ReasonCode): string {
  switch (code) {
    case "TARGET_UNREACHABLE":
      return "the changed symbol could not be invoked in isolation — expose it or route a caller to it";
    case "ENV_REPRODUCTION_FAILED":
      return "base/head environments could not be materialized identically — check lockfiles and build steps";
    case "HARNESS_SYNTHESIS_FAILED":
      return "no adapter could validly invoke the target within the probe limit — simplify the signature or add types";
    case "UNINTERCEPTABLE_EFFECT":
      return "the target touches a surface record/replay cannot intercept — the exact surface is named in the detail";
    case "NONDETERMINISTIC_BASE":
      return "base behavior differs run-to-run under identical conditions — fix that nondeterminism first";
    case "SANDBOX_UNAVAILABLE":
      return "no container runtime available — Tempest never runs user code unsandboxed";
    case "VALUE_UNSERIALIZABLE":
      return "an observed value has no canonical serialization, so sides cannot be compared honestly";
    case "RECORD_REPLAY_UNAVAILABLE":
      return "record/replay is not available for this target's runtime yet";
    default:
      return assertNever(code);
  }
}

/* -------------------------------------------------------------- Severity */

export function severityChipClass(severity: Severity): string {
  switch (severity) {
    case "LOW":
      return "border-panel-line text-ink-dim";
    case "NORMAL":
      return "border-panel-line text-ink";
    case "HEADLINE":
      return "border-divergent text-divergent";
    default:
      return assertNever(severity);
  }
}

/* -------------------------------------------- TargetClassification order */

/** Exhaustive record — a new Python classification fails this object literal. */
const CLASSIFICATION_ORDER: Record<TargetClassification, number> = {
  PURE_CANDIDATE: 0,
  IMPURE_RECORDABLE: 1,
  UNREACHABLE: 2,
};

export const ALL_CLASSIFICATIONS = (Object.keys(CLASSIFICATION_ORDER) as TargetClassification[]).sort(
  (a, b) => CLASSIFICATION_ORDER[a] - CLASSIFICATION_ORDER[b],
);

export function classificationNote(cls: TargetClassification): string {
  switch (cls) {
    case "PURE_CANDIDATE":
      return "pure candidate — differential over return values";
    case "IMPURE_RECORDABLE":
      return "impure — record/replay differential over effects";
    case "UNREACHABLE":
      return "unreachable — could not be exercised; reason attached";
    default:
      return assertNever(cls);
  }
}

/* ------------------------------------------------------------- RunStatus */

export function runStatusLabel(status: RunStatus): string {
  switch (status) {
    case "PENDING":
      return "pending — awaiting bundle upload";
    case "COMPLETE":
      return "complete";
    default:
      return assertNever(status);
  }
}

/* ------------------------------------------------------------------ Lang */

export function langBadge(lang: Lang): string {
  switch (lang) {
    case "PYTHON":
      return "py";
    case "TYPESCRIPT":
      return "ts";
    default:
      return assertNever(lang);
  }
}

/* ------------------------------------------------------------- ErrorCode */

export function errorCodeNote(code: ErrorCode): string {
  switch (code) {
    case "VALIDATION_ERROR":
      return "the request was malformed";
    case "NOT_FOUND":
      return "no such record";
    case "IDEMPOTENCY_CONFLICT":
      return "idempotency key reused for a different request";
    case "RUN_NOT_PENDING":
      return "the run already has its bundle";
    case "BUNDLE_INVALID":
      return "the uploaded bundle failed integrity checks";
    case "BUNDLE_SCHEMA_UNSUPPORTED":
      return "the bundle schema version is newer than this server understands";
    case "BUNDLE_MISMATCH":
      return "the bundle does not match the run it was uploaded to";
    case "REPO_NOT_FOUND":
      return "that path is not a git repository on this machine";
    case "REF_NOT_FOUND":
      return "that branch or commit does not exist in the repository";
    case "INTERNAL":
      return "the API failed internally";
    default:
      return assertNever(code);
  }
}

/* -------------------------------------------------- error envelope guard */

/** Narrows a thrown hook error to the generated `{error: {code, message, details?}}` envelope. */
export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const inner = (value as { error: unknown }).error;
  return (
    typeof inner === "object" &&
    inner !== null &&
    "code" in inner &&
    "message" in inner &&
    parseErrorCode((inner as { code: unknown }).code) !== undefined
  );
}

const ERROR_CODE_SET: Record<ErrorCode, true> = {
  VALIDATION_ERROR: true,
  NOT_FOUND: true,
  IDEMPOTENCY_CONFLICT: true,
  RUN_NOT_PENDING: true,
  BUNDLE_INVALID: true,
  BUNDLE_SCHEMA_UNSUPPORTED: true,
  BUNDLE_MISMATCH: true,
  REPO_NOT_FOUND: true,
  REF_NOT_FOUND: true,
  INTERNAL: true,
};

function parseErrorCode(value: unknown): ErrorCode | undefined {
  return (Object.keys(ERROR_CODE_SET) as ErrorCode[]).find((c) => c === value);
}
