/**
 * TempestSSE — the boundary-B stream transport's state machine (ADR-0078), measured without
 * an IPC: a scripted host stands in for the tauri glue (which lives in streamHost.ts and is
 * pinned end-to-end by the Playwright chat specs).
 *
 * The properties that matter: sse.js's numeric states verbatim (the vendored hook compares
 * against the ORIGINAL class's constants), subscribe-before-replay with seq-dedup (no frame
 * lost between the two, none delivered twice), a terminal frame closing the stream without
 * the abort event, close() tearing the subscription down even mid-connect, and failures
 * arriving as in-band error events rather than silence.
 */
import { afterEach, describe, expect, it } from "vitest";

import {
  type StreamPush,
  TempestSSE,
  type TempestSSEHost,
  setHostLoaderForTest,
} from "../../platform/client/tempest/stream/TempestSSE";

function frame(seq: number, body: Record<string, unknown>): { seq: number; frame_json: string } {
  return { seq, frame_json: JSON.stringify(body) };
}

class ScriptedHost implements TempestSSEHost {
  handler: ((push: StreamPush) => void) | null = null;
  unlistened = 0;
  replayPush: StreamPush;
  listenError: Error | null = null;
  /** When set, replay() parks until the test settles it — the deterministic way to enact
   * "the live final beat the replay" instead of hoping a race falls that way (trap 61). */
  replayControlled = false;
  private rejectReplay: ((error: Error) => void) | null = null;
  private replayResolve: (() => void) | null = null;
  replayRequested: Promise<void>;

  constructor(streamId: string) {
    this.replayPush = { stream_id: streamId, status: "active", events: [] };
    this.replayRequested = new Promise((resolve) => {
      this.replayResolve = resolve;
    });
  }

  async listen(handler: (push: StreamPush) => void): Promise<() => void> {
    if (this.listenError) {
      throw this.listenError;
    }
    this.handler = handler;
    return () => {
      this.unlistened += 1;
    };
  }

  replay(): Promise<StreamPush> {
    this.replayResolve?.();
    if (this.replayControlled) {
      return new Promise((_, reject) => {
        this.rejectReplay = reject;
      });
    }
    return Promise.resolve(this.replayPush);
  }

  failReplayNow(error: Error): void {
    this.rejectReplay?.(error);
  }
}

interface Seen {
  open: string[];
  message: string[];
  error: string[];
  abort: string[];
}

function collect(sse: TempestSSE): Seen {
  const seen: Seen = { open: [], message: [], error: [], abort: [] };
  for (const type of Object.keys(seen) as (keyof Seen)[]) {
    sse.addEventListener(type, (event) => seen[type].push(event.data));
  }
  return seen;
}

async function settled(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  setHostLoaderForTest(null);
  delete (window as { __TEMPEST_APP__?: boolean }).__TEMPEST_APP__;
});

describe("availability", () => {
  it("is off everywhere except under the desktop host's marker", () => {
    expect(TempestSSE.available()).toBe(false);
    window.__TEMPEST_APP__ = true;
    expect(TempestSSE.available()).toBe(true);
  });

  it("keeps sse.js's numeric states verbatim", () => {
    expect(TempestSSE.INITIALIZING).toBe(-1);
    expect(TempestSSE.CONNECTING).toBe(0);
    expect(TempestSSE.OPEN).toBe(1);
    expect(TempestSSE.CLOSED).toBe(2);
  });
});

describe("the stream lifecycle", () => {
  it("subscribes first, replays second, and dedupes the overlap by seq", async () => {
    const host = new ScriptedHost("c-1");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("tempest://x/api/agents/chat/stream/c-1?resume=true");
    const seen = collect(sse);

    host.replayPush = {
      stream_id: "c-1",
      status: "active",
      events: [frame(1, { created: true }), frame(2, { event: "on_run_step" })],
    };
    sse.stream();
    expect(sse.readyState).toBe(TempestSSE.CONNECTING);
    await settled();
    expect(sse.readyState).toBe(TempestSSE.OPEN);
    expect(seen.open).toHaveLength(1);

    // A live push that OVERLAPS the replay (both carry seq 2): one delivery each.
    host.handler?.({
      stream_id: "c-1",
      status: "active",
      events: [frame(2, { event: "on_run_step" }), frame(3, { event: "on_message_delta" })],
    });
    expect(seen.message.map((data) => JSON.parse(data))).toEqual([
      { created: true },
      { event: "on_run_step" },
      { event: "on_message_delta" },
    ]);
  });

  it("delivers out-of-order batches in seq order and ignores foreign streams", async () => {
    const host = new ScriptedHost("mine");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/mine");
    const seen = collect(sse);
    sse.stream();
    await settled();

    host.handler?.({
      stream_id: "other",
      status: "active",
      events: [frame(1, { stolen: true })],
    });
    host.handler?.({
      stream_id: "mine",
      status: "active",
      events: [frame(2, { second: true }), frame(1, { first: true })],
    });
    expect(seen.message.map((data) => JSON.parse(data))).toEqual([
      { first: true },
      { second: true },
    ]);
  });

  it("a terminal frame closes the stream with no abort event", async () => {
    const host = new ScriptedHost("c-2");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-2");
    const seen = collect(sse);
    sse.stream();
    await settled();

    host.handler?.({
      stream_id: "c-2",
      status: "complete",
      events: [frame(1, { created: true }), frame(2, { final: true })],
    });
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(host.unlistened).toBe(1);
    expect(seen.abort).toHaveLength(0);
    expect(seen.message).toHaveLength(2);

    // Frames after the final are a dead stream's echo and must not resurrect it.
    host.handler?.({ stream_id: "c-2", status: "complete", events: [frame(3, { late: true })] });
    expect(seen.message).toHaveLength(2);
  });

  it("close() emits abort, tears down the subscription, and repeated calls are inert", async () => {
    const host = new ScriptedHost("c-3");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-3");
    const seen = collect(sse);
    sse.stream();
    sse.stream(); // repeated stream() calls are ignored, as in sse.js
    await settled();
    sse.close();
    sse.close();
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.abort).toHaveLength(1);
    expect(host.unlistened).toBe(1);
  });

  it("a close that lands mid-connect still tears the subscription down", async () => {
    const host = new ScriptedHost("c-4");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-4");
    sse.stream();
    sse.close(); // before the listen promise resolves
    await settled();
    expect(host.unlistened).toBe(1);
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
  });

  it("an unparseable frame is delivered but never mistaken for a terminal", async () => {
    const host = new ScriptedHost("c-5");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-5");
    const seen = collect(sse);
    sse.stream();
    await settled();
    host.handler?.({
      stream_id: "c-5",
      status: "active",
      events: [{ seq: 1, frame_json: "not json{" }],
    });
    expect(seen.message).toEqual(["not json{"]);
    expect(sse.readyState).toBe(TempestSSE.OPEN);
  });
});

describe("failure arms", () => {
  it("a failed subscription is an in-band error event, not silence", async () => {
    const host = new ScriptedHost("c-6");
    host.listenError = new Error("no host");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-6");
    const seen = collect(sse);
    sse.stream();
    await settled();
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(1);
    expect(JSON.parse(seen.error[0] ?? "{}").error).toContain("no host");
  });

  it("a failed replay after a live final stays silent — the stream already ended honestly", async () => {
    const host = new ScriptedHost("c-7");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-7");
    const seen = collect(sse);
    sse.stream();
    await host.replayRequested; // the replay is now parked, awaiting the test's verdict
    host.handler?.({ stream_id: "c-7", status: "complete", events: [frame(1, { final: true })] });
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    host.failReplayNow(new Error("replay broke")); // the LATE failure, after the honest close
    await settled();
    expect(seen.error).toHaveLength(0);
    expect(seen.message).toHaveLength(1);
  });

  it("removeEventListener detaches exactly the named listener", async () => {
    const host = new ScriptedHost("c-8");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-8");
    const kept: string[] = [];
    const dropped: string[] = [];
    const keep = (event: { data: string }) => kept.push(event.data);
    const drop = (event: { data: string }) => dropped.push(event.data);
    sse.addEventListener("message", keep);
    sse.addEventListener("message", drop);
    sse.removeEventListener("message", drop);
    sse.removeEventListener("never-registered", drop); // a type nobody added: a no-op
    sse.stream();
    await settled();
    host.handler?.({ stream_id: "c-8", status: "active", events: [frame(1, { a: 1 })] });
    expect(kept).toHaveLength(1);
    expect(dropped).toHaveLength(0);
  });

  it("the default host loader reaches the real glue, and no IPC fails in-band", async () => {
    // The ONLY test that leaves the loader at its default: the real streamHost module
    // loads, its listen() finds no tauri IPC in this world, and the failure arrives as an
    // error event — a wiring typo in the lazy default cannot ship behind the overrides.
    setHostLoaderForTest(null);
    const sse = new TempestSSE("/api/agents/chat/stream/real-glue");
    const seen = collect(sse);
    sse.stream();
    const deadline = Date.now() + 5000; // dynamic imports take real ticks under vitest
    while (sse.readyState !== TempestSSE.CLOSED && Date.now() < deadline) {
      await settled();
    }
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(1);
  });

  it("degenerate stream urls resolve to an empty id rather than a crash", () => {
    expect(new TempestSSE("")).toBeInstanceOf(TempestSSE);
    expect(new TempestSSE("?only=query")).toBeInstanceOf(TempestSSE);
  });
});
