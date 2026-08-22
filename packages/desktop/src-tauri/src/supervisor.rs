//! Sidecar supervision (Phase 9 §3, L11; extended for boundary E in PLAN-V3 C2): the Rust
//! host OWNS every sidecar — it starts each in its own process group, health-checks it,
//! restarts it with capped backoff when it dies, and sweeps the entire group on shutdown so
//! orphans are impossible (L34). Calls travel as JSON-RPC 2.0 `Content-Length` frames over
//! the child's transport: stdin/stdout for the engine (boundary A), a Unix domain socket the
//! child binds for the platform sidecar (boundary E). **No TCP socket exists in either mode**
//! — a listening port fails enterprise security review and the threat model says so.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::framing::{read_frame, write_frame, FrameError};

pub const DEFAULT_CALL_TIMEOUT: Duration = Duration::from_secs(30);
const SPAWN_HEALTH_DEADLINE: Duration = Duration::from_secs(20);
const MONITOR_POLL: Duration = Duration::from_millis(300);
const RESTART_BACKOFF_START: Duration = Duration::from_millis(500);
const RESTART_BACKOFF_MAX: Duration = Duration::from_secs(8);
const HEALTHY_RESET: Duration = Duration::from_secs(60);
const SHUTDOWN_RPC_GRACE: Duration = Duration::from_millis(1000);
const SHUTDOWN_TERM_GRACE: Duration = Duration::from_secs(2);
/// How long a Unix-socket child gets to bind its socket after spawn before the connect gives
/// up. Generous: a cold Node process on a loaded machine parses its module graph first.
const UNIX_CONNECT_DEADLINE: Duration = Duration::from_secs(10);

/// How a child's JSON-RPC frames travel. The supervision story — process group, health,
/// backoff restart, guaranteed sweep — is identical in both; only the byte path differs.
#[derive(Clone)]
pub enum Transport {
    /// Frames over the child's stdin/stdout (boundary A — the engine sidecar).
    Stdio,
    /// Frames over a Unix domain socket the CHILD binds at this path (boundary E — the
    /// platform sidecar). The path reaches the child via `TEMPEST_PLATFORM_SOCKET`; the host
    /// connects after spawn. The child's stdin stays piped and open as its parent-death
    /// signal: SIGKILL of the host closes it, and the child exits on that EOF.
    Unix { socket: PathBuf },
}

#[derive(Debug)]
pub enum RpcError {
    /// No live sidecar right now (starting, restarting, or shut down).
    Unavailable(String),
    /// The sidecar did not answer within the deadline.
    Timeout,
    /// The byte stream broke; the supervisor will restart the child.
    Transport(String),
    /// The sidecar answered with a JSON-RPC error object.
    Peer { code: i64, message: String, data: Value },
}

impl std::fmt::Display for RpcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RpcError::Unavailable(why) => write!(f, "sidecar unavailable: {why}"),
            RpcError::Timeout => write!(f, "sidecar call timed out"),
            RpcError::Transport(why) => write!(f, "sidecar transport failed: {why}"),
            RpcError::Peer { code, message, .. } => write!(f, "sidecar error {code}: {message}"),
        }
    }
}

impl std::error::Error for RpcError {}

/// Extra environment computed fresh at EVERY spawn (initial, crash restart): a key saved in
/// Settings reaches the next engine process without an app relaunch.
pub type EnvProvider = Arc<dyn Fn() -> Vec<(String, String)> + Send + Sync>;

#[derive(Clone)]
pub struct SpawnConfig {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub env_provider: Option<EnvProvider>,
    pub transport: Transport,
    /// Method namespace for the lifecycle RPCs this supervisor issues itself: `<prefix>.ping`
    /// for health, `<prefix>.shutdown` for graceful stop. `"rpc"` for the engine (boundary A),
    /// `"platform"` for the Node sidecar (boundary E) — the schema owns each list.
    pub rpc_prefix: &'static str,
}

/// The write half of a child's frame stream.
enum Wire {
    Stdio(ChildStdin),
    #[cfg(unix)]
    Unix(std::os::unix::net::UnixStream),
}

impl Wire {
    fn write_frame(&mut self, payload: &[u8]) -> Result<(), FrameError> {
        match self {
            Wire::Stdio(stdin) => write_frame(stdin, payload),
            #[cfg(unix)]
            Wire::Unix(stream) => write_frame(stream, payload),
        }
    }
}

struct Live {
    child: Child,
    wire: Wire,
    /// For Unix-transport children: the piped stdin held open for the child's lifetime. Its
    /// closure — including by SIGKILL of this host — is the child's signal to exit itself.
    _parent_pipe: Option<ChildStdin>,
    frames: Receiver<Result<Vec<u8>, String>>,
    pgid: i32,
    next_id: u64,
}

/// Callback invoked on lifecycle transitions ("healthy", "restarting", "stopped") so the shell
/// can surface sidecar state to the UI without the supervisor depending on tauri types.
pub type StateListener = Arc<dyn Fn(&str) + Send + Sync>;

pub struct Supervisor {
    config: SpawnConfig,
    live: Mutex<Option<Live>>,
    shutting_down: AtomicBool,
    generation: AtomicU64,
    listener: Mutex<Option<StateListener>>,
}

impl Supervisor {
    pub fn new(config: SpawnConfig) -> Arc<Self> {
        Arc::new(Self {
            config,
            live: Mutex::new(None),
            shutting_down: AtomicBool::new(false),
            generation: AtomicU64::new(0),
            listener: Mutex::new(None),
        })
    }

    pub fn set_listener(&self, listener: StateListener) {
        *self.listener.lock().expect("listener lock") = Some(listener);
    }

    fn notify(&self, state: &str) {
        if let Some(listener) = self.listener.lock().expect("listener lock").as_ref() {
            listener(state);
        }
    }

    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }

    /// Spawn the sidecar, wait until it answers `rpc.ping`, and start the monitor thread that
    /// restarts it (with capped backoff) whenever it dies outside a shutdown.
    pub fn start(self: &Arc<Self>) -> Result<(), RpcError> {
        {
            let mut slot = self.live.lock().expect("live lock");
            if slot.is_none() {
                *slot = Some(spawn_child(&self.config)?);
                self.generation.fetch_add(1, Ordering::SeqCst);
            }
        }
        self.wait_healthy(SPAWN_HEALTH_DEADLINE)?;
        self.notify("healthy");

        let supervisor = Arc::clone(self);
        std::thread::Builder::new()
            .name("sidecar-monitor".into())
            .spawn(move || supervisor.monitor_loop())
            .map_err(|err| RpcError::Unavailable(format!("monitor thread failed: {err}")))?;
        Ok(())
    }

    fn monitor_loop(self: Arc<Self>) {
        let mut backoff = RESTART_BACKOFF_START;
        let mut last_spawn = Instant::now();
        loop {
            std::thread::sleep(MONITOR_POLL);
            if self.shutting_down.load(Ordering::SeqCst) {
                return;
            }
            let died = {
                let mut slot = self.live.lock().expect("live lock");
                match slot.as_mut() {
                    None => true,
                    Some(live) => match live.child.try_wait() {
                        Ok(Some(_status)) => {
                            let dead = slot.take().expect("checked above");
                            kill_group(dead.pgid); // sweep any runner children it left behind
                            true
                        }
                        Ok(None) => false,
                        Err(_) => false,
                    },
                }
            };
            if !died {
                if last_spawn.elapsed() > HEALTHY_RESET {
                    backoff = RESTART_BACKOFF_START;
                }
                continue;
            }
            if self.shutting_down.load(Ordering::SeqCst) {
                return;
            }
            self.notify("restarting");
            eprintln!("[tempest] sidecar died — restarting in {backoff:?}");
            std::thread::sleep(backoff);
            backoff = (backoff * 2).min(RESTART_BACKOFF_MAX);
            last_spawn = Instant::now();
            match spawn_child(&self.config) {
                Ok(live) => {
                    *self.live.lock().expect("live lock") = Some(live);
                    self.generation.fetch_add(1, Ordering::SeqCst);
                    // shutdown() may have run between our shutting_down check and the store
                    // above; its take() saw None then, so the fresh child is OURS to sweep —
                    // without this re-check it would outlive the app (the review's race #6).
                    if self.shutting_down.load(Ordering::SeqCst) {
                        if let Some(mut fresh) = self.live.lock().expect("live lock").take() {
                            kill_group(fresh.pgid);
                            let _ = fresh.child.wait();
                        }
                        if let Transport::Unix { socket } = &self.config.transport {
                            let _ = std::fs::remove_file(socket);
                        }
                        return;
                    }
                    if self.wait_healthy(SPAWN_HEALTH_DEADLINE).is_ok() {
                        self.notify("healthy");
                    }
                }
                Err(err) => eprintln!("[tempest] sidecar respawn failed: {err}"),
            }
        }
    }

    fn wait_healthy(&self, deadline: Duration) -> Result<(), RpcError> {
        let ping = format!("{}.ping", self.config.rpc_prefix);
        let until = Instant::now() + deadline;
        loop {
            match self.call(&ping, json!({}), Duration::from_secs(2)) {
                Ok(_) => return Ok(()),
                Err(_) if Instant::now() < until => std::thread::sleep(Duration::from_millis(100)),
                Err(err) => return Err(err),
            }
        }
    }

    /// One JSON-RPC call. Requests are serialized (one in flight); stale late responses from a
    /// timed-out predecessor are skipped by id, so a timeout never poisons the stream.
    pub fn call(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, RpcError> {
        let mut slot = self.live.lock().expect("live lock");
        let live = slot
            .as_mut()
            .ok_or_else(|| RpcError::Unavailable("sidecar is restarting".into()))?;
        live.next_id += 1;
        let id = live.next_id;
        let request = json!({"jsonrpc": "2.0", "id": id, "method": method, "params": params});
        let payload = serde_json::to_vec(&request)
            .map_err(|err| RpcError::Transport(format!("encode: {err}")))?;
        if let Err(err) = live.wire.write_frame(&payload) {
            let dead = slot.take().expect("held above");
            kill_group(dead.pgid);
            return Err(RpcError::Transport(format!("write: {err}")));
        }
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(RpcError::Timeout);
            }
            match live.frames.recv_timeout(remaining) {
                Ok(Ok(frame)) => {
                    let response: Value = serde_json::from_slice(&frame)
                        .map_err(|err| RpcError::Transport(format!("decode: {err}")))?;
                    if response.get("id").and_then(Value::as_u64) != Some(id) {
                        continue; // stale response from a timed-out earlier call
                    }
                    if let Some(error) = response.get("error") {
                        return Err(RpcError::Peer {
                            code: error.get("code").and_then(Value::as_i64).unwrap_or(-1),
                            message: error
                                .get("message")
                                .and_then(Value::as_str)
                                .unwrap_or("unknown sidecar error")
                                .to_string(),
                            data: error.get("data").cloned().unwrap_or(Value::Null),
                        });
                    }
                    return Ok(response.get("result").cloned().unwrap_or(Value::Null));
                }
                Ok(Err(why)) => {
                    let dead = slot.take().expect("held above");
                    kill_group(dead.pgid);
                    return Err(RpcError::Transport(why));
                }
                Err(RecvTimeoutError::Timeout) => return Err(RpcError::Timeout),
                Err(RecvTimeoutError::Disconnected) => {
                    let dead = slot.take().expect("held above");
                    kill_group(dead.pgid);
                    return Err(RpcError::Transport("reader thread ended".into()));
                }
            }
        }
    }

    /// Graceful stop, then guaranteed group sweep: `<prefix>.shutdown` → SIGTERM group →
    /// SIGKILL group. After this returns, no process of the sidecar's group exists, and a
    /// Unix-transport child's socket file is gone.
    pub fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::SeqCst);
        let taken = self.live.lock().expect("live lock").take();
        let Some(mut live) = taken else {
            // Even with no live child (mid-restart), a Unix child's socket file may exist —
            // remove it on every shutdown path, not only the graceful one.
            if let Transport::Unix { socket } = &self.config.transport {
                let _ = std::fs::remove_file(socket);
            }
            self.notify("stopped");
            return;
        };
        live.next_id += 1;
        let method = format!("{}.shutdown", self.config.rpc_prefix);
        let request =
            json!({"jsonrpc": "2.0", "id": live.next_id, "method": method, "params": {}});
        if let Ok(payload) = serde_json::to_vec(&request) {
            if live.wire.write_frame(&payload).is_ok() {
                let deadline = Instant::now() + SHUTDOWN_RPC_GRACE;
                while Instant::now() < deadline {
                    match live.child.try_wait() {
                        Ok(Some(_)) => break,
                        _ => std::thread::sleep(Duration::from_millis(50)),
                    }
                }
            }
        }
        terminate_group(live.pgid);
        let deadline = Instant::now() + SHUTDOWN_TERM_GRACE;
        while Instant::now() < deadline {
            if let Ok(Some(_)) = live.child.try_wait() {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        kill_group(live.pgid);
        let _ = live.child.wait(); // reap — no zombie rows in the process table
        if let Transport::Unix { socket } = &self.config.transport {
            let _ = std::fs::remove_file(socket);
        }
        self.notify("stopped");
    }
}

fn spawn_child(config: &SpawnConfig) -> Result<Live, RpcError> {
    let mut command = Command::new(&config.program);
    command
        .args(&config.args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(provider) = &config.env_provider {
        command.envs(provider());
    }
    if let Transport::Unix { socket } = &config.transport {
        // A stale file at OUR configured path would make the child's bind fail. The path is
        // namespaced to this host process (platform::socket_path embeds our pid), so a file
        // here can only be a leftover from a dead process — removal cannot race a sibling
        // instance's live socket. Directory creation and permissions are the CALLER's job
        // (platform::prepare_socket): a generic chmod of `socket.parent()` here would chmod
        // whatever the caller passed — on Linux, potentially the shared /tmp itself.
        let _ = std::fs::remove_file(socket);
        command.env("TEMPEST_PLATFORM_SOCKET", socket);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // Own process group: the sidecar and every runner it spawns share one pgid we can sweep.
        command.process_group(0);
    }
    let mut child = command
        .spawn()
        .map_err(|err| RpcError::Unavailable(format!("spawn {:?}: {err}", config.program)))?;
    let pgid = child.id() as i32;
    let stdin = child.stdin.take().expect("stdin piped");
    let stdout = child.stdout.take().expect("stdout piped");
    let stderr = child.stderr.take().expect("stderr piped");
    let tag: &'static str = match &config.transport {
        Transport::Stdio => "tempest-server",
        Transport::Unix { .. } => "tempest-platform",
    };
    std::thread::Builder::new()
        .name("sidecar-stderr".into())
        .spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("[{tag}] {line}");
            }
        })
        .map_err(|err| RpcError::Unavailable(format!("stderr thread failed: {err}")))?;

    let (tx, rx) = mpsc::channel::<Result<Vec<u8>, String>>();
    match &config.transport {
        Transport::Stdio => {
            std::thread::Builder::new()
                .name("sidecar-reader".into())
                .spawn(move || {
                    let mut reader = BufReader::new(stdout);
                    loop {
                        match read_frame(&mut reader) {
                            Ok(frame) => {
                                if tx.send(Ok(frame)).is_err() {
                                    return;
                                }
                            }
                            Err(FrameError::Eof) => return,
                            Err(err) => {
                                let _ = tx.send(Err(err.to_string()));
                                return;
                            }
                        }
                    }
                })
                .map_err(|err| RpcError::Unavailable(format!("reader thread failed: {err}")))?;
            Ok(Live {
                child,
                wire: Wire::Stdio(stdin),
                _parent_pipe: None,
                frames: rx,
                pgid,
                next_id: 0,
            })
        }
        #[cfg(unix)]
        Transport::Unix { socket } => {
            // A Unix child logs on stdout/stderr rather than speaking frames there; drain
            // stdout so a chatty child can never block on a full pipe.
            std::thread::Builder::new()
                .name("sidecar-stdout".into())
                .spawn(move || {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        eprintln!("[{tag}] {line}");
                    }
                })
                .map_err(|err| RpcError::Unavailable(format!("stdout thread failed: {err}")))?;

            // The child binds; we connect. Poll until it is listening or provably dead.
            let deadline = Instant::now() + UNIX_CONNECT_DEADLINE;
            let stream = loop {
                match std::os::unix::net::UnixStream::connect(socket) {
                    Ok(stream) => break stream,
                    Err(err) => {
                        if let Ok(Some(status)) = child.try_wait() {
                            kill_group(pgid);
                            return Err(RpcError::Unavailable(format!(
                                "platform sidecar exited before binding its socket ({status})"
                            )));
                        }
                        if Instant::now() >= deadline {
                            kill_group(pgid);
                            let _ = child.wait();
                            return Err(RpcError::Unavailable(format!(
                                "platform sidecar never bound {socket:?} within \
                                 {UNIX_CONNECT_DEADLINE:?}: {err}"
                            )));
                        }
                        std::thread::sleep(Duration::from_millis(50));
                    }
                }
            };
            let read_half = match stream.try_clone() {
                Ok(half) => half,
                Err(err) => {
                    // Same discipline as every other failing spawn path: no early return may
                    // leave the just-spawned child unswept or unreaped (L34).
                    kill_group(pgid);
                    let _ = child.wait();
                    return Err(RpcError::Unavailable(format!("socket clone failed: {err}")));
                }
            };
            std::thread::Builder::new()
                .name("sidecar-reader".into())
                .spawn(move || {
                    let mut reader = BufReader::new(read_half);
                    loop {
                        match read_frame(&mut reader) {
                            Ok(frame) => {
                                if tx.send(Ok(frame)).is_err() {
                                    return;
                                }
                            }
                            Err(FrameError::Eof) => return,
                            Err(err) => {
                                let _ = tx.send(Err(err.to_string()));
                                return;
                            }
                        }
                    }
                })
                .map_err(|err| RpcError::Unavailable(format!("reader thread failed: {err}")))?;
            Ok(Live {
                child,
                wire: Wire::Unix(stream),
                _parent_pipe: Some(stdin),
                frames: rx,
                pgid,
                next_id: 0,
            })
        }
        #[cfg(not(unix))]
        Transport::Unix { .. } => {
            kill_group(pgid);
            let _ = child.wait();
            Err(RpcError::Unavailable(
                "unix-socket transport is not supported on this platform (named-pipe support \
                 arrives with a Windows desktop)"
                    .into(),
            ))
        }
    }
}

#[cfg(unix)]
pub(crate) fn terminate_group(pgid: i32) {
    unsafe {
        libc::killpg(pgid, libc::SIGTERM);
    }
}

#[cfg(unix)]
pub(crate) fn kill_group(pgid: i32) {
    unsafe {
        libc::killpg(pgid, libc::SIGKILL);
    }
}

#[cfg(not(unix))]
pub(crate) fn terminate_group(_pgid: i32) {}

#[cfg(not(unix))]
pub(crate) fn kill_group(_pgid: i32) {}

/// True while any process of the group is alive (used by tests to prove the sweep worked).
#[cfg(unix)]
pub fn group_alive(pgid: i32) -> bool {
    unsafe { libc::killpg(pgid, 0) == 0 }
}
