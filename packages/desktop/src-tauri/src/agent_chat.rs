//! The `/api/agents/chat*` host seam (PLAN-V3 C5, ADR-0078): the thin client over the
//! engine's chat-turn service, living beside the C4 catalog/keys intercepts.
//!
//! The vendored client's turn contract is POST-ack + a separate live stream. The POST, the
//! abort, the status family and the conversation reads are ordinary one-shot responses and
//! are answered here directly from boundary A. The STREAM cannot ride this protocol (the
//! responder is one-shot — wry's scheme handler takes the whole body at once), so delivery
//! is boundary B: a per-turn poller drains the engine's frame ledger at token cadence and
//! pushes batches as `AgentStreamEvent`; the seam's `TempestSSE` replays the ledger over
//! `replay_chat_turn` and follows the pushes, deduping by seq. The e2e harness serves the
//! same routes as REAL SSE (node can stream), so both pipes of the one frame vocabulary
//! stay tested.
//!
//! Nothing here interprets frames: the engine speaks the client's wire vocabulary and this
//! seam carries bytes. One protocol implementation, two thin transports (L29's spirit at
//! the transport layer).

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use serde_json::{Value, json};
use tauri_specta::Event;

use crate::generated::domain::TurnEventsOut;
use crate::supervisor::Supervisor;

/// One ledger frame at boundary B. The frame itself crosses as its JSON TEXT: SSE's
/// `e.data` is a string by definition, the seam SSE hands it to the vendored parser
/// verbatim, and specta cannot type arbitrary JSON anyway (BigInt-forbidden). Boundary A
/// still types the frames as objects; the e2e suite validates their content against the
/// real client.
#[derive(Debug, Clone, serde::Serialize, specta::Type)]
pub struct AgentStreamFrame {
    pub seq: i32,
    pub frame_json: String,
}

/// One frame batch pushed to the webview.
#[derive(Debug, Clone, serde::Serialize, specta::Type, tauri_specta::Event)]
pub struct AgentStreamEvent {
    pub stream_id: String,
    pub status: String,
    pub events: Vec<AgentStreamFrame>,
}

/// A full ledger replay for one stream — what `replay_chat_turn` answers.
#[derive(Debug, Clone, serde::Serialize, specta::Type)]
pub struct ChatTurnReplay {
    pub stream_id: String,
    pub status: String,
    pub events: Vec<AgentStreamFrame>,
}

pub fn frames_from(page: &TurnEventsOut) -> Vec<AgentStreamFrame> {
    page.events
        .iter()
        .map(|event| AgentStreamFrame {
            seq: event.seq,
            frame_json: serde_json::to_string(&event.frame).unwrap_or_else(|_| "{}".into()),
        })
        .collect()
}

/// Live pollers, stream id → the generation epoch they serve. A NEW turn on the same
/// conversation-scoped stream id SUPERSEDES the old poller (its generation vanishes from the
/// map and it exits at its next check) — without this, a poller still draining turn N would
/// block turn N+1 from ever getting a live feed, and a rapid follow-up send would stall.
static POLLERS: OnceLock<Mutex<HashMap<String, i64>>> = OnceLock::new();

fn pollers() -> &'static Mutex<HashMap<String, i64>> {
    POLLERS.get_or_init(|| Mutex::new(HashMap::new()))
}

const POLL_INTERVAL: Duration = Duration::from_millis(40);
const POLL_CALL_TIMEOUT: Duration = Duration::from_secs(10);
/// Consecutive failed polls tolerated while the supervisor restarts the engine underneath
/// us before the poller gives up and reports the stream broken.
const POLL_MAX_CONSECUTIVE_FAILURES: u32 = 50;

fn response(status: u16, content_type: &str, body: Vec<u8>) -> tauri::http::Response<Vec<u8>> {
    tauri::http::Response::builder()
        .status(status)
        .header("content-type", content_type)
        .header("cache-control", "no-store")
        .body(body)
        .expect("static response construction cannot fail")
}

fn json_response(status: u16, value: &Value) -> tauri::http::Response<Vec<u8>> {
    response(
        status,
        "application/json",
        serde_json::to_vec(value).unwrap_or_default(),
    )
}

fn no_engine() -> tauri::http::Response<Vec<u8>> {
    json_response(503, &json!({"error": "the engine sidecar is not running"}))
}

/// Engine-call helper: boundary-A errors become in-band JSON the client can render, never a
/// swallowed exception (L15.3). The 200 arm serializes the engine's answer verbatim.
fn engine_reply(
    engine: &Arc<Supervisor>,
    operation: &str,
    params: Value,
) -> tauri::http::Response<Vec<u8>> {
    match engine.call(operation, params, POLL_CALL_TIMEOUT) {
        Ok(value) => json_response(200, &value),
        Err(err) => json_response(502, &json!({"error": format!("{operation}: {err}")})),
    }
}

/// The family router. `Some(response)` when the route belongs to this seam; `None` lets the
/// caller fall through to the generic forward. Routes handled here must NEVER reach the
/// Node sidecar — the vendored Express agent stack stays dormant (ADR-0078 / runtime_check).
pub fn handle_chat(
    app: Option<&tauri::AppHandle>,
    engine: Option<&Arc<Supervisor>>,
    method: &str,
    route: &str,
    query: &str,
    body: &[u8],
) -> Option<tauri::http::Response<Vec<u8>>> {
    let is_chat = route == "/api/agents/chat" || route.starts_with("/api/agents/chat/");
    let is_convos = route == "/api/convos" || route.starts_with("/api/convos/");
    let is_messages = route.starts_with("/api/messages/");
    if !is_chat && !is_convos && !is_messages {
        return None;
    }
    // Engine-independent answers first: these must hold even while the engine restarts.
    if route.starts_with("/api/convos/gen_title/") {
        // The title already lives on the conversation row (set at creation, carried by the
        // final frame); answer the poll from it so the client's fallback path stays quiet.
        let conversation_id = route.trim_start_matches("/api/convos/gen_title/");
        if let Some(engine) = engine {
            if let Ok(value) = engine.call("listConversations", json!({}), POLL_CALL_TIMEOUT) {
                let title = value
                    .get("conversations")
                    .and_then(Value::as_array)
                    .and_then(|rows| {
                        rows.iter().find(|row| {
                            row.get("conversationId").and_then(Value::as_str)
                                == Some(conversation_id)
                        })
                    })
                    .and_then(|row| row.get("title"))
                    .and_then(Value::as_str)
                    .map(str::to_string);
                if let Some(title) = title {
                    return Some(json_response(200, &json!({"title": title})));
                }
            }
        }
        return Some(json_response(404, &json!({"error": "no title yet"})));
    }
    if is_chat && route.trim_start_matches("/api/agents/chat/").starts_with("stream/") {
        // The app's live path is boundary B (the seam SSE); a stray fetch of the stream URL
        // must return at once rather than hang a one-shot protocol responder.
        return Some(response(200, "text/event-stream", Vec::new()));
    }
    let Some(engine) = engine else {
        return Some(no_engine());
    };

    if is_messages {
        if method != "GET" {
            return Some(json_response(405, &json!({"error": "method not allowed"})));
        }
        let conversation_id = route.trim_start_matches("/api/messages/");
        return Some(engine_reply(
            engine,
            "getConversationMessages",
            json!({"conversation_id": conversation_id}),
        ));
    }

    if is_convos {
        if route == "/api/convos" && method == "GET" {
            return Some(engine_reply(engine, "listConversations", json!({})));
        }
        if method == "GET" {
            // The single-conversation read the chat view mounts from; the rest of the
            // conversation platform (rename, archive, delete) joins at C7.
            let conversation_id = route.trim_start_matches("/api/convos/");
            if !conversation_id.is_empty() && !conversation_id.contains('/') {
                return Some(engine_reply(
                    engine,
                    "getConversation",
                    json!({"conversation_id": conversation_id}),
                ));
            }
        }
        return Some(json_response(
            404,
            &json!({"error": "not part of local mode yet (C7 conversations)"}),
        ));
    }

    // ── /api/agents/chat family ─────────────────────────────────────────────────────────
    let sub = route.trim_start_matches("/api/agents/chat");
    let sub = sub.trim_start_matches('/');

    if method == "GET" && sub == "active" {
        return Some(engine_reply(engine, "listActiveChatTurns", json!({})));
    }
    if method == "GET" && sub.starts_with("status/") {
        let id = sub.trim_start_matches("status/");
        return Some(engine_reply(engine, "getChatTurnStatus", json!({"stream_id": id})));
    }
    if method == "POST" && sub == "abort" {
        let parsed: Value = serde_json::from_slice(body).unwrap_or_else(|_| json!({}));
        let stream_id = ["streamId", "conversationId", "abortKey"]
            .iter()
            .find_map(|key| parsed.get(*key).and_then(Value::as_str))
            .unwrap_or_default()
            .to_string();
        if stream_id.is_empty() {
            return Some(json_response(400, &json!({"error": "no stream to abort"})));
        }
        let mut params = json!({"stream_id": stream_id});
        if let Some(epoch) = parsed.get("generationCreatedAt").and_then(Value::as_i64) {
            params["generation_created_at"] = json!(epoch);
        }
        return Some(engine_reply(engine, "cancelChatTurn", params));
    }
    if method == "POST" && !sub.contains('/') {
        // POST /api/agents/chat and POST /api/agents/chat/{endpoint}: the start. The body
        // is the client's own TPayload, forwarded verbatim; the path endpoint fills in only
        // when the body lacks one (they are the same value in every client build we serve).
        let mut payload: Value = match serde_json::from_slice(body) {
            Ok(value) => value,
            Err(err) => {
                return Some(json_response(
                    400,
                    &json!({"error": format!("unreadable chat payload: {err}")}),
                ));
            }
        };
        if payload.get("endpoint").and_then(Value::as_str).unwrap_or("").is_empty() && !sub.is_empty()
        {
            let decoded = urlencoding_decode(sub);
            payload["endpoint"] = json!(decoded);
        }
        let ack = match engine.call("startChatTurn", json!({"body": payload}), POLL_CALL_TIMEOUT) {
            Ok(value) => value,
            Err(err) => {
                return Some(json_response(
                    502,
                    &json!({"error": format!("startChatTurn: {err}")}),
                ));
            }
        };
        if let (Some(app), Some(stream_id)) = (app, ack.get("streamId").and_then(Value::as_str))
        {
            let generation = ack
                .get("generationCreatedAt")
                .and_then(Value::as_i64)
                .unwrap_or_default();
            spawn_poller(app.clone(), Arc::clone(engine), stream_id.to_string(), generation);
        }
        return Some(json_response(200, &ack));
    }

    let _ = query;
    Some(json_response(
        404,
        &json!({"error": "not part of the chat seam", "route": route, "method": method}),
    ))
}

/// Percent-decode the endpoint path segment ("Ollama%20(local)" → "Ollama (local)").
/// Deliberately tiny: endpoint keys are catalog labels, not arbitrary URLs.
fn urlencoding_decode(segment: &str) -> String {
    let mut out = Vec::with_capacity(segment.len());
    let bytes = segment.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'%' if index + 2 < bytes.len() => {
                let hex = &segment[index + 1..index + 3];
                match u8::from_str_radix(hex, 16) {
                    Ok(value) => {
                        out.push(value);
                        index += 3;
                    }
                    Err(_) => {
                        out.push(bytes[index]);
                        index += 1;
                    }
                }
            }
            b'+' => {
                out.push(b' ');
                index += 1;
            }
            other => {
                out.push(other);
                index += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Drain the engine's frame ledger for one turn at token cadence and push every batch to
/// the webview. Exits after the terminal status has been delivered with a drained read; a
/// dead engine is tolerated across supervisor restarts and reported honestly past the cap.
fn spawn_poller(app: tauri::AppHandle, engine: Arc<Supervisor>, stream_id: String, generation: i64) {
    {
        let mut live = pollers().lock().expect("poller lock");
        // Claim (or reclaim) the stream for THIS generation; a running predecessor sees its
        // epoch replaced and stands down at its next loop check.
        live.insert(stream_id.clone(), generation);
    }
    std::thread::spawn(move || {
        let mut after: i64 = 0;
        let mut failures: u32 = 0;
        loop {
            {
                let live = pollers().lock().expect("poller lock");
                if live.get(&stream_id) != Some(&generation) {
                    return; // superseded by a newer turn's poller — it owns the exit cleanup
                }
            }
            let reply = engine.call(
                "listChatTurnEvents",
                json!({"stream_id": stream_id, "after": after}),
                POLL_CALL_TIMEOUT,
            );
            match reply.ok().and_then(|value| {
                serde_json::from_value::<TurnEventsOut>(value).ok()
            }) {
                Some(page) => {
                    failures = 0;
                    let terminal = page.status != "active";
                    if let Some(last) = page.events.last() {
                        after = i64::from(last.seq);
                    }
                    let drained = page.events.is_empty();
                    if !drained || terminal {
                        let push = AgentStreamEvent {
                            stream_id: stream_id.clone(),
                            status: page.status.clone(),
                            events: frames_from(&page),
                        };
                        let _ = push.emit(&app); // a closed webview is not an error
                    }
                    if terminal && drained {
                        break;
                    }
                }
                None => {
                    failures += 1;
                    if failures >= POLL_MAX_CONSECUTIVE_FAILURES {
                        let _ = AgentStreamEvent {
                            stream_id: stream_id.clone(),
                            status: "error".to_string(),
                            events: Vec::new(),
                        }
                        .emit(&app);
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                    continue;
                }
            }
            std::thread::sleep(POLL_INTERVAL);
        }
        let mut live = pollers().lock().expect("poller lock");
        if live.get(&stream_id) == Some(&generation) {
            live.remove(&stream_id);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_router_ignores_foreign_routes() {
        assert!(handle_chat(None, None, "GET", "/api/banner", "", b"").is_none());
        assert!(handle_chat(None, None, "GET", "/api/agents/tools", "", b"").is_none());
    }

    #[test]
    fn the_family_without_an_engine_is_503_not_a_forward() {
        let reply = handle_chat(None, None, "POST", "/api/agents/chat/x", "", b"{}")
            .expect("chat routes belong to the seam");
        assert_eq!(reply.status(), 503);
        let reply = handle_chat(None, None, "GET", "/api/convos", "", b"")
            .expect("convos belong to the seam");
        assert_eq!(reply.status(), 503);
        let reply = handle_chat(None, None, "GET", "/api/messages/c1", "", b"")
            .expect("messages belong to the seam");
        assert_eq!(reply.status(), 503);
    }

    #[test]
    fn a_stray_stream_fetch_returns_at_once_even_with_no_engine() {
        let reply = handle_chat(None, None, "GET", "/api/agents/chat/stream/abc", "", b"")
            .expect("stream is the seam's route");
        assert_eq!(reply.status(), 200);
    }

    #[test]
    fn the_endpoint_segment_decodes_like_a_label() {
        assert_eq!(urlencoding_decode("Ollama%20(local)"), "Ollama (local)");
        assert_eq!(urlencoding_decode("plain"), "plain");
        assert_eq!(urlencoding_decode("a+b"), "a b");
        assert_eq!(urlencoding_decode("bad%zz"), "bad%zz");
        assert_eq!(urlencoding_decode("trail%2"), "trail%2");
    }

    #[test]
    fn gen_title_polls_get_an_honest_404_even_with_no_engine() {
        let reply = handle_chat(None, None, "GET", "/api/convos/gen_title/c1", "", b"")
            .expect("gen_title belongs to the seam");
        assert_eq!(reply.status(), 404);
    }
}
