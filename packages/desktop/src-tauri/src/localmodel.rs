//! Phase 20.3d — the local model runner. F11's "local-model capable (offline, air-gapped)".
//!
//! A llama.cpp-compatible binary is spawned per request, handed a prompt on stdin, and read for
//! a completion on stdout. It is NOT bundled: the binary and weights are the user's, named in
//! settings, and absent by default — which is why every refusal below is a first-class value
//! rather than an error string. A feature that silently does nothing when a model is missing is
//! indistinguishable from a broken one.
//!
//! **The deadline is the product decision, not an implementation detail.** §5 budgets a
//! completion at p50 120 ms, and a local model on a cold cache will miss that. Rather than let
//! the editor stall, the runner takes a deadline and the caller falls back to the offline
//! document source when it expires. Ghost text that arrives late is worse than ghost text that
//! is merely good: it appears under a cursor that has moved on. 20.3a already refuses stale
//! suggestions; this is the same rule enforced one layer down, before the tokens are even spent.

use std::io::{Read, Write};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

/// Why a local completion could not be produced. Each names a fact, never a guess.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum ModelError {
    /// No local model is configured. The expected state on a fresh install, not a failure.
    NotConfigured,
    /// A model is configured but its binary could not be launched — usually "moved or deleted".
    Unlaunchable,
    /// The model did not answer inside the deadline. The caller falls back; it does not stall.
    Deadline,
    /// The process ended without producing a usable completion.
    NoCompletion,
}

impl std::fmt::Display for ModelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotConfigured => write!(f, "no local model is configured"),
            Self::Unlaunchable => write!(f, "the local model could not be started"),
            Self::Deadline => write!(f, "the local model did not answer in time"),
            Self::NoCompletion => write!(f, "the local model returned nothing usable"),
        }
    }
}

/// How to run the user's model. `None` is the default and means "no local model".
#[derive(Debug, Clone)]
pub struct ModelSpec {
    pub program: String,
    pub args: Vec<String>,
}

pub struct LocalModel {
    spec: Option<ModelSpec>,
}

impl LocalModel {
    pub fn new(spec: Option<ModelSpec>) -> Self {
        Self { spec }
    }

    /// Ask for a completion, or refuse before the deadline.
    ///
    /// The process is killed when the deadline expires. A model left running after the answer is
    /// no longer wanted burns the user's battery to produce text nobody will read.
    pub fn complete(&self, prompt: &str, deadline: Duration) -> Result<String, ModelError> {
        let spec = self.spec.as_ref().ok_or(ModelError::NotConfigured)?;
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Own process group, exactly as `supervisor.rs` does for the sidecar and `lsp.rs`
            // for a language server. `TEMPEST_LOCAL_MODEL` is whitespace-split, so naming a
            // model whose path contains a space REQUIRES a wrapper script — which means the
            // common configuration is a shim whose real work is a grandchild. A probe against
            // a two-line wrapper printed `GRANDCHILD alive=true` after `child.kill()`: the
            // model keeps burning battery producing text nobody will read, which is the exact
            // outcome the deadline exists to prevent.
            command.process_group(0);
        }
        let mut child = command.spawn().map_err(|_| ModelError::Unlaunchable)?;
        let pgid = i32::try_from(child.id()).unwrap_or(0);

        let mut stdin = child.stdin.take().ok_or(ModelError::Unlaunchable)?;
        let mut stdout = child.stdout.take().ok_or(ModelError::Unlaunchable)?;
        let prompt_bytes = prompt.as_bytes().to_vec();
        std::thread::spawn(move || {
            // A model that never reads its prompt must not wedge us on the write.
            let _ = stdin.write_all(&prompt_bytes);
            let _ = stdin.flush();
        });

        let (tx, rx) = mpsc::channel();
        let mut reader = Some(std::thread::spawn(move || {
            let mut out = String::new();
            let read = stdout.read_to_string(&mut out);
            let _ = tx.send(read.map(|_| out));
        }));

        let outcome = rx.recv_timeout(deadline);
        // ONE sweep, on every path including success.
        //
        // The old code called `child.wait()` with no kill after a good answer, which assumes the
        // model exits once it has written. An interactive llama.cpp REPL does not: it writes its
        // completion and waits for the next prompt, and `wait()` then blocks for the life of the
        // process. The answer is already in hand; the process is no longer wanted; sweep it.
        let sweep = |child: &mut std::process::Child| {
            crate::supervisor::terminate_group(pgid);
            crate::supervisor::kill_group(pgid);
            let _ = child.kill();
            let _ = child.wait();
        };
        let verdict = match outcome {
            Ok(Ok(text)) => {
                sweep(&mut child);
                // Two different questions, and conflating them mangles real completions.
                //
                // IS IT A COMPLETION AT ALL? — asked of `text.trim()`, so a model answering a
                // single space or a tab is refused. The old check was
                // `trim_end_matches('\n')`, which let those through as an invisible "accept me"
                // under Tab, and the test that claimed to pin it drove the ONE whitespace string
                // the newline trim happens to handle (trap 43).
                //
                // WHAT DO WE RETURN? — the text with only its trailing newline removed. LEADING
                // whitespace is the completion: a mid-token FIM prompt ending in `\n` is
                // answered with `    return x`, and `trim()` would delete the indentation and
                // insert the body at column zero. The first fix here used `trim()` for both and
                // silently broke every indented answer.
                if text.trim().is_empty() {
                    Err(ModelError::NoCompletion)
                } else {
                    Ok(text.trim_end_matches('\n').to_string())
                }
            }
            Ok(Err(_)) => {
                sweep(&mut child);
                Err(ModelError::NoCompletion)
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // Kill, do not detach: see the doc comment above.
                sweep(&mut child);
                Err(ModelError::Deadline)
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                sweep(&mut child);
                Err(ModelError::NoCompletion)
            }
        };
        // Joining is what makes "abandoned" false: the sweep closes the pipe, the reader returns,
        // and this function does not leave a blocked thread and an open fd behind per F11 press.
        if let Some(handle) = reader.take() {
            let _ = handle.join();
        }
        verdict
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::Instant;
    use std::path::PathBuf;

    /// A REAL model process (L4). States enumerated before the tests, because a runner's
    /// behaviour is defined by a child it does not control: no model configured · the binary is
    /// missing · it answers normally · it answers NOTHING · it answers only whitespace · it is
    /// slower than the deadline · it never reads the prompt at all · it exits without writing.
    struct Fake {
        dir: PathBuf,
    }

    impl Fake {
        fn new(tag: &str) -> Self {
            let dir = std::env::temp_dir().join(format!("tempest-model-{}-{tag}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).expect("fixture dir");
            Self { dir }
        }

        fn spec(&self, behaviour: &str) -> ModelSpec {
            let script = self.dir.join(format!("model_{behaviour}.py"));
            fs::write(&script, FAKE_MODEL.replace("__BEHAVIOUR__", behaviour)).expect("script");
            ModelSpec {
                program: "python3".to_string(),
                args: vec![script.to_string_lossy().into_owned()],
            }
        }
    }

    impl Drop for Fake {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }

    const FAKE_MODEL: &str = r#"
import os, subprocess, sys, time
BEHAVIOUR = "__BEHAVIOUR__"
if BEHAVIOUR == "slow":
    time.sleep(30)
    sys.stdout.write("too late\n")
elif BEHAVIOUR == "silent":
    pass
elif BEHAVIOUR == "whitespace":
    sys.stdout.write("\n\n")
elif BEHAVIOUR == "spaces":
    # The whitespace the newline trim CANNOT see. Ordinary for a mid-token FIM prompt.
    sys.stdout.write("   ")
elif BEHAVIOUR == "tab":
    sys.stdout.write("\t\n")
elif BEHAVIOUR == "indented":
    # A mid-token FIM answer: the leading whitespace IS the completion.
    sys.stdout.write("    return total\n")
elif BEHAVIOUR == "deaf":
    # Never reads stdin — the runner must not wedge on the write.
    sys.stdout.write("answered without listening\n")
elif BEHAVIOUR == "shim":
    # A wrapper that runs the real model as a CHILD — which is what naming a model whose path
    # contains a space forces, because TEMPEST_LOCAL_MODEL is whitespace-split.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "grandchild.pid"), "w") as fh:
        fh.write(str(child.pid))
    sys.stdout.write("wrapped\n")
    sys.stdout.flush()
    time.sleep(120)
elif BEHAVIOUR == "never_exits":
    # Answers, CLOSES its stdout, and then lives on. The close is what matters: it gives the
    # reader EOF, so the answer really does arrive and the success path really is taken — and
    # that is the path whose `child.wait()` then had nothing to wait for but a process that
    # never ends. (A model that merely keeps stdout open is a different, already-handled case:
    # the read blocks and the deadline fires.)
    sys.stdout.write("an answer\n")
    sys.stdout.flush()
    os.close(1)
    time.sleep(120)
else:
    prompt = sys.stdin.read()
    sys.stdout.write("completion for: " + prompt.strip()[-12:] + "\n")
sys.stdout.flush()
"#;

    const QUICK: Duration = Duration::from_secs(5);

    #[test]
    fn no_configured_model_is_a_state_not_a_failure() {
        // The expected state on a fresh install. It must be distinguishable from a broken one.
        let model = LocalModel::new(None);
        assert_eq!(model.complete("x", QUICK), Err(ModelError::NotConfigured));
    }

    #[test]
    fn a_configured_model_answers() {
        let f = Fake::new("ok");
        let model = LocalModel::new(Some(f.spec("ok")));
        let out = model.complete("def calculateTotal", QUICK).expect("an answer");
        assert!(out.starts_with("completion for:"), "{out}");
        assert!(out.contains("culateTotal"), "{out}");
    }

    #[test]
    fn a_missing_binary_is_reported_not_hung() {
        let model = LocalModel::new(Some(ModelSpec {
            program: "tempest-no-such-model-binary".into(),
            args: vec![],
        }));
        assert_eq!(model.complete("x", QUICK), Err(ModelError::Unlaunchable));
    }

    #[test]
    fn a_model_slower_than_the_deadline_is_abandoned_not_awaited() {
        // §5 budgets 120 ms. A local model on a cold cache misses that, and the editor must fall
        // back rather than stall — ghost text that arrives late lands under a moved cursor.
        let f = Fake::new("slow");
        let model = LocalModel::new(Some(f.spec("slow")));
        let started = Instant::now();
        assert_eq!(model.complete("x", Duration::from_millis(300)), Err(ModelError::Deadline));
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "the deadline must bind, not merely be declared"
        );
    }

    #[test]
    fn a_model_that_says_nothing_is_not_a_completion() {
        let f = Fake::new("silent");
        let model = LocalModel::new(Some(f.spec("silent")));
        assert_eq!(model.complete("x", QUICK), Err(ModelError::NoCompletion));
    }

    #[test]
    fn whitespace_is_not_a_completion_either() {
        // An all-whitespace answer would render as an invisible "accept me" under Tab — the same
        // defect completionPolicy refuses one layer up, refused here before it can be shown.
        let f = Fake::new("whitespace");
        let model = LocalModel::new(Some(f.spec("whitespace")));
        assert_eq!(model.complete("x", QUICK), Err(ModelError::NoCompletion));
    }

    #[test]
    fn whitespace_the_newline_trim_cannot_see_is_still_not_a_completion() {
        // The old check was `trim_end_matches('\n')`, and the old test drove the ONE whitespace
        // string that happens to handle. Spaces and tabs came back as completions — an invisible
        // "accept me" under Tab. Every line was covered; the state was never set up (trap 43).
        for behaviour in ["spaces", "tab", "whitespace"] {
            let f = Fake::new(behaviour);
            let model = LocalModel::new(Some(f.spec(behaviour)));
            assert_eq!(
                model.complete("x", QUICK),
                Err(ModelError::NoCompletion),
                "{behaviour} is not a completion"
            );
        }
    }

    #[test]
    fn leading_whitespace_is_the_completion_and_survives() {
        // A FIM prompt ending in a newline is answered with an INDENTED line, and the indentation
        // is the answer. The first version of the whitespace fix used `trim()` for both the
        // is-this-a-completion test and the returned value, which deleted that indentation and
        // would have inserted the body at column zero — a regression introduced by a fix.
        let f = Fake::new("indented");
        let model = LocalModel::new(Some(f.spec("indented")));
        assert_eq!(model.complete("def total(xs):\n", QUICK).as_deref(), Ok("    return total"));
    }

    #[test]
    fn a_model_that_answers_and_then_keeps_running_is_swept_not_awaited() {
        // A model that writes its completion, closes stdout, and lives on — a served daemon, or
        // llama.cpp keeping a session warm. The answer arrives, so the SUCCESS path is taken,
        // and that path called `child.wait()` with no kill: `complete` then blocked there for
        // the life of the process, holding a Tauri command thread. The first version of this
        // test had the fake keep stdout open instead, and the code corrected me — that state is
        // the already-handled one where the read blocks and the deadline fires.
        let f = Fake::new("never-exits");
        let model = LocalModel::new(Some(f.spec("never_exits")));
        let started = Instant::now();
        assert_eq!(model.complete("x", QUICK).as_deref(), Ok("an answer"));
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "an answer in hand must not wait on a process that never exits"
        );
    }

    #[test]
    fn the_sweep_reaps_a_wrapper_model_grandchild() {
        // `TEMPEST_LOCAL_MODEL` is whitespace-split, so a model whose path contains a space can
        // only be named through a wrapper script — which makes "the real model is a grandchild"
        // the COMMON configuration, not an exotic one. A probe showed `child.kill()` leaving it
        // alive: the model keeps burning battery producing text nobody will read, which is the
        // exact outcome the deadline exists to prevent.
        let f = Fake::new("shim");
        let model = LocalModel::new(Some(f.spec("shim")));
        assert_eq!(model.complete("x", Duration::from_millis(400)), Err(ModelError::Deadline));
        let grandchild: i32 = fs::read_to_string(f.dir.join("grandchild.pid"))
            .expect("the wrapper records its grandchild")
            .trim()
            .parse()
            .expect("a pid");
        for _ in 0..50 {
            if unsafe { libc::kill(grandchild, 0) } != 0 {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert_ne!(
            unsafe { libc::kill(grandchild, 0) },
            0,
            "the model's own child must not outlive the deadline that killed its parent"
        );
    }

    #[test]
    fn a_model_that_never_reads_the_prompt_does_not_wedge_the_runner() {
        // Writing a large prompt to a child that never reads it fills the pipe and blocks
        // forever if the write is done inline. It is done on its own thread for exactly this.
        let f = Fake::new("deaf");
        let model = LocalModel::new(Some(f.spec("deaf")));
        let huge = "x".repeat(512 * 1024);
        let out = model.complete(&huge, QUICK).expect("an answer despite the unread prompt");
        assert_eq!(out, "answered without listening");
    }

    #[test]
    fn every_refusal_reads_as_a_sentence() {
        for refusal in [
            ModelError::NotConfigured,
            ModelError::Unlaunchable,
            ModelError::Deadline,
            ModelError::NoCompletion,
        ] {
            let text = refusal.to_string();
            assert!(!text.is_empty(), "{refusal:?} has no message");
            assert!(!text.contains('/'), "{refusal:?} leaks a path: {text}");
        }
    }
}
