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
