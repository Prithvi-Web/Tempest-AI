//! The local model server: a supervised loopback child (ADR-0080 §1).
//!
//! `supervisor.rs` owns every child that speaks a Tempest boundary, and its `Wire` enum has
//! exactly two variants — `Stdio` and `Unix`. A TCP child is not merely discouraged there, it
//! is **unrepresentable**, and that unrepresentability is a property L34 and the threat model
//! lean on. The entire local-model ecosystem is loopback HTTP.
//!
//! So the model server is supervised as its own kind of child rather than as a third `Wire`:
//! same process-group discipline, same teardown, no boundary. The deviation is bounded and
//! recorded (ADR-0080), and it is confined to a child that speaks no Tempest protocol at all —
//! `Wire` keeps both its variants and gains none.
//!
//! Three properties, each for a reason:
//!
//! - **Loopback only.** The bind address is `127.0.0.1`, never `0.0.0.0`. A model server
//!   reachable from the network is a model server anyone on the coffee-shop wifi can use, and
//!   `orphan_check`'s port probe would rightly fail the build.
//! - **Off until asked.** Nothing starts at launch. A user who never opens the panel never has
//!   a server, which is what keeps the airplane-mode claim honest.
//! - **Its own process group, swept on stop.** Same reason as every other child: `llama-server`
//!   spawns workers, and killing only the parent leaves them holding the port and the RAM.

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::supervisor::{kill_group, terminate_group};

/// Where a started server listens. Loopback, and the same port the `llamacpp` provider row
/// already points at — so a running server appears in the model picker through the catalog's
/// existing local probe, with no new provider code (ADR-0080 context §1).
pub(crate) const MODEL_SERVER_PORT: u16 = 8080;
pub(crate) const MODEL_SERVER_HOST: &str = "127.0.0.1";

/// How long `start` waits for the server to answer before calling it a failure. Loading a
/// multi-gigabyte model off disk is genuinely slow, so this is generous — but bounded, because
/// "still starting" forever is a spinner, and L23 forbids one.
const READY_TIMEOUT: Duration = Duration::from_secs(120);
const READY_POLL: Duration = Duration::from_millis(250);

/// What went wrong, in words a person can act on (L15.3, L23).
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ModelServerError {
    /// No `llama-server` anywhere we look. Names the install step rather than apologising.
    RunnerMissing(String),
    /// The model file named is not on disk.
    ModelMissing(String),
    /// It started but never answered.
    NeverReady(String),
    /// The spawn itself failed.
    Spawn(String),
    /// The fixed loopback port is already taken by something Tempest did not start.
    PortBusy(String),
}

impl std::fmt::Display for ModelServerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::RunnerMissing(m)
            | Self::ModelMissing(m)
            | Self::NeverReady(m)
            | Self::Spawn(m)
            | Self::PortBusy(m) => write!(f, "{m}"),
        }
    }
}

struct Running {
    child: Child,
    pgid: i32,
    model_path: String,
    /// False while the readiness loop is still waiting for the port to answer.
    ///
    /// The child is recorded BEFORE that wait, which is the whole point of the field: it used
    /// to be held in a local until readiness succeeded, so for the entire 120 s a large model
    /// takes to load, `RUNNING` was `None` — and `stop()`, which `sweep_on_exit` calls, takes
    /// `RUNNING`. Quitting during a start therefore left an `llama-server` nothing could
    /// reach: its own process group, so the host's death signals it nothing, and no UI left
    /// to press Stop. The window the previous fix opened while closing the one beside it.
    ready: bool,
}

static RUNNING: OnceLock<Arc<Mutex<Option<Running>>>> = OnceLock::new();

fn running() -> &'static Arc<Mutex<Option<Running>>> {
    RUNNING.get_or_init(|| Arc::new(Mutex::new(None)))
}

/// Serialises `start`. Two concurrent starts both spawned, and the second's assignment
/// dropped the first's `Running` — a `Child` dropped in Rust is neither killed nor waited on,
/// so that was a permanent orphan holding the port and the model's memory, with the UI
/// describing the second one.
static STARTING: OnceLock<Mutex<()>> = OnceLock::new();

fn starting() -> &'static Mutex<()> {
    STARTING.get_or_init(|| Mutex::new(()))
}

/// Reap a child we are giving up on: sweep its group, then WAIT.
///
/// `Child::kill` does not reap and `Child`'s `Drop` does not wait, so every early return that
/// merely killed left a zombie for the life of the app — visible in `orphan_check`'s pid tree
/// as a descendant that never goes away.
fn abandon(mut child: Child, pgid: i32) {
    terminate_group(pgid);
    for _ in 0..20 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    kill_group(pgid);
    let _ = child.kill();
    let _ = child.wait();
}

/// The one place a runner Tempest manages is kept: `<data>/runners/llama-server`.
///
/// This is ADR-0080 §6's "bundled" step made real without bundling anything into the app
/// itself. The directory belongs to Tempest, sits beside `models/`, and goes away with the
/// app — so a user who wants the runner gone deletes one folder, and a user who wants to
/// supply their own drops a binary in with that name.
pub(crate) fn managed_runner(data_dir: &std::path::Path) -> std::path::PathBuf {
    data_dir.join("runners").join("llama-server")
}

/// Where the runner binary is: Tempest's own `runners/` directory, then `PATH`.
///
/// **It used to take a path from the CALLER, and the caller is the webview.** `start_model_server`
/// is a `#[tauri::command]`, so any script that reaches `__TAURI_INVOKE` — rendered model output
/// in an artifact frame, an XSS in the vendored client, a hostile MCP tool result — could name
/// an arbitrary executable and an arbitrary file to feed it, and this function ran it. That is
/// the hazard `agent_tools.rs` makes unrepresentable for tools (`WriteScope` has no variant for
/// the user's tree), and it was expressible here through a plain command argument.
///
/// `data_dir` is not that parameter coming back. It is the HOST's own directory, handed down
/// from `tauri::State<DataDir>` — the same path the engine is spawned with — and the webview
/// cannot influence it. The distinction that matters is not "is there an argument" but "who
/// chooses the value", and here it is the app.
///
/// **Why `PATH` alone was not enough, learned the hard way.** A macOS app launched from Finder
/// does not inherit a login shell's `PATH`: it gets roughly `/usr/bin:/bin:/usr/sbin:/sbin`.
/// So a runner installed by Homebrew into `/opt/homebrew/bin` — the exact thing the old refusal
/// told users to do — would be invisible to the shipped app while being perfectly present in
/// their terminal. A PATH-only search made the advice in the error message wrong for the
/// machine it was printed on.
pub(crate) fn resolve_runner(data_dir: Option<&std::path::Path>) -> Result<String, ModelServerError> {
    if let Some(dir) = data_dir {
        let managed = managed_runner(dir);
        // `is_runnable`, not `is_file` — and NOT an early return on a file that merely exists.
        // A half-extracted archive, a copy made without `chmod +x`, or a text file with that
        // name used to be reported as a runner with an empty `runner_problem`, which ENABLED
        // the Serve button and hid the install note; the click then failed with "Permission
        // denied" (ADR-0086). It also shadowed a perfectly good `llama-server` on PATH, so a
        // broken file here made a working one unreachable. Falling through fixes both.
        if is_runnable(&managed) {
            return Ok(managed.to_string_lossy().into_owned());
        }
    }
    resolve_runner_in(
        &std::env::var_os("PATH").unwrap_or_default(),
        data_dir.map(managed_runner),
    )
}

/// `resolve_runner`, with the search path passed in.
///
/// The env read happens in exactly one place above, so the decision itself is a pure function
/// of its input and a test can ask "what happens when nothing is found" without emptying the
/// PROCESS's `PATH`. That matters more than it looks: cargo runs a binary's tests on parallel
/// threads sharing one environment, and an earlier cut of this did set `PATH=""` — which broke
/// two tests in other modules that were merely looking for their own programs at the time.
/// A test that reaches for a global to control its subject can fail a test it has never heard
/// of.
fn resolve_runner_in(
    search: &std::ffi::OsStr,
    managed: Option<std::path::PathBuf>,
) -> Result<String, ModelServerError> {
    if let Some(found) = which_in(search, "llama-server") {
        return Ok(found);
    }
    // The old message said `brew install llama.cpp` and nothing else, which is wrong twice on
    // a machine with no Homebrew: it names a command the user cannot run, and even where it
    // succeeds it installs into a directory a Finder-launched app cannot see. It now names the
    // place Tempest actually looks, which is a place the user can always put a file.
    let where_to_put_it = match managed {
        Some(path) => format!(
            "Put a `llama-server` binary at {} and Tempest will use it — that folder is \
             Tempest's own, so removing it removes the runner. ",
            path.display()
        ),
        None => String::new(),
    };
    Err(ModelServerError::RunnerMissing(format!(
        "no `llama-server` was found. Tempest does not bundle one yet, so running a downloaded \
         model needs one. {where_to_put_it}Official macOS builds are published at \
         github.com/ggml-org/llama.cpp/releases (the `bin-macos-arm64` archive); `brew install \
         llama.cpp` also works if you have Homebrew. Your downloaded models are kept either \
         way and will work as soon as a runner is there."
    )))
}

fn which_in(search: &std::ffi::OsStr, program: &str) -> Option<String> {
    std::env::split_paths(search)
        .map(|dir| dir.join(program))
        .find(|candidate| is_runnable(candidate))
        .map(|candidate| candidate.to_string_lossy().into_owned())
}

/// A file this process could actually execute.
///
/// The execute bit is checked, not merely existence, because "found" here is a claim the panel
/// acts on: `model_server_status` turning a path into `runner: Some(..)` with an empty
/// `runner_problem` is what enables Serve and hides the install note. A file that cannot be
/// executed is not a runner, and saying so before the click is the whole point of resolving on
/// every status read (L23: the reason arrives with the affordance, not after it).
///
/// `RunnerStatus::found` already documents exactly this rule for the EDITOR runners
/// (`runners.rs`); this is the same rule, finally applied to the model runner too.
fn is_runnable(candidate: &std::path::Path) -> bool {
    if !candidate.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::metadata(candidate)
            .map(|meta| meta.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        true
    }
}



/// True when something is answering on the model port.
///
/// This is the SQUATTER question — "is anything here before I spawn?" — and a bare connect is
/// exactly right for it: a dev server that will never speak our protocol still owns the port.
/// It is NOT the readiness question; see `responds_ready`.
pub(crate) fn port_answers() -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
            .parse()
            .expect("a literal loopback address parses"),
        Duration::from_millis(250),
    )
    .is_ok()
}

/// True when the server on the port is ready to answer a chat turn.
///
/// **`port_answers()` was used for this and it is the wrong question.** Measured against
/// llama.cpp b10612 with the catalogue's SMALLEST row (Qwen3 0.6B, 0.64 GB): the TCP connect
/// succeeds at **0.00 s** and `/health` only says `ok` at **0.99 s** — llama-server binds and
/// starts serving 503 `{"error":{"message":"Loading model"}}` on a thread *before* it loads
/// the weights, deliberately, so a client can tell the two apart. The largest row in the
/// catalogue is 5.03 GB, so that window is tens of seconds on a real machine.
///
/// What the old probe produced in that window: `ready` set within microseconds of the spawn,
/// `start()` returning Ok, and the panel rendering "Serving on 127.0.0.1 — pick llama.cpp
/// server (local) in the model list" over a model that cannot answer. The picker was empty
/// (the engine's discovery probe gets the same 503 and honestly lists nothing), and any turn
/// the user managed to send failed with a raw "Loading model". `READY_TIMEOUT` and the whole
/// `NeverReady` arm were unreachable except when the bind itself failed.
///
/// The rule is "answers HTTP with something other than *still loading*", not "answers
/// `/health` with ok". A runner that does not implement `/health` answers 404 and is treated
/// as ready — the old behaviour's intent, and better than refusing to serve an unfamiliar
/// runner — while llama.cpp's 503-while-loading is correctly read as not yet.
fn responds_ready() -> bool {
    use std::io::{Read, Write};

    let address = format!("{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
        .parse()
        .expect("a literal loopback address parses");
    let Ok(mut stream) = std::net::TcpStream::connect_timeout(&address, Duration::from_millis(250))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(750)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(750)));
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}\r\n\
         Connection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    // The status line is all that is needed, and reading only a prefix means a server that
    // holds the connection open cannot stall this probe behind its whole body.
    let mut head = [0u8; 64];
    let Ok(read) = stream.read(&mut head) else {
        return false;
    };
    if read == 0 {
        return false; // accepted the connection and said nothing: still coming up
    }
    let status = String::from_utf8_lossy(&head[..read]);
    !status.starts_with("HTTP/1.1 503") && !status.starts_with("HTTP/1.0 503")
}

/// The two pipes a spawned runner writes to. Both are drained; see the loop in `start`.
enum DrainSource {
    Out(std::process::ChildStdout),
    Err(std::process::ChildStderr),
}

/// Read a child pipe to EOF, echoing each line. Never returns while the child lives, which is
/// the point: an undrained pipe wedges the writer at 64 KB.
fn drain<R: std::io::Read>(handle: R) {
    for line in BufReader::new(handle).lines().map_while(Result::ok) {
        eprintln!("[llama-server] {line}");
    }
}

/// The exact command a server is started with. Split out so a test can read the ARGV.
///
/// `the_bind_address_is_loopback_and_never_the_wildcard` asserted `MODEL_SERVER_HOST ==
/// "127.0.0.1"` and nothing else — no test in this crate ever reached the spawn, so adding
/// `--host 0.0.0.0` to the arg list would have bound every interface with `cargo test` still
/// green. The constant was pinned; the socket was not.
fn server_command(runner: &str, model_path: &str) -> Command {
    let mut command = Command::new(runner);
    command
        .arg("--model")
        .arg(model_path)
        .arg("--host")
        .arg(MODEL_SERVER_HOST) // loopback, never 0.0.0.0
        .arg("--port")
        .arg(MODEL_SERVER_PORT.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // Its own group: `llama-server` spawns workers, and killing only the parent leaves
        // them holding the port and the memory.
        command.process_group(0);
    }
    command
}

/// Start a server for `model_path`, or return the one already running for it.
pub(crate) fn start(
    model_path: &str,
    data_dir: Option<&std::path::Path>,
) -> Result<String, ModelServerError> {
    // One start at a time. Two concurrent starts both spawned and the second's assignment
    // dropped the first's `Child` unreaped and unkilled.
    let _serialised = starting().lock().expect("model server start lock");

    if !std::path::Path::new(model_path).is_file() {
        return Err(ModelServerError::ModelMissing(format!(
            "{model_path} is not on disk — download the model first"
        )));
    }
    let runner = resolve_runner(data_dir)?;

    // `status()` reaps a child that has died, so asking it here is also how a crashed server
    // stops being reported as the one that is serving. Without this, pressing Serve after a
    // crash returned Ok in microseconds and spawned nothing.
    let (live, serving) = status();
    if live && serving.as_deref() == Some(model_path) {
        return Ok(runner);
    }
    // A different model was serving: stop it first. One port, one server — starting a second
    // would fail to bind and leave the user with the OLD model answering while the UI said
    // otherwise, which is worse than a clear stop-and-start.
    stop();

    // Readiness is "something answers on 8080", which cannot tell our child from a squatter:
    // with anything already listening there — a second Tempest's server, a dev server, another
    // llama-server — the first probe succeeded in microseconds, the spawned child failed to
    // bind and exited, and the panel said "Serving on 127.0.0.1" over a foreign process that
    // then received the user's chat turns. Refusing is the only honest answer, because the port
    // is fixed by the `llamacpp` provider row that makes a served model visible at all.
    if port_answers() {
        return Err(ModelServerError::PortBusy(format!(
            "something is already listening on {MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}, and \
             Tempest cannot tell it apart from its own model server. Stop whatever is using \
             that port and try again — serving over it would send your messages to a process \
             Tempest did not start."
        )));
    }

    let mut child = server_command(&runner, model_path)
        .spawn()
        .map_err(|err| ModelServerError::Spawn(format!("could not start {runner}: {err}")))?;
    let pgid = child.id() as i32;
    // BOTH pipes are drained. stderr is where llama.cpp b10612 actually writes — measured,
    // 0 bytes to stdout and ~11 KB to stderr across a load and ten turns — but stdout is
    // piped too, and a piped fd nobody reads is a 64 KB fuse: once the buffer fills the
    // child blocks in `write()` for ever, the port stays open, `try_wait()` still says it is
    // alive, and every turn hangs with no error. A different build, a different log level,
    // or a runner someone else supplies is all it would take. Draining costs one thread.
    for (label, pipe) in [
        ("stderr", child.stderr.take().map(DrainSource::Err),),
        ("stdout", child.stdout.take().map(DrainSource::Out),),
    ] {
        let Some(source) = pipe else { continue };
        std::thread::Builder::new()
            .name(format!("model-server-{label}"))
            .spawn(move || match source {
                DrainSource::Err(handle) => drain(handle),
                DrainSource::Out(handle) => drain(handle),
            })
            .ok();
    }

    // Recorded BEFORE the wait, so `stop()` — and `sweep_on_exit` through it — can reach this
    // child during the up-to-120 s a large model takes to load. Holding it in a local until
    // readiness succeeded is what made a quit mid-start leave an unreachable orphan.
    {
        let mut slot = running().lock().expect("model server lock");
        *slot = Some(Running {
            child,
            pgid,
            model_path: model_path.to_string(),
            ready: false,
        });
    }

    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        if responds_ready() {
            let mut slot = running().lock().expect("model server lock");
            match slot.as_mut() {
                Some(current) => current.ready = true,
                // Someone stopped it while we were waiting — a quit, or Stop. Nothing to
                // adopt, and claiming success would report a server that is already gone.
                None => {
                    return Err(ModelServerError::NeverReady(
                        "the model server was stopped while it was starting".to_string(),
                    ));
                }
            }
            return Ok(runner);
        }
        let exited = {
            let mut slot = running().lock().expect("model server lock");
            match slot.as_mut() {
                Some(current) => matches!(current.child.try_wait(), Ok(Some(_))),
                None => {
                    return Err(ModelServerError::NeverReady(
                        "the model server was stopped while it was starting".to_string(),
                    ));
                }
            }
        };
        if exited {
            // `stop()` sweeps the group and WAITS — the exited-child arm used to return
            // without either, so `llama-server`'s own workers survived it and the child
            // itself stayed a zombie.
            stop();
            return Err(ModelServerError::NeverReady(format!(
                "{runner} exited before it was ready — see the log for what it said"
            )));
        }
        if Instant::now() >= deadline {
            stop();
            return Err(ModelServerError::NeverReady(format!(
                "{runner} did not answer on {MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} within \
                 {}s — a very large model on a slow disk can exceed this; try a smaller one",
                READY_TIMEOUT.as_secs()
            )));
        }
        std::thread::sleep(READY_POLL);
    }
}

/// Stop the running server, sweeping its whole process group. Safe to call when nothing runs.
pub(crate) fn stop() {
    let taken = { running().lock().expect("model server lock").take() };
    if let Some(current) = taken {
        abandon(current.child, current.pgid);
    }
}

/// What the settings panel renders: whether a server is up, and for which model.
///
/// This reads the CHILD, not just the slot. It used to return `(true, path)` for as long as a
/// `Running` existed, without ever asking whether the process was alive — `port_answers`, the
/// probe written for exactly this and whose own doc-comment claimed the status call used it,
/// was wired into the readiness loop only (trap 45). An `llama-server` OOM-killed mid-session
/// therefore left the panel rendering "Serving on 127.0.0.1 — pick it in the model list" for
/// ever, over nothing, while every turn failed to connect: a spinner that stopped moving,
/// which L23 forbids.
///
/// A dead child is reaped here rather than merely forgotten, so its group goes with it.
pub(crate) fn status() -> (bool, Option<String>) {
    let dead = {
        let mut slot = running().lock().expect("model server lock");
        match slot.as_mut() {
            None => return (false, None),
            Some(current) => match current.child.try_wait() {
                Ok(Some(_)) => true,
                // Alive: `ready` and not merely spawned, because "Serving on 127.0.0.1" must
                // not appear over a model that is still loading.
                _ => return (current.ready, Some(current.model_path.clone())),
            },
        }
    };
    if dead {
        stop();
    }
    (false, None)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Serialises every test that touches the fixed port or `RUNNING`.
    ///
    /// cargo runs a binary's tests on parallel threads, and these share two pieces of global
    /// state: 127.0.0.1:8080 and the `RUNNING` slot. Without this they interleave and fail
    /// each other for reasons that have nothing to do with the code under test — the shape of
    /// a flaky suite that then gets "fixed" by deleting an assertion.
    static SHARED_PORT: Mutex<()> = Mutex::new(());

    /// A file that really exists, so `start` gets past its on-disk check and reaches the
    /// behaviour under test. `std::env::current_exe` is always a file and always readable.
    fn a_real_file() -> String {
        std::env::current_exe()
            .expect("the test binary is a file")
            .to_string_lossy()
            .into_owned()
    }

    #[test]
    #[ignore = "one-off: needs the managed runner and a downloaded model on THIS machine"]
    fn the_real_runner_serves_the_real_model_on_the_real_port() {
        // Not a CI gate — CI has neither a runner nor a 640 MB model. Run by hand with
        // `cargo test --lib modelserver -- --ignored --nocapture`, which is how the serve
        // path was proven against llama.cpp b10612 and Qwen3 0.6B on 2026-08-24.
        let data = dirs_next_home()
            .join("Library/Application Support/com.prithvi.tempest");
        let model = data.join("models/qwen3-0.6b-q8/Qwen3-0.6B-Q8_0.gguf");
        assert!(model.is_file(), "no downloaded model at {}", model.display());

        let runner = resolve_runner(Some(&data)).expect("the managed runner resolves");
        eprintln!("PROBE runner   = {runner}");
        assert!(runner.starts_with(data.to_str().unwrap()), "not the MANAGED runner: {runner}");

        let started = start(&model.to_string_lossy(), Some(&data)).expect("the server starts");
        eprintln!("PROBE started  = {started}");
        let (up, serving) = status();
        eprintln!("PROBE status   = up={up} serving={serving:?}");
        assert!(up);
        assert!(port_answers(), "the port really is open");
        eprintln!("PROBE port     = 127.0.0.1:{MODEL_SERVER_PORT} answering");
        stop();
        eprintln!("PROBE stopped");
    }

    fn dirs_next_home() -> std::path::PathBuf {
        std::path::PathBuf::from(std::env::var("HOME").expect("HOME"))
    }

    #[test]
    fn a_missing_model_file_is_refused_before_any_process_is_spawned() {
        // The order matters: resolving a runner that does not exist would otherwise report
        // "install llama.cpp" to someone whose actual problem is a model they never downloaded.
        let err = start("/nope/not-a-model.gguf", None).unwrap_err();
        assert!(matches!(err, ModelServerError::ModelMissing(_)), "{err:?}");
        assert!(err.to_string().contains("download the model first"));
    }

    #[test]
    fn the_runner_comes_from_the_path_and_cannot_be_named_by_a_caller() {
        // The old signature took a path from its caller, and the caller is the webview: any
        // script reaching `__TAURI_INVOKE` could name an executable for the host to run. The
        // parameter is gone rather than validated, because an arbitrary path is the whole
        // point of a configured runner and there is no validation to write for it.
        //
        // Asserted against the SIGNATURE, so re-adding the parameter cannot pass unnoticed.
        let resolve: fn(Option<&std::path::Path>) -> Result<String, ModelServerError> = resolve_runner;
        let _ = resolve;
        assert!(
            !include_str!("commands.rs").contains("configured_runner"),
            "a model-server command takes a runner path from the webview again — that is an \
             arbitrary local executable named by whatever is running in the page"
        );
    }

    #[test]
    fn a_missing_runner_names_the_install_step_and_keeps_the_models() {
        // ADR-0080 §6: the one place this feature is not yet zero-setup, said out loud rather
        // than left as a silence.
        //
        // The previous version began `let Err(err) = resolve_runner(None) else { return; }`,
        // so on a machine WITH llama.cpp installed — the state this very message tells users
        // to reach — it asserted nothing and reported as passed. An EMPTY SEARCH PATH is
        // passed instead, so the refusal is reachable on every machine, including the
        // developer's, without touching the environment other tests are reading.
        let err = resolve_runner_in(std::ffi::OsStr::new(""), None)
            .expect_err("an empty search path cannot produce a runner");
        let text = err.to_string();
        assert!(text.contains("brew install llama.cpp"), "{text}");
        assert!(text.contains("models are kept"), "{text}");
        assert!(matches!(err, ModelServerError::RunnerMissing(_)), "{err:?}");
    }

    #[test]
    fn a_runner_in_tempests_own_folder_is_found_when_the_path_has_nothing() {
        // The case that matters on a real Mac: an app launched from Finder gets roughly
        // `/usr/bin:/bin:/usr/sbin:/sbin`, so a runner installed anywhere a developer would
        // put one — Homebrew's `/opt/homebrew/bin`, a Nix profile, `~/.local/bin` — is
        // invisible to the shipped app while being perfectly present in their terminal. A
        // PATH-only search made the advice in the refusal wrong for the machine printing it.
        let data = std::env::temp_dir().join(format!("tempest-data-{}", std::process::id()));
        let runners = data.join("runners");
        std::fs::create_dir_all(&runners).expect("a temp data dir");
        let runner = runners.join("llama-server");
        std::fs::write(&runner, b"#!/bin/sh\nexit 0\n").expect("a managed runner");
        // Executable, because a real runner is and `is_runnable` now requires it (ADR-0086).
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&runner, std::fs::Permissions::from_mode(0o755)).ok();
        }

        let found = resolve_runner(Some(&data)).expect("the managed runner is found");
        assert_eq!(found, runner.to_string_lossy());
        assert_eq!(managed_runner(&data), runner);

        // And with nothing there, the refusal names the folder rather than a package manager
        // this machine may not have — the one the panel used to tell everybody to use.
        std::fs::remove_file(&runner).expect("remove it again");
        let err = resolve_runner_in(std::ffi::OsStr::new(""), Some(managed_runner(&data)))
            .expect_err("no runner anywhere");
        let text = err.to_string();
        assert!(text.contains(&runners.display().to_string()), "{text}");
        assert!(text.contains("github.com/ggml-org/llama.cpp"), "{text}");
        let _ = std::fs::remove_dir_all(&data);
    }

    #[test]
    fn a_file_that_cannot_be_executed_is_not_a_runner_and_does_not_shadow_the_path() {
        // ADR-0086. `is_file()` alone made a half-extracted archive, a copy made without
        // `chmod +x`, or a text file named `llama-server` look like a runner: the panel
        // enabled Serve and hid the install note, and the click failed with "Permission
        // denied" — the refusal arriving AFTER the affordance, which is the one thing
        // resolving on every status read exists to prevent.
        let data = std::env::temp_dir().join(format!("tempest-noexec-{}", std::process::id()));
        let runners = data.join("runners");
        std::fs::create_dir_all(&runners).expect("a temp data dir");
        let managed = runners.join("llama-server");
        std::fs::write(&managed, b"not a program\n").expect("a non-executable file");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&managed, std::fs::Permissions::from_mode(0o644)).ok();
        }

        // With nothing on PATH either, this is a refusal rather than a false positive.
        assert!(
            resolve_runner_in(std::ffi::OsStr::new(""), Some(managed_runner(&data))).is_err(),
            "a file with no execute bit is not a runner"
        );

        // And it must not SHADOW a real one: the managed check falls through to PATH rather
        // than returning early, so a broken file here cannot make a working runner
        // unreachable.
        let good = std::env::temp_dir().join(format!("tempest-goodrunner-{}", std::process::id()));
        std::fs::create_dir_all(&good).expect("a temp dir");
        let real = good.join("llama-server");
        std::fs::write(&real, b"#!/bin/sh\nexit 0\n").expect("an executable stub");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&real, std::fs::Permissions::from_mode(0o755)).ok();
        }
        let _guard = PathGuard::prepending(&good);
        let found = resolve_runner(Some(&data)).expect("the PATH runner is still reachable");
        assert_eq!(found, real.to_string_lossy());

        let _ = std::fs::remove_dir_all(&data);
        let _ = std::fs::remove_dir_all(&good);
    }

    #[test]
    fn a_runner_is_found_when_the_search_path_holds_one() {
        // The other side of the same decision: a directory containing an executable of that
        // name resolves to it, so the refusal above is about absence and not about the search
        // being broken (an assertion that only ever sees failures cannot tell those apart).
        let dir = std::env::temp_dir().join(format!("tempest-which-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("a temp dir");
        let runner = dir.join("llama-server");
        std::fs::write(&runner, b"#!/bin/sh\nexit 0\n").expect("a file named llama-server");
        // Executable, because a real runner is and `is_runnable` now requires it (ADR-0086).
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&runner, std::fs::Permissions::from_mode(0o755)).ok();
        }
        let found = resolve_runner_in(dir.as_os_str(), None).expect("the runner in the search path");
        assert_eq!(found, runner.to_string_lossy());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_port_already_taken_is_refused_rather_than_adopted() {
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        // Readiness is "something answers on 8080", which cannot tell our child from a
        // squatter. With anything already listening there the first probe succeeded in
        // microseconds, the spawned child failed to bind and exited, and the panel said
        // "Serving on 127.0.0.1" over a foreign process that then received the user's chat
        // turns. A real listener on the real port, because the port is the thing under test.
        // The runner is put in reach FIRST, and for both arms. `start()` triages in the order
        // a person can act on — is the model on disk, is there a program to run it, is the
        // port free — so without a resolvable runner the refusal is `RunnerMissing` and this
        // test never reaches its own subject. The fallback arm below used to skip this and
        // then assert PortBusy anyway; it went red the first time 8080 was genuinely taken on
        // a machine with no runner on PATH, naming a problem it was not testing.
        let runner = std::env::current_exe().expect("a runner-shaped file").display().to_string();
        let _guard = PathGuard::containing_llama_server(&runner);
        let squatter =
            match std::net::TcpListener::bind(format!("{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")) {
                Ok(listener) => Some(listener),
                Err(_) => {
                    // Something on this machine already holds 8080. The refusal is then
                    // exactly what the assertions below want, so the test is still
                    // meaningful — but say so rather than silently measuring a different
                    // world.
                    eprintln!("8080 was already taken; testing the refusal against that listener");
                    None
                }
            };
        let err = start(&a_real_file(), None).unwrap_err();
        drop(squatter);
        assert!(matches!(err, ModelServerError::PortBusy(_)), "{err:?}");
        assert!(
            err.to_string().contains("already listening"),
            "the refusal must name the cause a person can act on: {err}"
        );
    }

    #[test]
    fn the_spawned_command_binds_loopback_on_the_provider_row_s_port() {
        // `the_bind_address_is_loopback_and_never_the_wildcard` asserted the CONSTANT and
        // nothing else — no test in this crate reached the spawn, so `--host 0.0.0.0` added to
        // the arg list would have bound every interface with `cargo test` still green. This
        // reads the argv the child is actually given.
        let command = server_command("/usr/local/bin/llama-server", "/models/m.gguf");
        let args: Vec<String> =
            command.get_args().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(
            args,
            vec![
                "--model".to_string(),
                "/models/m.gguf".to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                "8080".to_string(),
            ],
            "the socket the child binds is what matters, not the constant beside it"
        );
        assert!(!args.iter().any(|a| a == "0.0.0.0"));
        assert_eq!(command.get_program().to_string_lossy(), "/usr/local/bin/llama-server");
    }

    #[test]
    fn the_exit_sweep_stops_this_child_too() {
        // The defect this pins is the one `sweep_on_exit`'s own doc-comment already describes:
        // the LSP multiplexer once rested its no-orphans case on `impl Drop`, and a `pgrep`
        // after quitting found the language server still running. The model server walked into
        // the same trap one function later.
        //
        // A `contains("modelserver::stop()")` was the first cut of this test, and a substring
        // search cannot tell a live call from a dead one: `// crate::modelserver::stop();`
        // satisfies it, which is the most likely way the call actually disappears. The line is
        // required to be uncommented and to be a statement.
        let lib = include_str!("lib.rs");
        let sweep = lib.split_once("fn sweep_on_exit").expect("sweep_on_exit exists").1;
        let body = sweep.split_once("\n}").expect("the sweep has a body").0;
        let stops = body.lines().any(|line| {
            let code = line.trim();
            !code.starts_with("//") && code.contains("modelserver::stop()") && code.ends_with(';')
        });
        assert!(
            stops,
            "sweep_on_exit does not stop the model server on a LIVE line: quitting the app \
             would leave llama-server holding {MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} and the \
             model's memory, with no UI left that could stop it (L34, L11)"
        );
    }

    #[test]
    fn a_child_is_recorded_before_the_readiness_wait_so_a_quit_can_still_reach_it() {
        // The P0 the previous fix opened while closing the one beside it: the child was held
        // in a LOCAL until readiness succeeded, so for the whole 120 s a large model takes to
        // load, `RUNNING` was `None` — and `stop()`, which `sweep_on_exit` calls, takes
        // `RUNNING`. Quitting mid-start left an llama-server nothing could reach.
        //
        // Asserted on the field that exists for it: a `Running` carries `ready`, so the record
        // can be present while the port is still silent. Without that field the struct cannot
        // represent "spawned but not answering", which is what forced the local.
        let source = include_str!("modelserver.rs");
        let start_body = source
            .split_once("pub(crate) fn start(")
            .expect("start exists")
            .1
            .split_once("\n}")
            .expect("start has a body")
            .0;
        let registration = start_body
            .find("*slot = Some(Running {")
            .expect("the child is recorded in RUNNING somewhere in start");
        let wait = start_body.find("let deadline = Instant::now()").expect("the readiness wait");
        assert!(
            registration < wait,
            "the child must be recorded BEFORE the readiness wait, or a quit during those \
             {}s leaves an orphan no code path can reach",
            READY_TIMEOUT.as_secs()
        );
    }

    #[test]
    fn readiness_waits_for_the_model_to_load_not_merely_for_the_port_to_open() {
        // ADR-0086. Measured against llama.cpp b10612 with the catalogue's SMALLEST row
        // (Qwen3 0.6B): the TCP connect succeeds at 0.00 s and `/health` says ok at 0.99 s,
        // because llama-server binds and answers 503 `Loading model` on a thread BEFORE it
        // loads the weights. The largest catalogue row is 5.03 GB, so that window is tens of
        // seconds on a real machine — during which the old probe reported "Serving on
        // 127.0.0.1", the picker was empty, and every turn failed with a raw "Loading model".
        //
        // The stub reproduces exactly that protocol. The assertion is not "start took a
        // while": it is that the PORT was open long before `start` returned, which is the
        // difference between the two probes and nothing else.
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        stop();
        if port_answers() {
            eprintln!("skipping: {MODEL_SERVER_PORT} is held by something else on this machine");
            return;
        }
        let Some(stub) = StubRunner::on_path() else {
            eprintln!("skipping: no python3 to build a stub runner with");
            return;
        };
        // Long enough to be unmistakable, short enough to keep the suite quick.
        let loading = Duration::from_millis(1_200);
        std::env::set_var("TEMPEST_STUB_LOADING_MS", loading.as_millis().to_string());

        let model = a_real_file();
        let began = Instant::now();
        // The port opens almost immediately; watch for it on another thread so the claim is
        // measured rather than assumed.
        let port_open_at = std::thread::spawn(move || {
            let watching = Instant::now();
            while watching.elapsed() < Duration::from_secs(10) {
                if port_answers() {
                    return Some(watching.elapsed());
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            None
        });

        let started = start(&model, None);
        let took = began.elapsed();
        let opened = port_open_at.join().expect("the watcher thread").expect("the port opened");
        std::env::remove_var("TEMPEST_STUB_LOADING_MS");
        stop();
        drop(stub);

        assert!(started.is_ok(), "the stub eventually becomes ready: {started:?}");
        assert!(
            opened < loading / 2,
            "the port must open EARLY for this test to be about anything — opened at {opened:?}"
        );
        assert!(
            took >= loading,
            "start() returned after {took:?}, before the stub finished loading ({loading:?}) — \
             readiness is measuring the socket again, not the model"
        );
    }

    #[test]
    fn a_runner_that_floods_stdout_is_drained_rather_than_wedged() {
        // ADR-0086. `server_command` pipes BOTH stdout and stderr, and only stderr was read.
        // A piped fd nobody drains is a 64 KB fuse: the child blocks in `write()` for ever,
        // the port stays open, `try_wait()` still reports it alive, and every chat turn hangs
        // with no error — the silent failure L23 forbids.
        //
        // Measured first: llama.cpp b10612 writes 0 bytes to stdout and ~11 KB to stderr
        // across a load and ten turns, so this is not what is biting today. It is one log-level
        // change, one build, or one user-supplied runner away, and the whole class goes away
        // by draining. 256 KB is four times the buffer — enough that an undrained pipe cannot
        // finish the write.
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        stop();
        if port_answers() {
            eprintln!("skipping: {MODEL_SERVER_PORT} is held by something else on this machine");
            return;
        }
        let Some(stub) = StubRunner::on_path() else {
            eprintln!("skipping: no python3 to build a stub runner with");
            return;
        };
        std::env::set_var("TEMPEST_STUB_STDOUT_BYTES", (256 * 1024).to_string());

        let model = a_real_file();
        let started = start(&model, None);
        std::env::remove_var("TEMPEST_STUB_STDOUT_BYTES");
        let (up, _) = status();
        stop();
        drop(stub);

        assert!(
            started.is_ok(),
            "a runner that writes 256 KB to stdout before binding must still start: {started:?}"
        );
        assert!(up, "and must still be alive afterwards rather than blocked in write()");
    }

    #[test]
    fn stopping_nothing_is_harmless() {
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        stop();
        let (up, model) = status();
        assert!(!up);
        assert_eq!(model, None);
    }

    #[test]
    fn a_child_that_died_stops_being_reported_as_serving() {
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        // `status()` read only the slot, never the child, so an llama-server OOM-killed
        // mid-session left the panel rendering "Serving on 127.0.0.1 — pick it in the model
        // list" for ever, over nothing, while every turn failed to connect. A real process
        // that really exits, because a stub would be asserting the stub.
        let child = Command::new("/bin/sh")
            .arg("-c")
            .arg("exit 0")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("/bin/sh runs");
        let pgid = child.id() as i32;
        let _ = child.wait_with_output();

        let dead = Command::new("/bin/sh")
            .arg("-c")
            .arg("exit 0")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("/bin/sh runs");
        // Give it a moment to actually be gone, then hand it to the module as its server.
        std::thread::sleep(Duration::from_millis(150));
        {
            let mut slot = running().lock().expect("model server lock");
            *slot = Some(Running {
                child: dead,
                pgid,
                model_path: "/models/gone.gguf".to_string(),
                ready: true,
            });
        }

        let (up, model) = status();
        assert!(!up, "a dead child is not a running server");
        assert_eq!(model, None);
        assert!(
            running().lock().expect("model server lock").is_none(),
            "the dead child is reaped, not merely reported as absent"
        );
    }

    #[test]
    fn the_port_matches_the_provider_row_that_makes_it_visible() {
        // The whole reason no new provider code was needed: `llamacpp` already points here,
        // so a running server appears in the picker through the catalog's local probe. If
        // these ever disagree the server runs and the model never shows up.
        assert_eq!(MODEL_SERVER_PORT, 8080);
        assert_eq!(MODEL_SERVER_HOST, "127.0.0.1");
    }

    #[test]
    fn a_real_child_is_started_supervised_and_swept_with_its_port() {
        // T37's claim, executed rather than argued: "a supervised loopback child, off by
        // default". Nothing in this crate had ever RUN one — the only test that called `start`
        // returned at the missing-model check — so the spawn, the readiness probe, the status
        // and the teardown were all unexercised, and `orphan_check` cannot reach them either
        // because no `llama-server` exists on this machine or on any CI runner.
        //
        // A stub runner closes that gap honestly. It is a stand-in for the RUNNER, not for the
        // model: the process is real, the port is real, the process group is real, and what is
        // proven is the supervision, which is the part Tempest owns. Whether llama.cpp serves
        // good tokens is llama.cpp's business.
        let _shared = SHARED_PORT.lock().unwrap_or_else(|e| e.into_inner());
        stop(); // whatever a previous test left

        if port_answers() {
            eprintln!("skipping: {MODEL_SERVER_PORT} is held by something else on this machine");
            return;
        }
        let Some(stub) = StubRunner::on_path() else {
            eprintln!("skipping: no python3 to build a stub runner with");
            return;
        };

        let model = a_real_file();
        let runner = start(&model, None).expect("the stub runner starts and answers");
        assert!(runner.ends_with("llama-server"), "{runner}");

        let (up, serving) = status();
        assert!(up, "a child that answers on the port is serving");
        assert_eq!(serving.as_deref(), Some(model.as_str()));
        assert!(port_answers(), "the port really is open — this is not a mocked probe");

        // Starting the same model again is the idempotent path, and must not spawn a second.
        assert!(start(&model, None).is_ok());
        assert!(status().0);

        stop();
        let (after, model_after) = status();
        assert!(!after, "stop() leaves nothing claiming to serve");
        assert_eq!(model_after, None);
        // The port goes with the child. A stop that reported success while the process kept
        // the socket is the orphan this whole struct exists to make impossible (L34).
        let mut freed = false;
        for _ in 0..40 {
            if !port_answers() {
                freed = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        drop(stub);
        assert!(freed, "the port was still answering two seconds after stop() — an orphan");
    }

    /// A directory on `PATH` holding an executable called `llama-server` that binds the model
    /// port and stays up. Removed, with its directory, on drop.
    struct StubRunner {
        _path: PathGuard,
        dir: std::path::PathBuf,
    }

    impl StubRunner {
        fn on_path() -> Option<Self> {
            let path = std::env::var_os("PATH").unwrap_or_default();
            let python = ["python3", "python"]
                .into_iter()
                .find_map(|name| which_in(&path, name))?;
            let dir = std::env::temp_dir().join(format!("tempest-stub-{}", std::process::id()));
            std::fs::create_dir_all(&dir).ok()?;

            // The server as a FILE, not an inline `-c`: a one-liner with embedded newlines and
            // nested quotes is where the first cut of this went wrong, and a stub that fails to
            // parse reports as "the runner exited before it was ready", which reads like the
            // code under test rather than the fixture.
            //
            // It speaks llama-server's READINESS PROTOCOL, because that is now the thing under
            // test: bind and start answering immediately, 503 `Loading model` for
            // `TEMPEST_STUB_LOADING_MS`, then 200 `{"status":"ok"}`. A stub that answered ok
            // from the first byte could not tell the old bare-connect probe from the new one.
            // `TEMPEST_STUB_STDOUT_BYTES` floods stdout before binding, for the pipe-drain test.
            let server = dir.join("stub_server.py");
            std::fs::write(
                &server,
                format!(
                    "import os, socketserver, sys, time\n\
                     LOADING_MS = int(os.environ.get('TEMPEST_STUB_LOADING_MS', '0'))\n\
                     FLOOD = int(os.environ.get('TEMPEST_STUB_STDOUT_BYTES', '0'))\n\
                     if FLOOD:\n\
                     \x20   sys.stdout.write('x' * FLOOD)\n\
                     \x20   sys.stdout.flush()\n\
                     START = time.monotonic()\n\n\
                     class Health(socketserver.StreamRequestHandler):\n\
                     \x20   def handle(self):\n\
                     \x20       self.rfile.readline()\n\
                     \x20       loading = (time.monotonic() - START) * 1000 < LOADING_MS\n\
                     \x20       body = b'{{\"error\":{{\"message\":\"Loading model\"}}}}' if loading else b'{{\"status\":\"ok\"}}'\n\
                     \x20       line = b'HTTP/1.1 503 Service Unavailable' if loading else b'HTTP/1.1 200 OK'\n\
                     \x20       self.wfile.write(line + b'\\r\\nContent-Length: ' + str(len(body)).encode() + b'\\r\\nConnection: close\\r\\n\\r\\n' + body)\n\n\
                     socketserver.TCPServer.allow_reuse_address = True\n\
                     socketserver.TCPServer(({MODEL_SERVER_HOST:?}, {MODEL_SERVER_PORT}), Health).serve_forever()\n"
                ),
            )
            .ok()?;

            // Ignores the argv it is handed — it stands in for the runner's LIFECYCLE, not its
            // behaviour — and holds the port until it is killed.
            let script = dir.join("llama-server");
            std::fs::write(
                &script,
                format!("#!/bin/sh\nexec {python} {}\n", server.display()),
            )
            .ok()?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).ok()?;
            }
            Some(Self { _path: PathGuard::prepending(&dir), dir })
        }
    }

    impl Drop for StubRunner {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.dir);
        }
    }

    /// Restores `PATH` on drop. Every test that needs a known PATH sets one, because the
    /// answer of `which_on_path` is otherwise a property of the developer's machine — which
    /// is how the refusal test came to assert nothing on exactly the machines where this
    /// feature is being built.
    struct PathGuard(Option<std::ffi::OsString>);

    impl PathGuard {
        /// PREPEND `dir` to `PATH`, never replace it.
        ///
        /// The two tests that need `start` to find a runner have to go through the process
        /// environment, because `start` resolves its own. Prepending keeps `PATH` a superset
        /// of what it was, so a test in another module looking for its own program still finds
        /// it — replacing it did not, and broke two.
        fn prepending(dir: &std::path::Path) -> Self {
            let previous = std::env::var_os("PATH");
            let joined = match previous.as_ref() {
                Some(existing) => {
                    let mut paths = vec![dir.to_path_buf()];
                    paths.extend(std::env::split_paths(existing));
                    std::env::join_paths(paths).expect("a joinable PATH")
                }
                None => dir.as_os_str().to_os_string(),
            };
            unsafe { std::env::set_var("PATH", joined) };
            Self(previous)
        }

        fn containing_llama_server(runner: &str) -> Self {
            let dir = std::env::temp_dir().join(format!("tempest-llama-{}", std::process::id()));
            std::fs::create_dir_all(&dir).expect("a temp dir for the fake runner");
            let link = dir.join("llama-server");
            let _ = std::fs::remove_file(&link);
            std::fs::copy(runner, &link).expect("a file named llama-server");
            Self::prepending(&dir)
        }
    }

    impl Drop for PathGuard {
        fn drop(&mut self) {
            match self.0.take() {
                Some(previous) => unsafe { std::env::set_var("PATH", previous) },
                None => unsafe { std::env::remove_var("PATH") },
            }
        }
    }
}
