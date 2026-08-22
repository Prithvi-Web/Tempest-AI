//! The `tempest://` webview protocol (PLAN-V3 C3): the mounted platform client's entire
//! world. Every byte the webview loads or requests flows through this handler —
//!
//!   - static assets come from the built client `dist/`;
//!   - `index.html` is transformed at serve time: the Tempest theme stylesheet is injected
//!     LAST (the C3 design-token seam — zero edits to vendored files) and the tab title
//!     becomes Tempest's (trademarks are not licensed; C1's strip covered images, this
//!     covers the text surface the moment it can actually render);
//!   - the PWA service worker is neutralized (`registerSW.js` becomes a no-op): a native
//!     shell has no business installing a browser-update layer;
//!   - `/api/*` is forwarded over boundary E to the supervised Node sidecar — JSON-RPC over
//!     the Unix socket, never a TCP port. The webview cannot reach the network for its API
//!     even in principle: its origin is this protocol, and this protocol only speaks to the
//!     supervisor.
//!
//! SPA routes (no file extension) fall back to `index.html`, exactly as the client's own
//! router expects.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use serde_json::json;

use crate::supervisor::Supervisor;

/// Where the built client lives. The bundled resource (`platform/client-dist/`) is the
/// product path; `TEMPEST_PLATFORM_WEB_DIST` overrides it for development against a fresh
/// build without re-bundling. An explicit-but-broken override resolves to None rather than
/// silently falling back to the stale bundled copy — a misconfiguration must surface.
pub fn dist_dir<R: tauri::Runtime, M: tauri::Manager<R>>(app: &M) -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var("TEMPEST_PLATFORM_WEB_DIST") {
        if !explicit.is_empty() {
            let path = PathBuf::from(explicit);
            return path.is_dir().then_some(path);
        }
    }
    app.path()
        .resolve("platform/client-dist", tauri::path::BaseDirectory::Resource)
        .ok()
        .filter(|p| p.is_dir())
}

fn mime_for(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript",
        "css" => "text/css",
        "json" | "webmanifest" => "application/json",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "jpg" | "jpeg" => "image/jpeg",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "mp3" => "audio/mpeg",
        "txt" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

fn response(status: u16, mime: &str, body: Vec<u8>) -> tauri::http::Response<Vec<u8>> {
    tauri::http::Response::builder()
        .status(status)
        .header("content-type", mime)
        // WKWebView treats custom-scheme responses without CORS headers as OPAQUE to any
        // `crossorigin` request — and every module script/preload in the built client
        // carries `crossorigin`. Without this header the module graph half-loads and React
        // dies with null internals. The scheme is app-private; "*" exposes nothing.
        .header("access-control-allow-origin", "*")
        .body(body)
        .expect("static response construction cannot fail")
}

fn not_found(path: &str) -> tauri::http::Response<Vec<u8>> {
    response(404, "text/plain; charset=utf-8", format!("not found: {path}").into_bytes())
}

/// `index.html`, transformed at the seam: theme injected last, identity text ours.
fn serve_index(dist: &Path) -> tauri::http::Response<Vec<u8>> {
    match std::fs::read_to_string(dist.join("index.html")) {
        Ok(body) => {
            // The console tap loads FIRST: every uncaught error, rejection, and
            // console.error in the webview reaches the host's stderr via /api/__console —
            // the instrument behind the C3 "zero console errors" gate, and the difference
            // between diagnosing a webview crash and guessing at one.
            let tap = "<script>(function(){var post=function(kind,text){try{fetch('/api/__console',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({kind:kind,text:String(text).slice(0,4000)})})}catch(e){}};window.addEventListener('error',function(e){post('error',(e.message||'')+' @ '+(e.filename||'')+':'+(e.lineno||'')+(e.error&&e.error.stack?'\\n'+e.error.stack:''))});window.addEventListener('unhandledrejection',function(e){var r=e.reason;post('unhandledrejection',r&&r.stack?(r.message?r.message+'\\n':'')+r.stack:String(r))});var orig=console.error;console.error=function(){post('console.error',Array.prototype.map.call(arguments,function(a){return a&&a.stack?(a.message?a.message+'\\n':'')+a.stack:String(a)}).join(' | '));return orig.apply(console,arguments)}})();</script>";
            let body = body
                .replace("<title>LibreChat</title>", "<title>Tempest AI</title>")
                .replacen("<head>", &format!("<head>{tap}"), 1)
                .replace(
                    "</head>",
                    "<link rel=\"stylesheet\" href=\"/tempest-theme.css\" />\n</head>",
                );
            response(200, "text/html; charset=utf-8", body.into_bytes())
        }
        Err(err) => response(
            503,
            "text/plain; charset=utf-8",
            format!("platform client dist unreadable: {err}").into_bytes(),
        ),
    }
}

/// Forward one `/api/*` request over boundary E. The sidecar's local-mode seam answers the
/// local-principal surface; everything unwired yet returns a structured, honest error the
/// client can render — never a hang, never a swallowed failure (L15.3).
fn forward_api(
    supervisor: &Supervisor,
    method: &str,
    path: &str,
    body: &[u8],
) -> tauri::http::Response<Vec<u8>> {
    use base64::Engine as _;
    let params = json!({
        "request": {
            "method": method,
            "path": path,
            "body_base64": base64::engine::general_purpose::STANDARD.encode(body),
        }
    });
    match supervisor.call("platform.http", params, Duration::from_secs(30)) {
        Ok(reply) => {
            // Typed parse of the GENERATED result type — deny_unknown_fields from the
            // schema's additionalProperties: false. An off-contract reply becomes a
            // surfaced 502 with the parse reason, never a half-rendered guess.
            match serde_json::from_value::<crate::generated::platform::HttpResult>(reply) {
                Ok(result) => {
                    let body = base64::engine::general_purpose::STANDARD
                        .decode(result.body_base64.as_bytes())
                        .unwrap_or_default();
                    // The schema bounds status to [100, 599]; the conversion cannot fail on
                    // a validated reply, and an out-of-range one becomes an honest 502.
                    let status = u16::try_from(result.status).unwrap_or(502);
                    response(status, &result.content_type, body)
                }
                Err(err) => response(
                    502,
                    "application/json",
                    serde_json::to_vec(&json!({
                        "error": "platform.http reply violates the boundary contract",
                        "detail": err.to_string(),
                    }))
                    .unwrap_or_default(),
                ),
            }
        }
        Err(err) => response(
            502,
            "application/json",
            serde_json::to_vec(&json!({
                "error": "platform sidecar unavailable",
                "detail": err.to_string(),
            }))
            .unwrap_or_default(),
        ),
    }
}

/// The complete request → response mapping, synchronous; the caller runs it off the main
/// thread and hands the result to the protocol responder.
pub fn handle(
    supervisor: Option<&Arc<Supervisor>>,
    dist: &Path,
    method: &str,
    path: &str,
    body: &[u8],
) -> tauri::http::Response<Vec<u8>> {
    if path == "/api/__console" {
        // The webview's console tap — host-side visibility, never forwarded to the sidecar.
        let line = String::from_utf8_lossy(body);
        eprintln!("[platform-webview] {line}");
        return response(204, "text/plain", Vec::new());
    }
    if let Some(api_path) = path.strip_prefix("/api").map(|_| path) {
        return match supervisor {
            Some(supervisor) => forward_api(supervisor, method, api_path, body),
            None => response(
                503,
                "application/json",
                serde_json::to_vec(&json!({
                    "error": "the platform sidecar is not running",
                }))
                .unwrap_or_default(),
            ),
        };
    }
    if path == "/tempest-theme.css" {
        // The seam stylesheet lives beside dist/ in the seam directory.
        let theme = dist.parent().map(|p| p.join("tempest/theme.css"));
        return match theme.and_then(|p| std::fs::read(p).ok()) {
            Some(body) => response(200, "text/css", body),
            None => not_found(path),
        };
    }
    if path == "/registerSW.js" {
        return response(
            200,
            "text/javascript",
            b"// service worker disabled: a native shell has no browser-update layer".to_vec(),
        );
    }
    if path == "/sw.js" || path.starts_with("/workbox-") {
        return not_found(path);
    }
    if path == "/" || path == "/index.html" {
        return serve_index(dist);
    }
    // Static asset — refuse traversal, serve by extension, SPA-fallback extensionless paths.
    let relative = path.trim_start_matches('/');
    if relative.split('/').any(|part| part == "..") {
        return not_found(path);
    }
    let file = dist.join(relative);
    if file.is_file() {
        let mime = mime_for(&file);
        return match std::fs::read(&file) {
            Ok(body) => response(200, mime, body),
            Err(_) => not_found(path),
        };
    }
    if !relative.contains('.') {
        return serve_index(dist); // client-side route: /c/new, /login, …
    }
    not_found(path)
}
