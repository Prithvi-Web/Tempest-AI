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
}

impl std::fmt::Display for ModelServerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::RunnerMissing(m)
            | Self::ModelMissing(m)
            | Self::NeverReady(m)
            | Self::Spawn(m) => write!(f, "{m}"),
        }
    }
}

struct Running {
    child: Child,
    pgid: i32,
    model_path: String,
}

static RUNNING: OnceLock<Arc<Mutex<Option<Running>>>> = OnceLock::new();

fn running() -> &'static Arc<Mutex<Option<Running>>> {
    RUNNING.get_or_init(|| Arc::new(Mutex::new(None)))
}

/// Where the runner binary is, in resolution order: an explicit setting, then `PATH`.
///
/// Nothing is bundled yet, and the refusal says so rather than pretending otherwise
/// (ADR-0080 §6). Bundling a signed `llama-server` per platform is what makes this feature
/// fully zero-setup, and it is recorded as a C8 plan item rather than a comment.
pub(crate) fn resolve_runner(configured: Option<&str>) -> Result<String, ModelServerError> {
    if let Some(path) = configured.filter(|p| !p.trim().is_empty()) {
        if std::path::Path::new(path).is_file() {
            return Ok(path.to_string());
        }
        return Err(ModelServerError::RunnerMissing(format!(
            "the configured model runner {path} is not a file — check the path in Settings, \
             or clear it to search your PATH instead"
        )));
    }
    if let Some(found) = which_on_path("llama-server") {
        return Ok(found);
    }
    Err(ModelServerError::RunnerMissing(
        "no `llama-server` was found on your PATH. Tempest does not bundle one yet, so serving \
         a downloaded model needs it installed — `brew install llama.cpp` on macOS. Your \
         downloaded models are kept and will work as soon as it is there."
            .to_string(),
    ))
}

fn which_on_path(program: &str) -> Option<String> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|dir| dir.join(program))
        .find(|candidate| candidate.is_file())
        .map(|candidate| candidate.to_string_lossy().into_owned())
}

/// True when something is answering on the model port. Used as the readiness probe and by the
/// status call — an HTTP server's readiness cannot be observed on a pipe that does not exist,
/// which is the whole reason this child needed its own supervision struct.
pub(crate) fn port_answers() -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}")
            .parse()
            .expect("a literal loopback address parses"),
        Duration::from_millis(250),
    )
    .is_ok()
}

/// Start a server for `model_path`, or return the one already running for it.
pub(crate) fn start(
    model_path: &str,
    configured_runner: Option<&str>,
) -> Result<String, ModelServerError> {
    if !std::path::Path::new(model_path).is_file() {
        return Err(ModelServerError::ModelMissing(format!(
            "{model_path} is not on disk — download the model first"
        )));
    }
    let runner = resolve_runner(configured_runner)?;

    {
        let live = running().lock().expect("model server lock");
        if let Some(current) = live.as_ref() {
            if current.model_path == model_path {
                return Ok(runner);
            }
        }
    }
    // A different model was serving: stop it first. One port, one server — starting a second
    // would fail to bind and leave the user with the OLD model answering while the UI said
    // otherwise, which is worse than a clear stop-and-start.
    stop();

    let mut command = Command::new(&runner);
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

    let mut child = command
        .spawn()
        .map_err(|err| ModelServerError::Spawn(format!("could not start {runner}: {err}")))?;
    let pgid = child.id() as i32;
    if let Some(stderr) = child.stderr.take() {
        std::thread::Builder::new()
            .name("model-server-stderr".into())
            .spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    eprintln!("[llama-server] {line}");
                }
            })
            .ok();
    }

    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        if port_answers() {
            let mut live = running().lock().expect("model server lock");
            *live = Some(Running { child, pgid, model_path: model_path.to_string() });
            return Ok(runner);
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(ModelServerError::NeverReady(format!(
                "{runner} exited before it was ready ({status}) — see the log for what it said"
            )));
        }
        if Instant::now() >= deadline {
            kill_group(pgid);
            let _ = child.kill();
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
    if let Some(mut current) = taken {
        terminate_group(current.pgid);
        // A brief grace, then the group — the same belt-and-braces every other child gets.
        for _ in 0..20 {
            if matches!(current.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        kill_group(current.pgid);
        let _ = current.child.kill();
        let _ = current.child.wait();
    }
}

/// What the settings panel renders: whether a server is up, and for which model.
pub(crate) fn status() -> (bool, Option<String>) {
    let live = running().lock().expect("model server lock");
    match live.as_ref() {
        Some(current) => (true, Some(current.model_path.clone())),
        None => (false, None),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_model_file_is_refused_before_any_process_is_spawned() {
        // The order matters: resolving a runner that does not exist would otherwise report
        // "install llama.cpp" to someone whose actual problem is a model they never downloaded.
        let err = start("/nope/not-a-model.gguf", Some("/nope/not-a-runner")).unwrap_err();
        assert!(matches!(err, ModelServerError::ModelMissing(_)), "{err:?}");
        assert!(err.to_string().contains("download the model first"));
    }

    #[test]
    fn a_configured_runner_that_is_not_a_file_names_the_setting() {
        let err = resolve_runner(Some("/definitely/not/here")).unwrap_err();
        assert!(err.to_string().contains("check the path in Settings"));
    }

    #[test]
    fn an_empty_configured_runner_falls_through_to_the_path_search() {
        // Blank is not a configured value: the panel writes "" when a user clears the field,
        // and treating that as a path would refuse with a nonsense message about "".
        let blank = resolve_runner(Some("   "));
        let none = resolve_runner(None);
        assert_eq!(blank.is_ok(), none.is_ok());
    }

    #[test]
    fn a_missing_runner_names_the_install_step_and_keeps_the_models() {
        // ADR-0080 §6: the one place this feature is not yet zero-setup, said out loud rather
        // than left as a silence. If a real llama-server IS on this machine's PATH the search
        // succeeds, and the refusal text is not what is under test.
        let Err(err) = resolve_runner(None) else {
            return;
        };
        let text = err.to_string();
        assert!(text.contains("brew install llama.cpp"), "{text}");
        assert!(text.contains("models are kept"), "{text}");
    }

    #[test]
    fn the_exit_sweep_stops_this_child_too() {
        // The defect this pins is the one `sweep_on_exit`'s own doc-comment already describes:
        // the LSP multiplexer once rested its no-orphans case on `impl Drop`, and a `pgrep`
        // after quitting found the language server still running. The model server walked into
        // the same trap one function later — spawned into its OWN process group (so the host's
        // death signals it nothing), stock `llama-server` (so no parent-watch of its own), and
        // `Running` has no `Drop`, which per that comment would not run anyway.
        //
        // Asserted as a SOURCE fact rather than by launching a real server, because the honest
        // end-to-end proof is `orphan_check` starting one — and that is where it now lives. A
        // comment naming a trap does not stop the next thing falling in; this makes the sweep's
        // membership checkable.
        let lib = include_str!("lib.rs");
        let sweep = lib
            .split_once("fn sweep_on_exit")
            .expect("sweep_on_exit exists")
            .1;
        let body = sweep.split_once("\n}").expect("the sweep has a body").0;
        assert!(
            body.contains("modelserver::stop()"),
            "sweep_on_exit does not stop the model server: quitting the app would leave \
             llama-server holding {MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} and the model's \
             memory, with no UI left that could stop it (L34, L11)"
        );
    }

    #[test]
    fn stopping_nothing_is_harmless() {
        stop();
        let (up, model) = status();
        assert!(!up);
        assert_eq!(model, None);
    }

    #[test]
    fn the_bind_address_is_loopback_and_never_the_wildcard() {
        // A model server on 0.0.0.0 is one anyone on the same wifi can use, and would fail
        // `orphan_check`'s port probe. Pinned as a value because the string is easy to widen
        // in a hurry and hard to notice in review.
        assert_eq!(MODEL_SERVER_HOST, "127.0.0.1");
        assert_ne!(MODEL_SERVER_HOST, "0.0.0.0");
    }

    #[test]
    fn the_port_matches_the_provider_row_that_makes_it_visible() {
        // The whole reason no new provider code was needed: `llamacpp` already points here,
        // so a running server appears in the picker through the catalog's local probe. If
        // these ever disagree the server runs and the model never shows up.
        assert_eq!(MODEL_SERVER_PORT, 8080);
    }
}
