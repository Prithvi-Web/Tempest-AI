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
use crate::supervisor::{RpcError, Supervisor};

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

/// `engine_reply` for the CRUD family: the ENGINE's OWN HTTP status and body pass through.
/// A 404 for a missing agent must reach the client as a 404 — the builder's error surfaces
/// read `error.response.status`, and a flattened 502 would turn "no such agent" into "the
/// backend is broken". Transport-level failures keep the loud 502.
fn engine_reply_passthrough(
    engine: &Arc<Supervisor>,
    operation: &str,
    params: Value,
) -> tauri::http::Response<Vec<u8>> {
    match engine.call(operation, params, POLL_CALL_TIMEOUT) {
        Ok(value) => json_response(200, &value),
        Err(RpcError::Peer { message, data, .. }) => {
            let status = data.get("status").and_then(Value::as_u64).unwrap_or(0);
            if (400..600).contains(&status) {
                let body = data
                    .get("body")
                    .cloned()
                    .unwrap_or_else(|| json!({"error": message}));
                return json_response(status as u16, &body);
            }
            json_response(502, &json!({"error": format!("{operation}: {message}")}))
        }
        Err(err) => json_response(502, &json!({"error": format!("{operation}: {err}")})),
    }
}

/// How long a READ will out-wait a supervised engine restart before failing loudly. The
/// supervisor's backoff brings the sidecar back within a few seconds; a read that painted
/// the console red (and blanked the rail) for that window would turn routine recovery into
/// visible breakage. Past the bound the failure IS the story and it surfaces honestly.
const PATIENT_READ_DEADLINE: Duration = Duration::from_secs(8);

/// `engine_reply` for machine-initiated READS: retries across the restart window. Writes
/// and user-initiated starts stay immediate — a user's click deserves a fast, loud answer.
fn engine_reply_patient(
    engine: &Arc<Supervisor>,
    operation: &str,
    params: Value,
) -> tauri::http::Response<Vec<u8>> {
    let deadline = std::time::Instant::now() + PATIENT_READ_DEADLINE;
    loop {
        match engine.call(operation, params.clone(), POLL_CALL_TIMEOUT) {
            Ok(value) => return json_response(200, &value),
            Err(err) => {
                if std::time::Instant::now() >= deadline {
                    return json_response(
                        502,
                        &json!({"error": format!("{operation}: {err}")}),
                    );
                }
                std::thread::sleep(Duration::from_millis(250));
            }
        }
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
    let is_agents = route == "/api/agents" || route.starts_with("/api/agents/");
    let is_convos = route == "/api/convos" || route.starts_with("/api/convos/");
    let is_messages = route.starts_with("/api/messages/");
    if !is_agents && !is_convos && !is_messages {
        return None;
    }
    // Sub-families the NODE seam still owns, forwarded deliberately: tool CALLS and per-tool
    // auth (honest local-mode stubs until C8), OpenAPI actions (C8), and the api-key v1
    // sub-routers (dormant server mode). Everything else under /api/agents is this seam's.
    if is_agents
        && !is_chat
        && (route.starts_with("/api/agents/tools/")
            || route == "/api/agents/actions"
            || route.starts_with("/api/agents/actions/")
            || route.starts_with("/api/agents/v1/"))
    {
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
    // The 5-second active-jobs poll must stay QUIET through a supervised engine restart:
    // a dead engine runs no generations, so the empty list is the truth — and a machine-
    // initiated poll painting the console red during recovery would fail the zero-console
    // bar for a condition the supervisor heals on its own. User-initiated operations below
    // keep their loud, honest errors.
    if method == "GET" && route == "/api/agents/chat/active" {
        let jobs = engine
            .and_then(|engine| {
                engine
                    .call("listActiveChatTurns", json!({}), POLL_CALL_TIMEOUT)
                    .ok()
            })
            .unwrap_or_else(|| json!({"activeJobIds": []}));
        return Some(json_response(200, &jobs));
    }
    // Preempt-arm is answered engine-free: this surface's steers drain at turn boundaries
    // (LC16's granularity here), so escalating one to interrupt the CURRENT step is
    // honestly unsupported — a code the client relabels the chip on, never an error.
    if is_chat && method == "POST" {
        let sub = route.trim_start_matches("/api/agents/chat").trim_start_matches('/');
        if sub == "steer/arm" {
            return Some(json_response(
                200,
                &json!({"armed": false, "code": "PREEMPT_UNSUPPORTED"}),
            ));
        }
    }
    let Some(engine) = engine else {
        return Some(no_engine());
    };

    if is_messages {
        if method != "GET" {
            return Some(json_response(405, &json!({"error": "method not allowed"})));
        }
        let conversation_id = route.trim_start_matches("/api/messages/");
        return Some(engine_reply_patient(
            engine,
            "getConversationMessages",
            json!({"conversation_id": conversation_id}),
        ));
    }

    if is_convos {
        if route == "/api/convos" && method == "GET" {
            return Some(engine_reply_patient(engine, "listConversations", json!({})));
        }
        if method == "GET" {
            // The single-conversation read the chat view mounts from; the rest of the
            // conversation platform (rename, archive, delete) joins at C7.
            let conversation_id = route.trim_start_matches("/api/convos/");
            if !conversation_id.is_empty() && !conversation_id.contains('/') {
                return Some(engine_reply_patient(
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

    if is_chat {
        // ── /api/agents/chat family ────────────────────────────────────────────────────
        let sub = route.trim_start_matches("/api/agents/chat");
        let sub = sub.trim_start_matches('/');

        if method == "GET" && sub.starts_with("status/") {
            let id = sub.trim_start_matches("status/");
            return Some(engine_reply_patient(
                engine,
                "getChatTurnStatus",
                json!({"stream_id": id}),
            ));
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
        if method == "POST" && (sub == "steer" || sub == "steer/deliver" || sub == "steer/cancel") {
            // C5 steering (LC16/LC17): queue, idempotent re-delivery (the engine dedupes by
            // clientSteerId), and reclaim. The stream id IS the conversation id; the
            // engine's own statuses and top-level codes pass through — NO_ACTIVE_RUN is how
            // the client knows to fall back to a plain send.
            let parsed: Value = match serde_json::from_slice(body) {
                Ok(value) => value,
                Err(err) => {
                    return Some(json_response(
                        400,
                        &json!({"error": format!("unreadable steer payload: {err}")}),
                    ));
                }
            };
            let stream_id = ["conversationId", "streamId"]
                .iter()
                .find_map(|key| parsed.get(*key).and_then(Value::as_str))
                .unwrap_or_default()
                .to_string();
            if stream_id.is_empty() {
                return Some(json_response(400, &json!({"error": "no conversation to steer"})));
            }
            let operation = if sub == "steer/cancel" { "cancelChatSteer" } else { "steerChatTurn" };
            return Some(engine_reply_passthrough(
                engine,
                operation,
                json!({"stream_id": stream_id, "body": parsed}),
            ));
        }
        if method == "POST" && sub == "resume" {
            // C5 HITL: answer the parked approval. The stream id IS the conversation id on
            // this surface; the engine validates the action and wakes the parked worker,
            // and its own statuses pass through (409 stale locks the client's submit).
            let parsed: Value = match serde_json::from_slice(body) {
                Ok(value) => value,
                Err(err) => {
                    return Some(json_response(
                        400,
                        &json!({"error": format!("unreadable resume payload: {err}")}),
                    ));
                }
            };
            let stream_id = ["streamId", "conversationId"]
                .iter()
                .find_map(|key| parsed.get(*key).and_then(Value::as_str))
                .unwrap_or_default()
                .to_string();
            if stream_id.is_empty() {
                return Some(json_response(400, &json!({"error": "no stream to resume"})));
            }
            return Some(engine_reply_passthrough(
                engine,
                "resolveChatApproval",
                json!({"stream_id": stream_id, "body": parsed}),
            ));
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
            if payload.get("endpoint").and_then(Value::as_str).unwrap_or("").is_empty()
                && !sub.is_empty()
            {
                let decoded = urlencoding_decode(sub);
                payload["endpoint"] = json!(decoded);
            }
            let ack =
                match engine.call("startChatTurn", json!({"body": payload}), POLL_CALL_TIMEOUT) {
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

        return Some(json_response(
            404,
            &json!({"error": "not part of the chat seam", "route": route, "method": method}),
        ));
    }

    // ── /api/agents CRUD family (PLAN-V3 C5: the builder's wire, ADR-0075) ─────────────
    // Literals before `{agent_id}`: an agent named "tools" must never shadow the picker —
    // the collision the vendored Express router carries a warning about.
    if method == "GET" && route == "/api/agents/tools" {
        return Some(engine_reply_patient(engine, "listAgentTools", json!({})));
    }
    if method == "GET" && route == "/api/agents/categories" {
        return Some(engine_reply_patient(engine, "listAgentCategories", json!({})));
    }
    if route == "/api/agents" {
        return Some(match method {
            "GET" => engine_reply_patient(engine, "listAgents", list_params(query)),
            "POST" => match serde_json::from_slice::<Value>(body) {
                Ok(payload) => {
                    engine_reply_passthrough(engine, "createAgent", json!({"body": payload}))
                }
                Err(err) => {
                    json_response(400, &json!({"error": format!("unreadable agent: {err}")}))
                }
            },
            _ => json_response(405, &json!({"error": "method not allowed"})),
        });
    }
    let rest = route.trim_start_matches("/api/agents/");
    let (agent_id, tail) = match rest.split_once('/') {
        Some((id, tail)) => (id, Some(tail)),
        None => (rest, None),
    };
    if agent_id.is_empty() {
        return Some(json_response(404, &json!({"error": "no agent id in the route"})));
    }
    let id = json!({"agent_id": agent_id});
    let with_body = |operation: &str| -> tauri::http::Response<Vec<u8>> {
        match serde_json::from_slice::<Value>(body) {
            Ok(payload) => engine_reply_passthrough(
                engine,
                operation,
                json!({"agent_id": agent_id, "body": payload}),
            ),
            Err(err) => json_response(400, &json!({"error": format!("unreadable body: {err}")})),
        }
    };
    Some(match (method, tail) {
        ("GET", None) => engine_reply_passthrough(engine, "getAgent", id),
        ("PATCH", None) => with_body("updateAgent"),
        ("DELETE", None) => engine_reply_passthrough(engine, "deleteAgent", id),
        ("GET", Some("expanded")) => engine_reply_passthrough(engine, "getExpandedAgent", id),
        ("GET", Some("versions")) => engine_reply_passthrough(engine, "listAgentVersions", id),
        ("POST", Some("duplicate")) => engine_reply_passthrough(engine, "duplicateAgent", id),
        ("POST", Some("revert")) => with_body("revertAgentVersion"),
        _ => json_response(
            404,
            &json!({"error": "not part of the agent seam", "route": route, "method": method}),
        ),
    })
}

/// The list query the builder sends, reduced to the scalars the engine op reads. Unknown
/// keys (requiredPermission, promoted) are deliberately dropped: local single-user mode has
/// one principal and no promotion tiers.
fn list_params(query: &str) -> Value {
    let mut params = serde_json::Map::new();
    for pair in query.split('&').filter(|p| !p.is_empty()) {
        let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
        if matches!(key, "limit" | "cursor" | "search" | "category") {
            params.insert(key.to_string(), json!(urlencoding_decode(value)));
        }
    }
    Value::Object(params)
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
    }

    #[test]
    fn node_owned_agent_subfamilies_are_forwarded_not_served() {
        // Tool CALLS, per-tool auth, actions, and the dormant v1 sub-routers keep their node
        // seam stubs until their C-phases; the router must hand them through untouched.
        for route in [
            "/api/agents/tools/calls",
            "/api/agents/tools/web_search/auth",
            "/api/agents/actions",
            "/api/agents/actions/agent_1/act_1",
            "/api/agents/v1/models",
        ] {
            assert!(
                handle_chat(None, None, "GET", route, "", b"").is_none(),
                "{route} must forward to the node seam"
            );
        }
    }

    #[test]
    fn the_crud_family_belongs_to_the_seam_now() {
        // Engineless 503 (not None, not a forward): the builder's wire is host-served. The
        // regression this pins: /api/agents/tools used to fall through to a stub that
        // answered an empty picker.
        for (method, route) in [
            ("GET", "/api/agents/tools"),
            ("GET", "/api/agents/categories"),
            ("GET", "/api/agents"),
            ("POST", "/api/agents"),
            ("GET", "/api/agents/agent_1"),
            ("PATCH", "/api/agents/agent_1"),
            ("DELETE", "/api/agents/agent_1"),
            ("GET", "/api/agents/agent_1/expanded"),
            ("GET", "/api/agents/agent_1/versions"),
            ("POST", "/api/agents/agent_1/duplicate"),
            ("POST", "/api/agents/agent_1/revert"),
        ] {
            let reply = handle_chat(None, None, method, route, "", b"{}")
                .unwrap_or_else(|| panic!("{method} {route} must belong to the seam"));
            assert_eq!(reply.status(), 503, "{method} {route} without an engine");
        }
    }

    #[test]
    fn resume_and_steer_are_never_mis_started() {
        // The defect this pins: both fell into the start branch ("no slash in the segment")
        // and began a NEW generation — a tool approval would have started a second turn.
        // Both are real engine-backed arms now: engineless answers a loud 503, never a
        // start. Preempt-arm alone stays engine-free with the code the client relabels on.
        for route in [
            "/api/agents/chat/resume",
            "/api/agents/chat/steer",
            "/api/agents/chat/steer/deliver",
            "/api/agents/chat/steer/cancel",
        ] {
            let reply = handle_chat(None, None, "POST", route, "", b"{}")
                .unwrap_or_else(|| panic!("{route} belongs to the seam"));
            assert_eq!(reply.status(), 503, "engineless {route} is a loud 503, never a start");
        }
        let reply = handle_chat(None, None, "POST", "/api/agents/chat/steer/arm", "", b"{}")
            .expect("steer/arm belongs to the seam");
        assert_eq!(reply.status(), 200);
        assert!(String::from_utf8_lossy(reply.body()).contains("PREEMPT_UNSUPPORTED"));
    }

    #[test]
    fn the_list_query_reduces_to_the_scalars_the_engine_reads() {
        let params = list_params("limit=2&cursor=agent_9&search=docs%20helper&promoted=1");
        assert_eq!(params["limit"], "2");
        assert_eq!(params["cursor"], "agent_9");
        assert_eq!(params["search"], "docs helper");
        assert!(params.get("promoted").is_none(), "unknown keys are dropped");
        assert_eq!(list_params(""), serde_json::json!({}));
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
