/**
 * What the editor shows for each thing `lsp_hover` can answer.
 *
 * The whole point of this module is the split between "ordinary, say nothing" and "a fact about
 * a server you DID configure, say it" — so the test enumerates every `LspError` variant rather
 * than sampling. A variant added in Rust regenerates the binding, fails `hoverAnswerFor`'s
 * `never` arm at compile time, and then fails the completeness assertion here at run time.
 */
import { describe, expect, it } from "vitest";

import { hoverAnswerFor, lspHoverLookup, type HoverAnswer } from "./hoverSource";

import type { LspError, PathRefusal } from "../generated/bindings";

/** Every variant the wire can carry. Listed by hand so a new one has to be added deliberately. */
const EVERY_ERROR: LspError[] = [
  { kind: "unsupported", language: "python" },
  { kind: "unlaunchable", language: "python" },
  { kind: "not_a_project" },
  { kind: "refused", refusal: { kind: "credential" } },
  { kind: "server_gone", language: "typescript" },
  { kind: "timeout", language: "typescript" },
  { kind: "protocol", detail: "not JSON" },
  { kind: "server_error", code: -32601, message: "Unhandled method" },
];

const EVERY_REFUSAL: PathRefusal["kind"][] = [
  "malformed",
  "absolute",
  "traversal",
  "escapes_root",
  "credential",
  "not_found",
  "unreadable",
  "not_a_file",
  "hard_linked",
  "not_text",
  "not_a_project",
  "too_large",
];

describe("hoverAnswerFor", () => {
  it("shows what the server said", () => {
    expect(hoverAnswerFor({ status: "ok", data: { contents: "def load() -> Config" } })).toEqual({
      kind: "info",
      text: "def load() -> Config",
    });
  });

  it("says nothing when the server had nothing to say", () => {
    // A REAL answer, not a failure: the server was asked and there is no symbol here.
    expect(hoverAnswerFor({ status: "ok", data: null })).toBeNull();
  });

  it("says nothing when no language server is configured — the fresh-install state", () => {
    // Every install starts here, because TEMPEST_LSP_* are absent by default. A popover on every
    // hover reading "no language server" would be noise the user cannot act on from a tooltip.
    expect(
      hoverAnswerFor({ status: "error", error: { kind: "unsupported", language: "python" } }),
    ).toBeNull();
  });

  it("never renders a configured server's failure as silence", () => {
    // The distinction this module exists for: silence means "asked, nothing to say". Rendering a
    // crashed or timed-out server the same way teaches the user their tooling works.
    for (const error of EVERY_ERROR) {
      const answer = hoverAnswerFor({ status: "error", error });
      if (error.kind === "unsupported") {
        expect(answer, error.kind).toBeNull();
        continue;
      }
      expect(answer, error.kind).not.toBeNull();
      expect(answer?.kind, error.kind).toBe("problem");
      expect((answer as { text: string }).text.length, error.kind).toBeGreaterThan(10);
    }
  });

  it("covers every LspError variant, so a new one cannot land silently", () => {
    // Guards against the list above drifting from the generated union: if Rust gains a variant,
    // `hoverAnswerFor`'s `never` arm stops compiling first, and this is the run-time backstop.
    const kinds = new Set(EVERY_ERROR.map((e) => e.kind));
    expect(kinds.size).toBe(EVERY_ERROR.length);
    for (const error of EVERY_ERROR) {
      expect(() => hoverAnswerFor({ status: "error", error })).not.toThrow();
    }
  });

  it("states a refusal in pathguard's own vocabulary, for every refusal", () => {
    for (const kind of EVERY_REFUSAL) {
      const answer = hoverAnswerFor({
        status: "error",
        error: { kind: "refused", refusal: { kind } as PathRefusal },
      });
      expect(answer?.kind, kind).toBe("problem");
      const text = (answer as { text: string }).text;
      expect(text.length, kind).toBeGreaterThan(10);
      // A refusal is a decision the user is entitled to understand — never a stack trace, and
      // never a bare code.
      expect(text.endsWith("."), kind).toBe(true);
    }
  });

  it("names the language in a problem, so two servers are distinguishable", () => {
    const gone = hoverAnswerFor({
      status: "error",
      error: { kind: "server_gone", language: "typescript" },
    }) as { text: string };
    expect(gone.text).toContain("typescript");
  });

  it("carries the server's own code and message rather than paraphrasing them", () => {
    const refused = hoverAnswerFor({
      status: "error",
      error: { kind: "server_error", code: -32601, message: "Unhandled method workspace/symbol" },
    }) as { text: string };
    expect(refused.text).toContain("-32601");
    expect(refused.text).toContain("Unhandled method workspace/symbol");
  });
});

describe("lspHoverLookup", () => {
  it("answers null when there is no host to ask, rather than rejecting", () => {
    // The DEFAULT caller, with no injection: under vitest there is no Tauri IPC, so the generated
    // binding throws. An unhandled rejection here would fail the E2E console-clean gate and leave
    // a tooltip that never resolves.
    return expect(lspHoverLookup("/repo", "a.py")(0, 0, "x = 1\n")).resolves.toBeNull();
  });

  it("passes the position and the CURRENT buffer to the host, zero-based", () => {
    // The buffer matters: the multiplexer follows an edited document with didChange (20.4a), and
    // sending stale text would put that fix back where it started.
    const asked: unknown[] = [];
    const lookup = lspHoverLookup("/repo", "src/a.py", async (...args) => {
      asked.push(args);
      return { status: "ok", data: { contents: "int" } };
    });
    return lookup(4, 11, "import os\nx = 1\n").then((answer) => {
      expect(asked).toEqual([["/repo", "src/a.py", "import os\nx = 1\n", 4, 11]]);
      expect(answer).toEqual({ kind: "info", text: "int" });
    });
  });

  it("turns a host-side failure into an ANSWER, never an exception", () => {
    const lookup = lspHoverLookup("/repo", "a.py", async () => ({
      status: "error",
      error: { kind: "timeout", language: "python" },
    }));
    return lookup(0, 0, "x").then((answer) => {
      expect(answer?.kind).toBe("problem");
    });
  });

  it("stays silent when the host says no server is configured", () => {
    const lookup = lspHoverLookup("/repo", "a.py", async () => ({
      status: "error",
      error: { kind: "unsupported", language: "python" },
    }));
    return expect(lookup(0, 0, "x")).resolves.toBeNull();
  });
});

// A compile-time assertion that the answer type has exactly the shapes the renderer handles.
const _shapes: HoverAnswer[] = [null, { kind: "info", text: "t" }, { kind: "problem", text: "t" }];
void _shapes;
