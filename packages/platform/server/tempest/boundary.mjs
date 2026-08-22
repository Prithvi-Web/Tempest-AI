// Boundary E's Node endpoint (PLAN-V3 C2; master prompt §7): JSON-RPC 2.0 over a Unix domain
// socket with `Content-Length` framing, supervised by the Rust host (supervisor.rs, L34).
//
// This file is the platform sidecar's front door. At C2 it serves the boundary's lifecycle
// methods only; C5 re-targets LibreChat's agent surface through it (ADR-0075) — the schema
// leads, services follow. Dependency-free on purpose: the vendored tree has no node_modules.
//
// Containment posture, each line load-bearing:
//   - listens ONLY on the Unix socket named by TEMPEST_PLATFORM_SOCKET — no TCP, ever;
//   - validates every inbound AND outbound message in production (boundary-validate.mjs);
//   - every failure is a structured JSON-RPC error with a diagnostic_id (L15.3);
//   - exits itself when the host dies: stdin EOF (the host holds our stdin pipe; SIGKILL of
//     the host closes it) plus a reparenting watch (ppid → 1), mirroring the engine sidecar;
//   - unlinks its socket on every exit path it can see.
import { createServer } from "node:net";
import { unlinkSync } from "node:fs";
import process from "node:process";

import { PLATFORM_METHODS, PROTOCOL_VERSION } from "./generated/platform-schema.mjs";
import { checkRequest, checkResponse, checkResult } from "./boundary-validate.mjs";
import { handleLocalApi } from "./local-api.mjs";

const MAX_FRAME_BYTES = 64 * 1024 * 1024; // mirrors framing.rs
const MAX_HEADER_BYTES = 8192;

const socketPath = process.env.TEMPEST_PLATFORM_SOCKET;
if (!socketPath) {
  process.stderr.write("boundary: TEMPEST_PLATFORM_SOCKET is not set — refusing to guess\n");
  process.exit(2);
}

let diagnosticCounter = 0;
const diagnosticId = () =>
  `E-${process.pid.toString(16)}-${Date.now().toString(16)}-${(diagnosticCounter++).toString(16)}`;

const log = (line) => process.stderr.write(`boundary: ${line}\n`);

// ── lifetime: die with the host ─────────────────────────────────────────────────────────────
const exitCleanly = (why, code = 0) => {
  log(`exiting (${why})`);
  try {
    unlinkSync(socketPath);
  } catch {
    // already gone — fine
  }
  process.exit(code);
};
process.stdin.resume();
process.stdin.on("end", () => exitCleanly("host closed our stdin"));
process.stdin.on("close", () => exitCleanly("host closed our stdin"));
process.stdin.on("error", () => exitCleanly("host stdin errored"));
setInterval(() => {
  if (process.ppid === 1) exitCleanly("reparented to init — the host is gone");
}, 2000).unref();
process.on("SIGTERM", () => exitCleanly("SIGTERM"));
process.on("SIGINT", () => exitCleanly("SIGINT"));

// ── method handlers (C2: lifecycle only) ────────────────────────────────────────────────────
let shutdownRequested = false;
const HANDLERS = {
  "platform.ping": () => ({
    ok: true,
    pid: process.pid,
    protocol_version: PROTOCOL_VERSION,
    node_version: process.version,
  }),
  "platform.describe": () => ({
    protocol_version: PROTOCOL_VERSION,
    methods: [...PLATFORM_METHODS],
  }),
  "platform.shutdown": () => {
    shutdownRequested = true;
    return { ok: true };
  },
  // C3: the webview's /api surface, carried over boundary E. In local mode the seam answers;
  // C5 re-targets this dispatch onto LibreChat's real services (ADR-0075) without the caller
  // changing shape.
  "platform.http": (params) => {
    const request = params?.request;
    if (
      !request ||
      typeof request.method !== "string" ||
      typeof request.path !== "string" ||
      typeof request.body_base64 !== "string"
    ) {
      throw new Error("platform.http params.request needs {method, path, body_base64}");
    }
    const reply = handleLocalApi(request.method, request.path);
    return {
      status: reply.status,
      content_type: reply.content_type,
      body_base64: Buffer.from(reply.body, "utf8").toString("base64"),
    };
  },
};

// The handler table and the generated method list must never drift: a schema method with no
// handler (or the reverse) is a contract violation this process refuses to start with.
{
  const handlerKeys = Object.keys(HANDLERS).sort().join(",");
  const schemaKeys = [...PLATFORM_METHODS].sort().join(",");
  if (handlerKeys !== schemaKeys) {
    log(`handler/schema drift: handlers [${handlerKeys}] vs schema [${schemaKeys}]`);
    process.exit(2);
  }
}

// ── framing (mirrors framing.rs: Content-Length header, CRLF CRLF, payload) ─────────────────
const encodeFrame = (payload) => {
  const body = Buffer.from(payload, "utf8");
  return Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, "ascii"), body]);
};

const respond = (connection, response, method) => {
  // Outbound validation IN PRODUCTION: a reply this process cannot prove well-formed does not
  // leave it — the envelope AND, for successes, the method's result shape. The replacement
  // error is minimal, schema-valid by construction, and logged.
  let verdict = checkResponse(response);
  if (verdict.ok && method && "result" in response) {
    verdict = checkResult(method, response.result);
  }
  if (!verdict.ok) {
    const id = diagnosticId();
    log(`OUTBOUND message failed validation [${id}]: ${verdict.why}`);
    response = {
      jsonrpc: "2.0",
      id: typeof response?.id === "number" ? response.id : 0,
      error: {
        code: -32603,
        message: "internal: the boundary produced an off-contract reply and refused to send it",
        diagnostic_id: id,
      },
    };
  }
  connection.write(encodeFrame(JSON.stringify(response)));
  if (shutdownRequested) {
    connection.end();
    server.close(() => exitCleanly("platform.shutdown"));
    // A peer that never reads leaves close() pending; the host's TERM ladder is the backstop.
    setTimeout(() => exitCleanly("platform.shutdown (close timeout)"), 500).unref();
  }
};

const handleFrame = (connection, payloadBytes) => {
  let parsed;
  try {
    parsed = JSON.parse(payloadBytes.toString("utf8"));
  } catch (err) {
    const id = diagnosticId();
    log(`inbound frame is not JSON [${id}]: ${err.message}`);
    respond(connection, {
      jsonrpc: "2.0",
      id: 0,
      error: { code: -32700, message: `parse error: frame is not JSON [diagnostic ${id}]`, diagnostic_id: id },
    });
    return;
  }
  const verdict = checkRequest(parsed);
  if (!verdict.ok) {
    const id = diagnosticId();
    log(`inbound message failed validation [${id}]: ${verdict.why}`);
    respond(connection, {
      jsonrpc: "2.0",
      id: isFiniteId(parsed) ? parsed.id : 0,
      error: {
        code: -32600,
        message: `invalid request: ${verdict.why} [diagnostic ${id}]`,
        diagnostic_id: id,
      },
    });
    return;
  }
  const handler = HANDLERS[parsed.method];
  try {
    respond(
      connection,
      { jsonrpc: "2.0", id: parsed.id, result: handler(parsed.params) },
      parsed.method,
    );
  } catch (err) {
    const id = diagnosticId();
    log(`handler ${parsed.method} threw [${id}]: ${err.stack ?? err}`);
    respond(connection, {
      jsonrpc: "2.0",
      id: parsed.id,
      error: { code: -32603, message: `internal error in handler [diagnostic ${id}]`, diagnostic_id: id },
    });
  }
};

const isFiniteId = (parsed) =>
  parsed &&
  typeof parsed === "object" &&
  Number.isInteger(parsed.id) &&
  parsed.id >= 0 &&
  parsed.id <= 2147483647;

// Incremental frame decoder per connection: buffer bytes, peel complete frames.
const makeDecoder = (connection) => {
  let buffer = Buffer.alloc(0);
  return (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    for (;;) {
      const headerEnd = buffer.indexOf("\r\n\r\n");
      if (headerEnd === -1) {
        if (buffer.length > MAX_HEADER_BYTES) {
          log("frame header exceeds 8 KiB — dropping the connection");
          connection.destroy();
        }
        return;
      }
      const headerBytes = buffer.subarray(0, headerEnd);
      // framing.rs rejects non-UTF-8 header lines; ascii-decoding would MASK high bytes onto
      // valid letters, so a garbage header could still read as Content-Length. Reject instead.
      if (headerBytes.some((byte) => byte > 0x7e || (byte < 0x20 && byte !== 0x0d && byte !== 0x0a && byte !== 0x09))) {
        log("frame header carries non-ASCII bytes — dropping the connection");
        connection.destroy();
        return;
      }
      const header = headerBytes.toString("ascii");
      const matches = [...header.matchAll(/content-length:\s*(\d+)/gi)];
      if (matches.length !== 1) {
        // framing.rs takes the LAST occurrence; taking the first here would let one frame
        // read as two different lengths on the two sides. Ambiguity is rejected, not chosen.
        log(`frame carries ${matches.length} Content-Length headers — dropping the connection`);
        connection.destroy();
        return;
      }
      const match = matches[0];
      const length = Number(match[1]);
      if (!Number.isSafeInteger(length) || length > MAX_FRAME_BYTES) {
        log(`frame length ${match[1]} exceeds the cap — dropping the connection`);
        connection.destroy();
        return;
      }
      const frameEnd = headerEnd + 4 + length;
      if (buffer.length < frameEnd) return; // wait for the rest
      const payload = buffer.subarray(headerEnd + 4, frameEnd);
      buffer = buffer.subarray(frameEnd);
      handleFrame(connection, payload);
    }
  };
};

const server = createServer((connection) => {
  connection.on("data", makeDecoder(connection));
  connection.on("error", (err) => log(`connection error: ${err.message}`));
});
server.on("error", (err) => {
  log(`cannot bind ${socketPath}: ${err.message}`);
  process.exit(2);
});
server.listen(socketPath, () => {
  log(`listening on ${socketPath} (protocol ${PROTOCOL_VERSION}, pid ${process.pid})`);
});
