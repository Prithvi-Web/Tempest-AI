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
};
const CATALOG_MODELS = { anthropic: [] };

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

const server = http.createServer((req, res) => {
  // Bodies are never consumed by any route below (local-api routes on method+path alone;
  // the key bridge stand-in answers by protocol) — drain so the socket never stalls.
  req.resume();

  const url = req.url ?? "/";
  const [route] = url.split("?");
  const method = (req.method ?? "GET").toUpperCase();

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
