//! Supervisor behavior against a REAL child process speaking the real frame protocol
//! (`frame_echo`, built by cargo for these tests): health, calls, timeout correlation,
//! crash → automatic restart, and the guaranteed no-orphan sweep on shutdown.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use serde_json::json;
use tempest_desktop_lib::supervisor::{SpawnConfig, Supervisor, DEFAULT_CALL_TIMEOUT};

fn peer_config() -> SpawnConfig {
    SpawnConfig {
        program: PathBuf::from(env!("CARGO_BIN_EXE_frame_echo")),
        // The production argument shape — the peer accepts and ignores it.
        args: vec!["--stdio".into(), "--data-dir".into(), "/tmp".into()],
        env_provider: None,
    }
}

#[test]
fn env_provider_reaches_the_child_and_survives_a_crash_restart() {
    use std::sync::Arc;
    let mut config = peer_config();
    // A planted fixture value, not a real key — the provider mechanism is what's under test.
    config.env_provider = Some(Arc::new(|| {
        vec![("TEMPEST_TEST_PLANTED_ENV".to_string(), "provider-payload-31337".to_string())]
    }));
    let supervisor = Supervisor::new(config);
    supervisor.start().expect("start + health");

    let seen = supervisor
        .call("env", json!({"name": "TEMPEST_TEST_PLANTED_ENV"}), DEFAULT_CALL_TIMEOUT)
        .expect("env call");
    assert_eq!(seen, json!({"value": "provider-payload-31337"}));

    // The provider must be consulted again on the crash-restart spawn path — a key saved in
    // Settings reaches the NEXT engine process without an app relaunch.
    let _ = supervisor.call("die", json!({}), Duration::from_millis(500));
    let deadline = Instant::now() + Duration::from_secs(10);
    let respawned = loop {
        if let Ok(value) =
            supervisor.call("env", json!({"name": "TEMPEST_TEST_PLANTED_ENV"}), DEFAULT_CALL_TIMEOUT)
        {
            break value;
        }
        assert!(Instant::now() < deadline, "peer never came back after crash");
        std::thread::sleep(Duration::from_millis(100));
    };
    assert_eq!(respawned, json!({"value": "provider-payload-31337"}));
    supervisor.shutdown();
}

#[test]
fn spawns_calls_and_shuts_down_without_orphans() {
    let supervisor = Supervisor::new(peer_config());
    supervisor.start().expect("start + health");

    let echoed = supervisor
        .call("echo", json!({"x": 41}), DEFAULT_CALL_TIMEOUT)
        .expect("echo call");
    assert_eq!(echoed, json!({"x": 41}));

    let health = supervisor
        .call("getHealth", json!({}), DEFAULT_CALL_TIMEOUT)
        .expect("health call");
    assert_eq!(health, json!({"status": "ok"}));

    supervisor.shutdown();
    let after = supervisor.call("rpc.ping", json!({}), Duration::from_millis(200));
    assert!(after.is_err(), "no live sidecar may remain after shutdown");
}

#[test]
fn restarts_after_a_crash_and_serves_again() {
    let supervisor = Supervisor::new(peer_config());
    supervisor.start().expect("start + health");
    let first_generation = supervisor.generation();

    // `die` exits the child without responding — the call fails, the monitor must respawn.
    let died = supervisor.call("die", json!({}), Duration::from_secs(5));
    assert!(died.is_err(), "a crashed child cannot have answered");

    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        if supervisor.generation() > first_generation
            && supervisor.call("rpc.ping", json!({}), Duration::from_secs(1)).is_ok()
        {
            break;
        }
        assert!(Instant::now() < deadline, "sidecar was never respawned after the crash");
        std::thread::sleep(Duration::from_millis(100));
    }

    supervisor.shutdown();
}

#[test]
fn timeouts_do_not_poison_the_stream() {
    let supervisor = Supervisor::new(peer_config());
    supervisor.start().expect("start + health");

    let slow = supervisor.call("sleep", json!({"ms": 1500}), Duration::from_millis(200));
    assert!(slow.is_err(), "the slow call must time out");

    // The late response for the timed-out id must be skipped, not returned to this call.
    let ping = supervisor
        .call("rpc.ping", json!({}), Duration::from_secs(5))
        .expect("ping after a timeout");
    assert_eq!(ping, json!({"pong": true}));

    supervisor.shutdown();
}

#[test]
fn run_watcher_pushes_progress_until_the_terminal_event_and_then_stops() {
    use std::sync::{Arc, Mutex};
    use tempest_desktop_lib::generated::domain::{RunStatus, Verdict};
    use tempest_desktop_lib::watcher::{RunProgress, RunWatcher};

    let supervisor = Supervisor::new(peer_config());
    supervisor.start().expect("start + health");

    let seen: Arc<Mutex<Vec<RunProgress>>> = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&seen);
    let watcher = RunWatcher::start(
        Arc::clone(&supervisor),
        Arc::new(move |progress| sink.lock().expect("sink lock").push(progress)),
    );

    watcher.track(7);
    // frame_echo answers PENDING twice, then COMPLETE/DIVERGENT (1s probe cadence).
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let events = seen.lock().expect("seen lock").clone();
        if events.iter().any(|e| e.status == RunStatus::Complete) {
            break;
        }
        assert!(Instant::now() < deadline, "terminal event never arrived: {events:?}");
        std::thread::sleep(Duration::from_millis(100));
    }

    let events = seen.lock().expect("seen lock").clone();
    assert!(
        events.iter().filter(|e| e.status == RunStatus::Pending).count() >= 1,
        "live PENDING progress must be pushed before the terminal event: {events:?}"
    );
    let last = events.last().expect("at least one event").clone();
    assert_eq!(last.run_id, 7);
    assert_eq!(last.status, RunStatus::Complete);
    assert_eq!(last.verdict, Some(Verdict::Divergent));

    // Terminal means untracked: no further probes, no further events.
    let count_at_terminal = seen.lock().expect("seen lock").len();
    std::thread::sleep(Duration::from_millis(2500));
    assert_eq!(
        seen.lock().expect("seen lock").len(),
        count_at_terminal,
        "a finished run must leave the watcher's tracking set"
    );

    watcher.shutdown();
    supervisor.shutdown();
}
