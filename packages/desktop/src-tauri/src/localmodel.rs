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
use std::time::{Duration, Instant};

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
        let mut child = Command::new(&spec.program)
            .args(&spec.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| ModelError::Unlaunchable)?;

        let mut stdin = child.stdin.take().ok_or(ModelError::Unlaunchable)?;
        let mut stdout = child.stdout.take().ok_or(ModelError::Unlaunchable)?;
        let prompt_bytes = prompt.as_bytes().to_vec();
        std::thread::spawn(move || {
            // A model that never reads its prompt must not wedge us on the write.
            let _ = stdin.write_all(&prompt_bytes);
            let _ = stdin.flush();
        });

        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let mut out = String::new();
            let read = stdout.read_to_string(&mut out);
            let _ = tx.send(read.map(|_| out));
        });

        let started = Instant::now();
        let outcome = rx.recv_timeout(deadline);
        let _ = started;
        match outcome {
            Ok(Ok(text)) => {
                let _ = child.wait();
                let trimmed = text.trim_end_matches('\n').to_string();
                if trimmed.is_empty() {
                    return Err(ModelError::NoCompletion);
                }
                Ok(trimmed)
            }
            Ok(Err(_)) => {
                let _ = child.kill();
                let _ = child.wait();
                Err(ModelError::NoCompletion)
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                // Kill, do not detach: see the doc comment above.
                let _ = child.kill();
                let _ = child.wait();
                Err(ModelError::Deadline)
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                let _ = child.wait();
                Err(ModelError::NoCompletion)
            }
        }
    }

    pub fn is_configured(&self) -> bool {
        self.spec.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
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
import sys, time
BEHAVIOUR = "__BEHAVIOUR__"
if BEHAVIOUR == "slow":
    time.sleep(30)
    sys.stdout.write("too late\n")
elif BEHAVIOUR == "silent":
    pass
elif BEHAVIOUR == "whitespace":
    sys.stdout.write("\n\n")
elif BEHAVIOUR == "deaf":
    # Never reads stdin — the runner must not wedge on the write.
    sys.stdout.write("answered without listening\n")
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
        assert!(!model.is_configured());
        assert_eq!(model.complete("x", QUICK), Err(ModelError::NotConfigured));
    }

    #[test]
    fn a_configured_model_answers() {
        let f = Fake::new("ok");
        let model = LocalModel::new(Some(f.spec("ok")));
        assert!(model.is_configured());
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
