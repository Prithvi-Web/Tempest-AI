/**
 * An error boundary around the lazily-loaded editor chunk (Phase 20.1).
 *
 * `React.lazy` is new to this codebase, and a failed dynamic import rejects a promise React
 * cannot handle on its own: without a boundary the whole app unmounts to a blank window. That is
 * not hypothetical — a stale chunk hash after an update, or an offline first open of a file, both
 * produce it. A blank window is the least honest failure this product could have (L7), so the
 * failure is caught and stated instead.
 */
import { Component, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { failed: boolean };

export class EditorChunkBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override render(): ReactNode {
    if (this.state.failed) {
      return (
        <p className="yellow" data-testid="editor-chunk-failed" role="alert">
          The editor could not be loaded. Reopen the window to try again.
        </p>
      );
    }
    return this.props.children;
  }
}
