/**
 * The app's stream transport — sse.js's interface over boundary-B events (ADR-0078).
 *
 * The tempest:// protocol cannot stream (wry's scheme responder is one-shot), so inside the
 * desktop app the vendored client's SSE subscription rides tauri events instead: the host
 * polls the engine's frame ledger and pushes batches; this class subscribes FIRST, then
 * replays the ledger so far, deduping by seq — no frame can fall between the two. The
 * harness and server mode never take this path: `available()` keys on the marker only the
 * desktop host injects, so real sse.js keeps serving everywhere else and both transports of
 * the one frame vocabulary stay tested.
 *
 * The surface is exactly the slice of sse.js the vendored hook consumes (measured, not
 * assumed): `new SSE(url, {headers, method})` · `stream()` · `close()` · `readyState`
 * compared against the class statics · `addEventListener('open'|'message'|'error'|'abort')`
 * with JSON text in `e.data`. The numeric states are sse.js's own — the hook compares this
 * instance's `readyState` against the ORIGINAL class's constants, so the numbers are the
 * contract, not an aesthetic.
 */

export interface StreamFrame {
  seq: number;
  frame_json: string;
}

export interface StreamPush {
  stream_id: string;
  status: string;
  events: StreamFrame[];
}

/** What the desktop host provides: a live event feed and a ledger replay. */
export interface TempestSSEHost {
  listen(handler: (push: StreamPush) => void): Promise<() => void>;
  /** `after` is the caller's high-water seq: the ledger is served, and COALESCED, from
   * there. Replaying from 0 while a live push has already delivered part of the run merges
   * a longer run than the push did, and the overlap arrives under a seq the client has
   * never seen. */
  replay(streamId: string, after: number): Promise<StreamPush>;
}

type Listener = (event: { data: string }) => void;

type HostLoader = () => Promise<TempestSSEHost>;

/** The tauri-binding glue lives in its own module (e2e-pinned, like hooks.ts); tests swap
 * the loader so this state machine is measurable without an IPC. */
const defaultHostLoader: HostLoader = () =>
  import("./streamHost").then((module) => module.streamHost);

let hostLoader: HostLoader = defaultHostLoader;

export function setHostLoaderForTest(loader: HostLoader | null): void {
  hostLoader = loader ?? defaultHostLoader;
}

declare global {
  interface Window {
    __TEMPEST_APP__?: boolean;
  }
}

export class TempestSSE {
  static INITIALIZING = -1;
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  readyState: number = TempestSSE.INITIALIZING;

  private readonly streamId: string;
  private readonly listeners = new Map<string, Listener[]>();
  private readonly delivered = new Set<number>();
  /** The highest seq delivered so far — the cursor a replay must be served from. Coalesced
   * delta frames make a membership set insufficient on its own: the same text can arrive
   * under two different seqs if two reads merge different runs. */
  private highWater = 0;
  private unlisten: (() => void) | null = null;
  /** False until the first replay page has been delivered. While false, live pushes are HELD
   * rather than delivered — see `receive` (ADR-0089). */
  private primed = false;
  /** Live pushes that arrived before the first page landed, in arrival order. */
  private held: StreamPush[] = [];
  private closed = false;

  constructor(url: string, _options?: Record<string, unknown>) {
    // …/api/agents/chat/stream/{streamId}?query — the id is the last path segment.
    const queryIndex = url.indexOf("?");
    const path = queryIndex === -1 ? url : url.slice(0, queryIndex);
    const segment = path.split("/").filter(Boolean).pop() ?? "";
    this.streamId = decodeURIComponent(segment);
  }

  /** True only inside the desktop app (the host injects the marker into index.html). */
  static available(): boolean {
    return typeof window !== "undefined" && window.__TEMPEST_APP__ === true;
  }

  addEventListener(type: string, listener: Listener): void {
    const bucket = this.listeners.get(type) ?? [];
    bucket.push(listener);
    this.listeners.set(type, bucket);
  }

  removeEventListener(type: string, listener: Listener): void {
    const bucket = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      bucket.filter((candidate) => candidate !== listener),
    );
  }

  stream(): void {
    if (this.readyState !== TempestSSE.INITIALIZING) {
      return; // sse.js ignores repeated stream() calls; so does this transport
    }
    this.readyState = TempestSSE.CONNECTING;
    void this.attach();
  }

  close(): void {
    if (this.closed) {
      return;
    }
    this.detach();
    this.emit("abort", "");
  }

  private detach(): void {
    this.closed = true;
    this.readyState = TempestSSE.CLOSED;
    this.held = [];
    if (this.unlisten !== null) {
      this.unlisten();
      this.unlisten = null;
    }
  }

  /** Everything the live feed pushes arrives here.
   *
   * Before the first replay page is on screen the push is HELD, not delivered. That single
   * rule is what closes the lost-`created` race (ADR-0089): the page is the authority for
   * everything up to its last seq, and the host starts this stream's feed inside that very
   * replay call, positioned at that same seq — so a held push can only contain frames the
   * page does not, and releasing the queue afterwards can neither duplicate nor lose.
   *
   * The transport used to deliver these immediately and then DISCARD the page whenever its
   * cursor had moved underneath it, on the correct reasoning that a coalesced delta carries
   * its run's last seq and a seq membership set cannot dedupe a partial overlap. What that
   * reasoning missed is that the poller's own first push — the one carrying `created` — was
   * emitted before `listen()` had resolved and was therefore lost, so the discarded page was
   * the only remaining copy of it. Holding instead of discarding keeps both halves.
   */
  private receive(push: StreamPush): void {
    if (this.primed) {
      this.deliver(push);
      return;
    }
    this.held.push(push);
  }

  /** Deliver everything held while the page was in flight, in arrival order.
   *
   * Frames at or below the page's last seq are dropped rather than delivered. That is the
   * coalescing rule read forwards: a merged delta frame carries its run's LAST seq, so a page
   * ending at seq N is a promise that everything up to N is on screen — and a held frame at
   * or below N is therefore already rendered, under whatever seq the page happened to merge
   * it into. Delivering it is precisely the double-render a seq membership set cannot catch.
   *
   * The host already guarantees this cannot arise, by starting the feed at the page's last
   * seq (`resume_cursor`), and THAT is where the guarantee lives. This filter is a backstop,
   * and an inexact one: a coalesced frame ending ABOVE the page's last seq may cover a run
   * that STARTED below it, and nothing in the frame says where its run began — so a
   * straddling frame from a mis-positioned feed would still render its overlap twice. Stated
   * rather than implied, because a backstop described as a guarantee is how the next reader
   * stops maintaining the real one. When no page arrived at all — the failure path —
   * `highWater` is still 0 and nothing is filtered, so held frames are never lost to this
   * rule.
   */
  private release(): void {
    const covered = this.highWater;
    this.primed = true;
    const held = this.held;
    this.held = [];
    for (const push of held) {
      this.deliver({ ...push, events: push.events.filter((event) => event.seq > covered) });
    }
  }

  private async attach(): Promise<void> {
    try {
      const host = await hostLoader();
      // Subscribe FIRST so nothing can land between replay and the live feed…
      const unlisten = await host.listen((push) => this.receive(push));
      if (this.closed) {
        unlisten(); // closed while connecting: the subscription must not outlive us
        return;
      }
      this.unlisten = unlisten;
      this.readyState = TempestSSE.OPEN;
      this.emit("open", "");
      // …then replay the ledger so far, FROM OUR OWN CURSOR. This call is also what starts
      // the host's live feed for this stream, positioned at the last seq it serves here — so
      // the page and everything that follows it are disjoint by construction, and this
      // transport no longer has to reason about a partial overlap it cannot dedupe.
      //
      // A live push can still land during the round trip (the poll interval is 40 ms and the
      // round trip is single-digit ms, so the window is hit routinely). It is HELD by
      // `receive` until the page is delivered, and released immediately after, in order.
      // One round trip, no retry, and no page is ever thrown away — the previous design
      // discarded exactly the page that held `created` (ADR-0089).
      const page = await host.replay(this.streamId, this.highWater);
      if (this.closed) {
        return;
      }
      this.deliver(page);
      this.release();
    } catch (error) {
      // The page never came. What the live feed already handed us is real ledger data, held
      // only for ordering, so release it BEFORE reporting: if it carried the turn's final
      // frame the stream ends honestly — exactly as it would have with no replay at all —
      // and `fail` then stays silent because the stream is already closed. Dropping the
      // queue here would report an error for a turn that had actually completed.
      this.release();
      this.fail(String(error));
    }
  }

  private deliver(push: StreamPush): void {
    if (this.closed || push.stream_id !== this.streamId) {
      return;
    }
    const ordered = [...push.events].sort((a, b) => a.seq - b.seq);
    for (const { seq, frame_json } of ordered) {
      if (this.delivered.has(seq)) {
        continue;
      }
      this.delivered.add(seq);
      if (seq > this.highWater) {
        this.highWater = seq;
      }
      this.emit("message", frame_json);
      let terminal = false;
      try {
        terminal = (JSON.parse(frame_json) as { final?: boolean }).final === true;
      } catch {
        terminal = false; // an unparseable frame is the client's problem to report, not ours
      }
      if (terminal) {
        // The terminal frame ends the stream exactly as a server closing the SSE would —
        // without the abort event a deliberate close() would emit.
        this.detach();
        return;
      }
    }
    // The host's own verdict on the feed, which this transport used to drop on the floor.
    //
    // A page that is TERMINAL and DRAINED is the poller's last word — it breaks its loop
    // straight after. If the stream is still open at that point we never saw the turn's
    // `final` frame, and no one is coming with it. That happens for real: after a mid-turn
    // sidecar restart the engine reconciles the dead turn by writing its aborted `final` at
    // `durable_max + 1`, which is at or BELOW a poller whose cursor tracked the live
    // in-memory ledger — so the engine filters it out and the page arrives empty with
    // `status: "aborted"`. Escalating only on `"error"` left exactly that case silent:
    // readyState OPEN, no error event, the reconnect ladder never armed. The same frozen
    // spinner ADR-0089 exists to end, one status word to the left.
    //
    // Terminal pages that still CARRY events are not escalated — the poller emits those
    // before its drained read, and the `final` frame may be in the next one.
    //
    // When the poller has failed for longer than its grace window it emits a push with
    // `status: "error"` and NO events — a purpose-built distress signal, added precisely so a
    // person is told rather than left watching a live-looking view that never moves. Every
    // reader here was frame-driven, `status` was declared on the interface and read nowhere,
    // and a push with an empty event list ran a loop body zero times. So the breaker fired
    // correctly, crossed boundary B fully typed, and changed nothing: no error event, no
    // close, `readyState` still OPEN, and `useResumableSSE.handleTransportFailure` — the
    // reconnect-and-adjudicate ladder — never armed. The outcome was the exact symptom the
    // 30-second deadline exists to prevent (ADR-0089 §2; ADR-0079's last deferral).
    //
    // Coverage could not have caught it: the branch did not exist to be missed.
    if (push.status !== "active" && push.events.length === 0) {
      this.fail(
        push.status === "error"
          ? "the live stream stopped: the host gave up waiting for the engine"
          : `the turn ended without a final frame (${push.status})`,
      );
    }
  }

  private fail(message: string): void {
    if (this.closed) {
      return;
    }
    this.detach();
    this.emit("error", JSON.stringify({ error: message }));
  }

  private emit(type: string, data: string): void {
    for (const listener of [...(this.listeners.get(type) ?? [])]) {
      listener({ data });
    }
  }
}
