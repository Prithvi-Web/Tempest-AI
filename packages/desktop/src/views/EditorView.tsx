/**
 * The editor route (Phase 20.1). Opens one text file out of one project.
 *
 * Every refusal `pathguard` can produce reaches the user as a sentence rather than a stack trace:
 * "no" plus a reason is a product surface (L7), and the reasons here are security decisions the
 * user is entitled to understand.
 */
import { Suspense, lazy } from "react";

import { useProjectFile } from "../hooks";

import type { Route } from "../router";

const CodeMirrorHost = lazy(() => import("../editor/CodeMirrorHost"));

export function EditorView({
  repo,
  file,
  navigate,
}: {
  repo: string;
  file: string;
  navigate: (r: Route) => void;
}) {
  const opened = useProjectFile(repo, file);

  return (
    <main>
      <nav className="crumbs">
        <a
          href="?"
          onClick={(e) => {
            e.preventDefault();
            navigate({ view: "runs" });
          }}
        >
          Runs
        </a>{" "}
        / <span data-testid="editor-path">{file}</span>
      </nav>

      {opened.isPending && <p className="dim">opening {file}…</p>}

      {opened.isError && (
        <p className="yellow" data-testid="editor-refusal">
          {opened.error.message}
        </p>
      )}

      {opened.isSuccess && (
        <Suspense fallback={<p className="dim">loading editor…</p>}>
          <CodeMirrorHost path={opened.data.path} text={opened.data.text} />
        </Suspense>
      )}
    </main>
  );
}
