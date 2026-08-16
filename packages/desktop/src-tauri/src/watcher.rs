//! Central run watcher (HANDOFF-WORLD-CLASS §1.2): ONE place polls the sidecar for live
//! runs — once per second per tracked run — and pushes a typed `RunProgressEvent` to the
//! webview. Views react to events instead of owning timers; their own polling survives only
//! as a slow fallback (the browser E2E harness has no Rust host, and a webview that missed
//! events must still converge).
//!
//! Tracking is explicit: `start_local_prove` registers the run it created; a run leaves the
//! set the moment a probe sees a terminal status (COMPLETE/CANCELLED — the final event
//! carries it). Probe failures keep the run tracked and emit nothing: a crashed sidecar is
//! the supervisor's story (SidecarStateEvent), not this one's, and the post-restart probe
//! resumes silently. The watcher thread parks when nothing is tracked — zero idle cost
//! (L11: the user's machine is not a busy-loop host).

use std::collections::HashMap;
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use serde_json::json;

use crate::generated::domain::{RunStatus, Verdict};
use crate::supervisor::Supervisor;

const PROBE_INTERVAL: Duration = Duration::from_secs(1);
const PROBE_TIMEOUT: Duration = Duration::from_secs(5);

/// What a probe learned about a tracked run — the payload pushed to the webview.
#[derive(Debug, Clone, PartialEq)]
pub struct RunProgress {
    pub run_id: i32,
    pub status: RunStatus,
    pub verdict: Option<Verdict>,
}

/// The subset of `getRun` the watcher needs; serde ignores the rest of the detail.
#[derive(serde::Deserialize)]
struct RunProbe {
    status: RunStatus,
    verdict: Option<Verdict>,
}

type EmitFn = Arc<dyn Fn(RunProgress) + Send + Sync>;

struct Shared {
    tracked: Mutex<HashMap<i32, ()>>,
    wake: Condvar,
    stopped: Mutex<bool>,
}

pub struct RunWatcher {
    shared: Arc<Shared>,
}

impl RunWatcher {
    pub fn start(supervisor: Arc<Supervisor>, emit: EmitFn) -> Self {
        let shared = Arc::new(Shared {
            tracked: Mutex::new(HashMap::new()),
            wake: Condvar::new(),
            stopped: Mutex::new(false),
        });
        let thread_shared = Arc::clone(&shared);
        std::thread::Builder::new()
            .name("run-watcher".into())
            .spawn(move || watch_loop(&thread_shared, &supervisor, &emit))
            .expect("spawn run-watcher thread");
        RunWatcher { shared }
    }

    /// Register a live run (called by `start_local_prove` with the id the engine answered).
    pub fn track(&self, run_id: i32) {
        self.shared.tracked.lock().expect("tracked lock").insert(run_id, ());
        self.shared.wake.notify_all();
    }

    pub fn shutdown(&self) {
        *self.shared.stopped.lock().expect("stopped lock") = true;
        self.shared.wake.notify_all();
    }
}

fn watch_loop(shared: &Shared, supervisor: &Supervisor, emit: &EmitFn) {
    loop {
        // Park while idle; tick while any run is live.
        {
            let mut stopped = shared.stopped.lock().expect("stopped lock");
            loop {
                if *stopped {
                    return;
                }
                if !shared.tracked.lock().expect("tracked lock").is_empty() {
                    break;
                }
                stopped = shared.wake.wait(stopped).expect("watcher wait");
            }
        }

        let ids: Vec<i32> =
            shared.tracked.lock().expect("tracked lock").keys().copied().collect();
        for run_id in ids {
            let answer = supervisor.call("getRun", json!({ "run_id": run_id }), PROBE_TIMEOUT);
            let Ok(value) = answer else { continue }; // sidecar down/restarting — keep tracking
            let Ok(probe) = serde_json::from_value::<RunProbe>(value) else { continue };
            let terminal = probe.status != RunStatus::Pending;
            emit(RunProgress { run_id, status: probe.status, verdict: probe.verdict });
            if terminal {
                shared.tracked.lock().expect("tracked lock").remove(&run_id);
            }
        }

        let (stopped_guard, _timeout) = shared
            .wake
            .wait_timeout(shared.stopped.lock().expect("stopped lock"), PROBE_INTERVAL)
            .expect("watcher tick wait");
        if *stopped_guard {
            return;
        }
    }
}
