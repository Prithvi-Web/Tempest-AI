/**
 * The CodeMirror 6 mount (Phase 20.1, ADR-0034 — Monaco measured out at 8.1x the bundle).
 *
 * Default-exported and loaded through `React.lazy` on purpose: CM6 with two languages is 545 KB
 * minified / 181 KB gzipped, and §5 budgets cold launch to interactive at a p50 of 800 ms. Code
 * that is not on the path to first paint should not be parsed before it.
 */
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState, Prec } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

import { divergenceLookup } from "./divergenceLookup";
import { inlineCompletion } from "./inlineCompletion";
import { modelBackedSource } from "./modelSource";

/**
 * Syntax colours as CSS VARIABLES, not literals.
 *
 * CodeMirror's bundled highlight style is tuned for a white page. Dropped into this app's dark
 * palette it rendered keywords at roughly 1.7:1 against the background — technically present,
 * practically unreadable, and invisible to every gate because no screenshot or contrast check
 * was looking at this view. Emitting `var(--code-*)` instead lets the app's existing
 * prefers-color-scheme block define both schemes in one place, the way every other surface here
 * already works.
 */
const appHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--code-keyword)" },
  { tag: [tags.controlKeyword, tags.moduleKeyword], color: "var(--code-keyword)" },
  { tag: [tags.name, tags.deleted, tags.character, tags.macroName], color: "var(--code-ink)" },
  { tag: [tags.function(tags.variableName), tags.labelName], color: "var(--code-function)" },
  { tag: [tags.propertyName], color: "var(--code-property)" },
  { tag: [tags.string, tags.special(tags.string), tags.inserted], color: "var(--code-string)" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--code-number)" },
  { tag: [tags.definition(tags.variableName), tags.className], color: "var(--code-type)" },
  { tag: [tags.typeName, tags.namespace], color: "var(--code-type)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--code-comment)" },
  { tag: [tags.operator, tags.punctuation, tags.separator], color: "var(--code-punctuation)" },
  { tag: tags.invalid, color: "var(--divergent)" },
]);

/** Language by extension. Unknown extensions get no language rather than a wrong one. */
function languageFor(path: string) {
  const lower = path.toLowerCase();
  if (lower.endsWith(".py") || lower.endsWith(".pyi")) return [python()];
  if (/\.(m?[jt]sx?|cjs)$/.test(lower)) return [javascript({ typescript: /\.tsx?$/.test(lower) })];
  return [];
}

export default function CodeMirrorHost({ path, text }: { path: string; text: string }) {
  const host = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (host.current === null) return undefined;
    const state = EditorState.create({
      doc: text,
      extensions: [
        basicSetup,
        // `basicSetup` already installs CodeMirror's default highlight style; highest precedence
        // is what makes the app's palette win rather than merely also being present.
        Prec.highest(syntaxHighlighting(appHighlight)),
        ...languageFor(path),
        EditorView.lineWrapping,
        // CodeMirror stamps role="textbox" on its content and deliberately leaves it unnamed —
        // naming is the embedder's job. Without this the editor is the only unlabelled control
        // in the app (WCAG 2.2 SC 4.1.2, Level A).
        EditorView.contentAttributes.of({ "aria-label": `Editor: ${path}` }),
        // F11 inline completion (Phase 20.3): the user's local model first, the offline
        // document completer whenever it cannot answer in time. The fallback is not a
        // degraded mode — it is what keeps F11 working on a plane.
        // ...and F11's twist: the badge reports what Tempest has RECORDED about the symbol the
        // completion names. Measured runs, not a heuristic and not a model's opinion.
        inlineCompletion(modelBackedSource(), divergenceLookup()),
      ],
    });
    const view = new EditorView({ state, parent: host.current });
    return () => view.destroy();
    // Keyed on `path` ALONE, not on `text`. Keying on text meant any refetch of the same file —
    // react-query refetches on mount by default — tore down the editor and rebuilt it, throwing
    // away the cursor, the selection and the undo history for a document that had not changed.
    // A new FILE is a new document; new bytes for the same file are not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return (
    <div
      className="editor-host"
      data-testid="editor-host"
      ref={host}
      /* The initial document is set from `text` at mount; see the effect above for why this is
         deliberately not a dependency. */
      data-doc-length={text.length}
    />
  );
}
