//! Boundary E, host side (PLAN-V3 C2): the typed client for the supervised Node platform
//! sidecar, and the wiring that spawns it.
//!
//! Validation posture, stated exactly: outbound method names come from the generated
//! `PlatformMethod` enum (a typo'd or schema-removed method cannot compile here — the
//! ENVELOPE is assembled by `supervisor::call`, whose shape is fixed code); inbound results
//! are PARSED into the typify'd contract types, which carry `deny_unknown_fields` from the
//! schema's `additionalProperties: false` — an off-contract reply fails here, in production,
//! with a diagnostic id (L15.3). Independently, the Node side validates BOTH directions in
//! production (`boundary-validate.mjs`: envelope + per-method result shapes) — there, types
//! are advisory and runtime validation is the only contract that exists.
//!
//! The sidecar is OPT-IN at C2 (`TEMPEST_PLATFORM_SIDECAR=1`): nothing user-facing consumes
//! it before C3 mounts the client, and spawning a Node process the product does not yet need
//! would be idle RAM spent on ceremony. The orphan gate exercises it explicitly.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use crate::generated::platform as contract;
use crate::supervisor::{RpcError, SpawnConfig, Supervisor, Transport};

/// Distinguishes the platform sidecar's supervisor in tauri managed state — the engine's is
/// managed as a bare `Arc<Supervisor>` and state lookup is by type.
pub struct Platform(pub Arc<Supervisor>);

#[derive(Debug)]
pub struct PlatformError {
    pub diagnostic_id: String,
    pub message: String,
}

impl std::fmt::Display for PlatformError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} [diagnostic {}]", self.message, self.diagnostic_id)
    }
}

impl std::error::Error for PlatformError {}

static DIAGNOSTIC_COUNTER: AtomicU64 = AtomicU64::new(0);

fn diagnostic_id() -> String {
    // Unique enough to grep a log by: pid + a monotone counter. No RNG dependency.
    format!(
        "E-{:x}-{:x}",
        std::process::id(),
        DIAGNOSTIC_COUNTER.fetch_add(1, Ordering::Relaxed)
    )
}

fn contract_error(kind: &str, why: impl std::fmt::Display) -> PlatformError {
    let id = diagnostic_id();
    eprintln!("[tempest-platform-client] {kind} [{id}]: {why}");
    PlatformError { diagnostic_id: id, message: format!("{kind}: {why}") }
}

/// The socket lives under a **private, per-user subdirectory of the temp dir** — never in the
/// temp dir itself: on Linux `temp_dir()` is the SHARED, sticky `/tmp`, and a socket there
/// (or a chmod of `/tmp`!) would be an exposure; on macOS the per-user `$TMPDIR` is already
/// 0700 and the subdir is belt-and-braces. The temp root rather than the app data dir because
/// `sun_path` is capped at ~104 bytes and a `~/Library/Application Support/…` path can
/// exceed it. The name carries OUR pid so two app instances can never unlink or bind each
/// other's live socket; `prepare_socket()` sweeps siblings whose embedded pid is dead, so a
/// SIGKILL'd run's file cannot accumulate.
/// Locate a Node runtime for the platform sidecar. `TEMPEST_PLATFORM_NODE` wins and, like
/// the dist override, an explicit-but-broken value resolves to None rather than silently
/// hunting elsewhere. Then PATH — which for a Finder-launched app is the login shell's
/// minimal `/usr/bin:/bin:…`, hence the final probe of the standard install prefixes.
/// Bundling a runtime (deleting this lookup) is a tracked PLAN-V3 item, not a comment.
pub fn resolve_node() -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var("TEMPEST_PLATFORM_NODE") {
        if !explicit.is_empty() {
            let path = PathBuf::from(explicit);
            return path.is_file().then_some(path);
        }
    }
    let binary = if cfg!(windows) { "node.exe" } else { "node" };
    if let Some(path) = std::env::var_os("PATH") {
        for dir in std::env::split_paths(&path) {
            let candidate = dir.join(binary);
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    ["/usr/local/bin/node", "/opt/homebrew/bin/node", "/usr/bin/node"]
        .into_iter()
        .map(PathBuf::from)
        .find(|p| p.is_file())
}

pub fn socket_dir() -> PathBuf {
    #[cfg(unix)]
    let owner = unsafe { libc::getuid() };
    #[cfg(not(unix))]
    let owner = 0;
    std::env::temp_dir().join(format!("tempest-platform-{owner}"))
}

pub fn socket_path() -> PathBuf {
    socket_dir().join(format!("platform-{}.sock", std::process::id()))
}

/// Create the private socket directory (0700) and sweep stale sockets left by dead instances.
/// Called by the host before spawning; the supervisor deliberately does NOT manage
/// directories — a generic chmod of a socket's parent chmods whatever the caller passed,
/// which is exactly the /tmp foot-gun this function exists to prevent.
pub fn prepare_socket() -> std::io::Result<PathBuf> {
    let dir = socket_dir();
    std::fs::create_dir_all(&dir)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
    }
    if let Ok(entries) = std::fs::read_dir(&dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let Some(pid) = name
                .to_str()
                .and_then(|n| n.strip_prefix("platform-"))
                .and_then(|n| n.strip_suffix(".sock"))
                .and_then(|n| n.parse::<i32>().ok())
            else {
                continue;
            };
            #[cfg(unix)]
            let owner_dead = unsafe { libc::kill(pid, 0) } != 0;
            #[cfg(not(unix))]
            let owner_dead = false;
            if pid != std::process::id() as i32 && owner_dead {
                let _ = std::fs::remove_file(entry.path());
            }
        }
    }
    Ok(socket_path())
}

pub fn spawn_config(node: PathBuf, boundary_script: PathBuf, socket: PathBuf) -> SpawnConfig {
    SpawnConfig {
        program: node,
        args: vec![boundary_script.to_string_lossy().into_owned()],
        env_provider: None,
        transport: Transport::Unix { socket },
        rpc_prefix: "platform",
    }
}

/// Shorter than `DEFAULT_CALL_TIMEOUT` (30 s) on purpose: every C2 lifecycle call is a
/// constant-time reply from an idle process — 10 s of silence already means "broken".
const LIFECYCLE_CALL_TIMEOUT: Duration = Duration::from_secs(10);

fn typed_call<T: serde::de::DeserializeOwned>(
    supervisor: &Supervisor,
    method: contract::PlatformMethod,
) -> Result<T, PlatformError> {
    let raw = supervisor
        .call(&method.to_string(), serde_json::json!({}), LIFECYCLE_CALL_TIMEOUT)
        .map_err(|err: RpcError| contract_error(&format!("{method} failed"), err))?;
    serde_json::from_value::<T>(raw)
        .map_err(|err| contract_error(&format!("{method} reply violates the contract"), err))
}

pub fn ping(supervisor: &Supervisor) -> Result<contract::PingResult, PlatformError> {
    typed_call(supervisor, contract::PlatformMethod::PlatformPing)
}

pub fn describe(supervisor: &Supervisor) -> Result<contract::DescribeResult, PlatformError> {
    typed_call(supervisor, contract::PlatformMethod::PlatformDescribe)
}
