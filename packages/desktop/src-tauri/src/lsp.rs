//! Phase 20.2 — the LSP multiplexer. Language servers live HERE, never in the webview.
//!
//! A language server is a long-lived child process that reads and writes JSON-RPC over stdio in
//! the same `Content-Length` framing this repo already speaks to its own sidecar (`framing`), so
//! there is one codec rather than two. The multiplexer owns those processes: it starts one per
//! (language, project root) on demand, correlates responses to requests by id, and kills every
//! one of them on shutdown.
//!
//! Why the webview never holds a handle: a language server is an arbitrary binary reading the
//! user's source. Handing the webview a pipe to it would make the renderer — the one place in
//! this product where hostile model output is rendered — the thing deciding what gets sent to
//! that binary. The webview names a language and a file; the host decides everything else.
//!
//! ## What the Phase 20 review changed, and why each was a real defect
//!
//! The first version of this module was reviewed by eleven independent lenses and two of its
//! claims were false in ways a probe could show in under a minute (trap 45 — a guard's ARGUMENT
//! is not a proof of the guard):
//!
//! * **`Drop` does not run at app exit.** `tao`'s macOS event loop ends in `process::exit`, which
//!   runs no destructors, so "managed state, therefore `Drop`, therefore no orphans" was three
//!   true statements and a false conclusion. `shutdown_all` is now called explicitly from the
//!   `RunEvent::Exit` handler, beside the sidecar sweep that was already there.
//! * **Killing the direct child does not kill the server.** A probe against a two-line shim
//!   printed `GRANDCHILD alive=true` after `child.kill()`. Real servers are shims:
//!   `npx typescript-language-server` execs a grandchild, `pyright-langserver` forks node. Every
//!   server now runs in its OWN PROCESS GROUP and is swept with `killpg`, exactly as
//!   `supervisor.rs` has always swept the sidecar — the same two functions, not a second copy.
//! * **...and that is also why `kill` could hang forever.** A pipe reports EOF when the LAST
//!   write end closes. With a grandchild holding it, `read_frame` never returned, so the
//!   `join()` at the end of `kill` blocked — on the Tauri command thread, holding the
//!   multiplexer's mutex, permanently. Sweeping the group closes every write end, which is what
//!   makes the join terminate rather than what makes it look like it should.
//! * **An id is not a correlation.** JSON-RPC gives the client and the server independent id
//!   counters that both start near 1, so a server-initiated REQUEST routinely carries the number
//!   we are waiting on. Matching on the id alone returned that request as our answer (as `null`,
//!   since it has no `result`) and left the server blocked forever waiting for a reply it will
//!   never get. A response is now a frame with an id and NO `method`, and a server request is
//!   answered — with `MethodNotFound`, honestly — rather than swallowed.
//! * **An error response is a response.** Treating one as a broken stream killed servers for
//!   answering correctly: `-32601 MethodNotFound` is the spec'd reply to an optional method, and
//!   the bring-up probe was `workspace/symbol`, which plenty of servers do not implement. Bring-up
//!   no longer sends a request at all, and `ServerError` is a first-class outcome that does not
//!   cost the server its life.
//! * **A document has more than one version.** `didOpen` was sent once and the `text` argument
//!   discarded on every later hover, so every hover after the first asked about a document the
//!   server had not seen since. Full-text `didChange` now follows an edited buffer.
//! * **A write has no deadline unless someone gives it one.** `write_all` on a pipe whose peer is
//!   not draining blocks forever, and the old deadline clock started AFTER the write. Frames now
//!   go through a writer thread with the deadline running across the whole exchange.

use std::collections::HashMap;
use std::io::BufReader;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::framing::{read_frame, write_frame, FrameError};
use crate::pathguard::PathRefusal;

/// How long to wait for one response before deciding the server is not coming back.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

/// How long a swept server gets to die of SIGTERM before SIGKILL. Short: the sweep runs on app
/// exit, and a user quitting an app is not waiting for a language server to think about it.
const TERM_GRACE: Duration = Duration::from_millis(300);

/// How many language servers may be live at once.
///
/// A cap rather than an unbounded map because `root` arrives from the webview, and `Path`
/// equality is textual: `/repo`, `/repo/.git/..` and (on a case-insensitive filesystem) `/REPO`
/// all pass the `.git` test while hashing differently. Roots are canonicalised first, which
/// removes that multiplication — and the cap is what remains true even if canonicalisation is
/// ever wrong again. At the cap the LEAST RECENTLY USED server is swept rather than the request
/// refused: a killed server costs one relaunch, while refusing costs the feature.
const MAX_SERVERS: usize = 8;

/// Why an LSP operation could not be completed. Every variant names a decision or an observed
/// fact, never a guess — a language server that is merely slow must not be reported as crashed.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum LspError {
    /// No server is configured for this language. Not an error the user caused.
    Unsupported { language: String },
    /// The server binary could not be launched — usually "not installed".
    Unlaunchable { language: String },
    /// The root is not a project (same rule as `pathguard`: containment needs a real root).
    NotAProject,
    /// The file was refused by `pathguard` — the SAME guard and the same vocabulary that decides
    /// whether the editor may read it. A second implementation of containment is a second thing
    /// that can disagree, and the first version of this module was exactly that: three lexical
    /// checks under a comment claiming parity with a guard that also canonicalises, re-applies
    /// the credential denylist to the resolved path, and refuses hard links.
    Refused { refusal: PathRefusal },
    /// The server exited, or its stream ended, while we were talking to it.
    ServerGone { language: String },
    /// The server is running but did not answer inside the timeout.
    Timeout { language: String },
    /// The server answered with something that is not a JSON-RPC response.
    Protocol { detail: String },
    /// The server answered with a JSON-RPC ERROR — which is a correct answer, not a broken
    /// stream. Kept distinct from `Protocol` because the two demand opposite reactions: a
    /// desynchronised stream must cost the server its life, and `MethodNotFound` must not.
    ///
    /// `i32`, not `i64`: JSON-RPC 2.0 defines `code` as an integer in the int32 range, specta
    /// forbids BigInt-style types across this boundary, and the alternative — widening and
    /// clamping — would put a number on the wire that no server ever sent. A code that does not
    /// fit is a server breaking protocol, and is reported as exactly that. (`PathRefusal::
    /// TooLarge` learned the same lesson one module over.)
    ServerError { code: i32, message: String },
}

impl std::fmt::Display for LspError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unsupported { language } => write!(f, "no language server for {language}"),
            Self::Unlaunchable { language } => {
                write!(f, "the {language} language server could not be started")
            }
            Self::NotAProject => write!(f, "that folder is not a project Tempest can open"),
            Self::Refused { refusal } => write!(f, "{refusal}"),
            Self::ServerGone { language } => write!(f, "the {language} language server stopped"),
            Self::Timeout { language } => write!(f, "the {language} language server did not reply"),
            Self::Protocol { detail } => write!(f, "the language server broke protocol: {detail}"),
            Self::ServerError { code, message } => {
                write!(f, "the language server refused ({code}): {message}")
            }
        }
    }
}

impl From<PathRefusal> for LspError {
    fn from(refusal: PathRefusal) -> Self {
        Self::Refused { refusal }
    }
}

/// Outcomes that mean the conversation itself is broken, so the server must not be reused: the
/// next request would inherit a stream already out of sync, and a desynchronised LSP stream
/// answers the WRONG question rather than failing. `ServerError` is deliberately absent.
fn is_fatal(err: &LspError) -> bool {
    matches!(
        err,
        LspError::ServerGone { .. } | LspError::Protocol { .. } | LspError::Timeout { .. }
    )
}

/// What the editor receives for a hover.
///
/// A TYPED result, not raw JSON. `serde_json::Value` cannot cross this boundary — it is
/// recursive, and specta overflows its stack trying to describe it — but the deeper reason is
/// that handing the webview an arbitrary LSP payload would make the renderer parse a protocol
/// it should never have to know. The host speaks LSP; the webview receives text.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
pub struct HoverInfo {
    pub contents: String,
}

/// Flatten an LSP hover result into text.
///
/// `contents` is one of three shapes across protocol versions: a bare string, a
/// `{kind, value}` MarkupContent, or an ARRAY of either. Handling only the modern one would
/// silently show nothing against older servers — a blank hover reads as "nothing to say here"
/// rather than "this client did not understand the answer".
pub fn hover_text(result: &serde_json::Value) -> Option<String> {
    fn one(value: &serde_json::Value) -> Option<String> {
        if let Some(text) = value.as_str() {
            return Some(text.to_string());
        }
        value.get("value").and_then(serde_json::Value::as_str).map(str::to_string)
    }
    let contents = result.get("contents")?;
    let text = match contents {
        serde_json::Value::Array(items) => {
            let parts: Vec<String> = items.iter().filter_map(one).collect();
            parts.join("\n")
        }
        other => one(other)?,
    };
    let trimmed = text.trim().to_string();
    // An empty hover is not a hover: showing an empty popover would claim the server answered.
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

/// Percent-encode a filesystem path into the path component of a `file:` URI.
///
/// A path is not a URI. `%`, `#`, `?`, spaces and every non-ASCII byte are legal in POSIX
/// filenames and all carry reserved meaning in a URI, and every server-side LSP library
/// (vscode-uri, which backs pyright and typescript-language-server) DECODES what it receives —
/// so `report%20final.py` concatenated straight into a URI names `report final.py`, a file that
/// does not exist, and the server answers about a phantom document. `pathguard` explicitly
/// accepts such names, so this is reachable from an ordinary repository.
fn encode_path(path: &Path) -> String {
    let raw = path.to_string_lossy();
    let mut out = String::with_capacity(raw.len());
    for byte in raw.as_bytes() {
        match byte {
            // RFC 3986 unreserved, plus the separator itself.
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' | b'/' => {
                out.push(char::from(*byte));
            }
            other => out.push_str(&format!("%{other:02X}")),
        }
    }
    out
}

/// The `file:` URI for an absolute path, encoded once and used for every message about it —
/// `didOpen`, `didChange` and the request all have to name the SAME string or the server answers
/// about a document it does not have.
fn file_uri(path: &Path) -> String {
    format!("file://{}", encode_path(path))
}

/// How to launch one language's server.
#[derive(Debug, Clone)]
pub struct ServerSpec {
    pub language: String,
    pub program: String,
    pub args: Vec<String>,
}

/// What the reader thread hands back. Framing errors cross the channel as data rather than as
/// a live `FrameError`, so the thread can end cleanly on any of them.
enum Incoming {
    Frame(Vec<u8>),
    Ended,
    Broken(String),
}

/// What the multiplexer believes the server currently holds for one document.
///
/// The version, because `didChange` must increment it — and a DIGEST of the text rather than the
/// text, because "have these bytes changed?" is all that is ever asked of it. Keeping the text
/// meant every document ever hovered was retained in full, per server, for the life of the app:
/// a 2 MiB file per open, never freed, with no `didClose` anywhere and no bound but the number of
/// files the user looks at. A hash answers the only question at 8 bytes.
///
/// A hash collision would suppress one `didChange`. That is a 1-in-2^64 event against text the
/// user typed, not against text an attacker chose — and the consequence is one stale hover, not a
/// wrong answer about a different file, because the URI is the key.
struct OpenDoc {
    version: i64,
    digest: u64,
}

/// A cheap, stable digest of the buffer. Not cryptographic and not required to be.
fn digest_of(text: &str) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    text.hash(&mut hasher);
    hasher.finish()
}

/// One running server, and the id counter for the conversation with it.
///
/// The stdout side is read by a THREAD and the stdin side written by another. `read_frame` on a
/// pipe blocks with no deadline available, and so does `write_all` — a timeout checked around
/// either is not a timeout at all. The threads turn both directions into `recv_timeout`, which
/// is a deadline that actually binds.
struct Running {
    child: Child,
    /// The process GROUP leader's id, which is the child's own pid after `process_group(0)`.
    /// Sweeping the group is what reaches the grandchildren every real server spawns.
    pgid: i32,
    outgoing: Option<Sender<Vec<u8>>>,
    /// One ack per frame handed to the writer thread — `Ok` written, `Err` the pipe is gone.
    writes: Receiver<Result<(), ()>>,
    incoming: Receiver<Incoming>,
    reader: Option<JoinHandle<()>>,
    writer: Option<JoinHandle<()>>,
    next_id: i64,
    /// Documents this server has been told about, and what it was told. `didOpen` twice for one
    /// file is a protocol violation; never following an edit is worse, because then every later
    /// answer is about text the user has already replaced.
    opened: HashMap<String, OpenDoc>,
    /// When this server was last used, for the LRU sweep at `MAX_SERVERS`.
    last_used: Instant,
}

/// Identity of a server: one per language PER PROJECT. Two projects must not share a server —
/// a language server's whole model is one workspace root, and sharing would let one project's
/// open files answer another's questions. The root is CANONICAL, so the many spellings of one
/// directory are one key rather than many servers.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct ServerKey {
    language: String,
    root: PathBuf,
}

/// Owns every running language server.
pub struct Multiplexer {
    specs: Vec<ServerSpec>,
    running: HashMap<ServerKey, Running>,
    timeout: Duration,
}

impl Multiplexer {
    pub fn new(specs: Vec<ServerSpec>) -> Self {
        Self { specs, running: HashMap::new(), timeout: REQUEST_TIMEOUT }
    }

    /// A shorter deadline, for tests that pin the timeout itself. Injectable rather than fixed
    /// because a test that proves "the deadline binds" should not cost ten seconds of every
    /// `make verify` to do it — and a suite people wait for is a suite people skip.
    #[cfg(test)]
    fn with_timeout(specs: Vec<ServerSpec>, timeout: Duration) -> Self {
        Self { specs, running: HashMap::new(), timeout }
    }

    /// The canonical root, or a refusal.
    ///
    /// Same root rule as `pathguard` — a language server is pointed at a workspace, and a
    /// workspace that is not a project is a caller naming somewhere it should not — plus the
    /// canonicalisation that keeps one project from being many keys.
    fn project_root(root: &Path) -> Result<PathBuf, LspError> {
        if !root.join(".git").exists() {
            return Err(LspError::NotAProject);
        }
        root.canonicalize().map_err(|_| LspError::NotAProject)
    }

    /// Send one request and return its result. Starts the server if it is not already running.
    pub fn request(
        &mut self,
        language: &str,
        root: &Path,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value, LspError> {
        let key = ServerKey { language: language.to_string(), root: Self::project_root(root)? };
        self.ensure_started(&key)?;
        let outcome = self.on(&key, |server, timeout| {
            server.exchange(&key.language, method, params, timeout)
        });
        self.evict_if_fatal(&key, &outcome);
        outcome
    }

    /// Bring a server up, WITHOUT asking it anything.
    ///
    /// The first version used a `workspace/symbol` request as its bring-up probe, which made an
    /// optional method the price of admission: a server that answers `MethodNotFound` — the
    /// spec'd reply — was killed for it, and hover never worked at all. Launching and
    /// handshaking is the whole of "started".
    fn ensure_started(&mut self, key: &ServerKey) -> Result<(), LspError> {
        if self.running.contains_key(key) {
            return Ok(());
        }
        // Make room BEFORE the spawn, so the cap bounds live processes rather than merely
        // recording that it was exceeded.
        self.evict_lru_if_full();
        let mut running = self.launch(&key.language, &key.root)?;
        // LSP is not request/response from byte one. A server asked anything before
        // `initialize` is entitled to refuse, and one that fails the handshake is not kept:
        // the alternative is a half-live server answering later questions unpredictably.
        if let Err(err) = running.handshake(&key.language, &key.root, self.timeout) {
            running.kill();
            return Err(err);
        }
        self.running.insert(key.clone(), running);
        Ok(())
    }

    /// Run one operation against a live server, refreshing its LRU stamp.
    fn on<T>(
        &mut self,
        key: &ServerKey,
        act: impl FnOnce(&mut Running, Duration) -> Result<T, LspError>,
    ) -> Result<T, LspError> {
        let timeout = self.timeout;
        let Some(server) = self.running.get_mut(key) else {
            return Err(LspError::ServerGone { language: key.language.clone() });
        };
        server.last_used = Instant::now();
        act(server, timeout)
    }

    /// ONE eviction policy, applied to every path.
    ///
    /// It used to live inside `request` alone, so a `didOpen` that failed with `ServerGone` left
    /// the dead server in the map: `running_count()` over-reported, and the next hover for a
    /// different file believed a server that no longer existed.
    fn evict_if_fatal<T>(&mut self, key: &ServerKey, outcome: &Result<T, LspError>) {
        if let Err(err) = outcome {
            if is_fatal(err) {
                if let Some(mut dead) = self.running.remove(key) {
                    dead.kill();
                }
            }
        }
    }

    fn evict_lru_if_full(&mut self) {
        while self.running.len() >= MAX_SERVERS {
            let Some(oldest) = self
                .running
                .iter()
                .min_by_key(|(_, server)| server.last_used)
                .map(|(key, _)| key.clone())
            else {
                return;
            };
            if let Some(mut evicted) = self.running.remove(&oldest) {
                evicted.kill();
            }
        }
    }

    fn launch(&self, language: &str, root: &Path) -> Result<Running, LspError> {
        let spec = self
            .specs
            .iter()
            .find(|s| s.language == language)
            .ok_or_else(|| LspError::Unsupported { language: language.to_string() })?;
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            // The server's diagnostics are its own; they must not land in the app's stdout and be
            // mistaken for a frame.
            .stderr(Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Own process group, exactly as `supervisor.rs` does for the sidecar: every real
            // language server is a shim over a grandchild (npx → typescript-language-server →
            // tsserver; pyright-langserver → node), and SIGKILL to the shim reaches none of them.
            command.process_group(0);
        }
        let mut child = command
            .spawn()
            .map_err(|_| LspError::Unlaunchable { language: language.to_string() })?;
        let pgid = i32::try_from(child.id()).unwrap_or(0);
        let stdin = child.stdin.take().ok_or_else(|| LspError::Unlaunchable {
            language: language.to_string(),
        })?;
        let stdout = child.stdout.take().ok_or_else(|| LspError::Unlaunchable {
            language: language.to_string(),
        })?;

        let (frames_tx, frames_rx) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            let mut stream = BufReader::new(stdout);
            loop {
                let message = match read_frame(&mut stream) {
                    Ok(frame) => Incoming::Frame(frame),
                    Err(FrameError::Eof) | Err(FrameError::Io(_)) => Incoming::Ended,
                    Err(FrameError::Protocol(detail)) => Incoming::Broken(detail),
                };
                let fatal = !matches!(message, Incoming::Frame(_));
                // The receiver going away means the server was killed; stopping is correct.
                if frames_tx.send(message).is_err() || fatal {
                    return;
                }
            }
        });

        let (out_tx, out_rx) = mpsc::channel::<Vec<u8>>();
        let (ack_tx, ack_rx) = mpsc::channel::<Result<(), ()>>();
        let writer = std::thread::spawn(move || {
            let mut stdin = stdin;
            while let Ok(body) = out_rx.recv() {
                let wrote = write_frame(&mut stdin, &body).is_ok();
                if ack_tx.send(if wrote { Ok(()) } else { Err(()) }).is_err() || !wrote {
                    return;
                }
            }
        });

        Ok(Running {
            child,
            pgid,
            outgoing: Some(out_tx),
            writes: ack_rx,
            incoming: frames_rx,
            reader: Some(reader),
            writer: Some(writer),
            next_id: 1,
            opened: HashMap::new(),
            last_used: Instant::now(),
        })
    }

    /// Hover at a position, for the editor. The webview names a FEATURE and a file — never a
    /// protocol method — so the set of things it can ask a language server stays a list the host
    /// wrote, not a string the renderer chose.
    ///
    /// `file` is an ABSOLUTE path that `pathguard` has already resolved and vouched for. Taking
    /// the resolved path rather than a relative string is what removes the second containment
    /// implementation: there is one guard, and this function cannot drift from it because it no
    /// longer contains a copy of it. The containment check that remains is not a substitute — it
    /// is this module refusing to trust its caller about the one invariant it depends on.
    pub fn hover(
        &mut self,
        language: &str,
        root: &Path,
        file: &Path,
        text: &str,
        line: u32,
        character: u32,
    ) -> Result<serde_json::Value, LspError> {
        let key = ServerKey { language: language.to_string(), root: Self::project_root(root)? };
        if !file.is_absolute() || !file.starts_with(&key.root) {
            return Err(LspError::Refused { refusal: PathRefusal::EscapesRoot });
        }
        let uri = file_uri(file);
        self.ensure_started(&key)?;
        let synced = self.on(&key, |server, timeout| {
            server.sync_document(&key.language, &uri, language, text, timeout)
        });
        self.evict_if_fatal(&key, &synced);
        synced?;
        let outcome = self.on(&key, |server, timeout| {
            server.exchange(
                &key.language,
                "textDocument/hover",
                serde_json::json!({
                    "textDocument": { "uri": uri },
                    "position": { "line": line, "character": character },
                }),
                timeout,
            )
        });
        self.evict_if_fatal(&key, &outcome);
        outcome
    }

    /// How many servers are running. The webview never sees this; tests and shutdown do.
    pub fn running_count(&self) -> usize {
        self.running.len()
    }

    /// Point this multiplexer at a new set of server commands (Phase 20.6 settings).
    ///
    /// Every running server is swept first. Keeping them would leave processes started from the
    /// OLD command answering hovers after the user changed it — a settings screen disagreeing
    /// with the process table, which is the same lie as a toggle that does not take effect. A
    /// killed server costs exactly one relaunch on the next hover.
    pub fn reconfigure(&mut self, specs: Vec<ServerSpec>) {
        self.shutdown_all();
        self.specs = specs;
    }

    /// Stop every server.
    ///
    /// Called from the `RunEvent::Exit` handler in `lib.rs` — EXPLICITLY, not via `Drop`. On
    /// macOS `tao`'s event loop ends in `process::exit`, so no destructor of any Tauri managed
    /// state ever runs; the previous version's whole no-orphans argument rested on one that
    /// does not. `Drop` is kept below for panics and early returns, where it genuinely does run.
    pub fn shutdown_all(&mut self) {
        for (_, mut server) in self.running.drain() {
            server.kill();
        }
    }
}

impl Drop for Multiplexer {
    /// Covers panics and early returns — the paths where unwinding actually happens. It does NOT
    /// cover app exit; `shutdown_all` is called by hand there, and the comment above says why.
    fn drop(&mut self) {
        self.shutdown_all();
    }
}

impl Running {
    /// Hand one frame to the writer thread and wait, with a deadline, for it to reach the pipe.
    ///
    /// `write_all` on a pipe whose peer is not draining blocks forever: macOS buffers 16–64 KiB,
    /// and a `didOpen` carrying a 1.5 MB buffer is far past that. The old code wrote inline and
    /// only started its clock afterwards, so a server busy in its initial workspace scan wedged
    /// the command thread — holding the multiplexer's mutex — with no error ever surfaced.
    fn send(&mut self, language: &str, body: Vec<u8>, deadline: Instant) -> Result<(), LspError> {
        let Some(outgoing) = self.outgoing.as_ref() else {
            return Err(LspError::ServerGone { language: language.to_string() });
        };
        if outgoing.send(body).is_err() {
            return Err(LspError::ServerGone { language: language.to_string() });
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        match self.writes.recv_timeout(remaining) {
            Ok(Ok(())) => Ok(()),
            Ok(Err(())) | Err(RecvTimeoutError::Disconnected) => {
                Err(LspError::ServerGone { language: language.to_string() })
            }
            // A write that misses the deadline is fatal by `is_fatal`, so the caller sweeps the
            // group — which is also what unblocks the writer thread still sitting in `write_all`.
            Err(RecvTimeoutError::Timeout) => Err(LspError::Timeout { language: language.to_string() }),
        }
    }

    /// One request, one answer, on this server's stream.
    fn exchange(
        &mut self,
        language: &str,
        method: &str,
        params: serde_json::Value,
        timeout: Duration,
    ) -> Result<serde_json::Value, LspError> {
        // The clock starts BEFORE the write, because the write is one of the things that can
        // take forever.
        let deadline = Instant::now() + timeout;
        let id = self.next_id;
        self.next_id += 1;
        let request = serde_json::json!({
            "jsonrpc": "2.0", "id": id, "method": method, "params": params,
        });
        let body = serde_json::to_vec(&request).map_err(|err| LspError::Protocol {
            detail: format!("could not encode the request: {err}"),
        })?;
        self.send(language, body, deadline)?;

        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(LspError::Timeout { language: language.to_string() });
            }
            let frame = match self.incoming.recv_timeout(remaining) {
                Ok(Incoming::Frame(frame)) => frame,
                Ok(Incoming::Ended) | Err(RecvTimeoutError::Disconnected) => {
                    return Err(LspError::ServerGone { language: language.to_string() })
                }
                Ok(Incoming::Broken(detail)) => return Err(LspError::Protocol { detail }),
                Err(RecvTimeoutError::Timeout) => {
                    return Err(LspError::Timeout { language: language.to_string() })
                }
            };
            let message: serde_json::Value =
                serde_json::from_slice(&frame).map_err(|err| LspError::Protocol {
                    detail: format!("the server sent a frame that is not JSON: {err}"),
                })?;

            // A server talks while it works: notifications and its own REQUESTS share this
            // stream, and its request ids come from a counter of its own that starts where ours
            // does. So an id is not a correlation — a response is a frame with an id and NO
            // `method`, and anything else is the server's business, not our answer.
            //
            // The id is taken as a raw `Value`, not as an i64. **JSON-RPC 2.0 allows a String id**
            // and real servers use them (`"id": "reg-1"` for `client/registerCapability`). Reading
            // it as an i64 answered `None` for those, which fell through to `continue` — so the
            // very case this fix exists to close, a server request left unanswered forever, was
            // still open for every server that numbers its requests with strings.
            let server_method = message.get("method").and_then(serde_json::Value::as_str);
            let their_id = message.get("id");
            match (their_id, server_method) {
                // The server is asking US something. Answer it — a server left waiting on a
                // reply to `client/registerCapability` blocks, which looks exactly like a hang.
                (Some(theirs), Some(asked)) if !theirs.is_null() => {
                    let refusal = serde_json::json!({
                        "jsonrpc": "2.0",
                        // Echoed VERBATIM: the spec requires the response id to equal the
                        // request's, of whatever type, and a server matching on a number it
                        // never sent is a server still waiting.
                        "id": theirs,
                        "error": {
                            "code": -32601,
                            "message": format!("Tempest's LSP client does not implement {asked}"),
                        },
                    });
                    if let Ok(body) = serde_json::to_vec(&refusal) {
                        self.send(language, body, deadline)?;
                    }
                }
                (Some(seen), None) if seen.as_i64() == Some(id) => {
                    if let Some(error) = message.get("error") {
                        let raw = error.get("code").and_then(serde_json::Value::as_i64);
                        let Some(code) = raw.and_then(|n| i32::try_from(n).ok()) else {
                            return Err(LspError::Protocol {
                                detail: format!(
                                    "error code {raw:?} is not a JSON-RPC integer code"
                                ),
                            });
                        };
                        let detail = error
                            .get("message")
                            .and_then(serde_json::Value::as_str)
                            .unwrap_or("no message")
                            .to_string();
                        return Err(LspError::ServerError { code, message: detail });
                    }
                    return Ok(message.get("result").cloned().unwrap_or(serde_json::Value::Null));
                }
                _ => continue,
            }
        }
    }

    /// `initialize` → result → `initialized`, exactly as the protocol requires.
    fn handshake(&mut self, language: &str, root: &Path, timeout: Duration) -> Result<(), LspError> {
        let params = serde_json::json!({
            "processId": std::process::id(),
            "rootUri": file_uri(root),
            "capabilities": {
                "textDocument": {
                    "hover": { "contentFormat": ["plaintext"] },
                    "synchronization": { "didSave": false, "willSave": false },
                },
            },
            "clientInfo": { "name": "Tempest" },
        });
        self.exchange(language, "initialize", params, timeout)?;
        // A notification, not a request: waiting for a reply to `initialized` would hang here
        // forever against a correct server.
        let deadline = Instant::now() + timeout;
        self.notify(language, "initialized", serde_json::json!({}), deadline)
    }

    /// Make the server's model of one document match the editor's buffer.
    ///
    /// `didOpen` the first time, `didChange` afterwards, nothing at all when the bytes have not
    /// moved. The insert happens only AFTER the notification is on the wire: recording the
    /// document as open and then failing to send it left the multiplexer believing a server knew
    /// about a file it had never been told about.
    fn sync_document(
        &mut self,
        language: &str,
        uri: &str,
        language_id: &str,
        text: &str,
        timeout: Duration,
    ) -> Result<(), LspError> {
        let deadline = Instant::now() + timeout;
        let incoming = digest_of(text);
        match self.opened.get(uri) {
            None => {
                self.notify(
                    language,
                    "textDocument/didOpen",
                    serde_json::json!({
                        "textDocument": {
                            "uri": uri,
                            "languageId": language_id,
                            "version": 1,
                            "text": text,
                        },
                    }),
                    deadline,
                )?;
                self.opened.insert(uri.to_string(), OpenDoc { version: 1, digest: incoming });
            }
            Some(open) if open.digest != incoming => {
                let version = open.version + 1;
                self.notify(
                    language,
                    "textDocument/didChange",
                    serde_json::json!({
                        "textDocument": { "uri": uri, "version": version },
                        // Full-document sync. Incremental sync would need the edit deltas, which
                        // the webview does not send and which would be a second model of the
                        // document to keep correct.
                        "contentChanges": [ { "text": text } ],
                    }),
                    deadline,
                )?;
                self.opened.insert(uri.to_string(), OpenDoc { version, digest: incoming });
            }
            Some(_) => {}
        }
        Ok(())
    }

    /// Send a notification — no id, and therefore no answer to wait for.
    fn notify(
        &mut self,
        language: &str,
        method: &str,
        params: serde_json::Value,
        deadline: Instant,
    ) -> Result<(), LspError> {
        let message = serde_json::json!({"jsonrpc": "2.0", "method": method, "params": params});
        let body = serde_json::to_vec(&message).map_err(|err| LspError::Protocol {
            detail: format!("could not encode the notification: {err}"),
        })?;
        self.send(language, body, deadline)
    }

    /// Sweep this server's whole process GROUP, then join its threads.
    ///
    /// The order is the point. Killing the group closes every write end of the stdout pipe,
    /// which is what makes the reader see EOF; killing only the direct child does not, and a
    /// probe against a two-line shim showed `join()` still blocked three seconds later — on the
    /// Tauri command thread, holding the multiplexer's mutex, for the life of the process.
    fn kill(&mut self) {
        crate::supervisor::terminate_group(self.pgid);
        let deadline = Instant::now() + TERM_GRACE;
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        crate::supervisor::kill_group(self.pgid);
        let _ = self.child.kill();
        let _ = self.child.wait();
        // Dropping the sender is what ends a writer thread parked in `recv`; the group sweep is
        // what ends one parked in `write_all`.
        self.outgoing = None;
        if let Some(handle) = self.writer.take() {
            let _ = handle.join();
        }
        if let Some(handle) = self.reader.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// A REAL language server subprocess (L4: no mock where behaviour is the subject).
    ///
    /// States enumerated before these tests were written, in the trap-43/45 spirit — a
    /// multiplexer's behaviour is defined by what its children do, and children misbehave:
    ///   answers normally · is not installed at all · exits mid-conversation · never answers ·
    ///   writes a frame that is not JSON · answers a DIFFERENT id than it was asked ·
    ///   ANSWERS WITH A JSON-RPC ERROR · SENDS ITS OWN REQUEST BEARING OUR ID · NEVER READS ITS
    ///   STDIN AT ALL · IS A SHIM OVER A GRANDCHILD · two languages at once · the same language
    ///   in two projects · the same root spelled two ways · the same key twice · a root that is
    ///   not a project · more projects than the cap · shutdown while servers are live.
    struct Fixture {
        root: PathBuf,
    }

    impl Fixture {
        fn new(tag: &str) -> Self {
            let root = std::env::temp_dir().join(format!("tempest-lsp-{}-{tag}", std::process::id()));
            let _ = fs::remove_dir_all(&root);
            fs::create_dir_all(root.join(".git")).expect("fixture project");
            Self { root: root.canonicalize().expect("canonical root") }
        }

        /// Writes a python "language server" that speaks LSP framing, and returns its spec.
        fn server(&self, language: &str, behaviour: &str) -> ServerSpec {
            let script = self.root.join(format!("server_{language}_{behaviour}.py"));
            fs::write(&script, FAKE_SERVER.replace("__BEHAVIOUR__", behaviour)).expect("script");
            ServerSpec {
                language: language.to_string(),
                program: "python3".to_string(),
                args: vec![script.to_string_lossy().into_owned()],
            }
        }

        /// An absolute path inside this project — what `pathguard` hands the multiplexer.
        fn file(&self, name: &str) -> PathBuf {
            let path = self.root.join(name);
            fs::write(&path, "x = 1\n").expect("fixture file");
            path
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    /// The fake server. Real framing, real process, behaviour switched by a marker.
    const FAKE_SERVER: &str = r#"
import json, os, subprocess, sys, time

BEHAVIOUR = "__BEHAVIOUR__"

# Answers the handshake, then stops reading stdin entirely — so the deadline the test observes is
# the one on the WRITE of a large didOpen, not one on the handshake's read. The first version of
# this fake never read anything, so `a_server_that_never_reads_its_stdin_cannot_wedge_the_
# multiplexer` timed out during `initialize` and never reached the big write it claimed to test.
if BEHAVIOUR == "deaf":
    def _read_frame():
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            ch = sys.stdin.buffer.read(1)
            if not ch:
                return None
            header += ch
        length = int(header.split(b":")[1].strip())
        return json.loads(sys.stdin.buffer.read(length))

    def _write_frame(obj):
        body = json.dumps(obj).encode()
        sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        sys.stdout.buffer.flush()

    first = _read_frame()          # initialize
    if first is not None:
        _write_frame({"jsonrpc": "2.0", "id": first["id"],
                      "result": {"capabilities": {"hoverProvider": True}}})
    _read_frame()                  # the `initialized` notification
    time.sleep(120)                # ...and then never read another byte
    sys.exit(0)

# A shim over a grandchild that inherits stdout — npx, an nvm shim, a wrapper.sh. Killing the
# shim alone reaches neither the grandchild nor the pipe's other write end.
if BEHAVIOUR == "shim":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "grandchild.pid"), "w") as fh:
        fh.write(str(child.pid))

def read_frame():
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        header += ch
    length = int(header.split(b":")[1].strip())
    return json.loads(sys.stdin.buffer.read(length))

def write_frame(obj):
    body = json.dumps(obj).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()

seen = []
collided = False

while True:
    request = read_frame()
    if request is None:
        break
    if "method" not in request:
        # A RESPONSE from the client to one of OUR requests. Recorded so a test can prove the
        # client answered rather than swallowing it — a server left waiting on a reply to
        # `client/registerCapability` is indistinguishable from a hang.
        seen.append("client-reply")
        continue
    method = request["method"]
    seen.append(method)
    if BEHAVIOUR == "exit":
        sys.exit(3)
    if BEHAVIOUR == "no_initialize" and method == "initialize":
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "error": {"code": -32603, "message": "refusing to initialize"}})
        continue
    if method == "initialize":
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "result": {"capabilities": {"hoverProvider": True}}})
        continue
    if request.get("id") is None:
        # A notification. No reply, by protocol.
        continue
    if BEHAVIOUR == "string_id" and not collided:
        # A server-initiated request numbered with a STRING, which JSON-RPC 2.0 allows and real
        # servers use. A client that reads ids as integers sees None here and never answers.
        collided = True
        write_frame({"jsonrpc": "2.0", "id": "reg-1",
                     "method": "client/registerCapability", "params": {"registrations": []}})
        write_frame({"jsonrpc": "2.0", "id": request["id"], "result": {"echo": method}})
        continue
    if BEHAVIOUR == "collide" and not collided and method != "textDocument/hover":
        # OUR id, but a REQUEST of the server's own: a client that correlates on the number
        # alone returns this as the answer, and leaves the server waiting forever.
        collided = True
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "method": "client/registerCapability", "params": {"registrations": []}})
        # ...and the real answer afterwards, which a correct client is still waiting for.
        write_frame({"jsonrpc": "2.0", "id": request["id"], "result": {"echo": method}})
        continue
    if BEHAVIOUR == "refuses" and method == "workspace/symbol":
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "error": {"code": -32601, "message": "Unhandled method workspace/symbol"}})
        continue
    if BEHAVIOUR == "huge_code":
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "error": {"code": 9223372036854775807, "message": "not an int32"}})
        continue
    if method == "textDocument/hover":
        write_frame({"jsonrpc": "2.0", "id": request["id"],
                     "result": {"contents": "seen: " + ",".join(seen)}})
        continue
    if BEHAVIOUR == "silent":
        time.sleep(60)
        continue
    if BEHAVIOUR == "garbage":
        body = b"this is not json"
        sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        sys.stdout.buffer.flush()
        continue
    if BEHAVIOUR == "wrong_id":
        write_frame({"jsonrpc": "2.0", "id": request["id"] + 1000, "result": {"stray": True}})
        continue
    write_frame({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {"echo": request["method"], "params": request.get("params"), "pid": 1},
    })
"#;

    fn alive(pid: i32) -> bool {
        // Signal 0 asks "may I signal this process", which answers "does it exist" without
        // touching it.
        unsafe { libc::kill(pid, 0) == 0 }
    }

    #[test]
    fn a_request_reaches_a_real_server_and_the_answer_comes_back() {
        let f = Fixture::new("ok");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        // Deliberately NOT hover: the fake answers that one specially (it reports the methods it
        // has seen, which is how the handshake test gets its evidence). This case is about the
        // plain request path, so it uses a method the fake merely echoes.
        let out = mux
            .request("python", &f.root, "textDocument/definition", serde_json::json!({"x": 1}))
            .expect("a running server answers");
        assert_eq!(out["echo"], "textDocument/definition");
        assert_eq!(out["params"]["x"], 1);
        mux.shutdown_all();
    }

    #[test]
    fn the_same_language_and_root_reuses_one_server() {
        let f = Fixture::new("reuse");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.request("python", &f.root, "a", serde_json::json!({})).expect("first");
        mux.request("python", &f.root, "b", serde_json::json!({})).expect("second");
        assert_eq!(mux.running_count(), 1, "one server, not one per request");
        mux.shutdown_all();
    }

    #[test]
    fn the_same_project_spelled_differently_is_still_one_server() {
        // `root` arrives from the webview. `Path` equality is textual, so `/repo` and
        // `/repo/.git/..` are different keys naming one directory — and every miss used to spawn
        // another server that nothing ever reaped.
        let f = Fixture::new("spelling");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.request("python", &f.root, "a", serde_json::json!({})).expect("plain");
        let roundabout = f.root.join(".git").join("..");
        mux.request("python", &roundabout, "b", serde_json::json!({})).expect("roundabout");
        assert_eq!(mux.running_count(), 1, "one canonical project, one server");
        mux.shutdown_all();
    }

    #[test]
    fn two_languages_get_two_servers() {
        let f = Fixture::new("two-langs");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok"), f.server("ts", "ok")]);
        mux.request("python", &f.root, "a", serde_json::json!({})).expect("python");
        mux.request("ts", &f.root, "a", serde_json::json!({})).expect("ts");
        assert_eq!(mux.running_count(), 2);
        mux.shutdown_all();
    }

    #[test]
    fn the_same_language_in_two_projects_gets_two_servers() {
        // A language server's model is ONE workspace root. Sharing one across projects would let
        // one project's open files answer another project's questions.
        let a = Fixture::new("proj-a");
        let b = Fixture::new("proj-b");
        let mut mux = Multiplexer::new(vec![a.server("python", "ok")]);
        mux.request("python", &a.root, "x", serde_json::json!({})).expect("a");
        mux.request("python", &b.root, "x", serde_json::json!({})).expect("b");
        assert_eq!(mux.running_count(), 2, "one server PER PROJECT");
        mux.shutdown_all();
    }

    #[test]
    fn live_servers_are_capped_and_the_least_recently_used_is_swept() {
        // The map is keyed on a path the webview names. Canonicalisation removes the obvious
        // multiplication; the cap is what still bounds live processes if it ever does not.
        let projects: Vec<Fixture> =
            (0..MAX_SERVERS + 2).map(|n| Fixture::new(&format!("cap-{n}"))).collect();
        let mut mux = Multiplexer::new(vec![projects[0].server("python", "ok")]);
        for project in &projects {
            mux.request("python", &project.root, "x", serde_json::json!({})).expect("a server");
            assert!(mux.running_count() <= MAX_SERVERS, "the cap must bind while running");
        }
        assert_eq!(mux.running_count(), MAX_SERVERS);
        mux.shutdown_all();
    }

    #[test]
    fn an_unconfigured_language_is_refused_rather_than_guessed() {
        let f = Fixture::new("unsupported");
        let mut mux = Multiplexer::new(vec![]);
        assert_eq!(
            mux.request("cobol", &f.root, "x", serde_json::json!({})),
            Err(LspError::Unsupported { language: "cobol".into() })
        );
    }

    #[test]
    fn a_server_binary_that_does_not_exist_is_reported_not_hung() {
        let f = Fixture::new("missing-binary");
        let mut mux = Multiplexer::new(vec![ServerSpec {
            language: "python".into(),
            program: "tempest-no-such-language-server".into(),
            args: vec![],
        }]);
        assert_eq!(
            mux.request("python", &f.root, "x", serde_json::json!({})),
            Err(LspError::Unlaunchable { language: "python".into() })
        );
    }

    #[test]
    fn a_root_that_is_not_a_project_is_refused() {
        let plain = std::env::temp_dir().join(format!("tempest-lsp-plain-{}", std::process::id()));
        let _ = fs::remove_dir_all(&plain);
        fs::create_dir_all(&plain).expect("plain dir");
        let mut mux = Multiplexer::new(vec![ServerSpec {
            language: "python".into(),
            program: "python3".into(),
            args: vec![],
        }]);
        let verdict = mux.request("python", &plain, "x", serde_json::json!({}));
        let _ = fs::remove_dir_all(&plain);
        assert_eq!(verdict, Err(LspError::NotAProject));
    }

    #[test]
    fn a_server_that_exits_mid_conversation_is_reported_not_hung() {
        let f = Fixture::new("exits");
        let mut mux = Multiplexer::new(vec![f.server("python", "exit")]);
        assert_eq!(
            mux.request("python", &f.root, "x", serde_json::json!({})),
            Err(LspError::ServerGone { language: "python".into() })
        );
    }

    #[test]
    fn a_frame_that_is_not_json_is_a_protocol_error_not_a_crash() {
        let f = Fixture::new("garbage");
        let mut mux = Multiplexer::new(vec![f.server("python", "garbage")]);
        match mux.request("python", &f.root, "x", serde_json::json!({})) {
            Err(LspError::Protocol { .. }) => {}
            other => panic!("expected a protocol error, got {other:?}"),
        }
    }

    #[test]
    fn an_answer_to_a_different_id_is_not_mistaken_for_ours() {
        // The state that makes a multiplexer a multiplexer: ids correlate answers to questions.
        // A server that answers id+1000 must not have that treated as this request's result.
        let f = Fixture::new("wrong-id");
        let mut mux =
            Multiplexer::with_timeout(vec![f.server("python", "wrong_id")], Duration::from_millis(600));
        match mux.request("python", &f.root, "x", serde_json::json!({})) {
            Err(LspError::Timeout { .. }) => {}
            other => panic!("a stray id must never answer our request, got {other:?}"),
        }
    }

    #[test]
    fn a_server_request_bearing_our_id_is_not_our_answer_and_is_replied_to() {
        // The collision case, which the first version got wrong: client and server id counters
        // are INDEPENDENT and both start near 1, so `{"id": 2, "method": "..."}` from the server
        // is the normal case, not an exotic one. Matching on the number alone returned it as our
        // result (as `null`, since a request has no `result`) and left the server blocked.
        let f = Fixture::new("collide");
        let mut mux = Multiplexer::new(vec![f.server("python", "collide")]);
        let out = mux
            .request("python", &f.root, "textDocument/definition", serde_json::json!({}))
            .expect("the real answer, not the server's own request");
        assert_eq!(
            out["echo"], "textDocument/definition",
            "a server-initiated request must not be returned as our result"
        );
        // ...and the server must not be left waiting: the reply is visible in what it has seen.
        let hover = mux
            .hover("python", &f.root, &f.file("main.py"), "x = 1\n", 0, 0)
            .expect("hover");
        let contents = hover["contents"].as_str().expect("contents");
        assert!(
            contents.contains("client-reply"),
            "the server must receive an answer to its own request: {contents}"
        );
        mux.shutdown_all();
    }

    #[test]
    fn a_server_request_numbered_with_a_string_id_is_answered_too() {
        // JSON-RPC 2.0 allows a String id, and real servers use them. Reading the id as an i64
        // answered `None` for those and fell through to `continue` — so the case the collision
        // fix exists to close was still open for every server that numbers with strings, and the
        // integer-only test could never have seen it.
        let f = Fixture::new("string-id");
        let mut mux = Multiplexer::new(vec![f.server("python", "string_id")]);
        let out = mux
            .request("python", &f.root, "textDocument/definition", serde_json::json!({}))
            .expect("our own answer, not the server's request");
        assert_eq!(out["echo"], "textDocument/definition");
        let hover = mux
            .hover("python", &f.root, &f.file("main.py"), "x = 1\n", 0, 0)
            .expect("hover");
        let contents = hover["contents"].as_str().expect("contents");
        assert!(
            contents.contains("client-reply"),
            "a string-id request must be answered, not swallowed: {contents}"
        );
        mux.shutdown_all();
    }

    #[test]
    fn a_json_rpc_error_is_an_answer_and_does_not_cost_the_server_its_life() {
        // `-32601 MethodNotFound` is the spec'd reply to an optional method. Killing a server for
        // it meant hover never worked at all against a server without `workspace/symbol`.
        let f = Fixture::new("refuses");
        let mut mux = Multiplexer::new(vec![f.server("python", "refuses")]);
        match mux.request("python", &f.root, "workspace/symbol", serde_json::json!({"query": ""})) {
            Err(LspError::ServerError { code, .. }) => assert_eq!(code, -32601),
            other => panic!("expected a server error, got {other:?}"),
        }
        assert_eq!(mux.running_count(), 1, "a server that answered must not be killed for it");
        let hover = mux
            .hover("python", &f.root, &f.file("main.py"), "x = 1\n", 0, 0)
            .expect("the same server still works");
        assert!(hover["contents"].as_str().is_some());
        mux.shutdown_all();
    }

    #[test]
    fn an_error_code_outside_int32_is_a_protocol_violation_not_a_clamped_number() {
        // The contract gate refused `i64` across this boundary, and widening-and-clamping would
        // have put a number on the wire that no server ever sent. JSON-RPC defines `code` as an
        // integer in the int32 range; anything else is the server breaking protocol.
        let f = Fixture::new("huge-code");
        let mut mux = Multiplexer::new(vec![f.server("python", "huge_code")]);
        match mux.request("python", &f.root, "x", serde_json::json!({})) {
            Err(LspError::Protocol { detail }) => {
                assert!(detail.contains("not a JSON-RPC integer code"), "{detail}");
            }
            other => panic!("expected a protocol error, got {other:?}"),
        }
        assert_eq!(mux.running_count(), 0, "a server that broke protocol is not kept");
    }

    #[test]
    fn a_server_that_never_answers_times_out_rather_than_hanging_the_app() {
        // The deadline has to bind on a BLOCKING read. It did not, at first: `read_frame` on a
        // pipe blocks with no timeout available, so a check between reads never got control back
        // and the first version of this module hung forever. The reader thread is what turns
        // waiting into `recv_timeout`.
        let f = Fixture::new("silent");
        let mut mux =
            Multiplexer::with_timeout(vec![f.server("python", "silent")], Duration::from_millis(600));
        let started = Instant::now();
        assert_eq!(
            mux.request("python", &f.root, "x", serde_json::json!({})),
            Err(LspError::Timeout { language: "python".into() })
        );
        assert!(started.elapsed() < Duration::from_secs(5), "the deadline must actually bind");
        mux.shutdown_all();
    }

    #[test]
    fn a_server_that_never_reads_its_stdin_cannot_wedge_the_multiplexer() {
        // The WRITE side. A pipe whose peer is not draining blocks the writer once the kernel
        // buffer fills (16-64 KiB on macOS), and the old code started its clock only after the
        // write returned — so a 1.5 MB `didOpen` against a busy server hung the command thread
        // forever, holding the mutex, with no error ever surfaced.
        let f = Fixture::new("deaf");
        let mut mux =
            Multiplexer::with_timeout(vec![f.server("python", "deaf")], Duration::from_millis(700));
        // The fake ANSWERS the handshake and only then stops reading, so the deadline observed
        // below is the one on the big write. The first version of this fake never read a byte,
        // so the timeout fired during `initialize` and this test passed without the large write
        // ever being attempted — a test that could not fail for the reason it names.
        let small = mux.hover("python", &f.root, &f.file("small.py"), "x = 1\n", 0, 0);
        assert!(small.is_err(), "the server is not reading, so even a small hover ends");
        let mut mux =
            Multiplexer::with_timeout(vec![f.server("python", "deaf")], Duration::from_millis(700));
        let started = Instant::now();
        let huge = "x = 1\n".repeat(200_000); // ~1.2 MB, far past any pipe buffer
        let verdict = mux.hover("python", &f.root, &f.file("big.py"), &huge, 0, 0);
        assert_eq!(verdict, Err(LspError::Timeout { language: "python".into() }));
        assert!(started.elapsed() < Duration::from_secs(5), "the write deadline must bind");
        assert_eq!(mux.running_count(), 0, "a wedged server is swept, not kept");
    }

    #[test]
    fn killing_a_server_reaps_the_grandchildren_it_spawned() {
        // Every real language server is a shim over a grandchild. A probe against a two-line
        // wrapper printed `GRANDCHILD alive=true` after `child.kill()` — and because that
        // grandchild still holds the stdout write end, the reader never sees EOF and the join at
        // the end of `kill` blocks forever. The process group is what makes both go away.
        let f = Fixture::new("shim");
        let mut mux = Multiplexer::new(vec![f.server("python", "shim")]);
        mux.request("python", &f.root, "x", serde_json::json!({})).expect("the shim answers");
        let pid_file = f.root.join("grandchild.pid");
        let grandchild: i32 = fs::read_to_string(&pid_file)
            .expect("the shim records its grandchild")
            .trim()
            .parse()
            .expect("a pid");
        assert!(alive(grandchild), "the grandchild is running before the sweep");
        let started = Instant::now();
        mux.shutdown_all();
        assert!(started.elapsed() < Duration::from_secs(5), "shutdown must not block on a join");
        // The group sweep is synchronous, but the kernel reaps asynchronously; give it a moment.
        for _ in 0..50 {
            if !alive(grandchild) {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(!alive(grandchild), "a language server's children must not outlive the sweep");
    }

    #[test]
    fn a_server_is_initialized_before_it_is_asked_anything() {
        // LSP is not request/response from byte one: a server that is asked before `initialize`
        // is entitled to refuse or misbehave. The fake reports every method it saw, so the
        // ANSWER is the evidence — the handshake cannot be asserted by the thing that performs
        // it without becoming a test of itself.
        let f = Fixture::new("handshake");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        let hover = mux
            .hover("python", &f.root, &f.file("main.py"), "x = 1\n", 0, 0)
            .expect("a hover");
        let contents = hover["contents"].as_str().expect("contents");
        assert!(contents.starts_with("seen: initialize,initialized,"), "{contents}");
        assert!(contents.contains("textDocument/didOpen"), "{contents}");
        // Bring-up asks the server NOTHING of its own: `workspace/symbol` used to be sent as a
        // probe, which made an optional method the price of admission.
        assert!(!contents.contains("workspace/symbol"), "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn a_server_that_refuses_to_initialize_is_reported_not_used() {
        let f = Fixture::new("no-init");
        let mut mux = Multiplexer::new(vec![f.server("python", "no_initialize")]);
        match mux.hover("python", &f.root, &f.file("main.py"), "x\n", 0, 0) {
            Err(LspError::ServerError { code, .. }) => assert_eq!(code, -32603),
            other => panic!("expected the server's own error from a refused handshake, got {other:?}"),
        }
        assert_eq!(mux.running_count(), 0, "a server that never initialized is not kept");
    }

    #[test]
    fn a_document_is_opened_once_not_once_per_request() {
        // didOpen twice for one document is a protocol violation, and the second one silently
        // replaces the server's model of the file with whatever the editor last sent.
        let f = Fixture::new("didopen-once");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        let file = f.file("a.py");
        mux.hover("python", &f.root, &file, "x\n", 0, 0).expect("first");
        let second = mux.hover("python", &f.root, &file, "x\n", 0, 0).expect("second");
        let contents = second["contents"].as_str().expect("contents");
        assert_eq!(contents.matches("textDocument/didOpen").count(), 1, "{contents}");
        assert!(!contents.contains("didChange"), "unchanged text is not an edit: {contents}");
        mux.shutdown_all();
    }

    #[test]
    fn an_edited_buffer_is_resynchronised_before_the_next_hover() {
        // `hover` takes `text` on EVERY call, and the first version discarded it after the
        // first: every later hover asked for a position in a document the server had not seen
        // since, and got an answer about the wrong symbol — or none, reported to the UI as "the
        // server had nothing to say".
        let f = Fixture::new("didchange");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        let file = f.file("a.py");
        mux.hover("python", &f.root, &file, "x = 1\n", 0, 0).expect("first");
        let second = mux
            .hover("python", &f.root, &file, "import os\nimport sys\nx = 1\n", 2, 0)
            .expect("second");
        let contents = second["contents"].as_str().expect("contents");
        assert_eq!(contents.matches("textDocument/didOpen").count(), 1, "{contents}");
        assert_eq!(contents.matches("textDocument/didChange").count(), 1, "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn two_documents_are_opened_separately() {
        let f = Fixture::new("didopen-two");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.hover("python", &f.root, &f.file("a.py"), "x\n", 0, 0).expect("a");
        let second = mux.hover("python", &f.root, &f.file("b.py"), "y\n", 0, 0).expect("b");
        let contents = second["contents"].as_str().expect("contents");
        assert_eq!(contents.matches("textDocument/didOpen").count(), 2, "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn hover_refuses_a_file_outside_the_project_even_when_its_caller_does_not() {
        // `pathguard` is the guard; this is the multiplexer declining to TRUST its caller about
        // the one invariant it depends on. Containment stated in two implementations is
        // containment that can disagree with itself — so this is a precondition check, not a
        // second copy of the denylist.
        let f = Fixture::new("hover-escape");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        assert_eq!(
            mux.hover("python", &f.root, Path::new("/etc/hosts"), "x\n", 0, 0),
            Err(LspError::Refused { refusal: PathRefusal::EscapesRoot })
        );
        assert_eq!(
            mux.hover("python", &f.root, Path::new("relative.py"), "x\n", 0, 0),
            Err(LspError::Refused { refusal: PathRefusal::EscapesRoot })
        );
    }

    #[test]
    fn hover_text_reads_every_shape_the_protocol_allows() {
        use serde_json::json;
        // A bare string (LSP 2.x), MarkupContent (3.x), and an array of either.
        assert_eq!(hover_text(&json!({"contents": "plain"})), Some("plain".into()));
        assert_eq!(
            hover_text(&json!({"contents": {"kind": "markdown", "value": "marked"}})),
            Some("marked".into())
        );
        assert_eq!(
            hover_text(&json!({"contents": ["one", {"kind": "plaintext", "value": "two"}]})),
            Some("one\ntwo".into())
        );
        // Nothing to say, said honestly.
        assert_eq!(hover_text(&json!({})), None);
        assert_eq!(hover_text(&json!({"contents": "   "})), None);
        assert_eq!(hover_text(&json!({"contents": []})), None);
        assert_eq!(hover_text(&json!({"contents": 42})), None);
    }

    #[test]
    fn a_file_uri_is_encoded_not_concatenated() {
        // Every one of these is a legal POSIX filename that `pathguard` accepts, and every one
        // names a DIFFERENT file once a server-side URI library decodes it.
        assert_eq!(file_uri(Path::new("/p/plain.py")), "file:///p/plain.py");
        assert_eq!(file_uri(Path::new("/p/two words.py")), "file:///p/two%20words.py");
        assert_eq!(file_uri(Path::new("/p/report%20final.py")), "file:///p/report%2520final.py");
        assert_eq!(file_uri(Path::new("/p/a#b.py")), "file:///p/a%23b.py");
        assert_eq!(file_uri(Path::new("/p/a?b.py")), "file:///p/a%3Fb.py");
        assert_eq!(file_uri(Path::new("/p/café.py")), "file:///p/caf%C3%A9.py");
    }

    #[test]
    fn errors_state_what_happened_in_words_a_user_can_act_on() {
        assert_eq!(
            LspError::Unsupported { language: "cobol".into() }.to_string(),
            "no language server for cobol"
        );
        assert_eq!(
            LspError::Unlaunchable { language: "python".into() }.to_string(),
            "the python language server could not be started"
        );
        assert_eq!(
            LspError::NotAProject.to_string(),
            "that folder is not a project Tempest can open"
        );
        assert_eq!(
            LspError::Refused { refusal: PathRefusal::Credential }.to_string(),
            "that path holds credentials and is never read"
        );
        assert_eq!(
            LspError::ServerGone { language: "ts".into() }.to_string(),
            "the ts language server stopped"
        );
        assert_eq!(
            LspError::Timeout { language: "ts".into() }.to_string(),
            "the ts language server did not reply"
        );
        assert_eq!(
            LspError::Protocol { detail: "boom".into() }.to_string(),
            "the language server broke protocol: boom"
        );
        assert_eq!(
            LspError::ServerError { code: -32601, message: "nope".into() }.to_string(),
            "the language server refused (-32601): nope"
        );
        // A refusal crosses into this vocabulary rather than being re-worded.
        assert_eq!(
            LspError::from(PathRefusal::HardLinked),
            LspError::Refused { refusal: PathRefusal::HardLinked }
        );
    }

    #[test]
    fn only_a_broken_conversation_costs_a_server_its_life() {
        assert!(is_fatal(&LspError::ServerGone { language: "p".into() }));
        assert!(is_fatal(&LspError::Timeout { language: "p".into() }));
        assert!(is_fatal(&LspError::Protocol { detail: "d".into() }));
        assert!(!is_fatal(&LspError::ServerError { code: -32601, message: "m".into() }));
        assert!(!is_fatal(&LspError::Unsupported { language: "p".into() }));
        assert!(!is_fatal(&LspError::Unlaunchable { language: "p".into() }));
        assert!(!is_fatal(&LspError::NotAProject));
        assert!(!is_fatal(&LspError::Refused { refusal: PathRefusal::Absolute }));
    }

    #[test]
    fn reconfiguring_sweeps_the_servers_started_from_the_old_command() {
        // Phase 20.6: changing the command in Settings must not leave the previous binary
        // answering hovers. A settings screen that disagrees with the process table is the same
        // lie as a toggle that does not take effect.
        let f = Fixture::new("reconfigure");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.request("python", &f.root, "x", serde_json::json!({})).expect("the first server");
        assert_eq!(mux.running_count(), 1);

        mux.reconfigure(vec![]);
        assert_eq!(mux.running_count(), 0, "the old server is swept, not kept");
        assert_eq!(
            mux.request("python", &f.root, "x", serde_json::json!({})),
            Err(LspError::Unsupported { language: "python".into() }),
            "and the new configuration is what is in force"
        );

        mux.reconfigure(vec![f.server("python", "ok")]);
        mux.request("python", &f.root, "x", serde_json::json!({})).expect("the new server");
        assert_eq!(mux.running_count(), 1);
        mux.shutdown_all();
    }

    #[test]
    fn shutdown_stops_every_server() {
        // A language server that outlives the app is an orphan, and this repo gates on orphans.
        let f = Fixture::new("shutdown");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok"), f.server("ts", "ok")]);
        mux.request("python", &f.root, "x", serde_json::json!({})).expect("python");
        mux.request("ts", &f.root, "x", serde_json::json!({})).expect("ts");
        assert_eq!(mux.running_count(), 2);
        mux.shutdown_all();
        assert_eq!(mux.running_count(), 0, "shutdown must forget as well as kill");
    }
}
