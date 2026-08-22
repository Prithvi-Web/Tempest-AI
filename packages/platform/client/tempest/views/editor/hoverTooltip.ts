/**
 * Phase 20.5 — a CodeMirror hover tooltip wired to `commands.lspHover`.
 *
 * The WIRING only: every decision about what a given answer means lives in `hoverSource`, which
 * is unit-tested to 100%. What is pinned here, end to end, is that hovering a symbol produces a
 * popover, that hovering empty space produces nothing, and that a language server's failure
 * reaches the user as a sentence instead of silence.
 *
 * Why a tooltip at all, rather than a panel: hover is the one LSP feature whose whole value is
 * that it costs nothing to ask for. It is also the smallest possible surface over a capability
 * this large — the multiplexer can already be asked anything the host chooses to expose — so it
 * is the right first way in, not the last.
 */
import { EditorView, hoverTooltip, type Tooltip } from "@codemirror/view";

import type { HoverLookup } from "./hoverSource";

/**
 * How long the pointer must rest before Tempest asks. CodeMirror's own default is 300 ms.
 *
 * This is a budget, not a preference: every hover starts a language server if one is not already
 * running, and sends the whole buffer to it. Asking on every pixel of pointer travel would spawn
 * work the user never requested — the same reasoning that put an in-flight guard on F11.
 */
export const HOVER_DELAY_MS = 300;

/** The DOM for one answer. Kept here so `hoverSource` needs no document. */
function render(answer: { kind: "info" | "problem"; text: string }): HTMLElement {
  const dom = document.createElement("div");
  dom.className = `cm-tempest-hover cm-tempest-hover-${answer.kind}`;
  dom.setAttribute("data-testid", answer.kind === "info" ? "hover-info" : "hover-problem");
  // `role="tooltip"` names it for assistive technology; CodeMirror's container carries no role
  // of its own, so without this the popover is an anonymous div to a screen reader.
  dom.setAttribute("role", "tooltip");
  // `textContent`, never `innerHTML`: hover contents are produced by an arbitrary user-configured
  // binary reading the user's source, and this is the renderer — the one place in this product
  // where hostile output is displayed. Markdown rendering here would be a script-injection
  // surface for a language server, and the host already flattens LSP's three `contents` shapes
  // to text precisely so the webview never parses that protocol.
  dom.textContent = answer.text;
  return dom;
}

/**
 * The extension. `lookup` is injected so the editor works against any host — or none.
 *
 * The `text` handed to the lookup is the CURRENT buffer, read at the moment of the hover. That
 * matters: the multiplexer follows an edited document with `textDocument/didChange` (20.4a), and
 * before that fix every hover after the first was answered against the text the file had when it
 * was first opened.
 */
export function lspHoverTooltip(lookup: HoverLookup): ReturnType<typeof hoverTooltip> {
  // ONE question at a time, exactly as F11 has.
  //
  // CodeMirror does not provide this: `HoverPlugin.checkHover` skips only when a tooltip is
  // already SHOWN (`if (this.active.length) return`), not when a request is pending — so every
  // ~300 ms rest at a new position starts another `lsp_hover`. Each one blocks a thread for up
  // to the multiplexer's ten-second timeout while holding its mutex, so ordinary reading over a
  // slow or wedged server queued unbounded work. The host now runs that on the blocking pool
  // rather than a tokio worker, which stops it starving every other command — and this stops it
  // being started in the first place, which is the half CodeMirror cannot do for us.
  let inFlight = false;
  return hoverTooltip(
    async (view: EditorView, pos: number): Promise<Tooltip | null> => {
      // Only over a word. Hovering whitespace or punctuation has no symbol to ask about, and
      // asking anyway would spawn a language server for a pointer resting in the margin.
      const word = view.state.wordAt(pos);
      if (word === null) return null;
      if (inFlight) return null;
      inFlight = true;
      try {
        return await answer(view, pos, word, lookup);
      } finally {
        inFlight = false;
      }
    },
    { hoverTime: HOVER_DELAY_MS },
  );
}

async function answer(
  view: EditorView,
  pos: number,
  word: { from: number; to: number },
  lookup: HoverLookup,
): Promise<Tooltip | null> {
  const line = view.state.doc.lineAt(pos);
  const said = await lookup(
    // LSP positions are zero-based; CodeMirror numbers lines from 1.
    line.number - 1,
    pos - line.from,
    view.state.doc.toString(),
  );
  if (said === null) return null;
  return {
    pos: word.from,
    end: word.to,
    above: true,
    create: () => ({ dom: render(said) }),
  };
}
