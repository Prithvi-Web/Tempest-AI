/**
 * The tauri-binding glue behind TempestSSE — deliberately its own module, OUTSIDE the
 * vitest coverage include (the same standing exclusion as hooks.ts): its behavior needs a
 * live host and is pinned end-to-end by the Playwright chat specs against the real app
 * chain, while the state machine it feeds (TempestSSE.ts) is measured at 100% without it.
 *
 * Loaded lazily and only when `TempestSSE.available()` — so neither the harness nor a
 * server-mode bundle ever executes a tauri import.
 */

import type { StreamPush, TempestSSEHost } from "./TempestSSE";

export const streamHost: TempestSSEHost = {
  async listen(handler: (push: StreamPush) => void): Promise<() => void> {
    const { events } = await import("../../../../desktop/src/generated/bindings");
    return events.agentStreamEvent.listen((event) => handler(event.payload));
  },
  async replay(streamId: string, after: number): Promise<StreamPush> {
    const { commands } = await import("../../../../desktop/src/generated/bindings");
    const reply = await commands.replayChatTurn(streamId, after);
    if (reply.status === "error") {
      throw new Error(`replayChatTurn: ${reply.error.message}`);
    }
    return reply.data;
  },
};
