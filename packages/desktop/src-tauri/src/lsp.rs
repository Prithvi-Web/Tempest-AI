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

use std::collections::{HashMap, HashSet};
use std::io::{BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::framing::{read_frame, write_frame, FrameError};

/// How long to wait for one response before deciding the server is not coming back.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

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
    /// The server exited, or its stream ended, while we were talking to it.
    ServerGone { language: String },
    /// The server is running but did not answer inside the timeout.
    Timeout { language: String },
    /// The server answered with something that is not a JSON-RPC response.
    Protocol { detail: String },
}

impl std::fmt::Display for LspError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unsupported { language } => write!(f, "no language server for {language}"),
            Self::Unlaunchable { language } => {
                write!(f, "the {language} language server could not be started")
            }
            Self::NotAProject => write!(f, "that folder is not a project Tempest can open"),
            Self::ServerGone { language } => write!(f, "the {language} language server stopped"),
            Self::Timeout { language } => write!(f, "the {language} language server did not reply"),
            Self::Protocol { detail } => write!(f, "the language server broke protocol: {detail}"),
        }
    }
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

/// One running server, and the id counter for the conversation with it.
///
/// The stdout side is read by a THREAD, not inline. `read_frame` on a pipe blocks with no
/// deadline available, so a timeout checked between reads is not a timeout at all: the first
/// version of this module hung forever on a server that answered a stray id, because the loop
/// that was supposed to notice never got control back. The thread turns "wait for a frame" into
/// `recv_timeout`, which is a deadline that actually binds.
struct Running {
    child: Child,
    stdin: ChildStdin,
    incoming: Receiver<Incoming>,
    reader: Option<JoinHandle<()>>,
    next_id: i64,
    /// Documents this server has already been told about. `didOpen` twice for one file is a
    /// protocol violation, and the second one silently replaces the server's model of the file.
    opened: HashSet<String>,
}

/// Identity of a server: one per language PER PROJECT. Two projects must not share a server —
/// a language server's whole model is one workspace root, and sharing would let one project's
/// open files answer another's questions.
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

    /// Send one request and return its result. Starts the server if it is not already running.
    pub fn request(
        &mut self,
        language: &str,
        root: &Path,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value, LspError> {
        // Same root rule as `pathguard`: a language server is pointed at a workspace, and a
        // workspace that is not a project is a caller naming somewhere it should not.
        if !root.join(".git").exists() {
            return Err(LspError::NotAProject);
        }
        let key = ServerKey { language: language.to_string(), root: root.to_path_buf() };
        if !self.running.contains_key(&key) {
            let mut running = self.launch(language, root)?;
            // LSP is not request/response from byte one. A server asked anything before
            // `initialize` is entitled to refuse, and one that fails the handshake is not kept:
            // the alternative is a half-live server answering later questions unpredictably.
            if let Err(err) = running.handshake(language, root, self.timeout) {
                running.kill();
                return Err(err);
            }
            self.running.insert(key.clone(), running);
        }

        let outcome = {
            let timeout = self.timeout;
            let server = self.running.get_mut(&key).expect("just inserted");
            server.exchange(language, method, params, timeout)
        };
        // A server that broke the conversation is not reused: the next request would inherit a
        // stream already out of sync, and a desynchronised LSP stream answers the wrong question
        // rather than failing.
        if matches!(
            outcome,
            Err(LspError::ServerGone { .. }) | Err(LspError::Protocol { .. }) | Err(LspError::Timeout { .. })
        ) {
            if let Some(mut dead) = self.running.remove(&key) {
                dead.kill();
            }
        }
        outcome
    }

    fn launch(&self, language: &str, root: &Path) -> Result<Running, LspError> {
        let spec = self
            .specs
            .iter()
            .find(|s| s.language == language)
            .ok_or_else(|| LspError::Unsupported { language: language.to_string() })?;
        let mut child = Command::new(&spec.program)
            .args(&spec.args)
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            // The server's diagnostics are its own; they must not land in the app's stdout and be
            // mistaken for a frame.
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| LspError::Unlaunchable { language: language.to_string() })?;
        let stdin = child.stdin.take().ok_or_else(|| LspError::Unlaunchable {
            language: language.to_string(),
        })?;
        let stdout = child.stdout.take().ok_or_else(|| LspError::Unlaunchable {
            language: language.to_string(),
        })?;
        let (tx, rx) = mpsc::channel();
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
                if tx.send(message).is_err() || fatal {
                    return;
                }
            }
        });
        Ok(Running {
            child,
            stdin,
            incoming: rx,
            reader: Some(reader),
            next_id: 1,
            opened: HashSet::new(),
        })
    }

    /// Hover at a position, for the editor. The webview names a FEATURE and a file — never a
    /// protocol method — so the set of things it can ask a language server stays a list the host
    /// wrote, not a string the renderer chose.
    pub fn hover(
        &mut self,
        language: &str,
        root: &Path,
        relative_path: &str,
        text: &str,
        line: u32,
        character: u32,
    ) -> Result<serde_json::Value, LspError> {
        // The same containment rule pathguard enforces. Naming a file outside the project must
        // not send its path to a language server, whatever the server would do with it.
        if relative_path.is_empty()
            || Path::new(relative_path).is_absolute()
            || Path::new(relative_path)
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err(LspError::NotAProject);
        }
        let uri = format!("file://{}", root.join(relative_path).to_string_lossy());
        self.ensure_open(language, root, &uri, relative_path, text)?;
        self.request(
            language,
            root,
            "textDocument/hover",
            serde_json::json!({
                "textDocument": { "uri": uri },
                "position": { "line": line, "character": character },
            }),
        )
    }

    /// Tell the server about a document once, and only once.
    fn ensure_open(
        &mut self,
        language: &str,
        root: &Path,
        uri: &str,
        relative_path: &str,
        text: &str,
    ) -> Result<(), LspError> {
        // Starting the server (and its handshake) has to happen before any notification, so an
        // ordinary request is used to bring it up rather than duplicating the launch logic.
        if !self.running.contains_key(&ServerKey {
            language: language.to_string(),
            root: root.to_path_buf(),
        }) {
            self.request(language, root, "workspace/symbol", serde_json::json!({"query": ""}))?;
        }
        let key = ServerKey { language: language.to_string(), root: root.to_path_buf() };
        let Some(server) = self.running.get_mut(&key) else {
            return Err(LspError::ServerGone { language: language.to_string() });
        };
        if !server.opened.insert(uri.to_string()) {
            return Ok(());
        }
        server.notify(
            language,
            "textDocument/didOpen",
            serde_json::json!({
                "textDocument": {
                    "uri": uri,
                    "languageId": language,
                    "version": 1,
                    "text": text,
                },
            }),
        )?;
        let _ = relative_path;
        Ok(())
    }

    /// How many servers are running. The webview never sees this; tests and shutdown do.
    pub fn running_count(&self) -> usize {
        self.running.len()
    }

    /// Stop every server. Called on app exit — a language server outliving the app is an orphan,
    /// and this repo gates on orphans (`tempest.dev.orphan_check`).
    pub fn shutdown_all(&mut self) {
        for (_, mut server) in self.running.drain() {
            server.kill();
        }
    }
}

impl Drop for Multiplexer {
    /// Dropping the multiplexer must not leave language servers behind. `shutdown_all` is the
    /// explicit path; this is the one that covers panics and early returns.
    fn drop(&mut self) {
        self.shutdown_all();
    }
}

impl Running {
    /// One request, one answer, on this server's stream.
    fn exchange(
        &mut self,
        language: &str,
        method: &str,
        params: serde_json::Value,
        timeout: Duration,
    ) -> Result<serde_json::Value, LspError> {
        let id = self.next_id;
        self.next_id += 1;
        let request = serde_json::json!({
            "jsonrpc": "2.0", "id": id, "method": method, "params": params,
        });
        let body = serde_json::to_vec(&request).map_err(|err| LspError::Protocol {
            detail: format!("could not encode the request: {err}"),
        })?;
        write_frame(&mut self.stdin, &body).map_err(|_| LspError::ServerGone {
            language: language.to_string(),
        })?;
        self.stdin.flush().map_err(|_| LspError::ServerGone {
            language: language.to_string(),
        })?;

        let deadline = Instant::now() + timeout;
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

            // A server talks while it works: notifications and its own requests share this
            // stream. Anything without OUR id is not our answer, and skipping it is what keeps
            // the correlation honest — the alternative is returning a stray message as a result.
            match message.get("id").and_then(serde_json::Value::as_i64) {
                Some(seen) if seen == id => {
                    if let Some(error) = message.get("error") {
                        return Err(LspError::Protocol { detail: error.to_string() });
                    }
                    return Ok(message.get("result").cloned().unwrap_or(serde_json::Value::Null));
                }
                Some(_) | None => continue,
            }
        }
    }

    /// `initialize` → result → `initialized`, exactly as the protocol requires.
    fn handshake(&mut self, language: &str, root: &Path, timeout: Duration) -> Result<(), LspError> {
        let params = serde_json::json!({
            "processId": std::process::id(),
            "rootUri": format!("file://{}", root.to_string_lossy()),
            "capabilities": {
                "textDocument": { "hover": { "contentFormat": ["plaintext"] } },
            },
            "clientInfo": { "name": "Tempest" },
        });
        self.exchange(language, "initialize", params, timeout)?;
        // A notification, not a request: waiting for a reply to `initialized` would hang here
        // forever against a correct server.
        self.notify(language, "initialized", serde_json::json!({}))
    }

    /// Send a notification — no id, and therefore no answer to wait for.
    fn notify(
        &mut self,
        language: &str,
        method: &str,
        params: serde_json::Value,
    ) -> Result<(), LspError> {
        let message = serde_json::json!({"jsonrpc": "2.0", "method": method, "params": params});
        let body = serde_json::to_vec(&message).map_err(|err| LspError::Protocol {
            detail: format!("could not encode the notification: {err}"),
        })?;
        write_frame(&mut self.stdin, &body)
            .map_err(|_| LspError::ServerGone { language: language.to_string() })?;
        self.stdin
            .flush()
            .map_err(|_| LspError::ServerGone { language: language.to_string() })
    }

    fn kill(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        // The child is gone, so the reader sees EOF and returns. Joining makes shutdown mean
        // "the threads are finished too", not "the processes were signalled".
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
    ///   two languages at once · the same language in two projects · the same key asked twice ·
    ///   a root that is not a project · shutdown while a server is live.
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
            let script = self.root.join(format!("server_{language}.py"));
            fs::write(&script, FAKE_SERVER.replace("__BEHAVIOUR__", behaviour)).expect("script");
            ServerSpec {
                language: language.to_string(),
                program: "python3".to_string(),
                args: vec![script.to_string_lossy().into_owned()],
            }
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    /// The fake server. Real framing, real process, behaviour switched by a marker.
    const FAKE_SERVER: &str = r#"
import json, sys, time

BEHAVIOUR = "__BEHAVIOUR__"

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

while True:
    request = read_frame()
    if request is None:
        break
    method = request.get("method", "")
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
            Err(LspError::Protocol { .. }) | Err(LspError::Timeout { .. }) => {}
            other => panic!("a stray id must never answer our request, got {other:?}"),
        }
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
    fn a_server_is_initialized_before_it_is_asked_anything() {
        // LSP is not request/response from byte one: a server that is asked before `initialize`
        // is entitled to refuse or misbehave. The fake reports every method it saw, so the
        // ANSWER is the evidence — the handshake cannot be asserted by the thing that performs
        // it without becoming a test of itself.
        let f = Fixture::new("handshake");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        let hover = mux
            .hover("python", &f.root, "main.py", "x = 1\n", 0, 0)
            .expect("a hover");
        let contents = hover["contents"].as_str().expect("contents");
        assert!(contents.starts_with("seen: initialize,initialized,"), "{contents}");
        assert!(contents.contains("textDocument/didOpen"), "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn a_server_that_refuses_to_initialize_is_reported_not_used() {
        let f = Fixture::new("no-init");
        let mut mux = Multiplexer::new(vec![f.server("python", "no_initialize")]);
        match mux.hover("python", &f.root, "main.py", "x\n", 0, 0) {
            Err(LspError::Protocol { .. }) => {}
            other => panic!("expected a protocol error from a refused handshake, got {other:?}"),
        }
        assert_eq!(mux.running_count(), 0, "a server that never initialized is not kept");
    }

    #[test]
    fn a_document_is_opened_once_not_once_per_request() {
        // didOpen twice for one document is a protocol violation, and the second one silently
        // replaces the server's model of the file with whatever the editor last sent.
        let f = Fixture::new("didopen-once");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.hover("python", &f.root, "a.py", "x\n", 0, 0).expect("first");
        let second = mux.hover("python", &f.root, "a.py", "x\n", 0, 0).expect("second");
        let contents = second["contents"].as_str().expect("contents");
        assert_eq!(contents.matches("textDocument/didOpen").count(), 1, "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn two_documents_are_opened_separately() {
        let f = Fixture::new("didopen-two");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        mux.hover("python", &f.root, "a.py", "x\n", 0, 0).expect("a");
        let second = mux.hover("python", &f.root, "b.py", "y\n", 0, 0).expect("b");
        let contents = second["contents"].as_str().expect("contents");
        assert_eq!(contents.matches("textDocument/didOpen").count(), 2, "{contents}");
        mux.shutdown_all();
    }

    #[test]
    fn hover_refuses_a_path_that_escapes_the_project() {
        // The same rule pathguard enforces: the webview names a file, and naming one outside the
        // project must not send its path to a language server.
        let f = Fixture::new("hover-escape");
        let mut mux = Multiplexer::new(vec![f.server("python", "ok")]);
        assert_eq!(
            mux.hover("python", &f.root, "../secrets.env", "x\n", 0, 0),
            Err(LspError::NotAProject)
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
