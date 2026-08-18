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
import http from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
let stdoutBuf = Buffer.alloc(0);
let nextRpcId = 1;
const pending = new Map(); // rpc id -> {resolve, reject, timer}

function spawnSidecar() {
  child = spawn("uv", ["run", "tempest-server", "--stdio", "--data-dir", dataDir], {
    cwd: REPO_ROOT,
    env: { ...process.env, TEMPEST_DEV: "1", TEMPEST_NO_POWER_PAUSE: "1" },
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
  cancel_run: (a) => ["cancelRun", { run_id: a.runId }],
  search_divergences: (a) => ["searchDivergences", omitNulls({ q: a.q, limit: a.limit })],
  list_log_records: (a) => ["listLogs", omitNulls({ limit: a.limit, level: a.level })],
  get_settings: () => ["getSettings", {}],
  update_settings: (a) => ["updateSettings", { body: a.settings }],
  test_ai_key: () => ["testAiKey", {}],
  sync_push: (a) => ["syncPush", { body: { server_url: a.serverUrl } }],
  export_diagnostics: () => ["exportDiagnostics", {}],
  get_watch_status: () => ["getWatchStatus", {}],
  start_watch: (a) => ["startWatch", { body: a.request }],
  stop_watch: () => ["stopWatch", {}],
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
        trace(`< ${operation} ok ${Date.now() - t0}ms ${JSON.stringify(data).slice(0, 80)}`);
        json(res, 200, { data });
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
