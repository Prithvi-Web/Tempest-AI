/**
 * The editor route (Phase 20.1). Opens one text file out of one project.
 *
 * Every refusal `pathguard` can produce reaches the user as a sentence rather than a stack trace:
 * "no" plus a reason is a product surface (L7), and the reasons here are security decisions the
 * user is entitled to understand — so each one also carries what to do about it.
 */
import { Suspense, lazy } from "react";

import { EditorChunkBoundary } from "../editor/EditorChunkBoundary";
import { useProjectFile } from "../hooks";

import type { PathRefusal } from "../generated/bindings";
import type { Route } from "../router";

const CodeMirrorHost = lazy(() => import("../editor/CodeMirrorHost"));

/**
 * What the user can DO about each refusal.
 *
 * The `never` in the default arm is the point: adding a variant to `PathRefusal` in Rust
 * regenerates the binding and then fails this compile until it is handled here. 43fbb25 claimed
 * that property ("adding a variant breaks the UI until it is handled") while nothing in the app
 * read `.kind` at all, so the claim was false. This is it made true.
 */
export function refusalHint(refusal: PathRefusal): string {
  switch (refusal.kind) {
    case "credential":
      return "Tempest never opens files that carry credentials.";
    case "hard_linked":
      return "This file has more than one name on disk, so its name cannot be trusted.";
    case "not_a_project":
      return "Open a folder that is a git repository.";
    case "escapes_root":
      return "That path leads outside the project.";
    case "absolute":
    case "traversal":
    case "malformed":
      return "Use a path inside the project.";
    case "not_found":
      return "Check the path — nothing is there.";
    case "unreadable":
      return "Check the file's permissions.";
    case "not_a_file":
      return "That is a folder, not a file.";
    case "not_text":
      return "Tempest's editor opens text files only.";
    case "too_large":
      return "This file is larger than the editor will open.";
    default: {
      const unhandled: never = refusal;
      return unhandled;
    }
  }
}

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
        /{" "}
        <span data-testid="editor-path">
          {/* The RESOLVED path once it is known. Showing the requested one would let a symlink
              title the window with one name while displaying another file's contents — which is
              precisely why pathguard returns where it landed. */}
          {opened.isSuccess ? opened.data.path : file}
        </span>
      </nav>

      {/* Every other view has one, and App.tsx's route-change effect focuses it so a keyboard
          user lands somewhere meaningful. Without it the effect silently no-ops here — the one
          route where focus matters most, because CodeMirror captures the keyboard. */}
      <h1 className="visually-hidden">Editor — {file}</h1>

      {opened.isPending && <p className="dim">opening {file}…</p>}

      {opened.isError && (
        <p className="yellow" data-testid="editor-refusal" role="alert">
          {opened.error.message}
          {" — "}
          {refusalHint(opened.error.refusal)}
        </p>
      )}

      {opened.isSuccess && (
        <EditorChunkBoundary>
          <Suspense fallback={<p className="dim">loading editor…</p>}>
            <CodeMirrorHost repo={repo} path={opened.data.path} text={opened.data.text} />
          </Suspense>
        </EditorChunkBoundary>
      )}
    </main>
  );
}
