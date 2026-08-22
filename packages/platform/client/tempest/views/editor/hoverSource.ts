/**
 * Phase 20.5 — the way IN to the LSP multiplexer.
 *
 * 20.2 built a multiplexer, gave it a typed command, generated the binding, and tested it with
 * eighteen Rust tests against real subprocesses — and nothing in the webview ever called it. The
 * handoff named this first among what was NOT done, and it is the same defect the 20.1 review
 * found one layer down ("the editor surface has no way in"), repeated. A substrate nobody can
 * reach is not a feature; it is a claim.
 *
 * This module is the DECISION half: given what `lsp_hover` answered, what should the editor put
 * on screen? It is pure and unit-tested, for the same reason `completionPolicy` is — the
 * CodeMirror wiring in `hoverTooltip.ts` is a rendering question, and this is a correctness one.
 *
 * ## What each answer means, and why silence is not always right
 *
 * `local_completion` set the precedent: "no model configured" is the expected state on a fresh
 * install and is answered with `null`, while "a model IS configured and something went wrong" is
 * a real fact the caller acts on. The same split applies here, and getting it wrong in either
 * direction is a product defect:
 *
 * - **Unsupported** — no server for this language, or the extension is one Tempest does not map.
 *   That is the ordinary state on every fresh install, because `TEMPEST_LSP_PYTHON` and
 *   `TEMPEST_LSP_TYPESCRIPT` are absent by default. A popover on every hover reading "no language
 *   server" would be noise the user cannot act on from inside a tooltip. Silence.
 * - **`ok(null)`** — the server was asked and had nothing to say about this position. Silence,
 *   and it is a REAL answer rather than a failure.
 * - **everything else** — `ServerGone`, `Timeout`, `Unlaunchable`, `ServerError`, `Refused`,
 *   `NotAProject`. Each is a fact about a server the user DID configure, or about a file the
 *   guard refused. Rendering these as silence would teach the user that their language server
 *   works and simply has nothing to say — which is exactly the confusion between "no evidence"
 *   and "evidence of nothing" this product exists to refuse. They are shown, as a sentence.
 */
import { commands, type LspError, type PathRefusal } from "../../../../../desktop/src/generated/bindings";

/** What the editor should display for one hover. `null` means: draw nothing at all. */
export type HoverAnswer =
  | { kind: "info"; text: string }
  /** A fact about a configured server, stated plainly. Never rendered as documentation. */
  | { kind: "problem"; text: string }
  | null;

/** The generated binding's result shape for `lspHover`. */
type HoverResult =
  | { status: "ok"; data: { contents: string } | null }
  | { status: "error"; error: LspError };

/**
 * Decide what to show. The `never` in the default arm is load-bearing: adding a variant to
 * `LspError` in Rust regenerates the binding and then fails this compile until somebody decides
 * whether the new state is ordinary or worth telling the user about. 20.4a added two variants
 * (`Refused`, `ServerError`) and this is where that decision now has to be made explicitly.
 */
export function hoverAnswerFor(result: HoverResult): HoverAnswer {
  if (result.status === "ok") {
    // `null` is the server saying "nothing here" — a real answer, and not a problem.
    return result.data === null ? null : { kind: "info", text: result.data.contents };
  }
  const error = result.error;
  switch (error.kind) {
    case "unsupported":
      // The fresh-install state. Silence, deliberately: see the module comment.
      return null;
    case "unlaunchable":
      return {
        kind: "problem",
        text: `The ${error.language} language server is configured but could not start — check that the command still exists.`,
      };
    case "server_gone":
      return { kind: "problem", text: `The ${error.language} language server stopped.` };
    case "timeout":
      return {
        kind: "problem",
        text: `The ${error.language} language server did not answer in time.`,
      };
    case "protocol":
      return {
        kind: "problem",
        text: `The language server broke protocol, so Tempest stopped trusting this session: ${error.detail}`,
      };
    case "server_error":
      return {
        kind: "problem",
        text: `The language server refused this request (${error.code}): ${error.message}`,
      };
    case "not_a_project":
      return { kind: "problem", text: "That folder is not a project Tempest can open." };
    case "refused":
      // pathguard's own vocabulary, unchanged — one guard, one set of words (§9b).
      return { kind: "problem", text: refusalSentence(error.refusal.kind) };
  }
  // No `default` arm on purpose. Every case returns, so adding a variant to `LspError` in Rust
  // makes this function fall through and violate its declared return type — the compiler enforces
  // exhaustiveness without a branch no test can reach. `riskLabel` uses the same construction and
  // records the same reason; a `default: never` arm is a permanent hole in a 100% gate.
}

/**
 * Why a file was refused, in the editor's voice.
 *
 * Kept as its own exhaustive switch rather than reusing `EditorView`'s `refusalHint`, because the
 * two answer different questions: that one explains what the user can DO about a file that failed
 * to open, and this one explains why a hover over an already-open file went nowhere.
 */
function refusalSentence(kind: PathRefusal["kind"]): string {
  switch (kind) {
    case "credential":
      return "Tempest never sends files that carry credentials to a language server.";
    case "hard_linked":
      return "This file has more than one name on disk, so its name cannot be trusted.";
    case "escapes_root":
      return "That path resolves outside the project.";
    case "not_a_project":
      return "That folder is not a project Tempest can open.";
    case "absolute":
    case "traversal":
    case "malformed":
      return "That is not a path inside the project.";
    case "not_found":
      return "That file is no longer on disk.";
    case "unreadable":
      return "That file could not be read.";
    case "not_a_file":
      return "That is not a regular file.";
    case "not_text":
      return "That file is not text.";
    case "too_large":
      return "That file is larger than the editor will send.";
  }
  // Same construction, same reason: exhaustiveness by return type, not by an unreachable arm.
}

/** Asks the host. Injected everywhere it is used, so the decision above is testable without Tauri. */
export type HoverLookup = (
  line: number,
  character: number,
  text: string,
) => Promise<HoverAnswer>;

/**
 * The real lookup: one Boundary B call, and every failure turned into an ANSWER rather than an
 * exception. A hover that throws would surface as an unhandled rejection and fail the E2E
 * console-clean gate; worse, it would leave the user with a tooltip that never resolves.
 */
export function lspHoverLookup(
  repoPath: string,
  path: string,
  ask: (
    repoPath: string,
    path: string,
    text: string,
    line: number,
    character: number,
  ) => Promise<HoverResult> = (repo, file, text, line, character) =>
    commands.lspHover(repo, file, text, line, character) as Promise<HoverResult>,
): HoverLookup {
  return async (line, character, text) => {
    try {
      return hoverAnswerFor(await ask(repoPath, path, text, line, character));
    } catch {
      // The host itself is unreachable — not a language-server fact, and not something a
      // tooltip can help with. Silence here is right: the sidecar-state pill already says so.
      return null;
    }
  };
}
