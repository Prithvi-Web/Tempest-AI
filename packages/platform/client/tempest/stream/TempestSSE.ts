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
    if (this.unlisten !== null) {
      this.unlisten();
      this.unlisten = null;
    }
  }

  private async attach(): Promise<void> {
    try {
      const host = await hostLoader();
      // Subscribe FIRST so nothing can land between replay and the live feed…
      const unlisten = await host.listen((push) => this.deliver(push));
      if (this.closed) {
        unlisten(); // closed while connecting: the subscription must not outlive us
        return;
      }
      this.unlisten = unlisten;
      this.readyState = TempestSSE.OPEN;
      this.emit("open", "");
      // …then replay the ledger so far, FROM OUR OWN CURSOR.
      //
      // A live push can land during the replay's round trip — the poll interval is 40 ms and
      // the round trip is single-digit ms, so this window is hit routinely. Both reads
      // coalesce, and a merged delta frame carries its run's LAST seq, so a replay computed
      // from a lower cursor merges a LONGER run than the push did: the overlap arrives under
      // a seq the client has never seen, and a membership set cannot collapse it. The user
      // saw the run's text twice.
      //
      // So the cursor is re-read after every round trip, and a replay that was overtaken is
      // re-requested rather than delivered. It converges immediately in practice (one extra
      // round trip at most), and the bound keeps a pathological feed from spinning here.
      for (let attempt = 0; attempt < 4; attempt += 1) {
        const requestedFrom = this.highWater;
        const page = await host.replay(this.streamId, requestedFrom);
        if (this.closed) {
          return;
        }
        if (this.highWater === requestedFrom) {
          this.deliver(page);
          return;
        }
      }
      // Exhausted: serve what the last cursor can still be trusted for. Frames at or below
      // the high-water mark are already on screen; anything above it is genuinely new.
      this.deliver(await host.replay(this.streamId, this.highWater));
    } catch (error) {
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
