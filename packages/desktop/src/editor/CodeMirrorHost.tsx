/**
 * The CodeMirror 6 mount (Phase 20.1, ADR-0034 — Monaco measured out at 8.1x the bundle).
 *
 * Default-exported and loaded through `React.lazy` on purpose: CM6 with two languages is 545 KB
 * minified / 181 KB gzipped, and §5 budgets cold launch to interactive at a p50 of 800 ms. Code
 * that is not on the path to first paint should not be parsed before it.
 */
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

/** Language by extension. Unknown extensions get no language rather than a wrong one. */
function languageFor(path: string) {
  const lower = path.toLowerCase();
  if (lower.endsWith(".py") || lower.endsWith(".pyi")) return [python()];
  if (/\.(m?[jt]sx?|cjs)$/.test(lower)) return [javascript({ typescript: /\.tsx?$/.test(lower) })];
  return [];
}

export default function CodeMirrorHost({ path, text }: { path: string; text: string }) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);

  useEffect(() => {
    if (host.current === null) return undefined;
    const state = EditorState.create({
      doc: text,
      extensions: [basicSetup, ...languageFor(path), EditorView.lineWrapping],
    });
    const created = new EditorView({ state, parent: host.current });
    view.current = created;
    // The open-file budget is measured to the moment the document is actually on screen, not to
    // the moment React rendered a container — the E2E harness reads this mark (§5, Phase 20).
    performance.mark("tempest:editor:ready");
    return () => {
      created.destroy();
      view.current = null;
    };
    // A new file is a new document: recreating the state is what discards the old undo history,
    // which is correct — undo must not cross files.
  }, [path, text]);

  return <div className="editor-host" data-testid="editor-host" ref={host} />;
}
