//! Boundary B (CLAUDE.md §9b): every webview interaction with the sidecar is one of these
//! typed commands. `tauri-specta` exports their exact signatures to
//! `packages/desktop/src/generated/bindings.ts`; handwritten `invoke()` calls are banned.
//! Payload types come from the generated Boundary A domain (`crate::generated::domain`) —
//! one Pydantic source of truth, three languages, zero handwritten mirrors.

use std::sync::Arc;

use serde_json::{json, Map, Value};

use crate::generated::domain::{
    AiKeyTestResult, CancelAccepted, ComposeRequest, ComposeView, DiagnosticBundle,
    DivergenceDetail, HealthResponse,
    LocalProveRequest, LogRecordOut, PageRunSummary, RunCreated, RunDetail, RunEventOut,
    SearchResults, SettingsIn, SettingsOut, SymbolDivergences, SyncReport, TargetDetail,
    UiErrorRecorded, UiErrorReport, Verdict, WatchStartRequest, WatchStatus,
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

/// Pushed once per second for every live run by the central watcher (§1.2): views refetch
/// on this instead of owning timers. Status/verdict ride as the GENERATED domain enums —
/// the payload cannot drift from the Python truth (§9b).
#[derive(Debug, Clone, serde::Serialize, specta::Type, tauri_specta::Event)]
pub struct RunProgressEvent {
    pub run_id: i32,
    pub status: crate::generated::domain::RunStatus,
    pub verdict: Option<crate::generated::domain::Verdict>,
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

/// Hard ceiling on an editor read, regardless of what the caller asks for. A cap the caller
/// chooses is not a cap (L15.4).
const MAX_READ_BYTES: u64 = 2 * 1024 * 1024;

/// One file, as the editor receives it.
///
/// Deliberately NOT a Boundary A domain type: nothing about opening a file in the user's editor
/// exists in the Pydantic model, and minting a domain shape for a desktop-local capability would
/// put a fiction in the contract. `SidecarStateEvent` sets the precedent for Tauri-local types.
#[derive(Debug, Clone, serde::Serialize, specta::Type)]
pub struct ProjectFile {
    /// Repository-relative path as RESOLVED — a symlink reports where it actually landed, so the
    /// editor's title bar cannot claim one file while showing another.
    pub path: String,
    pub text: String,
    pub bytes: u32,
}

/// Why a read was refused: the machine-readable reason the UI branches on, plus the sentence it
/// shows. The reason is `pathguard::PathRefusal` itself rather than a parallel enum — a second
/// copy of the vocabulary is a second thing to keep in step (§9b).
#[derive(Debug, Clone, serde::Serialize, specta::Type)]
pub struct ProjectFileRefusal {
    pub refusal: crate::pathguard::PathRefusal,
    pub message: String,
}

impl From<crate::pathguard::PathRefusal> for ProjectFileRefusal {
    fn from(refusal: crate::pathguard::PathRefusal) -> Self {
        Self { message: refusal.to_string(), refusal }
    }
}

/// Hover information from a language server (Phase 20.2 dispatch).
///
/// The webview names a FILE and a POSITION. It never names a protocol method, a server, or a
/// command line: the set of things a language server can be asked is a list this host wrote, not
/// a string the renderer chose. That matters because the renderer is where hostile model output
/// is displayed, and a language server is an arbitrary binary reading the user's source.
///
/// The language is inferred from the RESOLVED path here rather than accepted from the caller,
/// for the same reason — and from the resolved one rather than the requested one because a
/// symlink named `notes.txt` pointing at `main.py` is a Python file, and the server that reads
/// it should be the one that understands what it will find.
///
/// **`pathguard` decides whether this file may be named at all**, exactly as it does for
/// `read_project_file`. The first version re-implemented containment inline as three lexical
/// checks under a comment claiming parity with a guard that also canonicalises, re-applies the
/// credential denylist to the RESOLVED path, and refuses hard links — so `src/notes.py`
/// symlinked to `~/.ssh/id_rsa` was refused by the editor and accepted here (trap 45, again).
/// One guard, one vocabulary: `PathRefusal` crosses into `LspError::Refused` unchanged.
///
/// **The blocking work runs on the BLOCKING POOL, and that took two attempts to get right.**
/// A bare `#[tauri::command]` is `ExecutionContext::Blocking` in tauri-macros and runs the body
/// inline on the IPC handler — the main thread on macOS. Adding `(async)` to a SYNCHRONOUS fn
/// does not fix that; it spawns the future on tokio's multi-thread runtime, where the sync body
/// then blocks a WORKER. With no in-flight guard on hover and a ten-second request timeout held
/// across the multiplexer's mutex, ordinary reading could occupy every worker and starve every
/// other async command — including the Settings screen, the user's only way to clear the bad
/// command. The stall had been moved, not removed. `spawn_blocking` is what actually removes it.
///
/// Servers are named by `TEMPEST_LSP_PYTHON` / `TEMPEST_LSP_TYPESCRIPT` and are absent by
/// default, so `Unsupported` is the ordinary answer on a fresh install — not an error.
#[tauri::command]
#[specta::specta]
pub async fn lsp_hover(
    state: tauri::State<'_, Arc<std::sync::Mutex<crate::lsp::Multiplexer>>>,
    repo_path: String,
    path: String,
    text: String,
    line: u32,
    character: u32,
) -> Result<Option<crate::lsp::HoverInfo>, crate::lsp::LspError> {
    let mux = Arc::clone(&state);
    // Everything below blocks: a path canonicalisation, a mutex, and up to REQUEST_TIMEOUT of
    // waiting on a child process. None of it may hold a tokio worker.
    tauri::async_runtime::spawn_blocking(move || {
        let root = std::path::Path::new(&repo_path);
        // The same guard the editor read the file through, applied before a single byte of the
        // path reaches an arbitrary user-configured binary.
        let resolved = crate::pathguard::resolve_within(root, &path, MAX_READ_BYTES)?;
        let Some(language) = language_for(&resolved.to_string_lossy()) else {
            return Err(crate::lsp::LspError::Unsupported { language: "unknown".into() });
        };
        let mut guard = mux.lock().map_err(|_| crate::lsp::LspError::ServerGone {
            language: language.to_string(),
        })?;
        let result = guard.hover(language, root, &resolved, &text, line, character)?;
        // `None` means the server had nothing to say — a real answer, different from an error.
        Ok(crate::lsp::hover_text(&result).map(|contents| crate::lsp::HoverInfo { contents }))
    })
    .await
    .map_err(|_| crate::lsp::LspError::ServerGone { language: "unknown".into() })?
}

/// Which language server, from the file's extension. Unknown extensions get none rather than a
/// guess — starting the wrong server is worse than starting none.
fn language_for(path: &str) -> Option<&'static str> {
    let lower = path.to_ascii_lowercase();
    if lower.ends_with(".py") || lower.ends_with(".pyi") {
        return Some("python");
    }
    if lower.ends_with(".ts") || lower.ends_with(".tsx") || lower.ends_with(".js") {
        return Some("typescript");
    }
    None
}

/// The app's data directory, as managed state, so the runner commands need not re-resolve it.
pub struct DataDir(pub std::path::PathBuf);

/// The editor's two runners as the settings screen sees them (Phase 20.6).
///
/// Host-local, like `ProjectFile` and for the same reason: nothing about which binary this host
/// spawns for a hover exists in the Pydantic model, and minting a domain shape for a
/// desktop-local capability would put a fiction in the contract.
#[tauri::command(async)]
#[specta::specta]
pub fn get_editor_runners(
    data_dir: tauri::State<'_, DataDir>,
) -> Result<crate::runners::EditorRunnersOut, SidecarFailure> {
    Ok(crate::runners::describe(&data_dir.0))
}

/// Save both runners, and re-point the multiplexer at the new commands.
///
/// The running servers are swept rather than kept: a language server started from the OLD
/// command must not go on answering hovers after the user has changed it, which would make the
/// settings screen disagree with the process table — the same "a control that silently disagrees
/// with reality is a lie" rule the engine settings screen follows. A killed server costs one
/// relaunch on the next hover.
#[tauri::command(async)]
#[specta::specta]
pub fn update_editor_runners(
    data_dir: tauri::State<'_, DataDir>,
    lsp: tauri::State<'_, Arc<std::sync::Mutex<crate::lsp::Multiplexer>>>,
    runners: crate::runners::EditorRunners,
) -> Result<crate::runners::EditorRunnersOut, SidecarFailure> {
    crate::runners::save(&data_dir.0, &runners).map_err(|err| SidecarFailure {
        code: -5,
        message: format!("the editor settings could not be saved — {err}"),
    })?;
    let specs = crate::runners::server_specs(&data_dir.0);
    let mut mux = lsp.lock().map_err(|_| SidecarFailure {
        code: -5,
        message: "the language-server multiplexer is unavailable".into(),
    })?;
    mux.reconfigure(specs);
    Ok(crate::runners::describe(&data_dir.0))
}

/// Ask the user's local model for a completion (Phase 20.3d, F11).
///
/// Returns `null` rather than an error when there is simply no model configured — the expected
/// state on a fresh install, and one the editor answers by falling back to its offline document
/// source. Every other refusal is a real fact about a model that IS configured, and the caller
/// falls back on those too: a completion that misses its deadline is worse than no completion,
/// because it lands under a cursor that has moved on.
///
/// The model is named in Settings (`runners::EditorRunners::local_model`), or forced by
/// `TEMPEST_LOCAL_MODEL` / `TEMPEST_LOCAL_MODEL_ARGS` for a launcher that sets them. Until
/// Phase 20.6 the environment was the ONLY way, which made this an undiscoverable feature —
/// i.e. one nobody has.
///
/// `async` is load-bearing, not decoration. `#[tauri::command]` on its own is
/// `ExecutionContext::Blocking` in tauri-macros 2.6.3, whose codegen runs the body INLINE in the
/// IPC handler — on macOS, the WKWebView script-message callback on the app's main thread. This
/// function spawns a process and waits up to the deadline for it, so as a sync command it froze
/// the window for exactly as long as `localmodel.rs`'s doc comment says it refuses to.
#[tauri::command]
#[specta::specta]
pub async fn local_completion(
    data_dir: tauri::State<'_, DataDir>,
    prompt: String,
    deadline_ms: u32,
) -> Result<Option<String>, SidecarFailure> {
    let dir = data_dir.0.clone();
    // Spawns a process and waits on it — blocking-pool work, not tokio-worker work.
    tauri::async_runtime::spawn_blocking(move || local_completion_blocking(&dir, &prompt, deadline_ms))
        .await
        .map_err(|_| SidecarFailure { code: -6, message: "the local model task failed".into() })
}

fn local_completion_blocking(
    data_dir: &std::path::Path,
    prompt: &str,
    deadline_ms: u32,
) -> Option<String> {
    let spec = crate::runners::model_spec(data_dir);
    // The deadline the CALLER chose, clamped: a webview asking for a ten-minute completion would
    // hold a model process open long past any use for its answer.
    let deadline = std::time::Duration::from_millis(u64::from(deadline_ms).min(2_000));
    crate::localmodel::LocalModel::new(spec).complete(prompt, deadline).ok()
}

/// Read one text file out of an open project, for the editor surface (Phase 20.1).
///
/// This does NOT go through the sidecar. Every other command here forwards to Python, but §5
/// budgets "open file (10k lines)" at a p50 of 40 ms, and a JSON-RPC round trip through a
/// separate process to hand back bytes the OS already has is latency spent for nothing. The
/// safety that the sidecar boundary would have provided is provided instead by `pathguard`,
/// which is the same module Phase 21's `read_file` dispatch will use.
///
/// On the blocking pool for the same reason as the other two host commands: canonicalising a
/// path and reading up to 2 MiB through a UTF-8 validation is real work, and neither the main
/// thread nor a tokio worker is the place for it.
#[tauri::command]
#[specta::specta]
pub async fn read_project_file(
    repo_path: String,
    path: String,
    max_bytes: Option<u32>,
) -> Result<ProjectFile, ProjectFileRefusal> {
    tauri::async_runtime::spawn_blocking(move || read_project_file_blocking(repo_path, path, max_bytes))
        .await
        .unwrap_or(Err(ProjectFileRefusal::from(crate::pathguard::PathRefusal::Unreadable)))
}

fn read_project_file_blocking(
    repo_path: String,
    path: String,
    max_bytes: Option<u32>,
) -> Result<ProjectFile, ProjectFileRefusal> {
    // The caller may ask for LESS than the ceiling, never more.
    let cap = max_bytes.map_or(MAX_READ_BYTES, |n| u64::from(n).min(MAX_READ_BYTES));
    let root = std::path::Path::new(&repo_path);
    let opened = crate::pathguard::open_within(root, &path, cap)?;
    let canonical_root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
    let shown = opened
        .path
        .strip_prefix(&canonical_root)
        .unwrap_or(&opened.path)
        .to_string_lossy()
        .into_owned();
    Ok(ProjectFile {
        path: shown,
        bytes: u32::try_from(opened.text.len()).unwrap_or(u32::MAX),
        text: opened.text,
    })
}

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

/// The seam SSE's ledger replay: everything the turn has emitted so far, so a stream that
/// subscribes late (or a webview that reloaded) starts complete before following the live
/// pushes. Same boundary-A operation the host poller drains.
#[tauri::command]
#[specta::specta]
pub fn replay_chat_turn(
    state: tauri::State<'_, Arc<Supervisor>>,
    stream_id: String,
    after: i32,
) -> CmdResult<crate::agent_chat::ChatTurnReplay> {
    // The cursor is the CLIENT's high-water mark, not a constant 0. Delta frames are
    // coalesced on the read side and a merged frame carries its run's LAST seq, so a replay
    // computed from 0 merges a LONGER run than a live push that landed meanwhile — and the
    // same text arrives under two different seqs, which no membership dedupe can collapse.
    // Serving from the caller's cursor makes the two windows disjoint by construction.
    let page: crate::generated::domain::TurnEventsOut =
        call_typed(&state, "listChatTurnEvents", json!({"stream_id": stream_id, "after": after}))?;
    Ok(crate::agent_chat::ChatTurnReplay {
        stream_id: page.stream_id.clone(),
        status: page.status.clone(),
        events: crate::agent_chat::frames_from(&page),
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
    watcher: tauri::State<'_, Arc<crate::watcher::RunWatcher>>,
    request: LocalProveRequest,
) -> CmdResult<RunCreated> {
    let created: RunCreated = call_typed(&state, "startLocalProve", json!({"body": request}))?;
    // The run is live from this moment — the watcher pushes RunProgressEvent until it ends
    // (cancellation included: the same probe sees CANCELLED and emits the final event).
    watcher.track(created.run_id);
    Ok(created)
}

/// F12's composer: split a change into hunks, prove the accepted subset, return both (ADR-0061).
///
/// `async` because it is not fast. A composer toggle is a sub-second INCREMENTAL re-proof, but the
/// first call of a session proves the whole accepted selection and can take seconds — and a
/// synchronous Tauri command holds the main thread, which is the one that paints. The sidecar
/// already does the work off its own event loop; this keeps the webview responsive while it does.
#[tauri::command(async)]
#[specta::specta]
pub fn compose_change(
    state: tauri::State<'_, Arc<Supervisor>>,
    request: ComposeRequest,
) -> CmdResult<ComposeView> {
    call_typed(&state, "composeChange", json!({"body": request}))
}

#[tauri::command]
#[specta::specta]
pub fn cancel_run(state: tauri::State<'_, Arc<Supervisor>>, run_id: i32) -> CmdResult<CancelAccepted> {
    call_typed(&state, "cancelRun", json!({"run_id": run_id}))
}

/// Every divergence Tempest has RECORDED for one symbol (Phase 20.3e, the risk badge).
///
/// Distinct from `search_divergences`, which is free-text over an FTS index that does not
/// contain `qualname`. The editor asked the text endpoint for a symbol name and got nothing for
/// symbols Tempest had watched diverge, so the badge said "unmeasured" — the failure looking
/// exactly like the honest answer.
#[tauri::command(async)]
#[specta::specta]
pub fn divergences_for_symbol(
    state: tauri::State<'_, Arc<Supervisor>>,
    symbol: String,
    limit: Option<u32>,
) -> CmdResult<SymbolDivergences> {
    let mut params = Map::new();
    params.insert("symbol".into(), Value::String(symbol));
    if let Some(limit) = limit {
        params.insert("limit".into(), json!(limit));
    }
    call_typed(&state, "divergencesForSymbol", Value::Object(params))
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

/// Everything the webview is allowed to know about the stored AI key (L9): whether one
/// exists and its last four characters for recognition — never the key itself.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct AiKeyStatus {
    pub configured: bool,
    pub last4: Option<String>,
}

fn ai_key_status_now() -> CmdResult<AiKeyStatus> {
    // Canonical per-provider account first (C4); the pre-C4 single item answers for an
    // install that has never written since the migration.
    let read_result = crate::keychain::read(crate::keychain::SERVICE, crate::keychain::ANTHROPIC_ACCOUNT)
        .and_then(|found| match found {
            Some(key) => Ok(Some(key)),
            None => crate::keychain::read(crate::keychain::SERVICE, crate::keychain::LEGACY_ACCOUNT),
        });
    match read_result {
        Ok(Some(key)) => Ok(AiKeyStatus {
            configured: true,
            last4: Some(crate::keychain::last4(&key)),
        }),
        Ok(None) => Ok(AiKeyStatus { configured: false, last4: None }),
        Err(message) => Err(SidecarFailure { code: -3, message }),
    }
}

#[tauri::command]
#[specta::specta]
pub fn ai_key_status() -> CmdResult<AiKeyStatus> {
    ai_key_status_now()
}

#[tauri::command]
#[specta::specta]
pub fn set_ai_key(key: String) -> CmdResult<AiKeyStatus> {
    let trimmed = key.trim();
    if !crate::keychain::looks_like_anthropic_key(trimmed) {
        return Err(SidecarFailure {
            code: -3,
            message: "that does not look like an Anthropic API key — keys start with \
                      sk-ant- (create one at console.anthropic.com)"
                .to_string(),
        });
    }
    // Writing migrates: the canonical account gets the key, the legacy item is retired so
    // enumeration can never inject the same variable twice.
    let stored = crate::keychain::store(crate::keychain::SERVICE, crate::keychain::ANTHROPIC_ACCOUNT, trimmed)
        .and_then(|()| crate::keychain::clear(crate::keychain::SERVICE, crate::keychain::LEGACY_ACCOUNT));
    stored
        .map_err(|message| SidecarFailure { code: -3, message })?;
    ai_key_status_now()
}

#[tauri::command]
#[specta::specta]
pub fn clear_ai_key() -> CmdResult<AiKeyStatus> {
    crate::keychain::clear(crate::keychain::SERVICE, crate::keychain::ANTHROPIC_ACCOUNT)
        .and_then(|()| crate::keychain::clear(crate::keychain::SERVICE, crate::keychain::LEGACY_ACCOUNT))
        .map_err(|message| SidecarFailure { code: -3, message })?;
    ai_key_status_now()
}

/// Settings (§3.2). The document, its environment overrides, and the storage facts the
/// screen states — all decided by the engine, never re-derived here.
#[tauri::command]
#[specta::specta]
pub fn get_settings(state: tauri::State<'_, Arc<Supervisor>>) -> CmdResult<SettingsOut> {
    call_typed(&state, "getSettings", json!({}))
}

#[tauri::command]
#[specta::specta]
pub fn update_settings(
    state: tauri::State<'_, Arc<Supervisor>>,
    settings: SettingsIn,
) -> CmdResult<SettingsOut> {
    call_typed(&state, "updateSettings", json!({"body": settings}))
}

/// One live, user-initiated ping on the sanctioned synthesis egress path. The key itself
/// never crosses this boundary — the engine already holds it in its spawn environment (L9).
#[tauri::command]
#[specta::specta]
pub fn test_ai_key(state: tauri::State<'_, Arc<Supervisor>>) -> CmdResult<AiKeyTestResult> {
    call_typed(&state, "testAiKey", json!({}))
}

#[tauri::command]
#[specta::specta]
pub fn sync_push(
    state: tauri::State<'_, Arc<Supervisor>>,
    server_url: String,
) -> CmdResult<SyncReport> {
    call_typed(&state, "syncPush", json!({"body": {"server_url": server_url}}))
}

#[tauri::command]
#[specta::specta]
pub fn export_diagnostics(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> CmdResult<DiagnosticBundle> {
    call_typed(&state, "exportDiagnostics", json!({}))
}

/// Onboarding (Phase 18): one click writes a fresh demo repository and proves it — the run
/// this answers with is ORDINARY, tracked by the watcher like any hand-started prove.
#[tauri::command]
#[specta::specta]
pub fn start_demo_prove(
    state: tauri::State<'_, Arc<Supervisor>>,
    watcher: tauri::State<'_, Arc<crate::watcher::RunWatcher>>,
) -> CmdResult<RunCreated> {
    let created: RunCreated = call_typed(&state, "startDemoProve", json!({}))?;
    watcher.track(created.run_id);
    Ok(created)
}

/// The webview's crash reports (§1.1): forwarded to the engine, which scrubs them through
/// the production redaction context before they touch the obslog. Fire-and-forget from the
/// page's perspective — but typed end to end like everything else.
#[tauri::command]
#[specta::specta]
pub fn report_ui_error(
    state: tauri::State<'_, Arc<Supervisor>>,
    report: UiErrorReport,
) -> CmdResult<UiErrorRecorded> {
    call_typed(&state, "reportUiError", json!({"body": report}))
}

/// Watch mode (ADR-0029 in the app). Whatever run the loop has in flight is handed to the
/// central watcher, so a commit proven by watch pushes RunProgressEvent exactly like a run
/// the user started by hand — one live-progress mechanism, not two.
fn tracked(
    watcher: &crate::watcher::RunWatcher,
    status: WatchStatus,
) -> CmdResult<WatchStatus> {
    if let Some(run_id) = status.active_run_id {
        watcher.track(run_id);
    }
    Ok(status)
}

#[tauri::command]
#[specta::specta]
pub fn get_watch_status(
    state: tauri::State<'_, Arc<Supervisor>>,
    watcher: tauri::State<'_, Arc<crate::watcher::RunWatcher>>,
) -> CmdResult<WatchStatus> {
    tracked(&watcher, call_typed(&state, "getWatchStatus", json!({}))?)
}

#[tauri::command]
#[specta::specta]
pub fn start_watch(
    state: tauri::State<'_, Arc<Supervisor>>,
    watcher: tauri::State<'_, Arc<crate::watcher::RunWatcher>>,
    request: WatchStartRequest,
) -> CmdResult<WatchStatus> {
    tracked(&watcher, call_typed(&state, "startWatch", json!({"body": request}))?)
}

#[tauri::command]
#[specta::specta]
pub fn stop_watch(state: tauri::State<'_, Arc<Supervisor>>) -> CmdResult<WatchStatus> {
    call_typed(&state, "stopWatch", json!({}))
}

/// Reject anything that could escape the data dir. The webview may name a FILE inside
/// `diagnostics/`, never a path: no separators, no `..`, no absolutes, no hidden entries.
fn safe_leaf(name: &str) -> Result<&str, SidecarFailure> {
    let bad = name.is_empty()
        || name == ".."
        || name.starts_with('.')
        || name.contains('/')
        || name.contains('\\')
        || name.contains('\0');
    if bad {
        return Err(SidecarFailure {
            code: -4,
            message: format!("{name:?} is not a plain file name inside the data folder"),
        });
    }
    Ok(name)
}

/// Show the data folder in Finder, or reveal one diagnostic archive inside it. The path is
/// built HERE from the app's own data dir — the webview can only name a leaf (see `safe_leaf`),
/// so no webview string ever becomes a command argument that could point elsewhere.
#[tauri::command]
#[specta::specta]
pub fn reveal_in_data_dir(app: tauri::AppHandle, diagnostic: Option<String>) -> CmdResult<()> {
    use tauri::Manager;
    let data_dir = app.path().app_data_dir().map_err(|err| SidecarFailure {
        code: -4,
        message: format!("the data folder could not be resolved — {err}"),
    })?;
    let (target, reveal) = match diagnostic.as_deref() {
        Some(name) => (data_dir.join("diagnostics").join(safe_leaf(name)?), true),
        None => (data_dir, false),
    };
    open_in_file_manager(&target, reveal)
}

#[cfg(target_os = "macos")]
fn open_in_file_manager(target: &std::path::Path, reveal: bool) -> CmdResult<()> {
    let mut command = std::process::Command::new("/usr/bin/open");
    if reveal {
        command.arg("-R");
    }
    match command.arg(target).status() {
        Ok(status) if status.success() => Ok(()),
        Ok(status) => Err(SidecarFailure {
            code: -4,
            message: format!("Finder could not open {}: exit {status}", target.display()),
        }),
        Err(err) => Err(SidecarFailure {
            code: -4,
            message: format!("Finder could not open {}: {err}", target.display()),
        }),
    }
}

#[cfg(not(target_os = "macos"))]
fn open_in_file_manager(target: &std::path::Path, _reveal: bool) -> CmdResult<()> {
    // Linux/Windows desktop packaging is not a shipped target yet (ADR-0021): say so
    // plainly rather than guessing at a file manager that may not exist.
    Err(SidecarFailure {
        code: -4,
        message: format!(
            "revealing {} in a file manager is only implemented on macOS today",
            target.display()
        ),
    })
}

#[cfg(test)]
mod data_dir_paths {
    //! `safe_leaf` is the whole containment argument for `reveal_in_data_dir`: every string
    //! that could leave `<data dir>/diagnostics/` must be refused before it becomes a path.

    use super::safe_leaf;

    #[test]
    fn a_plain_archive_name_is_accepted() {
        assert_eq!(safe_leaf("tempest-diagnostic-20260817T101500.zip").unwrap(),
                   "tempest-diagnostic-20260817T101500.zip");
    }

    #[test]
    fn every_escape_shape_is_refused() {
        for bad in [
            "",
            "..",
            "../secrets.zip",
            "a/b.zip",
            "a\\b.zip",
            "/etc/passwd",
            ".hidden",
            "nul\0byte.zip",
        ] {
            assert!(safe_leaf(bad).is_err(), "{bad:?} must be refused");
        }
    }
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
            ReasonCode::SynthesisDeclined,
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
            ReasonCode::SynthesisDeclined => "the AI-written adapter failed validation",
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

// ── Local models (ADR-0080) ─────────────────────────────────────────────────────────────────
//
// The catalogue and the downloads live in the ENGINE and cross boundary A like every other
// long operation; these are pass-throughs. Serving is different: it is a supervised child of
// THIS process, so it has no boundary-A hop at all.

/// One download's state. TYPED rather than `serde_json::Value`: specta cannot express an
/// arbitrary JSON value at this boundary (the generator overflows its stack on one — a trap
/// this repository has paid once already), and a typed row is what L36.8 asks for anyway.
///
/// **Byte counts are `f64`, deliberately against this file's `i32`/`u32` habit.** Specta
/// refuses `i64` outright to avoid precision loss, and `u32` caps at 4.29 GB — fine for
/// today's catalogue and a silent overflow the first time someone adds a larger model, which
/// is exactly the kind of limit nobody remembers is there. A JS number IS an `f64` and is
/// exact for integers to 2^53 (nine petabytes), so this is not a widening for convenience: it
/// is the type the value actually has once it arrives.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct ModelDownloadState {
    #[serde(rename = "modelId")]
    pub model_id: String,
    /// `running` | `done` | `failed` | `cancelled` | `absent`.
    ///
    /// `absent` is a model nobody has started. It used to report `failed` with the sentence
    /// "not downloaded", so a caller switching on the state read a fresh install as a fault.
    pub state: String,
    #[serde(rename = "doneBytes")]
    pub done_bytes: f64,
    #[serde(rename = "totalBytes")]
    pub total_bytes: f64,
    /// Empty on success; a sentence a person can act on otherwise (L23).
    pub error: String,
}

/// One catalogue row, with everything the panel needs to decide in a single reply.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct ModelCatalogRow {
    pub id: String,
    pub label: String,
    #[serde(rename = "goodAt")]
    pub good_at: String,
    pub license: String,
    #[serde(rename = "sizeBytes")]
    pub size_bytes: f64,
    #[serde(rename = "ramNote")]
    pub ram_note: String,
    pub installed: bool,
    /// Where the file is (or would be). Serving takes a PATH, and the panel should not have
    /// to reconstruct one — a UI that recomputes a filesystem layout is a second place for
    /// that layout to be wrong.
    #[serde(rename = "installedPath")]
    pub installed_path: String,
    #[serde(rename = "freeBytes")]
    pub free_bytes: f64,
    #[serde(rename = "fitsOnDisk")]
    pub fits_on_disk: bool,
    /// Resume progress. A partial download used to be invisible to the panel: gigabytes with
    /// no UI that could name them, let alone free them.
    #[serde(rename = "partialBytes")]
    pub partial_bytes: f64,
    /// A file at the installed path that is NOT this row's model — a truncated copy, or a
    /// model whose row was refreshed after an upstream re-upload. Non-zero is a state the
    /// panel has to be able to show and act on, because `installed` no longer covers it.
    #[serde(rename = "strayBytes")]
    pub stray_bytes: f64,
    pub download: Option<ModelDownloadState>,
}

/// The catalogue, with `installed`, `freeBytes` and `fitsOnDisk` already resolved — the size
/// and the room for it on screen before the spend (L21).
#[tauri::command]
#[specta::specta]
pub fn list_model_catalog(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> CmdResult<Vec<ModelCatalogRow>> {
    call_typed(&state, "listModelCatalog", json!({}))
}

#[tauri::command]
#[specta::specta]
pub fn start_model_download(
    state: tauri::State<'_, Arc<Supervisor>>,
    model_id: String,
) -> CmdResult<ModelDownloadState> {
    call_typed(&state, "startModelDownload", json!({ "model_id": model_id }))
}

#[tauri::command]
#[specta::specta]
pub fn cancel_model_download(
    state: tauri::State<'_, Arc<Supervisor>>,
    model_id: String,
) -> CmdResult<ModelDownloadState> {
    call_typed(&state, "cancelModelDownload", json!({ "model_id": model_id }))
}

/// `removed` is false when there was nothing there — a delete that reports success for a file
/// it never saw teaches a user their disk is emptier than it is.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct ModelRemoved {
    #[serde(rename = "modelId")]
    pub model_id: String,
    pub removed: bool,
}

#[tauri::command]
#[specta::specta]
pub fn remove_model(
    state: tauri::State<'_, Arc<Supervisor>>,
    model_id: String,
) -> CmdResult<ModelRemoved> {
    call_typed(&state, "removeModel", json!({ "model_id": model_id }))
}

/// Serving state: whether a loopback model server is up, and for which file.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, specta::Type)]
pub struct ModelServerStatus {
    pub running: bool,
    pub model_path: Option<String>,
    /// The runner Tempest would use, or `None` when there is none to find. Resolved on every
    /// status read so the panel can say "install this" BEFORE the user clicks start and gets
    /// a refusal (L23: the reason arrives with the affordance, not after it).
    pub runner: Option<String>,
    /// Why there is no runner, when there is none. Empty otherwise.
    pub runner_problem: String,
}

#[tauri::command]
#[specta::specta]
pub fn model_server_status() -> CmdResult<ModelServerStatus> {
    let (running, model_path) = crate::modelserver::status();
    let (runner, runner_problem) = match crate::modelserver::resolve_runner() {
        Ok(path) => (Some(path), String::new()),
        Err(err) => (None, err.to_string()),
    };
    Ok(ModelServerStatus { running, model_path, runner, runner_problem })
}

/// The model file must be one Tempest downloaded — under `<data>/models/` and nowhere else.
///
/// `start_model_server` is reachable from the webview, and neither of its strings was checked:
/// any script that reaches `__TAURI_INVOKE` could name an arbitrary executable and an
/// arbitrary file to feed it. The executable half is gone (`resolve_runner` takes no argument
/// now); this is the file half. `<data>/models` is exactly the engine's `model_root()` — the
/// host passes this same directory as `--data-dir` and `server.py` exports it as
/// `TEMPEST_DATA_DIR`, which is what that function reads.
fn model_path_inside_the_models_dir(
    data_dir: &std::path::Path,
    model_path: &str,
) -> Result<std::path::PathBuf, SidecarFailure> {
    let models = data_dir.join("models");
    // Canonicalised on both sides: `..` in the argument, and a symlink anywhere along it,
    // are the two ways a containment check gets talked out of its own answer.
    let root = models.canonicalize().map_err(|err| SidecarFailure {
        code: -3,
        message: format!(
            "no models directory yet ({err}) — download a model before serving one"
        ),
    })?;
    let candidate = std::path::Path::new(model_path).canonicalize().map_err(|err| SidecarFailure {
        code: -3,
        message: format!("{model_path} is not on disk ({err}) — download the model first"),
    })?;
    if !candidate.starts_with(&root) {
        return Err(SidecarFailure {
            code: -3,
            message: format!(
                "{model_path} is not one of Tempest's downloaded models. Only files under \
                 {} can be served — a model server is a process that reads the file it is \
                 given, so the file it is given is not the webview's to choose.",
                root.display()
            ),
        });
    }
    Ok(candidate)
}

/// Start serving a downloaded model on loopback. Off until asked — nothing starts at launch,
/// which is what keeps the airplane-mode claim honest.
/// `async` + `spawn_blocking`, and both halves matter. `start` waits up to 120 s for a
/// multi-gigabyte model to load, and a plain `#[tauri::command]` runs on the IPC thread — the
/// whole window, including the Stop button, would be frozen for that entire time.
///
/// `#[tauri::command(async)]` on a SYNCHRONOUS body would not fix it either: this repository
/// has already paid that one. It spawns the future on tokio's multi-thread runtime and the
/// sync body then blocks a WORKER, where it can starve every other async command — including
/// the Settings screen, which is the only way to undo whatever caused it. So the blocking work
/// goes to `spawn_blocking`, which is the pool that exists for exactly this.
#[tauri::command]
#[specta::specta]
pub async fn start_model_server(
    data_dir: tauri::State<'_, DataDir>,
    model_path: String,
) -> CmdResult<ModelServerStatus> {
    let contained = model_path_inside_the_models_dir(&data_dir.0, &model_path)?;
    tauri::async_runtime::spawn_blocking(move || start_model_server_blocking(contained))
        .await
        .unwrap_or_else(|err| {
            Err(SidecarFailure { code: -3, message: format!("the model server task failed: {err}") })
        })
}

fn start_model_server_blocking(model_path: std::path::PathBuf) -> CmdResult<ModelServerStatus> {
    match crate::modelserver::start(&model_path.to_string_lossy()) {
        Ok(runner) => {
            let (running, path) = crate::modelserver::status();
            Ok(ModelServerStatus {
                running,
                model_path: path,
                runner: Some(runner),
                runner_problem: String::new(),
            })
        }
        // A refusal is a VALUE with a reason a person can act on, not a swallowed error and
        // not a generic failure toast (L15.3, L23).
        Err(err) => Err(SidecarFailure { code: -3, message: err.to_string() }),
    }
}

#[tauri::command]
#[specta::specta]
pub fn stop_model_server() -> CmdResult<ModelServerStatus> {
    crate::modelserver::stop();
    let (running, model_path) = crate::modelserver::status();
    Ok(ModelServerStatus { running, model_path, runner: None, runner_problem: String::new() })
}
