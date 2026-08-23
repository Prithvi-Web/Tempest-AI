/**
 * E2E bridge: the Rust host's Boundary A role, played by node so Playwright can drive the
 * REAL webview UI against the REAL engine sidecar in a plain browser.
 *
 *   Chromium (vite dev, shim.js) ──HTTP──▶ this bridge ──stdio JSON-RPC──▶ tempest-server
 *
 * It speaks the exact frames the Rust supervisor speaks (Content-Length framing,
 * operation names + snake_case params copied from src-tauri/src/commands.rs) against a
 * sidecar spawned the exact way the app spawns it (--stdio --data-dir). Nothing here mocks
 * engine behavior — every response the UI renders was computed by the real engine (Law L4).
 *
 * Admin endpoints exist ONLY to stage lifecycle scenarios the Rust supervisor owns in the
 * real app (crash → restart): /admin/engine-down SIGKILLs the sidecar process group,
 * /admin/engine-up respawns it on the same data dir.
 *
 * Zero npm dependencies — node:http + node:child_process only.
 */

import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, existsSync, appendFileSync } from "node:fs";
import fs from "node:fs/promises";
import http from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Boundary B deep validation (ADR-0077): the schema net the legacy webview ran in dev builds
// lives in the bridge now — every engine reply is validated before the page sees it, and
// /admin/corrupt-next + /admin/contract-ledger let the 07 spec prove the net CATCHES.
import { checkContract, corruptNext, ledger } from "./contract-net.mjs";

const PORT = Number(process.env.E2E_BRIDGE_PORT ?? 39755);
// Optional per-call trace (E2E_BRIDGE_LOG=/path): one line per invoke with latency and
// outcome — the first thing to reach for when a spec sees the UI stall.
const TRACE = process.env.E2E_BRIDGE_LOG ?? null;
function trace(line) {
  if (TRACE) appendFileSync(TRACE, `${new Date().toISOString()} ${line}\n`);
}
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const CALL_TIMEOUT_MS = 30_000;

// ── fixture: the pyfix repo (base/head branches, 12 seeded behavior changes) ──────────────
const workRoot = mkdtempSync(path.join(tmpdir(), "tempest-e2e-"));
const dataDir = path.join(workRoot, "data");
const fixtureRepo = path.join(workRoot, "pyfix");
execFileSync(
  "uv",
  ["run", "python", "corpus/fixtures/pyfix/make_fixture.py", fixtureRepo],
  { cwd: REPO_ROOT, stdio: ["ignore", "ignore", "inherit"] },
);
if (!existsSync(fixtureRepo)) throw new Error("pyfix fixture build produced nothing");

// ── sidecar process (spawned exactly like the app: --stdio --data-dir) ────────────────────
let child = null;
let chatPeer = {
  chunks: ["Hello ", "from ", "the peer"],
  usage: { prompt_tokens: 5, completion_tokens: 3 },
  holdAfterFirst: false,
  status: 200,
  resume: false,
  closedEarly: false,
  requests: [],
};
let stdoutBuf = Buffer.alloc(0);
let nextRpcId = 1;
const pending = new Map(); // rpc id -> {resolve, reject, timer}

function spawnSidecar() {
  child = spawn("uv", ["run", "tempest-server", "--stdio", "--data-dir", dataDir], {
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      TEMPEST_DEV: "1",
      TEMPEST_NO_POWER_PAUSE: "1",
      // C5 chat specs: the engine's ollama provider reaches the bridge's own scripted
      // OpenAI-wire peer — the exact way a real local runner is reached, no mocks (L4).
      TEMPEST_MODEL_BASE_URL_OLLAMA: `http://127.0.0.1:${PORT}/chat-peer/v1`,
    },
    stdio: ["pipe", "pipe", "inherit"],
    detached: true, // own process group, so engine-down can SIGKILL the whole tree
  });
  stdoutBuf = Buffer.alloc(0);
  const proc = child;
  // A SIGKILLed engine with a write in flight raises EPIPE on stdin — swallow it (the
  // pending-call rejection already reports the death) instead of crashing the bridge.
  proc.stdin.on("error", () => {});
  proc.stdout.on("data", (chunk) => {
    if (proc !== child) return; // frames from a killed generation must not resolve new calls
    stdoutBuf = Buffer.concat([stdoutBuf, chunk]);
    drainFrames();
  });
  proc.on("exit", () => {
    if (proc !== child) return;
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject({ code: -32099, message: "engine process is not running" });
    }
    pending.clear();
  });
}

function killSidecar() {
  if (child === null) return;
  const proc = child;
  child = null;
  for (const entry of pending.values()) {
    clearTimeout(entry.timer);
    entry.reject({ code: -32099, message: "engine process is not running" });
  }
  pending.clear();
  try {
    process.kill(-proc.pid, "SIGKILL"); // the whole group: uv wrapper + server
  } catch {
    try {
      proc.kill("SIGKILL");
    } catch {
      /* already gone */
    }
  }
}

function drainFrames() {
  for (;;) {
    const headerEnd = stdoutBuf.indexOf("\r\n\r\n");
    if (headerEnd === -1) return;
    const header = stdoutBuf.subarray(0, headerEnd).toString("ascii");
    const match = /content-length:\s*(\d+)/i.exec(header);
    if (!match) throw new Error(`sidecar frame missing Content-Length: ${header}`);
    const length = Number(match[1]);
    const frameEnd = headerEnd + 4 + length;
    if (stdoutBuf.length < frameEnd) return; // wait for the rest of the payload
    const payload = stdoutBuf.subarray(headerEnd + 4, frameEnd).toString("utf-8");
    stdoutBuf = stdoutBuf.subarray(frameEnd);
    const message = JSON.parse(payload);
    const entry = pending.get(message.id);
    if (entry) {
      pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error !== undefined) entry.reject(message.error);
      else entry.resolve(message.result);
    }
  }
}

function call(operation, params) {
  return new Promise((resolve, reject) => {
    if (child === null) {
      reject({ code: -32099, message: "engine process is not running" });
      return;
    }
    const id = nextRpcId++;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject({ code: -32098, message: `call ${operation} timed out after ${CALL_TIMEOUT_MS}ms` });
    }, CALL_TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    const payload = Buffer.from(
      JSON.stringify({ jsonrpc: "2.0", id, method: operation, params }),
      "utf-8",
    );
    child.stdin.write(`Content-Length: ${payload.length}\r\n\r\n`);
    child.stdin.write(payload);
  });
}

// ── command → operation mapping (transcribed from src-tauri/src/commands.rs: same names,
//    same snake_case params, same omit-when-null discipline) ──────────────────────────────
function omitNulls(obj) {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== null && v !== undefined));
}

const COMMANDS = {
  get_health: () => ["getHealth", {}],
  list_runs: (a) => ["listRuns", omitNulls({ verdict: a.verdict, cursor: a.cursor, limit: a.limit })],
  get_run: (a) => ["getRun", { run_id: a.runId }],
  list_run_events: (a) => ["listRunEvents", { run_id: a.runId }],
  get_target: (a) => ["getTarget", { target_id: a.targetId }],
  get_divergence: (a) => ["getDivergence", { divergence_id: a.divergenceId }],
  get_divergence_repro: (a) => ["getDivergenceRepro", { divergence_id: a.divergenceId }],
  start_local_prove: (a) => ["startLocalProve", { body: a.request }],
  compose_change: (a) => ["composeChange", { body: a.request }],
  cancel_run: (a) => ["cancelRun", { run_id: a.runId }],
  search_divergences: (a) => ["searchDivergences", omitNulls({ q: a.q, limit: a.limit })],
  divergences_for_symbol: (a) =>
    ["divergencesForSymbol", omitNulls({ symbol: a.symbol, limit: a.limit })],
  list_log_records: (a) => ["listLogs", omitNulls({ limit: a.limit, level: a.level })],
  get_settings: () => ["getSettings", {}],
  update_settings: (a) => ["updateSettings", { body: a.settings }],
  test_ai_key: () => ["testAiKey", {}],
  sync_push: (a) => ["syncPush", { body: { server_url: a.serverUrl } }],
  export_diagnostics: () => ["exportDiagnostics", {}],
  get_watch_status: () => ["getWatchStatus", {}],
  start_watch: (a) => ["startWatch", { body: a.request }],
  stop_watch: () => ["stopWatch", {}],
  report_ui_error: (a) => ["reportUiError", { body: a.report }],
  start_demo_prove: () => ["startDemoProve", {}],
};

// ── HTTP surface (CORS: the page lives on localhost:1420, we are 127.0.0.1:PORT) ──────────
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
};

function json(res, status, body) {
  res.writeHead(status, { ...CORS, "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS);
    res.end();
    return;
  }
  if (req.method === "GET" && req.url === "/health") {
    json(res, 200, {
      ok: true,
      sidecarAlive: child !== null,
      dataDir,
      fixture: { repo: fixtureRepo, base: "base", head: "head" },
    });
    return;
  }
  if (req.method === "POST" && req.url === "/admin/engine-down") {
    killSidecar();
    json(res, 200, { sidecarAlive: false });
    return;
  }
  if (req.method === "POST" && req.url === "/admin/engine-up") {
    if (child === null) spawnSidecar();
    json(res, 200, { sidecarAlive: true });
    return;
  }
  // Boundary B net staging (ADR-0077): script exactly ONE corrupted reply, so the 07 spec can
  // prove the schema net catches drift rather than merely running. The corruption happens on
  // the bridge side of the wire — the ENGINE's reply is real; what is being tested is the net.
  if (req.method === "POST" && req.url === "/admin/corrupt-next") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        const body = JSON.parse(raw);
        if (typeof body.operation !== "string" || body.operation === "") {
          json(res, 400, { error: { code: -32602, message: "operation (string) is required" } });
          return;
        }
        corruptNext(body.operation);
        json(res, 200, { armed: body.operation });
      } catch (err) {
        json(res, 400, { error: { code: -32700, message: String(err) } });
      }
    });
    return;
  }
  if (req.method === "GET" && req.url === "/admin/contract-ledger") {
    json(res, 200, { violations: ledger });
    return;
  }
  // ── C5: the scripted chat peer + the chat-operation door ────────────────────────────
  // The peer is the OpenAI-wire SSE endpoint the engine's ollama row points at (spawn env
  // above); /admin/chat-peer scripts its next answers. hold/resume make cancellation a fact
  // rather than a race (trap 61): the peer stops after its first delta until resumed, and
  // records whether the client genuinely hung up.
  if (req.method === "POST" && req.url === "/admin/chat-peer") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      try {
        const body = JSON.parse(raw);
        chatPeer = {
          chunks: Array.isArray(body.chunks) ? body.chunks : ["Hello ", "from ", "the peer"],
          usage: body.usage === null ? null : (body.usage ?? { prompt_tokens: 5, completion_tokens: 3 }),
          // Frame indices to PARK after; each /resume releases one hold in order. Staged
          // holds are how "the engine hung up" becomes observable without a buffer race
          // (trap 61): park, let the test drive the state it needs, then the NEXT write
          // is the measurement.
          holds: Array.isArray(body.holds)
            ? body.holds
            : body.holdAfterFirst === true
              ? [0]
              : [],
          resumeCount: 0,
          status: typeof body.status === "number" ? body.status : 200,
          closedEarly: false,
          requests: [],
        };
        json(res, 200, { armed: true });
      } catch (err) {
        json(res, 400, { error: String(err) });
      }
    });
    return;
  }
  if (req.method === "POST" && req.url === "/admin/chat-peer/resume") {
    chatPeer.resumeCount += 1;
    json(res, 200, { resumed: chatPeer.resumeCount });
    return;
  }
  if (req.method === "GET" && req.url === "/admin/chat-peer/state") {
    json(res, 200, {
      closedEarly: chatPeer.closedEarly,
      requests: chatPeer.requests,
    });
    return;
  }
  if (req.method === "POST" && req.url === "/chat-peer/v1/chat/completions") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      const body = JSON.parse(raw);
      chatPeer.requests.push(body);
      if (chatPeer.status !== 200) {
        json(res, chatPeer.status, { error: { message: "planted failure" } });
        return;
      }
      res.writeHead(200, { "content-type": "text/event-stream" });
      const frames = chatPeer.chunks.map(
        (chunk) => `data: ${JSON.stringify({ choices: [{ delta: { content: chunk } }] })}\n\n`,
      );
      if (chatPeer.usage !== null) {
        frames.push(`data: ${JSON.stringify({ choices: [], usage: chatPeer.usage })}\n\n`);
      }
      frames.push("data: [DONE]\n\n");
      try {
        let holdsPassed = 0;
        for (let index = 0; index < frames.length; index += 1) {
          res.write(frames[index]);
          if (res.writableEnded || res.destroyed) throw new Error("gone");
          if (chatPeer.holds.includes(index)) {
            holdsPassed += 1;
            const needed = holdsPassed;
            const deadline = Date.now() + 10_000; // safety net, not an expected wait
            while (chatPeer.resumeCount < needed && Date.now() < deadline) {
              await new Promise((resolve) => setTimeout(resolve, 20));
            }
          }
        }
        res.end();
      } catch {
        chatPeer.closedEarly = true;
      }
    });
    res.on("close", () => {
      // Abnormal close ONLY: node fires 'close' on ordinary completion too, and a flag
      // that sets itself on success is a vacuous assertion (trap 45).
      if (!res.writableEnded) {
        chatPeer.closedEarly = true;
      }
    });
    return;
  }
  // The platform harness's chat routes reach the engine's chat operations here — raw
  // operationIds, no tauri-command indirection (these are host-protocol intercepts in the
  // app, not commands; their shapes are pinned by the api suite and the client's behavior).
  if (req.method === "POST" && req.url === "/chat-op") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      try {
        const body = JSON.parse(raw);
        const reply = await call(body.operation, body.params ?? {});
        json(res, 200, reply);
      } catch (err) {
        // The engine's own HTTP status and body ride the RPC error's data (stdiorpc's
        // _HTTP_ERROR envelope); pass them through so a 404 stays a 404 — mirroring the
        // host's engine_reply_passthrough. Transport failures keep the loud 502.
        const data = err && typeof err === "object" ? err.data : undefined;
        const status =
          data && typeof data.status === "number" && data.status >= 400 && data.status < 600
            ? data.status
            : 502;
        const body =
          data && data.body !== undefined
            ? data.body
            : { error: err instanceof Error ? err.message : (err && err.message) || JSON.stringify(err) };
        json(res, status, body);
      }
    });
    return;
  }

  // Phase 20.1: `read_project_file` is a HOST command with no sidecar behind it, so the bridge
  // performs a genuine read from a real fixture project. The guard's RULES (traversal,
  // credentials, symlink escapes, binary) are pinned by 26 Rust tests in pathguard.rs; what this
  // endpoint exists to prove is the other half — that real bytes off a real disk reach the real
  // CodeMirror instance in the real webview.
  if (req.method === "POST" && req.url === "/project-file") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      try {
        const body = JSON.parse(raw);
        const root = await fs.realpath(body.repo_path);
        const resolved = await fs.realpath(path.join(root, body.path));
        if (!resolved.startsWith(root + path.sep)) throw new Error("escapes root");
        const text = await fs.readFile(resolved, "utf8");
        json(res, 200, {
          path: path.relative(root, resolved),
          text,
          bytes: Buffer.byteLength(text),
        });
      } catch (err) {
        // A MISSING file is a product refusal; anything else is the harness breaking, and the two
        // must not look alike. They did once: a missing `fs` import made every read throw, the
        // refusal spec went green on the resulting "not found", and only the specs that needed a
        // mounted editor noticed. A broken bridge now says so, loudly.
        const missing = err && (err.code === "ENOENT" || err.code === "ENOTDIR");
        json(res, 200, {
          error: missing
            ? { refusal: { kind: "not_found" }, message: "no such file in the project" }
            : { refusal: { kind: "unreadable" }, message: `e2e bridge failure: ${err?.message ?? err}` },
        });
      }
    });
    return;
  }

  if (req.method === "POST" && req.url === "/invoke") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      let cmd = "";
      try {
        const body = JSON.parse(raw);
        cmd = body.cmd;
        const mapping = COMMANDS[cmd];
        if (!mapping) {
          json(res, 400, { error: { code: -32601, message: `unknown command ${cmd}` } });
          return;
        }
        const [operation, params] = mapping(body.args ?? {});
        const t0 = Date.now();
        trace(`> ${operation} ${JSON.stringify(params).slice(0, 120)}`);
        const data = await call(operation, params);
        // The Boundary B net (contract-net.mjs): an off-contract reply becomes an in-band
        // error the view renders as a failure — never data the view renders as truth.
        const verdict = checkContract(operation, data);
        if (!verdict.ok) {
          trace(`< ${operation} CONTRACT ${verdict.failure.message.slice(0, 100)}`);
          json(res, 200, { error: verdict.failure });
          return;
        }
        trace(`< ${operation} ok ${Date.now() - t0}ms ${JSON.stringify(data).slice(0, 80)}`);
        json(res, 200, { data: verdict.data });
      } catch (err) {
        const failure =
          err && typeof err === "object" && "code" in err
            ? { code: err.code, message: String(err.message ?? "engine error") }
            : { code: -32603, message: `bridge failure on ${cmd}: ${String(err)}` };
        trace(`< ${cmd} ERR ${failure.code} ${failure.message.slice(0, 100)}`);
        // 200, not 5xx: an engine-level error is a RESULT the shim rethrows, exactly like a
        // real Tauri invoke rejection. A non-2xx would make Chromium log a resource error
        // and trip the console-clean gate on flows that are behaving correctly.
        json(res, 200, { error: failure });
      }
    });
    return;
  }
  json(res, 404, { error: { code: -32601, message: `no route ${req.method} ${req.url}` } });
});

// ── boot: spawn, wait for a healthy engine, then open the HTTP port ───────────────────────
spawnSidecar();
const deadline = Date.now() + 90_000;
for (;;) {
  try {
    await call("getHealth", {});
    break;
  } catch {
    if (Date.now() > deadline) {
      console.error("bridge: sidecar never became healthy");
      killSidecar();
      process.exit(1);
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}
server.listen(PORT, "127.0.0.1", () => {
  console.log(`bridge: ready on 127.0.0.1:${PORT} (data ${dataDir})`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    killSidecar();
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1000).unref();
  });
}
