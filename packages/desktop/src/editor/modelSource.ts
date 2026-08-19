/**
 * Phase 20.3d — the completion source that asks the user's local model first.
 *
 * The order is the product decision. The model answers when it can; the offline document source
 * answers when it cannot — no model configured, binary missing, or slower than the deadline. A
 * completion engine that only works when a model is loaded stops working on a plane, and one
 * that waits for a slow model puts ghost text under a cursor that has already moved.
 *
 * §5 budgets a completion at p50 120 ms. The deadline handed to the model is deliberately
 * SMALLER than that budget: the fallback still has to render inside it, so the model's share is
 * what remains after the editor's own work, not the whole allowance.
 */
import { commands } from "../generated/bindings";
import { documentCompletionSource } from "./documentSource";

/** The model's share of the §5 budget. The rest is the editor's own round trip. */
export const MODEL_DEADLINE_MS = 90;

export type CompletionContext = { textBeforeCursor: string; textAfterCursor: string };

/**
 * Ask the local model, fall back to the document.
 *
 * `invokeLocal` is injected so this is testable without Tauri — and so a test can prove the
 * fallback fires, which is the behaviour that matters and the one an integration test would be
 * least able to force.
 */
export function modelBackedSource(
  invokeLocal: (prompt: string, deadlineMs: number) => Promise<string | null> = async (p, d) => {
    // `local_completion` became a Result when it moved to the blocking pool (a spawn_blocking
    // task can itself fail). An error is not a completion, and the fallback below is the answer.
    const result = await commands.localCompletion(p, d);
    return result.status === "ok" ? result.data : null;
  },
): (context: CompletionContext) => Promise<string> {
  return async (context) => {
    let fromModel: string | null = null;
    try {
      fromModel = await invokeLocal(context.textBeforeCursor, MODEL_DEADLINE_MS);
    } catch {
      // A failed invoke is a fallback, not an error the user should see: the offline source is
      // still a real answer, and an editor that surfaces IPC problems as completion failures
      // teaches users to ignore its messages.
      fromModel = null;
    }
    // Whitespace-only is not a completion — it renders as an invisible "accept me" under Tab.
    if (fromModel !== null && fromModel.trim().length > 0) return fromModel;
    return documentCompletionSource(context);
  };
}
