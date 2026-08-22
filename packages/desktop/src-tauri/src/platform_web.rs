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

/// Where the built client lives. Env-provided while the platform surface is an opt-in
/// preview; when C3 completes and the client becomes the primary webview, this moves into
/// the app's bundled resources like the boundary seam did.
pub fn dist_dir() -> Option<PathBuf> {
    std::env::var("TEMPEST_PLATFORM_WEB_DIST").ok().map(PathBuf::from).filter(|p| p.is_dir())
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
            let body = body
                .replace("<title>LibreChat</title>", "<title>Tempest</title>")
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
