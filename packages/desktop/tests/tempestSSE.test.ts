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
  private settleReplay: ((push: StreamPush) => void) | null = null;
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

  /** Cursors this host was asked to serve from, in order — the replay's contract is that it
   * is served from the CLIENT's high-water mark, and a test can only assert that by seeing
   * the argument. */
  cursors: number[] = [];
  /** Pages keyed by the cursor they answer, so the harness models an engine serving (and
   * coalescing) from `after` rather than always replaying the whole ledger. */
  replayByCursor: Map<number, StreamPush> = new Map();

  /** Called inside replay(), before it resolves — the hook that lets a test enact "a live
   *  push landed while this round trip was in flight" without a sleep. */
  onReplay: ((after: number) => void) | null = null;

  replay(_streamId: string, after: number): Promise<StreamPush> {
    this.cursors.push(after);
    this.onReplay?.(after);
    this.replayResolve?.();
    const page = this.replayByCursor.get(after);
    if (page !== undefined) {
      return Promise.resolve(page);
    }
    if (this.replayControlled) {
      return new Promise((resolve, reject) => {
        this.settleReplay = resolve;
        this.rejectReplay = reject;
      });
    }
    return Promise.resolve(this.replayPush);
  }

  failReplayNow(error: Error): void {
    this.rejectReplay?.(error);
  }

  /** Settle a parked replay with an explicit page — the deterministic way to order "a live
   * push landed, THEN the replay returned" without hoping a race falls that way (trap 61). */
  settleReplayNow(push: StreamPush): void {
    this.settleReplay?.(push);
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

function deltaText(messages: string[]): string {
  return messages
    .map((raw) => JSON.parse(raw) as { event?: string; data?: { delta?: { content?: unknown } } })
    .filter((body) => body.event === "on_message_delta")
    .map((body) => {
      const content = body.data?.delta?.content;
      if (!Array.isArray(content) || content.length !== 1) {
        return "";
      }
      const part = content[0] as { type?: string; text?: string };
      return part?.type === "text" ? (part.text ?? "") : "";
    })
    .join("");
}

function delta(seq: number, stepId: string, text: string): { seq: number; frame_json: string } {
  return frame(seq, {
    event: "on_message_delta",
    data: { id: stepId, delta: { content: [{ type: "text", text }] } },
  });
}

describe("coalesced overlap", () => {
  it("does not re-deliver text when the replay merges a LONGER run than the live push", async () => {
    // `_coalesce_deltas` merges a run of adjacent same-step deltas into ONE frame carrying
    // the run's LAST seq. The live poller pages the ledger from its own cursor; the replay
    // reads it from 0. When the ledger grows between the push and the replay's service time,
    // the two merge DIFFERENT runs and the same text arrives under two different seqs.
    //
    // A membership Set of exact seqs cannot collapse that: seq 6 is simply not seq 5. The
    // LAST-seq rule's guarantee — "a consumer that saw the merged frame has seen everything
    // up to that seq" — is a statement about a high-water CURSOR, and the only consumer used
    // a set. The user saw the run's text twice.
    const host = new ScriptedHost("c-1");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("tempest://x/api/agents/chat/stream/c-1");
    const seen = collect(sse);

    sse.stream();
    await host.replayRequested;

    // The live push: the ledger held 5 frames when the poller read it.
    host.handler?.({
      stream_id: "c-1",
      status: "active",
      events: [
        frame(1, { created: true }),
        frame(2, { event: "on_run_step" }),
        delta(5, "step_0", "Hello world!"),
      ],
    });

    // Served from the client's cursor, the engine coalesces only the UNDELIVERED tail.
    host.replayByCursor.set(5, {
      stream_id: "c-1",
      status: "active",
      events: [delta(6, "step_0", " Bye")],
    });

    // The replay, serviced a few ms later over a ledger that had grown to 6.
    host.settleReplayNow({
      stream_id: "c-1",
      status: "active",
      events: [
        frame(1, { created: true }),
        frame(2, { event: "on_run_step" }),
        delta(6, "step_0", "Hello world! Bye"),
      ],
    });
    await settled();

    expect(deltaText(seen.message)).toBe("Hello world! Bye");
    // ONE round trip now, not two. The overlap is resolved by the page's own last-seq
    // promise — everything at or below seq 6 is on screen, so the held push's 1, 2 and 5 are
    // dropped rather than re-asked for. The host makes the same guarantee from the other
    // side by starting the feed at the page's last seq (`resume_cursor`), so in the real
    // system this push cannot even be built; the drop is the reading side of one invariant
    // (ADR-0089).
    expect(host.cursors).toEqual([0]);
  });

  it("still delivers genuinely new text that arrives after the replay", async () => {
    // The other half of the bound: suppressing the overlap must not suppress the TAIL, or a
    // turn would stop rendering the moment a replay landed (trap 60 — a dedupe that drops
    // everything passes a "no duplicates" assertion perfectly).
    const host = new ScriptedHost("c-1");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("tempest://x/api/agents/chat/stream/c-1");
    const seen = collect(sse);

    sse.stream();
    await host.replayRequested;
    host.settleReplayNow({
      stream_id: "c-1",
      status: "active",
      events: [frame(1, { created: true }), delta(4, "step_0", "Hello")],
    });
    await settled();

    host.handler?.({
      stream_id: "c-1",
      status: "active",
      events: [delta(7, "step_0", " world")],
    });
    await settled();

    expect(deltaText(seen.message)).toBe("Hello world");
  });
});

describe("the replay's own edges", () => {
  it("a close during the replay round trip delivers nothing", async () => {
    // The subscription is already live at this point, so a page delivered after close()
    // would push frames into a stream the caller has abandoned — and, worse, re-open a
    // readyState the caller set to CLOSED.
    const host = new ScriptedHost("c-9");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-9");
    const seen = collect(sse);

    sse.stream();
    await host.replayRequested;
    sse.close();
    host.settleReplayNow({
      stream_id: "c-9",
      status: "active",
      events: [frame(1, { created: true })],
    });
    await settled();

    expect(seen.message).toHaveLength(0);
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(0); // an abandoned replay is not a failure
  });

  it("holds what the feed pushes until the page lands, then releases it in order", async () => {
    // What replaced the bounded-retry loop. The loop existed because a push landing during
    // the round trip moved the cursor under the request, so the page was discarded and
    // re-asked for from higher up — which is exactly what LOST `created` when the poller's
    // first push had already gone to nobody (ADR-0089).
    //
    // Now a push that lands mid-round-trip is HELD, the page is delivered whole, and the
    // held frames follow it. One replay, one cursor, nothing discarded.
    const host = new ScriptedHost("c-10");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-10");
    const seen = collect(sse);

    sse.stream();
    await host.replayRequested;

    // Two pushes land while the page is in flight. In the real system the feed was started
    // by this very replay call, positioned at the page's last seq — so both are above it.
    host.handler?.({
      stream_id: "c-10",
      status: "active",
      events: [delta(11, "step_0", "second ")],
    });
    host.handler?.({
      stream_id: "c-10",
      status: "active",
      events: [delta(12, "step_0", "third")],
    });
    // Nothing from the feed may reach the reader before the page it belongs after.
    expect(seen.message).toHaveLength(0);

    host.settleReplayNow({
      stream_id: "c-10",
      status: "active",
      events: [
        frame(1, { created: true }),
        frame(2, { event: "on_run_step" }),
        delta(10, "step_0", "first "),
      ],
    });
    await settled();

    expect(host.cursors).toEqual([0]); // one replay, never re-asked
    expect(deltaText(seen.message)).toBe("first second third");
    const created = seen.message.filter(
      (raw) => (JSON.parse(raw) as { created?: boolean }).created === true,
    );
    expect(created).toHaveLength(1);
  });
});

describe("the created-frame race (ADR-0089)", () => {
  it("delivers `created` even when the poller's FIRST push was emitted before anyone listened", async () => {
    // The P1 that produced a spinner which never stops, reproduced without a slow model.
    //
    // `spawn_poller` is called inside the POST handler, before the ack is even returned, and
    // starts at cursor 0 — so its first push carries seq 1..k, INCLUDING `created`.
    // `attach()` only reaches `host.listen()` after a lazy module load plus an IPC, reliably
    // slower, and tauri does not replay events to listeners that register afterwards. That
    // first push is simply lost, which the scripted host models by never calling the handler
    // for it.
    //
    // Then the second push lands DURING the replay's round trip. The cursor has moved, so
    // attach discards the page it asked for from 0 — correctly, because a coalesced delta
    // carries its run's LAST seq and a membership set cannot dedupe the overlap — and
    // re-asks from the higher cursor. Seq 1..2 are now unreachable from either path.
    //
    // Downstream, `useResumableSSE` buffers every later frame into `preCreatedStepEvents` and
    // replays them from exactly one place: the `data.created != null` branch. No `created`
    // means no replay, no render, no error, and no timeout.
    const host = new ScriptedHost("c-race");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-race");
    const seen = collect(sse);

    // What the engine's ledger can serve, per cursor. From 0 it still holds `created`.
    host.replayControlled = true;
    sse.stream();
    await host.replayRequested;

    // The poller's push. Under the fix the feed is started BY this replay call and
    // positioned at the page's last seq, so it lands ABOVE the page instead of before it.
    host.handler?.({
      stream_id: "c-race",
      status: "active",
      events: [delta(12, "step_0", "world")],
    });

    // The page the replay serves — still holding `created`, and no longer discarded.
    host.settleReplayNow({
      stream_id: "c-race",
      status: "active",
      events: [
        frame(1, { created: true }),
        frame(2, { event: "on_run_step" }),
        delta(10, "step_0", "hello "),
      ],
    });
    await settled();

    const created = seen.message.filter(
      (raw) => (JSON.parse(raw) as { created?: boolean }).created === true,
    );
    expect(created).toHaveLength(1);
    // …and the text still arrives exactly once, which is what the discard protects.
    expect(deltaText(seen.message)).toBe("hello world");
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
    // The final is HELD while the page is in flight, so the close lands when the queue is
    // released rather than the instant the push arrives (ADR-0089). What must NOT change is
    // the outcome: a turn that genuinely finished is never reported as an error because the
    // replay behind it failed — so the queue is released BEFORE the failure is reported.
    expect(sse.readyState).toBe(TempestSSE.OPEN);
    host.failReplayNow(new Error("replay broke")); // the LATE failure, after an honest final
    await settled();
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(0);
    expect(seen.message).toHaveLength(1);
  });

  it("the host's circuit breaker reaches the reader as an error, not a frozen stream", async () => {
    // ADR-0079's last named deferral — "an agent-stream-specific fault-injection pin beyond
    // e2e 06's engine-SIGKILL coverage". It was hiding a live defect rather than a missing
    // test: e2e 06 exercises the masthead health probe on /tempest with no chat turn in
    // flight, and the two cargo tests LC22 named are arithmetic over `Instant`s that never
    // reach `spawn_poller`'s emit. Nothing anywhere drove this push.
    //
    // The host emits it once the poller has failed for longer than POLL_FAILURE_GRACE: an
    // empty event list and `status: "error"`. Before the fix `deliver` read frames only, the
    // loop ran zero times, and the breaker changed nothing — readyState stayed OPEN and the
    // reconnect ladder never armed (ADR-0089 §2).
    const host = new ScriptedHost("c-11");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-11");
    const seen = collect(sse);
    sse.stream();
    await settled();

    host.handler?.({ stream_id: "c-11", status: "error", events: [] });

    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(1);
    const reported = JSON.parse(seen.error[0] ?? "{}") as { error?: string };
    expect(reported.error).toContain("the live stream stopped");
    expect(seen.abort).toHaveLength(0); // a breaker is not a user-initiated close
  });

  it("a breaker that fires while the page is in flight is not lost to the hold queue", async () => {
    // The interaction between the two fixes: an error push arriving before the page is held,
    // and must still reach the reader when the queue releases.
    const host = new ScriptedHost("c-12");
    host.replayControlled = true;
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-12");
    const seen = collect(sse);
    sse.stream();
    await host.replayRequested;

    host.handler?.({ stream_id: "c-12", status: "error", events: [] });
    expect(seen.error).toHaveLength(0); // held, not dropped

    host.settleReplayNow({ stream_id: "c-12", status: "active", events: [frame(1, { a: 1 })] });
    await settled();

    expect(seen.message).toHaveLength(1); // the page still rendered
    expect(seen.error).toHaveLength(1); // …and the breaker still reported
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
  });

  it("a terminal page with no frames ends the stream even when the status is not `error`", async () => {
    // The hole the `error`-only escalation left, and it is reachable for real. After a
    // mid-turn sidecar restart the engine reconciles the dead turn by writing its aborted
    // `final` at `durable_max + 1` — at or BELOW a poller whose cursor tracked the LIVE
    // in-memory ledger (the store flushes every 25 frames or 250 ms, so it lags). The engine
    // filters that frame out as not-after-the-cursor, and the poller's last word is an EMPTY
    // page with `status: "aborted"`. Escalating only on "error" left readyState OPEN with no
    // event at all: the same frozen spinner, one status word to the left.
    const host = new ScriptedHost("c-13");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-13");
    const seen = collect(sse);
    sse.stream();
    await settled();

    host.handler?.({ stream_id: "c-13", status: "aborted", events: [] });

    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(1);
    const reported = JSON.parse(seen.error[0] ?? "{}") as { error?: string };
    expect(reported.error).toContain("aborted");
  });

  it("a terminal page that still CARRIES frames is not ended early", async () => {
    // The counter-test that keeps the rule above from firing on the happy path. The poller
    // emits terminal pages that still have events BEFORE its drained read, and the turn's
    // `final` frame may be in the next one — closing on the first would truncate every turn.
    const host = new ScriptedHost("c-14");
    setHostLoaderForTest(async () => host);
    const sse = new TempestSSE("/api/agents/chat/stream/c-14");
    const seen = collect(sse);
    sse.stream();
    await settled();

    host.handler?.({ stream_id: "c-14", status: "complete", events: [delta(1, "s", "hi")] });
    expect(sse.readyState).toBe(TempestSSE.OPEN);
    expect(seen.error).toHaveLength(0);

    // …and the real final, arriving next, closes it honestly with no error.
    host.handler?.({ stream_id: "c-14", status: "complete", events: [frame(2, { final: true })] });
    expect(sse.readyState).toBe(TempestSSE.CLOSED);
    expect(seen.error).toHaveLength(0);

    // The poller's drained tail push then lands on a closed stream and must stay silent.
    host.handler?.({ stream_id: "c-14", status: "complete", events: [] });
    expect(seen.error).toHaveLength(0);
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
