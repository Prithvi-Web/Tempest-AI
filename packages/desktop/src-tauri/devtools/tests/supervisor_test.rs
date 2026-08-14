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
    }
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
