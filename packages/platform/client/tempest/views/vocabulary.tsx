/**
 * The enum vocabulary, exhaustively (CLAUDE.md §9 / HANDOFF-WORLD-CLASS §1.1).
 *
 * Every generated enum the UI renders passes through a switch here with a `never` guard —
 * adding a variant in Python regenerates the union and BREAKS THIS BUILD until the new
 * variant has copy. That is the design working: the app cannot ship a state it has no words
 * for. The vitest suite drives every function over every variant read from the generated
 * domain schema at runtime, so the copy is also proven non-empty, not just compilable.
 *
 * Verdict copy is bound by L2: EQUIVALENT_UNDER_BUDGET is never softened into "correct",
 * UNPROVEN is a first-class honest state, and nothing here invents claims the engine did
 * not make — these are captions on evidence, not verdicts of their own.
 */
import type {
  DivergenceClass,
  Lang,
  ReasonCode,
  RunStatus,
  Severity,
  TargetClassification,
  Verdict,
} from "../../../../desktop/src/generated/bindings";

/** Exhaustiveness backstop: unreachable when the switches above it cover the union. */
function unhandled(variant: never): never {
  throw new Error(`unhandled enum variant: ${String(variant)}`);
}

/** One plain-English sentence per verdict — the tooltip on every verdict chip. */
export function verdictHint(verdict: Verdict): string {
  switch (verdict) {
    case "DIVERGENT":
      return "At least one input produced different observable behavior — the evidence and a minimized reproduction are attached.";
    case "EQUIVALENT_UNDER_BUDGET":
      return "Every generated input behaved identically under this run's budget. That is not a proof of correctness — only of what was exercised.";
    case "UNPROVEN":
      return "Tempest could not exercise this and says so instead of guessing — the reason states exactly what blocked it.";
    case "ERROR":
      return "Tempest itself failed here. The internal trace is recorded; this says nothing about the change.";
    default:
      return unhandled(verdict);
  }
}

/** What blocked the proof, and what to do about it — remediation is the product (§12). */
export function reasonHint(code: ReasonCode): string {
  switch (code) {
    case "TARGET_UNREACHABLE":
      return "This symbol cannot be constructed or invoked in isolation. An Anthropic API key in Settings lets Tempest attempt AI constructor synthesis for targets like this.";
    case "ENV_REPRODUCTION_FAILED":
      return "The revision's environment could not be rebuilt (dependencies, interpreter, or layout). The detail names the first failing step.";
    case "HARNESS_SYNTHESIS_FAILED":
      return "No adapter could invoke the target — its signature or module shape defeated every strategy.";
    case "SYNTHESIS_DECLINED":
      return "The AI-written adapter failed real execution validation, so it was rejected rather than trusted (verdicts never ride on unvalidated code).";
    case "UNINTERCEPTABLE_EFFECT":
      return "The code reaches a surface record/replay cannot intercept (raw sockets, native extensions). Proving it would require guessing — Tempest does not.";
    case "NONDETERMINISTIC_BASE":
      return "The base revision disagrees with itself under identical conditions, so no comparison is meaningful (Law L3).";
    case "SANDBOX_UNAVAILABLE":
      return "No sandbox tier is available on this machine, and Tempest never runs repository code unsandboxed (Law L6). Install Docker, or run on macOS for the OS-native tier.";
    case "VALUE_UNSERIALIZABLE":
      return "The target produced values with no canonical encoding, so equality between revisions cannot be stated honestly.";
    case "RECORD_REPLAY_UNAVAILABLE":
      return "Record/replay for this code's language or shape has not shipped yet — stated instead of silently skipped.";
    default:
      return unhandled(code);
  }
}

/** What kind of difference a divergence is, in words a reviewer can act on. */
export function divergenceClassLabel(divergenceClass: DivergenceClass): string {
  switch (divergenceClass) {
    case "RETURN_VALUE":
      return "return values differ";
    case "EXCEPTION_TYPE":
      return "different exception type";
    case "EXCEPTION_MESSAGE":
      return "different exception message";
    case "EFFECT_SEQUENCE":
      return "side effects happen in a different order";
    case "EFFECT_ARGUMENTS":
      return "side effects receive different arguments";
    case "CASSETTE_MISS":
      return "head requested IO the recording never saw";
    case "CRASH":
      return "one revision crashes the process";
    case "HANG":
      return "one revision exceeds the time budget";
    case "OUTPUT_STREAM":
      return "stdout/stderr output differs";
    default:
      return unhandled(divergenceClass);
  }
}

export function severityLabel(severity: Severity): string {
  switch (severity) {
    case "LOW":
      return "low (representation-level difference)";
    case "NORMAL":
      return "normal";
    case "HEADLINE":
      return "headline (crash or contract break)";
    default:
      return unhandled(severity);
  }
}

/** How the engine decided this target could be exercised. */
export function classificationHint(classification: TargetClassification): string {
  switch (classification) {
    case "PURE_CANDIDATE":
      return "invoked directly — no observed IO";
    case "IMPURE_RECORDABLE":
      return "performs IO that record/replay can intercept";
    case "UNREACHABLE":
      return "cannot be invoked in isolation";
    case "SYNTHESIZED":
      return "reached through an AI-written, execution-validated adapter";
    case "TYPE_SYNTHESIZED":
      return "reached through a type-driven constructor, no AI involved";
    default:
      return unhandled(classification);
  }
}

export function runStatusLabel(status: RunStatus): string {
  switch (status) {
    case "PENDING":
      return "running";
    case "COMPLETE":
      return "complete";
    case "CANCELLED":
      return "cancelled by you — no verdict claimed";
    default:
      return unhandled(status);
  }
}

export function langLabel(lang: Lang): string {
  switch (lang) {
    case "PYTHON":
      return "Python";
    case "TYPESCRIPT":
      return "TypeScript";
    default:
      return unhandled(lang);
  }
}

/** The one way a verdict is rendered: color-classed chip + the honest tooltip. */
export function VerdictChip({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`chip ${verdict}`} title={verdictHint(verdict)}>
      {verdict}
    </span>
  );
}

export function ClassificationChip({
  classification,
}: {
  classification: TargetClassification;
}) {
  return (
    <span className="chip neutral" title={classificationHint(classification)}>
      {classification}
    </span>
  );
}
