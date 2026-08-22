/** Test-only globals installed by shim.js (see fixtures.ts addInitScript). */
interface Window {
  __E2E__: {
    /** Deliver a host-emitted Tauri event to in-page listeners; returns delivery count. */
    emit(name: string, payload: unknown): number;
    /** Every `reveal_in_data_dir` argument the UI has sent (null = the data folder itself). */
    revealed: (string | null)[];
    /** Every `lsp_hover` the webview has issued — Phase 20.5's reachability evidence. */
    hovered: {
      repoPath: string;
      path: string;
      line: number;
      character: number;
      textLength: number;
    }[];
    /** Script the next hover answer, or null to behave as a fresh install does. */
    scriptHover(reply: { ok?: { contents: string } | null; error?: unknown } | null): void;
  };
  __E2E_BRIDGE_URL__?: string;
  /** The F11 completion instrument, published by the seam's editor/inlineCompletion.ts. Declared with
   * the shape the budget harness reads rather than importing `Metrics` — this project is a
   * separate tsconfig, and a type import across it would be a second definition to keep in step. */
  __TEMPEST_COMPLETION_METRICS__?: () => {
    latencies: number[];
    shown: number;
    accepted: number;
    stale: number;
  };
  __TEMPEST_RESET_COMPLETION_METRICS__?: () => void;
}
