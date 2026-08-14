//! Boundary B (CLAUDE.md §9b): every webview interaction with the sidecar is one of these
//! typed commands. `tauri-specta` exports their exact signatures to
//! `packages/desktop/src/generated/bindings.ts`; handwritten `invoke()` calls are banned.
//! Payload types come from the generated Boundary A domain (`crate::generated::domain`) —
//! one Pydantic source of truth, three languages, zero handwritten mirrors.

use std::sync::Arc;

use serde_json::{json, Map, Value};

use crate::generated::domain::{
    CancelAccepted, DivergenceDetail, HealthResponse, LocalProveRequest, LogRecordOut,
    PageRunSummary, RunCreated, RunDetail, RunEventOut, SearchResults, TargetDetail, Verdict,
};
use crate::supervisor::{RpcError, Supervisor, DEFAULT_CALL_TIMEOUT};

/// What the UI receives when a sidecar call fails: the JSON-RPC error code (or -1 for
/// transport-level failures, -2 for contract violations) plus a human-readable message.
#[derive(Debug, Clone, serde::Serialize, specta::Type)]
pub struct SidecarFailure {
    pub code: i32,
    pub message: String,
}

/// Sidecar lifecycle transitions ("healthy" / "restarting" / "stopped"), delivered to the UI
/// as a typed tauri-specta event — event payloads are generated, never handwritten (§9b).
#[derive(Debug, Clone, serde::Serialize, specta::Type, tauri_specta::Event)]
pub struct SidecarStateEvent {
    pub state: String,
}

impl From<RpcError> for SidecarFailure {
    fn from(err: RpcError) -> Self {
        match err {
            RpcError::Peer { code, message, .. } => {
                Self { code: i32::try_from(code).unwrap_or(-1), message }
            }
            other => Self { code: -1, message: other.to_string() },
        }
    }
}

type CmdResult<T> = Result<T, SidecarFailure>;

/// Not a domain object: the transport wrapper the stdio bridge uses for text responses.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct ReproSource {
    pub content_type: String,
    pub text: String,
}

fn call_typed<T: serde::de::DeserializeOwned>(
    supervisor: &Supervisor,
    operation: &str,
    params: Value,
) -> CmdResult<T> {
    let value = supervisor.call(operation, params, DEFAULT_CALL_TIMEOUT)?;
    serde_json::from_value(value).map_err(|err| SidecarFailure {
        code: -2,
        message: format!("contract violation decoding {operation}: {err}"),
    })
}

#[tauri::command]
#[specta::specta]
pub fn get_health(state: tauri::State<'_, Arc<Supervisor>>) -> CmdResult<HealthResponse> {
    call_typed(&state, "getHealth", json!({}))
}

#[tauri::command]
#[specta::specta]
pub fn list_runs(
    state: tauri::State<'_, Arc<Supervisor>>,
    verdict: Option<Verdict>,
    cursor: Option<String>,
    limit: Option<u32>,
) -> CmdResult<PageRunSummary> {
    let mut params = Map::new();
    if let Some(verdict) = verdict {
        params.insert("verdict".into(), json!(verdict));
    }
    if let Some(cursor) = cursor {
        params.insert("cursor".into(), Value::String(cursor));
    }
    if let Some(limit) = limit {
        params.insert("limit".into(), json!(limit));
    }
    call_typed(&state, "listRuns", Value::Object(params))
}

#[tauri::command]
#[specta::specta]
pub fn get_run(state: tauri::State<'_, Arc<Supervisor>>, run_id: i32) -> CmdResult<RunDetail> {
    call_typed(&state, "getRun", json!({"run_id": run_id}))
}

#[tauri::command]
#[specta::specta]
pub fn list_run_events(
    state: tauri::State<'_, Arc<Supervisor>>,
    run_id: i32,
) -> CmdResult<Vec<RunEventOut>> {
    call_typed(&state, "listRunEvents", json!({"run_id": run_id}))
}

#[tauri::command]
#[specta::specta]
pub fn get_target(
    state: tauri::State<'_, Arc<Supervisor>>,
    target_id: i32,
) -> CmdResult<TargetDetail> {
    call_typed(&state, "getTarget", json!({"target_id": target_id}))
}

#[tauri::command]
#[specta::specta]
pub fn get_divergence(
    state: tauri::State<'_, Arc<Supervisor>>,
    divergence_id: i32,
) -> CmdResult<DivergenceDetail> {
    call_typed(&state, "getDivergence", json!({"divergence_id": divergence_id}))
}

#[tauri::command]
#[specta::specta]
pub fn get_divergence_repro(
    state: tauri::State<'_, Arc<Supervisor>>,
    divergence_id: i32,
) -> CmdResult<ReproSource> {
    call_typed(&state, "getDivergenceRepro", json!({"divergence_id": divergence_id}))
}

#[tauri::command]
#[specta::specta]
pub fn start_local_prove(
    state: tauri::State<'_, Arc<Supervisor>>,
    request: LocalProveRequest,
) -> CmdResult<RunCreated> {
    call_typed(&state, "startLocalProve", json!({"body": request}))
}

#[tauri::command]
#[specta::specta]
pub fn cancel_run(state: tauri::State<'_, Arc<Supervisor>>, run_id: i32) -> CmdResult<CancelAccepted> {
    call_typed(&state, "cancelRun", json!({"run_id": run_id}))
}

#[tauri::command]
#[specta::specta]
pub fn search_divergences(
    state: tauri::State<'_, Arc<Supervisor>>,
    q: String,
    limit: Option<u32>,
) -> CmdResult<SearchResults> {
    let mut params = Map::new();
    params.insert("q".into(), Value::String(q));
    if let Some(limit) = limit {
        params.insert("limit".into(), json!(limit));
    }
    call_typed(&state, "searchDivergences", Value::Object(params))
}

#[tauri::command]
#[specta::specta]
pub fn list_log_records(
    state: tauri::State<'_, Arc<Supervisor>>,
    limit: Option<u32>,
    level: Option<String>,
) -> CmdResult<Vec<LogRecordOut>> {
    let mut params = Map::new();
    if let Some(limit) = limit {
        params.insert("limit".into(), json!(limit));
    }
    if let Some(level) = level {
        params.insert("level".into(), Value::String(level));
    }
    call_typed(&state, "listLogs", Value::Object(params))
}

#[cfg(test)]
mod enum_discipline {
    //! §9b enum discipline: exhaustive matches with no wildcard arm — adding a variant in
    //! Python regenerates the Rust enum and breaks this build until it is handled here.

    use crate::generated::domain::{ReasonCode, Verdict};

    #[test]
    fn every_reason_code_has_an_operator_hint() {
        for code in [
            ReasonCode::TargetUnreachable,
            ReasonCode::EnvReproductionFailed,
            ReasonCode::HarnessSynthesisFailed,
            ReasonCode::UninterceptableEffect,
            ReasonCode::NondeterministicBase,
            ReasonCode::SandboxUnavailable,
            ReasonCode::ValueUnserializable,
            ReasonCode::RecordReplayUnavailable,
        ] {
            let hint = match code {
                ReasonCode::TargetUnreachable => "cannot be constructed or invoked in isolation",
                ReasonCode::EnvReproductionFailed => "environment could not be reproduced",
                ReasonCode::HarnessSynthesisFailed => "no adapter could invoke the target",
                ReasonCode::UninterceptableEffect => "reaches a surface replay cannot intercept",
                ReasonCode::NondeterministicBase => "base disagrees with itself (Law L3)",
                ReasonCode::SandboxUnavailable => "no sandbox tier available (Law L6)",
                ReasonCode::ValueUnserializable => "produced values with no canonical encoding",
                ReasonCode::RecordReplayUnavailable => "record/replay not available for this code",
            };
            assert!(!hint.is_empty());
        }
    }

    #[test]
    fn every_verdict_is_classified_for_severity() {
        for verdict in [
            Verdict::Divergent,
            Verdict::EquivalentUnderBudget,
            Verdict::Unproven,
            Verdict::Error,
        ] {
            let is_actionable = match verdict {
                Verdict::Divergent | Verdict::Error => true,
                Verdict::EquivalentUnderBudget | Verdict::Unproven => false,
            };
            let _ = is_actionable;
        }
    }
}
