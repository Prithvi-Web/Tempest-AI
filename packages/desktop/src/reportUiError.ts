/**
 * Frontend crash honesty (HANDOFF-WORLD-CLASS §1.1): the window's `error` and
 * `unhandledrejection` events are reported into the engine's obslog through the typed
 * `reportUiError` command — the UI must never fail silently. The engine scrubs every field
 * through the production redaction context before writing (L9), so nothing the page was
 * holding can leak through an error message.
 *
 * The reporter itself must be harmless: it never throws (a failing reporter inside an error
 * handler would recurse), and it stops after a burst cap so a crash-looping component cannot
 * flood the log — the loop's FIRST reports are the evidence; the ten-thousandth is noise.
 */
import { commands } from "./generated/bindings";

const BURST_CAP = 20;
let reported = 0;

function send(source: string, message: string, stack: string | null): void {
  if (reported >= BURST_CAP || message.length === 0) return;
  reported += 1;
  try {
    // Fire-and-forget: the binding's own failure is swallowed — there is nowhere left to
    // report a failure to report, and the console still carries the original error.
    void commands.reportUiError({ message, source, stack }).catch(() => undefined);
  } catch {
    // invoke itself threw (no host in a plain browser tab) — nothing to do.
  }
}

export function installUiErrorReporting(): void {
  window.addEventListener("error", (event) => {
    send("window.error", event.message ?? String(event.error), event.error?.stack ?? null);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = event.reason;
    const message = reason instanceof Error ? reason.message : String(reason);
    const stack = reason instanceof Error ? (reason.stack ?? null) : null;
    send("unhandledrejection", message, stack);
  });
}
