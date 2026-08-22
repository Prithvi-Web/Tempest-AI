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
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use serde_json::json;

use crate::supervisor::Supervisor;

/// Set once by the host at startup; the first `/api/config` serve prints the elapsed time
/// as the merged-app cold-launch number (§10). A `OnceLock` rather than a constructor
/// argument because `handle` is called from a protocol closure that owns nothing.
static PROCESS_START: OnceLock<Instant> = OnceLock::new();
static COLD_LAUNCH_PRINTED: AtomicBool = AtomicBool::new(false);

/// Record the host's start instant for the cold-launch instrument. Idempotent.
pub fn mark_process_start(start: Instant) {
    let _ = PROCESS_START.set(start);
}

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
            // First paint in the right mode: the vendored client only sets html.dark from a
            // React effect, so a dark-mode launch flashed light-token UI. Mirrors the
            // ThemeProvider's storage contract exactly (raw 'dark'|'light'|'system' under
            // 'color-theme'; anything else = system).
            let mode = "<script>(function(){try{var t=localStorage.getItem('color-theme');var d=t==='dark'||((t==null||t==='system')&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d)}catch(e){}})();</script>";
            let tap = "<script>(function(){var post=function(kind,text){try{fetch('/api/__console',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({kind:kind,text:String(text).slice(0,4000)})})}catch(e){}};window.addEventListener('error',function(e){post('error',(e.message||'')+' @ '+(e.filename||'')+':'+(e.lineno||'')+(e.error&&e.error.stack?'\\n'+e.error.stack:''))});window.addEventListener('unhandledrejection',function(e){var r=e.reason;post('unhandledrejection',r&&r.stack?(r.message?r.message+'\\n':'')+r.stack:String(r))});var orig=console.error;console.error=function(){post('console.error',Array.prototype.map.call(arguments,function(a){return a&&a.stack?(a.message?a.message+'\\n':'')+a.stack:String(a)}).join(' | '));return orig.apply(console,arguments)}})();</script>";
            let body = body
                .replace("<title>LibreChat</title>", "<title>Tempest AI</title>")
                .replacen("<head>", &format!("<head>{mode}{tap}"), 1)
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

/// Fetch the provider catalog from the engine (Boundary A). One registry answers the chat
/// surface's whole model world; the failure arm is a diagnosable 503, never a hang.
fn fetch_catalog(
    engine: Option<&Arc<Supervisor>>,
) -> Result<crate::generated::domain::PlatformCatalog, Box<tauri::http::Response<Vec<u8>>>> {
    let Some(engine) = engine else {
        return Err(Box::new(response(
            503,
            "application/json",
            serde_json::to_vec(&json!({"error": "the engine sidecar is not running"}))
                .unwrap_or_default(),
        )));
    };
    let value = engine
        .call("getPlatformCatalog", json!({}), Duration::from_secs(20))
        .map_err(|err| {
            Box::new(response(
                503,
                "application/json",
                serde_json::to_vec(&json!({
                    "error": format!("provider catalog unavailable: {err}"),
                }))
                .unwrap_or_default(),
            ))
        })?;
    serde_json::from_value(value).map_err(|err| {
        Box::new(response(
            502,
            "application/json",
            serde_json::to_vec(&json!({
                "error": format!("contract violation decoding getPlatformCatalog: {err}"),
            }))
            .unwrap_or_default(),
        ))
    })
}

fn catalog_response(
    engine: Option<&Arc<Supervisor>>,
    route: &str,
) -> tauri::http::Response<Vec<u8>> {
    let catalog = match fetch_catalog(engine) {
        Ok(catalog) => catalog,
        Err(refusal) => return *refusal,
    };
    let payload = if route == "/api/endpoints" {
        serde_json::to_vec(&catalog.endpoints)
    } else {
        serde_json::to_vec(&catalog.models)
    };
    response(200, "application/json", payload.unwrap_or_default())
}

/// The `value` a key save carries: the built-in anthropic dialog sends the raw key, the
/// custom-endpoint form sends `JSON.stringify({apiKey, baseURL})`. Pure, and pinned.
fn key_from_dialog_value(value: &str) -> String {
    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(value) {
        if let Some(api_key) = parsed.get("apiKey").and_then(|v| v.as_str()) {
            return api_key.trim().to_string();
        }
    }
    value.trim().to_string()
}

/// One percent-decoding, exactly what `?name=` needs (space and %XX); anything undecodable
/// stays as-is rather than guessing.
fn query_param(query: &str, name: &str) -> Option<String> {
    for pair in query.split('&') {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        if key == name {
            let mut out = Vec::with_capacity(value.len());
            let bytes = value.as_bytes();
            let mut i = 0;
            while i < bytes.len() {
                match bytes[i] {
                    b'%' if i + 3 <= bytes.len() => {
                        let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
                        match hex.and_then(|h| u8::from_str_radix(h, 16).ok()) {
                            Some(byte) => {
                                out.push(byte);
                                i += 3;
                            }
                            None => {
                                out.push(b'%');
                                i += 1;
                            }
                        }
                    }
                    b'+' => {
                        out.push(b' ');
                        i += 1;
                    }
                    other => {
                        out.push(other);
                        i += 1;
                    }
                }
            }
            return Some(String::from_utf8_lossy(&out).into_owned());
        }
    }
    None
}

/// The key bridge (C4, L18): presence, storage, and revocation of provider keys, answered
/// from the OS keychain under the account named by the provider's environment variable —
/// `credentials.ts` replaced, not bridged (MERGE-CONTRACT). Key VALUES never appear in a
/// response, an error, or a log line.
fn keys_response(
    engine: Option<&Arc<Supervisor>>,
    method: &str,
    route: &str,
    query: &str,
    body: &[u8],
) -> tauri::http::Response<Vec<u8>> {
    let catalog = match fetch_catalog(engine) {
        Ok(catalog) => catalog,
        Err(refusal) => return *refusal,
    };
    let env_for = |endpoint_key: &str| -> Option<String> {
        catalog
            .providers
            .iter()
            .find(|p| p.endpoint_key == endpoint_key && !p.key_env.is_empty())
            .map(|p| p.key_env.clone())
    };
    let honest_404 = |endpoint_key: &str| {
        response(
            404,
            "application/json",
            serde_json::to_vec(&json!({
                "error": format!("no keyed provider named {endpoint_key:?}"),
            }))
            .unwrap_or_default(),
        )
    };
    match method {
        "GET" => {
            let Some(name) = query_param(query, "name") else {
                return response(
                    422,
                    "application/json",
                    serde_json::to_vec(&json!({"error": "the name parameter is required"}))
                        .unwrap_or_default(),
                );
            };
            let Some(env_var) = env_for(&name) else { return honest_404(&name) };
            match crate::keychain::read(crate::keychain::SERVICE, &env_var) {
                // Upstream's exact shapes (data/src/methods/key.ts): a stored key with no
                // expiry answers the literal "never"; no key answers expiresAt null. Both
                // are OBJECTS — a bare null here crashed the sidebar's destructuring
                // default, which only covers undefined.
                Ok(Some(_)) => {
                    response(200, "application/json", b"{\"expiresAt\":\"never\"}".to_vec())
                }
                Ok(None) => {
                    // The legacy single-item install still answers for anthropic until a
                    // write migrates it.
                    if env_var == crate::keychain::ANTHROPIC_ACCOUNT
                        && matches!(
                            crate::keychain::read(
                                crate::keychain::SERVICE,
                                crate::keychain::LEGACY_ACCOUNT
                            ),
                            Ok(Some(_))
                        )
                    {
                        return response(
                            200,
                            "application/json",
                            b"{\"expiresAt\":\"never\"}".to_vec(),
                        );
                    }
                    response(200, "application/json", b"{\"expiresAt\":null}".to_vec())
                }
                Err(err) => response(
                    500,
                    "application/json",
                    serde_json::to_vec(&json!({"error": err})).unwrap_or_default(),
                ),
            }
        }
        "PUT" | "POST" => {
            let Ok(parsed) = serde_json::from_slice::<serde_json::Value>(body) else {
                return response(
                    422,
                    "application/json",
                    serde_json::to_vec(&json!({"error": "the key payload is not JSON"}))
                        .unwrap_or_default(),
                );
            };
            let name = parsed.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let value = parsed.get("value").and_then(|v| v.as_str()).unwrap_or("");
            let Some(env_var) = env_for(name) else { return honest_404(name) };
            let key = key_from_dialog_value(value);
            if key.is_empty() {
                return response(
                    422,
                    "application/json",
                    serde_json::to_vec(&json!({"error": "an empty key was refused"}))
                        .unwrap_or_default(),
                );
            }
            let stored = crate::keychain::store(crate::keychain::SERVICE, &env_var, &key)
                .and_then(|()| {
                    if env_var == crate::keychain::ANTHROPIC_ACCOUNT {
                        // Writing migrates the pre-C4 item so enumeration cannot inject
                        // the same variable twice.
                        crate::keychain::clear(
                            crate::keychain::SERVICE,
                            crate::keychain::LEGACY_ACCOUNT,
                        )
                    } else {
                        Ok(())
                    }
                });
            match stored {
                // Upstream answers a bare 201 on save.
                Ok(()) => response(201, "application/json", Vec::new()),
                Err(err) => response(
                    500,
                    "application/json",
                    serde_json::to_vec(&json!({"error": err})).unwrap_or_default(),
                ),
            }
        }
        "DELETE" => {
            if query_param(query, "all").as_deref() == Some("true") {
                for provider in &catalog.providers {
                    if !provider.key_env.is_empty() {
                        let _ = crate::keychain::clear(crate::keychain::SERVICE, &provider.key_env);
                    }
                }
                let _ =
                    crate::keychain::clear(crate::keychain::SERVICE, crate::keychain::LEGACY_ACCOUNT);
                return response(204, "application/json", Vec::new());
            }
            let endpoint_key = route.trim_start_matches("/api/keys/").to_string();
            let Some(env_var) = env_for(&endpoint_key) else { return honest_404(&endpoint_key) };
            let cleared = crate::keychain::clear(crate::keychain::SERVICE, &env_var).and_then(
                |()| {
                    if env_var == crate::keychain::ANTHROPIC_ACCOUNT {
                        crate::keychain::clear(
                            crate::keychain::SERVICE,
                            crate::keychain::LEGACY_ACCOUNT,
                        )
                    } else {
                        Ok(())
                    }
                },
            );
            match cleared {
                // Upstream answers a bare 204 on revoke.
                Ok(()) => response(204, "application/json", Vec::new()),
                Err(err) => response(
                    500,
                    "application/json",
                    serde_json::to_vec(&json!({"error": err})).unwrap_or_default(),
                ),
            }
        }
        other => response(
            405,
            "application/json",
            serde_json::to_vec(&json!({"error": format!("method {other} is not part of the key bridge")}))
                .unwrap_or_default(),
        ),
    }
}

/// The complete request → response mapping, synchronous; the caller runs it off the main
/// thread and hands the result to the protocol responder. `path` may carry a query string;
/// `route` below is the query-less form every exact match uses.
pub fn handle(
    supervisor: Option<&Arc<Supervisor>>,
    engine: Option<&Arc<Supervisor>>,
    dist: &Path,
    method: &str,
    path: &str,
    body: &[u8],
) -> tauri::http::Response<Vec<u8>> {
    let (route, query) = match path.split_once('?') {
        Some((route, query)) => (route, query),
        None => (path, ""),
    };
    // The C4 provider bridge: the chat surface's model world and its keys are answered by
    // the HOST — the catalog from the engine's one registry, key presence and storage from
    // the OS keychain (L18) — before anything is forwarded to the Node sidecar.
    if route == "/api/endpoints" || route == "/api/models" {
        return catalog_response(engine, route);
    }
    if route == "/api/keys" || route.starts_with("/api/keys/") {
        return keys_response(engine, method, route, query, body);
    }
    if route == "/api/config" && !COLD_LAUNCH_PRINTED.swap(true, Ordering::Relaxed) {
        // The §10 merged-app cold-launch instrument: process start → the authed shell
        // fetching its world. One line, once, on stderr — bench_merged reads it.
        if let Some(started) = PROCESS_START.get() {
            eprintln!(
                "[tempest-perf] merged_cold_launch_ms={}",
                started.elapsed().as_millis()
            );
        }
    }
    if route == "/api/__console" {
        // The webview's console tap — host-side visibility, never forwarded to the sidecar.
        let line = String::from_utf8_lossy(body);
        eprintln!("[platform-webview] {line}");
        return response(204, "text/plain", Vec::new());
    }
    if route.starts_with("/api") {
        // The node sidecar receives path+query verbatim; its own router splits the query.
        return match supervisor {
            Some(supervisor) => forward_api(supervisor, method, path, body),
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
    if route == "/tempest-theme.css" {
        // The seam stylesheet lives beside dist/ in the seam directory.
        let theme = dist.parent().map(|p| p.join("tempest/theme.css"));
        return match theme.and_then(|p| std::fs::read(p).ok()) {
            Some(body) => response(200, "text/css", body),
            None => not_found(path),
        };
    }
    if route == "/registerSW.js" {
        return response(
            200,
            "text/javascript",
            b"// service worker disabled: a native shell has no browser-update layer".to_vec(),
        );
    }
    if route == "/sw.js" || route.starts_with("/workbox-") {
        return not_found(path);
    }
    if route == "/" || route == "/index.html" {
        return serve_index(dist);
    }
    // Static asset — refuse traversal, serve by extension, SPA-fallback extensionless paths.
    let relative = route.trim_start_matches('/');
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_anthropic_dialog_sends_a_raw_key_and_the_custom_form_sends_json() {
        assert_eq!(key_from_dialog_value("sk-ant-api03-RAWKEY"), "sk-ant-api03-RAWKEY");
        assert_eq!(
            key_from_dialog_value(r#"{"apiKey":"gsk-live-key","baseURL":""}"#),
            "gsk-live-key"
        );
        assert_eq!(key_from_dialog_value("  padded  "), "padded");
        // JSON without an apiKey field is treated as a raw (odd) key, not a crash.
        assert_eq!(key_from_dialog_value(r#"{"other":1}"#), r#"{"other":1}"#);
    }

    #[test]
    fn query_params_decode_the_two_encodings_the_client_uses() {
        assert_eq!(query_param("name=OpenAI", "name").as_deref(), Some("OpenAI"));
        assert_eq!(
            query_param("name=Ollama%20(local)&x=1", "name").as_deref(),
            Some("Ollama (local)")
        );
        assert_eq!(query_param("name=Together+AI", "name").as_deref(), Some("Together AI"));
        assert_eq!(query_param("all=true", "all").as_deref(), Some("true"));
        assert_eq!(query_param("all=true", "name"), None);
        assert_eq!(query_param("", "name"), None);
        // A truncated escape stays literal rather than panicking or guessing.
        assert_eq!(query_param("name=x%2", "name").as_deref(), Some("x%2"));
    }

    #[test]
    fn the_key_bridge_refuses_without_an_engine_rather_than_hanging() {
        let reply = keys_response(None, "GET", "/api/keys", "name=OpenAI", b"");
        assert_eq!(reply.status(), 503);
        let reply = catalog_response(None, "/api/endpoints");
        assert_eq!(reply.status(), 503);
    }
}
