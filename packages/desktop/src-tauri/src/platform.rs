//! Boundary E, host side (PLAN-V3 C2): the typed client for the supervised Node platform
//! sidecar, and the wiring that spawns it.
//!
//! Validation posture, stated exactly: outbound calls are CONSTRUCTED from the typify'd
//! contract types (a request that violates `platform.schema.json` cannot be expressed);
//! inbound results are PARSED into those same types, which carry
//! `deny_unknown_fields` from the schema's `additionalProperties: false` — an off-contract
//! reply fails here, in production, with a diagnostic id (L15.3). The JSON-RPC envelope
//! itself is enforced by `supervisor::call` on this side and by `boundary-validate.mjs` —
//! both directions — on the Node side, where types are advisory and validation is the only
//! contract that exists at runtime.
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

/// The socket lives in the per-user temp dir (private on macOS by construction) rather than
/// the app data dir: `sun_path` is capped at ~104 bytes and a data-dir path under
/// `~/Library/Application Support/…` can exceed it. One app instance, one fixed name; a stale
/// file from a SIGKILL'd run is removed at spawn.
pub fn socket_path() -> PathBuf {
    std::env::temp_dir().join("tempest-platform.sock")
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

fn typed_call<T: serde::de::DeserializeOwned>(
    supervisor: &Supervisor,
    method: &str,
) -> Result<T, PlatformError> {
    let raw = supervisor
        .call(method, serde_json::json!({}), Duration::from_secs(10))
        .map_err(|err: RpcError| contract_error(&format!("{method} failed"), err))?;
    serde_json::from_value::<T>(raw)
        .map_err(|err| contract_error(&format!("{method} reply violates the contract"), err))
}

pub fn ping(supervisor: &Supervisor) -> Result<contract::PingResult, PlatformError> {
    typed_call(supervisor, "platform.ping")
}

pub fn describe(supervisor: &Supervisor) -> Result<contract::DescribeResult, PlatformError> {
    typed_call(supervisor, "platform.describe")
}
