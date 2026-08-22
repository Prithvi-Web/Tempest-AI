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

/// False when `apply_vibrancy` failed on this launch: serve_index then withholds the
/// `tempest-vibrancy` class so the CSS keeps its OPAQUE grounds — a transparent window with
/// thinned grounds and no material behind it is a window onto the raw desktop. The host sets
/// this before the first page load (setup runs to completion before the webview navigates),
/// so the class and the material can never disagree.
static VIBRANCY_ATTACHED: AtomicBool = AtomicBool::new(true);

/// Record that the window material failed to attach; the page then keeps solid grounds.
pub fn mark_vibrancy_failed() {
    VIBRANCY_ATTACHED.store(false, Ordering::Relaxed);
}

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
        // Never cached: WKWebView otherwise keeps serving a PREVIOUS install's theme,
        // badges, or chunks after the bundle updates (observed live with theme.css). Every
        // response here is a local disk read — caching buys nothing and costs staleness.
        .header("cache-control", "no-store")
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
            // 'color-theme'). First run seeds 'dark': the storm-navy identity ships dark
            // (owner mandate); the user's own later choice persists over it.
            let mode = "<script>(function(){try{var t=localStorage.getItem('color-theme');if(t==null){t='dark';localStorage.setItem('color-theme','dark')}var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d)}catch(e){}})();</script>";
            // Liquid glass, macOS only. Two independent pieces:
            // — the drag surfaces exist whenever the overlay-titlebar window does (without
            //   them the full-bleed window cannot be moved): a 10px strip along the top edge
            //   and a 52×38 zone under the traffic lights — 52 matches the sidebar rail's
            //   width, and the whole sidebar pads itself 38px down (theme.css §7), so both
            //   zones cover only empty glass;
            // — the `tempest-vibrancy` class keys the translucent grounds, and is withheld
            //   when the material failed to attach: transparent CSS over a windowless
            //   desktop is a hole, not a theme.
            let drag = if cfg!(target_os = "macos") {
                "<script>(function(){var mk=function(css){var d=document.createElement('div');d.setAttribute('data-tauri-drag-region','');d.style.cssText=css;return d};var add=function(){document.body.appendChild(mk('position:fixed;top:0;left:0;right:0;height:10px;z-index:2147482000'));document.body.appendChild(mk('position:fixed;top:0;left:0;width:52px;height:38px;z-index:2147482000'))};if(document.body){add()}else{document.addEventListener('DOMContentLoaded',add)}})();</script>"
            } else {
                ""
            };
            let glass = if cfg!(target_os = "macos") && VIBRANCY_ATTACHED.load(Ordering::Relaxed)
            {
                "<script>document.documentElement.classList.add('tempest-vibrancy');</script>"
            } else {
                ""
            };
            let tap = "<script>(function(){var post=function(kind,text){try{fetch('/api/__console',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({kind:kind,text:String(text).slice(0,4000)})})}catch(e){}};window.addEventListener('error',function(e){post('error',(e.message||'')+' @ '+(e.filename||'')+':'+(e.lineno||'')+(e.error&&e.error.stack?'\\n'+e.error.stack:''))});window.addEventListener('unhandledrejection',function(e){var r=e.reason;post('unhandledrejection',r&&r.stack?(r.message?r.message+'\\n':'')+r.stack:String(r))});var orig=console.error;console.error=function(){post('console.error',Array.prototype.map.call(arguments,function(a){return a&&a.stack?(a.message?a.message+'\\n':'')+a.stack:String(a)}).join(' | '));return orig.apply(console,arguments)}})();</script>";
            // The identity rewrites are exact-string; an upstream merge that rewords either
            // pattern would otherwise ship LibreChat's text again SILENTLY. Absence is
            // stated on stderr the moment it happens, not discovered in a screenshot.
            for (pattern, name) in [
                ("<title>LibreChat</title>", "title"),
                ("content=\"LibreChat - An open source chat application", "description"),
            ] {
                if !body.contains(pattern) {
                    eprintln!(
                        "[tempest] serve_index: the {name} identity rewrite found no target — \
                         upstream index.html changed shape; re-pin the pattern"
                    );
                }
            }
            let body = body
                .replace("<title>LibreChat</title>", "<title>Tempest AI</title>")
                .replace(
                    "content=\"LibreChat - An open source chat application with support for multiple AI models\"",
                    "content=\"Tempest AI — the assistant that shows you the evidence\"",
                )
                .replacen("<head>", &format!("<head>{mode}{tap}{drag}{glass}"), 1)
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

/// Percent-encode a diagnostic detail for the `?detail=` query: unreserved bytes pass,
/// everything else becomes %XX, and the result is bounded — an error string is context,
/// not a payload.
pub fn encode_detail(detail: &str) -> String {
    let mut out = String::new();
    for byte in detail.bytes().take(500) {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                out.push(byte as char)
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// Minimal HTML escape for text interpolated into the diagnostic page. The inputs are our
/// own error strings, but an error string can quote arbitrary paths and env values — escaped
/// on principle, pinned by test.
fn html_escape(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// The full-screen diagnostic the fallback window shows when the platform surface cannot
/// start. Copy is curated per cause slug — the page explains what failed and what fixes it,
/// in the product's own voice and identity, with the raw detail quoted underneath.
fn diagnostic_page(cause: &str, detail: &str) -> String {
    let (title, remedy): (&str, &str) = match cause {
        "client-missing" => (
            "The chat surface isn\u{2019}t in this build",
            "The bundled client files are missing. Reinstall Tempest AI \u{2014} or, in a \
             development checkout, run `make platform-client-dist` (or point \
             TEMPEST_PLATFORM_WEB_DIST at a built client).",
        ),
        "node-missing" => (
            "Tempest AI needs Node.js for its chat surface",
            "No Node runtime was found on this machine. Install Node 22 or newer (e.g. from \
             nodejs.org), or set TEMPEST_PLATFORM_NODE to the full path of a node binary, \
             then reopen Tempest AI.",
        ),
        "boundary-missing" => (
            "This build is incomplete",
            "A bundled component (boundary.mjs) is missing, which usually means a broken \
             install. Reinstall Tempest AI.",
        ),
        "socket-failed" => (
            "Tempest AI couldn\u{2019}t prepare its private socket",
            "The per-user socket directory could not be created. Check the detail below \
             \u{2014} it names the exact path and error \u{2014} then reopen Tempest AI.",
        ),
        _ => (
            "Tempest AI couldn\u{2019}t open its chat surface",
            "Something outside the usual failure set went wrong. The detail below names it; \
             reopening the app is the first thing to try.",
        ),
    };
    let detail_block = if detail.is_empty() {
        String::new()
    } else {
        format!("<pre>{}</pre>", html_escape(detail))
    };
    format!(
        r##"<!doctype html><html><head><meta charset="utf-8"><title>Tempest AI</title><style>
:root {{ color-scheme: dark; }}
html, body {{ margin: 0; height: 100%; background: #090E1A; color: #EDF2FC;
  font: 400 13px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif; }}
main {{ min-height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 12px; padding: 48px; box-sizing: border-box; text-align: center; }}
svg {{ margin-bottom: 8px; }}
h1 {{ font-size: 20px; font-weight: 600; letter-spacing: -0.019em; margin: 0; }}
p {{ max-width: 52ch; margin: 0; color: #93A1BF; }}
code {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; color: #A9B6D2; }}
pre {{ max-width: 60ch; overflow-x: auto; text-align: left; background: #060A14;
  border: 1px solid rgba(143, 176, 255, 0.14); border-radius: 8px; padding: 10px 12px;
  color: #A9B6D2; font: 400 11px/1.5 ui-monospace, "SF Mono", Menlo, monospace; }}
footer {{ margin-top: 16px; color: #5A657E; font-size: 11px; }}
</style></head><body><main>
<svg width="56" height="56" viewBox="0 0 1024 1024" aria-hidden="true"><path d="M577 206 337 556h133l-63 262 280-378H545l90-234Z" fill="#4D94FF"/></svg>
<h1>{title}</h1>
<p>{remedy}</p>
{detail_block}
<footer>The proof engine is unaffected — <code>tempest prove</code> works from any terminal.</footer>
</main></body></html>"##
    )
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
    let mut catalog = match fetch_catalog(engine) {
        Ok(catalog) => catalog,
        Err(refusal) => return *refusal,
    };
    let payload = if route == "/api/endpoints" {
        decorate_endpoint_icons(&mut catalog);
        serde_json::to_vec(&catalog.endpoints)
    } else {
        serde_json::to_vec(&catalog.models)
    };
    response(200, "application/json", payload.unwrap_or_default())
}

/// The badge URLs are a HOST detail — only this protocol serves /tempest-assets/, so only
/// this bridge writes them. The engine's own catalog stays clean of desktop serving layout,
/// and any other consumer keeps the client's graceful no-iconURL fallback instead of a
/// broken `<img>`.
fn decorate_endpoint_icons(catalog: &mut crate::generated::domain::PlatformCatalog) {
    for row in &catalog.providers {
        if let Some(endpoint) = catalog.endpoints.get_mut(&row.endpoint_key) {
            endpoint.icon_url = Some(format!("/tempest-assets/providers/{}.svg", row.id));
        }
    }
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
    if route == "/__tempest-diagnostic" {
        // The fallback surface when the platform client cannot start (L15.3: a failure is
        // surfaced on SCREEN with its cause and remedy, never only a stderr line a
        // Finder-launched app swallows). Self-contained — no dist, no sidecar, no assets.
        let cause = query_param(query, "cause").unwrap_or_default();
        let detail = query_param(query, "detail").unwrap_or_default();
        return response(
            200,
            "text/html; charset=utf-8",
            diagnostic_page(&cause, &detail).into_bytes(),
        );
    }
    if route == "/tempest-theme.css" {
        // The seam stylesheet lives beside dist/ in the seam directory.
        let theme = dist.parent().map(|p| p.join("tempest/theme.css"));
        return match theme.and_then(|p| std::fs::read(p).ok()) {
            Some(body) => response(200, "text/css", body),
            None => not_found(path),
        };
    }
    if let Some(asset) = route.strip_prefix("/tempest-assets/") {
        // Seam-owned static assets (the provider badges the catalog's iconURL points at)
        // live beside dist/ exactly like the theme does. Same traversal refusal as the
        // dist branch, plus a leading-slash trim so a doubled slash cannot re-root the join.
        let relative = asset.trim_start_matches('/');
        if relative.is_empty() || relative.split('/').any(|part| part == "..") {
            return not_found(path);
        }
        let file = dist.parent().map(|p| p.join("tempest/assets").join(relative));
        return match file.filter(|p| p.is_file()) {
            Some(file) => match std::fs::read(&file) {
                Ok(body) => response(200, mime_for(&file), body),
                Err(_) => not_found(path),
            },
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

    #[test]
    fn serve_index_injects_identity_mode_tap_and_glass_in_order() {
        let base =
            std::env::temp_dir().join(format!("tempest-index-test-{}", std::process::id()));
        std::fs::create_dir_all(&base).unwrap();
        std::fs::write(
            base.join("index.html"),
            "<html><head><meta name=\"description\" content=\"LibreChat - An open source chat application with support for multiple AI models\" /><title>LibreChat</title></head><body></body></html>",
        )
        .unwrap();
        let reply = serve_index(&base);
        assert_eq!(reply.status(), 200);
        let html = String::from_utf8(reply.body().clone()).unwrap();

        // Identity rewrites: no LibreChat name survives in the served page's head text.
        assert!(html.contains("<title>Tempest AI</title>"));
        assert!(html.contains("the assistant that shows you the evidence"));
        assert!(!html.contains("LibreChat"));

        // The mode script seeds dark on first run and toggles the class before paint.
        assert!(html.contains("localStorage.setItem('color-theme','dark')"));
        // The console tap reaches the host.
        assert!(html.contains("/api/__console"));
        // The theme loads LAST in <head> so the seam wins every cascade tie.
        let theme_at = html.find("/tempest-theme.css").expect("theme link injected");
        let head_end = html.find("</head>").expect("head survives");
        assert!(theme_at < head_end);

        // macOS only: the vibrancy class and both drag surfaces (the overlay-titlebar
        // window is undraggable without them — a silent regression here ships a window
        // that cannot be moved).
        if cfg!(target_os = "macos") {
            assert!(html.contains("classList.add('tempest-vibrancy')"));
            assert_eq!(html.matches("data-tauri-drag-region").count(), 1); // the injector source
            assert!(html.contains("height:10px"));
            // 52 = the sidebar rail's width; wider overhangs the panel's first control row.
            assert!(html.contains("width:52px;height:38px"));
        } else {
            assert!(!html.contains("tempest-vibrancy"));
        }
        std::fs::remove_dir_all(&base).ok();
    }

    #[test]
    fn the_host_decorates_catalog_rows_with_badge_urls_by_provider_id() {
        use crate::generated::domain::{CatalogEndpoint, CatalogProvider, PlatformCatalog};
        let endpoint = |order: i32| CatalogEndpoint {
            icon_url: None,
            model_display_label: "X".into(),
            order,
            type_: Some("custom".into()),
            user_provide: true,
            user_provide_url: false,
        };
        let mut catalog = PlatformCatalog {
            endpoints: [("Groq".to_string(), endpoint(0)), ("Orphan".to_string(), endpoint(1))]
                .into_iter()
                .collect(),
            models: Default::default(),
            providers: vec![CatalogProvider {
                id: "groq".into(),
                endpoint_key: "Groq".into(),
                label: "Groq".into(),
                wire: "openai".into(),
                key_env: "GROQ_API_KEY".into(),
                local: false,
            }],
        };
        decorate_endpoint_icons(&mut catalog);
        // Keyed by the registry row's ID (the badge filename), looked up by endpoint key.
        assert_eq!(
            catalog.endpoints["Groq"].icon_url.as_deref(),
            Some("/tempest-assets/providers/groq.svg")
        );
        // A row with no registry entry stays undecorated — absent, not invented.
        assert_eq!(catalog.endpoints["Orphan"].icon_url, None);
    }

    #[test]
    fn the_diagnostic_page_names_the_cause_and_escapes_the_detail() {
        let reply = handle(
            None,
            None,
            Path::new("/nonexistent-dist"),
            "GET",
            "/__tempest-diagnostic?cause=node-missing&detail=%3Cscript%3Ealert(1)%3C%2Fscript%3E",
            b"",
        );
        assert_eq!(reply.status(), 200);
        let html = String::from_utf8(reply.body().clone()).unwrap();
        // Curated remedy for the known cause; raw detail escaped, never interpreted.
        assert!(html.contains("TEMPEST_PLATFORM_NODE"));
        assert!(html.contains("&lt;script&gt;alert(1)&lt;/script&gt;"));
        assert!(!html.contains("<script>alert(1)"));
        // The engine's independence is stated — the failure is scoped, not total.
        assert!(html.contains("tempest prove"));

        // An unknown cause still renders a complete page, never a blank window.
        let generic = handle(
            None,
            None,
            Path::new("/nonexistent-dist"),
            "GET",
            "/__tempest-diagnostic?cause=who-knows",
            b"",
        );
        let html = String::from_utf8(generic.body().clone()).unwrap();
        assert!(html.contains("couldn\u{2019}t open its chat surface"));
    }

    #[test]
    fn tempest_assets_serve_from_the_seam_and_refuse_traversal() {
        let base = std::env::temp_dir().join(format!("tempest-assets-test-{}", std::process::id()));
        let dist = base.join("dist");
        let providers = base.join("tempest/assets/providers");
        std::fs::create_dir_all(&dist).unwrap();
        std::fs::create_dir_all(&providers).unwrap();
        std::fs::write(providers.join("openai.svg"), b"<svg/>").unwrap();
        std::fs::write(base.join("secret.txt"), b"nope").unwrap();

        let ok = handle(None, None, &dist, "GET", "/tempest-assets/providers/openai.svg", b"");
        assert_eq!(ok.status(), 200);
        assert_eq!(ok.headers().get("content-type").unwrap(), "image/svg+xml");
        assert_eq!(ok.body().as_slice(), b"<svg/>");

        // `..` refused; a doubled slash cannot re-root the join; a missing badge is an
        // honest 404, and the empty path is not a directory listing.
        for path in [
            "/tempest-assets/../secret.txt",
            "/tempest-assets//etc/hosts",
            "/tempest-assets/providers/absent.svg",
            "/tempest-assets/",
        ] {
            assert_eq!(handle(None, None, &dist, "GET", path, b"").status(), 404, "{path}");
        }
        std::fs::remove_dir_all(&base).ok();
    }
}
