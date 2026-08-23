/**
 * E2E platform surface: the `tempest://` protocol handler's semantics, on a port (ADR-0077).
 *
 * The suite's page is the BUILT platform client (packages/platform/client/dist — the exact
 * bytes the app bundles), so the server the suite needs is the one the Rust host implements
 * in platform_web.rs `handle()`. This file mirrors that mapping route for route:
 *
 *   - static assets from dist/ by extension; `..` refused; extensionless paths fall back to
 *     the transformed index.html (SPA routes);
 *   - index.html transformed exactly as `serve_index` does — a mode script first in <head>,
 *     the Tempest theme stylesheet injected LAST before </head>, the tab title ours. Two
 *     deliberate omissions, both stated: the console tap is NOT injected (fixtures.ts already
 *     listens on the page and the tap would swallow nothing it doesn't), and the
 *     `tempest-vibrancy` class is NOT added (macOS-app-only);
 *   - `/api/endpoints`, `/api/models` and `/api/keys*` are the host-intercept families
 *     (the C4 provider bridge answers them from the engine catalog and the OS keychain in the
 *     real app — neither exists in a browser harness), answered here with the exact upstream
 *     wire shapes the client consumes: a minimal static catalog, and the keyless
 *     `{"expiresAt":null}` / bare-201 / bare-204 key protocol;
 *   - every other `/api/*` is answered by the REAL local-mode seam: handleLocalApi from
 *     packages/platform/server/tempest/local-api.mjs, imported directly — the same code path
 *     the boundary sidecar runs in the app.
 *
 * The mode script SEEDS `color-theme='dark'` when unset (headless Chromium reports a light
 * system scheme, and the suite's baseline is the dark shell the product launches into); a
 * spec that emulates a scheme still owns the tempest views' own palette, which keys on
 * `prefers-color-scheme` (tempest-views.css).
 *
 * Zero npm dependencies — node:http + node:fs only (bridge.mjs discipline).
 */

import { readFileSync, existsSync, statSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { handleLocalApi } from "../../platform/server/tempest/local-api.mjs";

const PORT = Number(process.env.E2E_PLATFORM_PORT ?? 4180);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_ROOT = path.resolve(HERE, "..", "..", "platform", "client");
const DIST = path.join(CLIENT_ROOT, "dist");
const THEME_CSS = path.join(CLIENT_ROOT, "tempest", "theme.css");
const TEMPEST_ASSETS = path.join(CLIENT_ROOT, "tempest", "assets");

if (!existsSync(path.join(DIST, "index.html"))) {
  console.error(
    `platform-server: no built client at ${DIST} — run \`make platform-client-dist\` first`,
  );
  process.exit(1);
}

// ── mime map (platform_web.rs mime_for, verbatim) ─────────────────────────────────────────
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".webmanifest": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".mp3": "audio/mpeg",
  ".txt": "text/plain; charset=utf-8",
};
const mimeFor = (file) => MIME[path.extname(file).toLowerCase()] ?? "application/octet-stream";

// ── index.html, transformed at the seam (serve_index, minus tap and vibrancy) ─────────────
const MODE_SCRIPT =
  "<script>(function(){try{var t=localStorage.getItem('color-theme');" +
  "if(t==null){t='dark';localStorage.setItem('color-theme','dark')}" +
  "var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);" +
  "document.documentElement.classList.toggle('dark',d)}catch(e){}})();</script>";

function serveIndex(res) {
  let body;
  try {
    body = readFileSync(path.join(DIST, "index.html"), "utf-8");
  } catch (err) {
    respond(res, 503, "text/plain; charset=utf-8", `platform client dist unreadable: ${err}`);
    return;
  }
  body = body
    .replace("<title>LibreChat</title>", "<title>Tempest AI</title>")
    .replace("<head>", `<head>${MODE_SCRIPT}`)
    .replace("</head>", '<link rel="stylesheet" href="/tempest-theme.css" />\n</head>');
  respond(res, 200, "text/html; charset=utf-8", body);
}

// ── the two host-intercept families (C4 provider bridge, stood in for) ────────────────────
// The proof views never read the catalog; the chat shell's boot just needs valid LibreChat
// shapes. One keyless BYOK row, no models — the honest state of a machine with no key.
const CATALOG_ENDPOINTS = {
  anthropic: {
    order: 0,
    type: null,
    userProvide: true,
    userProvideURL: false,
    modelDisplayLabel: "Anthropic",
    iconURL: "/tempest-assets/providers/anthropic.svg",
  },
  // The C5 chat specs' endpoint: keyless and local, exactly the catalog row the engine
  // serves for ollama — whose base URL the bridge points at its own scripted peer.
  "Ollama (local)": {
    order: 1,
    type: "custom",
    userProvide: false,
    userProvideURL: false,
    modelDisplayLabel: "Ollama (local)",
    iconURL: "/tempest-assets/providers/ollama.svg",
  },
  // The C5 agents endpoint, mirroring routers/providers.py: this key EXISTING is what
  // mounts the builder nav and arms the agent queries — without it the whole surface is
  // invisible, and the builder specs would pass vacuously against nothing.
  agents: {
    order: 2,
    type: null,
    userProvide: false,
    userProvideURL: false,
    modelDisplayLabel: "Agents",
    capabilities: ["tools"],
    disableBuilder: false,
  },
};
const CATALOG_MODELS = { anthropic: [], "Ollama (local)": ["test-model"], agents: [] };

function keysResponse(res, method) {
  switch (method) {
    case "GET":
      // Upstream's exact keyless shape (data/src/methods/key.ts): an OBJECT with a null
      // expiresAt — a bare null crashes the sidebar's destructuring default.
      respond(res, 200, "application/json", '{"expiresAt":null}');
      return;
    case "PUT":
    case "POST":
      respond(res, 201, "application/json", ""); // upstream answers a bare 201 on save
      return;
    case "DELETE":
      respond(res, 204, "application/json", ""); // …and a bare 204 on revoke
      return;
    default:
      respond(res, 405, "application/json", JSON.stringify({ error: `method ${method}` }));
  }
}

function respond(res, status, contentType, body) {
  res.writeHead(status, {
    "content-type": contentType,
    // platform_web.rs sets CORS on every response for WKWebView's crossorigin module loads;
    // harmless here and keeps the mirror faithful.
    "access-control-allow-origin": "*",
  });
  res.end(body);
}

const BRIDGE = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;

async function chatOp(operation, params) {
  const reply = await fetch(`${BRIDGE}/chat-op`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ operation, params }),
  });
  if (!reply.ok) {
    throw new Error(`chat-op ${operation}: ${reply.status} ${await reply.text()}`);
  }
  return reply.json();
}

/** READS out-wait a supervised engine restart (mirroring the host's patient window):
 * routine recovery must not paint the console red or blank the rail. Past the bound the
 * failure surfaces honestly. */
async function chatOpPatient(operation, params) {
  const deadline = Date.now() + 8000;
  for (;;) {
    try {
      return await chatOp(operation, params);
    } catch (err) {
      if (Date.now() >= deadline) throw err;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  });
}

/// The C5 agent seam, mirroring agent_chat.rs route for route — with the ONE deliberate
/// difference ADR-0078 names: node can stream, so GET stream/:id is REAL SSE (the sse.js
/// transport path), while the app rides boundary-B events for the same frames.
async function handleChatSeam(req, res, method, route) {
  if (route.startsWith("/api/convos/gen_title/")) {
    const conversationId = decodeURIComponent(route.slice("/api/convos/gen_title/".length));
    const listing = await chatOpPatient("listConversations", {});
    const row = (listing.conversations ?? []).find((c) => c.conversationId === conversationId);
    if (row && typeof row.title === "string") {
      respond(res, 200, "application/json", JSON.stringify({ title: row.title }));
    } else {
      respond(res, 404, "application/json", JSON.stringify({ error: "no title yet" }));
    }
    return true;
  }
  if (route === "/api/convos" && method === "GET") {
    respond(res, 200, "application/json", JSON.stringify(await chatOpPatient("listConversations", {})));
    return true;
  }
  if (route.startsWith("/api/convos/") && method === "GET" && !route.includes("/gen_title/")) {
    const conversationId = decodeURIComponent(route.slice("/api/convos/".length));
    if (conversationId && !conversationId.includes("/")) {
      try {
        respond(
          res,
          200,
          "application/json",
          JSON.stringify(await chatOpPatient("getConversation", { conversation_id: conversationId })),
        );
      } catch {
        respond(res, 404, "application/json", JSON.stringify({ error: "no such conversation" }));
      }
      return true;
    }
  }
  if (route.startsWith("/api/messages/") && method === "GET") {
    const conversationId = decodeURIComponent(route.slice("/api/messages/".length));
    respond(
      res,
      200,
      "application/json",
      JSON.stringify(await chatOpPatient("getConversationMessages", { conversation_id: conversationId })),
    );
    return true;
  }
  if (!(route === "/api/agents/chat" || route.startsWith("/api/agents/chat/"))) {
    return handleAgentCrud(req, res, method, route);
  }
  const sub = route.replace(/^\/api\/agents\/chat\/?/, "");
  if (method === "POST" && sub === "steer/arm") {
    // Mirrors the host: preempt is honestly unsupported at this surface's granularity.
    respond(res, 200, "application/json", JSON.stringify({ armed: false, code: "PREEMPT_UNSUPPORTED" }));
    return true;
  }
  if (method === "POST" && (sub === "steer" || sub === "steer/deliver" || sub === "steer/cancel")) {
    // C5 steering, mirroring the host: engine statuses and top-level codes pass through.
    const parsed = JSON.parse((await readBody(req)) || "{}");
    const streamId = parsed.conversationId ?? parsed.streamId ?? "";
    if (!streamId) {
      respond(res, 400, "application/json", JSON.stringify({ error: "no conversation to steer" }));
      return true;
    }
    const operation = sub === "steer/cancel" ? "cancelChatSteer" : "steerChatTurn";
    await agentOp(res, operation, { stream_id: streamId, body: parsed });
    return true;
  }
  if (method === "POST" && sub === "resume") {
    // C5 HITL, mirroring the host: the stream id IS the conversation id; the engine's own
    // statuses pass through (409 stale locks the client's submit).
    const parsed = JSON.parse((await readBody(req)) || "{}");
    const streamId = parsed.streamId ?? parsed.conversationId ?? "";
    if (!streamId) {
      respond(res, 400, "application/json", JSON.stringify({ error: "no stream to resume" }));
      return true;
    }
    await agentOp(res, "resolveChatApproval", { stream_id: streamId, body: parsed });
    return true;
  }
  if (method === "GET" && sub === "active") {
    // Quiet through an engine restart, mirroring the host: a dead engine runs nothing.
    let jobs = { activeJobIds: [] };
    try {
      jobs = await chatOp("listActiveChatTurns", {});
    } catch {
      /* the empty answer above is the truth while the engine is down */
    }
    respond(res, 200, "application/json", JSON.stringify(jobs));
    return true;
  }
  if (method === "GET" && sub.startsWith("status/")) {
    const id = decodeURIComponent(sub.slice("status/".length));
    respond(
      res,
      200,
      "application/json",
      JSON.stringify(await chatOpPatient("getChatTurnStatus", { stream_id: id })),
    );
    return true;
  }
  if (method === "GET" && sub.startsWith("stream/")) {
    const id = decodeURIComponent(sub.slice("stream/".length).split("?")[0] ?? "");
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    });
    let after = 0;
    for (;;) {
      let page;
      try {
        page = await chatOp("listChatTurnEvents", { stream_id: id, after });
      } catch (err) {
        res.write(`event: error\ndata: ${JSON.stringify({ error: String(err) })}\n\n`);
        break;
      }
      for (const event of page.events) {
        after = event.seq;
        res.write(`event: message\ndata: ${JSON.stringify(event.frame)}\n\n`);
      }
      if (page.status !== "active" && page.events.length === 0) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 40));
      if (res.writableEnded || res.destroyed) {
        return true;
      }
    }
    res.end();
    return true;
  }
  if (method === "POST" && sub === "abort") {
    const parsed = JSON.parse((await readBody(req)) || "{}");
    const streamId = parsed.streamId ?? parsed.conversationId ?? parsed.abortKey ?? "";
    const params = { stream_id: streamId };
    if (typeof parsed.generationCreatedAt === "number") {
      params.generation_created_at = parsed.generationCreatedAt;
    }
    respond(res, 200, "application/json", JSON.stringify(await chatOp("cancelChatTurn", params)));
    return true;
  }
  if (method === "POST" && !sub.includes("/")) {
    const payload = JSON.parse((await readBody(req)) || "{}");
    if (!payload.endpoint && sub) {
      payload.endpoint = decodeURIComponent(sub);
    }
    respond(
      res,
      200,
      "application/json",
      JSON.stringify(await chatOp("startChatTurn", { body: payload })),
    );
    return true;
  }
  respond(res, 404, "application/json", JSON.stringify({ error: "not part of the chat seam" }));
  return true;
}

/** One engine op with the engine's own status and body passed through — the mirror of the
 * host's `engine_reply_passthrough` (a missing agent must 404, never flatten to 502). */
async function agentOp(res, operation, params) {
  const reply = await fetch(`${BRIDGE}/chat-op`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ operation, params }),
  });
  const text = await reply.text();
  respond(res, reply.status, "application/json", text);
}

/// The C5 agent CRUD seam, mirroring agent_chat.rs route for route. Node-owned stubs
/// (tool calls, per-tool auth, actions, the dormant v1 sub-routers) fall through to
/// handleLocalApi exactly as the host forwards them to the node seam.
async function handleAgentCrud(req, res, method, route) {
  if (!(route === "/api/agents" || route.startsWith("/api/agents/"))) {
    return false;
  }
  if (
    route.startsWith("/api/agents/tools/") ||
    route === "/api/agents/actions" ||
    route.startsWith("/api/agents/actions/") ||
    route.startsWith("/api/agents/v1/")
  ) {
    return false;
  }
  if (method === "GET" && route === "/api/agents/tools") {
    respond(res, 200, "application/json", JSON.stringify(await chatOpPatient("listAgentTools", {})));
    return true;
  }
  if (method === "GET" && route === "/api/agents/categories") {
    respond(res, 200, "application/json", JSON.stringify(await chatOpPatient("listAgentCategories", {})));
    return true;
  }
  if (route === "/api/agents") {
    if (method === "GET") {
      const query = new URL(req.url ?? "/", "http://x").searchParams;
      const params = {};
      for (const key of ["limit", "cursor", "search", "category"]) {
        const value = query.get(key);
        if (value) params[key] = value;
      }
      respond(res, 200, "application/json", JSON.stringify(await chatOpPatient("listAgents", params)));
      return true;
    }
    if (method === "POST") {
      const payload = JSON.parse((await readBody(req)) || "{}");
      await agentOp(res, "createAgent", { body: payload });
      return true;
    }
    respond(res, 405, "application/json", JSON.stringify({ error: "method not allowed" }));
    return true;
  }
  const rest = route.slice("/api/agents/".length);
  const slash = rest.indexOf("/");
  const agentId = decodeURIComponent(slash === -1 ? rest : rest.slice(0, slash));
  const tail = slash === -1 ? null : rest.slice(slash + 1);
  const id = { agent_id: agentId };
  if (method === "GET" && tail === null) {
    await agentOp(res, "getAgent", id);
    return true;
  }
  if (method === "PATCH" && tail === null) {
    const payload = JSON.parse((await readBody(req)) || "{}");
    await agentOp(res, "updateAgent", { agent_id: agentId, body: payload });
    return true;
  }
  if (method === "DELETE" && tail === null) {
    await agentOp(res, "deleteAgent", id);
    return true;
  }
  if (method === "GET" && tail === "expanded") {
    await agentOp(res, "getExpandedAgent", id);
    return true;
  }
  if (method === "GET" && tail === "versions") {
    await agentOp(res, "listAgentVersions", id);
    return true;
  }
  if (method === "POST" && tail === "duplicate") {
    await agentOp(res, "duplicateAgent", id);
    return true;
  }
  if (method === "POST" && tail === "revert") {
    const payload = JSON.parse((await readBody(req)) || "{}");
    await agentOp(res, "revertAgentVersion", { agent_id: agentId, body: payload });
    return true;
  }
  respond(res, 404, "application/json", JSON.stringify({ error: "not part of the agent seam", route, method }));
  return true;
}

const server = http.createServer((req, res) => {
  const url = req.url ?? "/";
  const [route] = url.split("?");
  const method = (req.method ?? "GET").toUpperCase();

  // The C5 seam consumes ITS OWN bodies; everything else drains below. The whole
  // /api/agents family routes through it (chat + CRUD, mirroring agent_chat.rs); a FALSE
  // answer means the seam forwards this sub-family to the node stubs, exactly as the host
  // returns None and platform_web falls through to boundary E.
  const seamFamily =
    route === "/api/agents" ||
    route.startsWith("/api/agents/") ||
    route === "/api/convos" ||
    route.startsWith("/api/convos/") ||
    route.startsWith("/api/messages/");
  if (seamFamily) {
    handleChatSeam(req, res, method, route)
      .then((handled) => {
        if (!handled) {
          req.resume();
          const answer = handleLocalApi(method, url);
          respond(res, answer.status, answer.content_type, answer.body);
        }
      })
      .catch((err) => {
        respond(res, 502, "application/json", JSON.stringify({ error: String(err) }));
      });
    return;
  }

  // Bodies are never consumed by any route below (local-api routes on method+path alone;
  // the key bridge stand-in answers by protocol) — drain so the socket never stalls.
  req.resume();

  // The C4 provider bridge families, before anything reaches the local seam.
  if (route === "/api/endpoints" || route === "/api/models") {
    respond(
      res,
      200,
      "application/json",
      JSON.stringify(route === "/api/endpoints" ? CATALOG_ENDPOINTS : CATALOG_MODELS),
    );
    return;
  }
  if (route === "/api/keys" || route.startsWith("/api/keys/")) {
    keysResponse(res, method);
    return;
  }
  if (route === "/api/__console") {
    // The host's console tap sink. This harness injects no tap (fixtures.ts listens on the
    // page instead), so nothing should arrive here — answered anyway, mirroring the host.
    respond(res, 204, "text/plain", "");
    return;
  }
  if (route.startsWith("/api")) {
    const answer = handleLocalApi(method, url);
    respond(res, answer.status, answer.content_type, answer.body);
    return;
  }

  if (route === "/tempest-theme.css") {
    try {
      respond(res, 200, "text/css", readFileSync(THEME_CSS));
    } catch {
      respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
    }
    return;
  }
  if (route.startsWith("/tempest-assets/")) {
    const relative = route.slice("/tempest-assets/".length);
    if (relative.split("/").some((part) => part === "..")) {
      respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
      return;
    }
    const file = path.join(TEMPEST_ASSETS, relative);
    try {
      respond(res, 200, mimeFor(file), readFileSync(file));
    } catch {
      respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
    }
    return;
  }
  if (route === "/registerSW.js") {
    respond(
      res,
      200,
      "text/javascript",
      "// service worker disabled: a native shell has no browser-update layer",
    );
    return;
  }
  if (route === "/sw.js" || route.startsWith("/workbox-")) {
    respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
    return;
  }
  if (route === "/" || route === "/index.html") {
    serveIndex(res);
    return;
  }

  // Static asset — refuse traversal, serve by extension, SPA-fallback extensionless paths.
  const relative = route.replace(/^\/+/, "");
  if (relative.split("/").some((part) => part === "..")) {
    respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
    return;
  }
  const file = path.join(DIST, relative);
  if (existsSync(file) && statSync(file).isFile()) {
    try {
      respond(res, 200, mimeFor(file), readFileSync(file));
    } catch {
      respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
    }
    return;
  }
  if (!relative.includes(".")) {
    serveIndex(res); // client-side route: /tempest/runs/3, /c/new, …
    return;
  }
  respond(res, 404, "text/plain; charset=utf-8", `not found: ${url}`);
});

server.listen(PORT, () => {
  console.log(`platform-server: ready on :${PORT} (dist ${DIST})`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1000).unref();
  });
}
