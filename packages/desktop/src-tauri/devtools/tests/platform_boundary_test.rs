//! Boundary E against the REAL Node endpoint over the REAL Unix socket (PLAN-V3 C2): the
//! supervised spawn, typed lifecycle calls, production validation in both directions, the
//! no-TCP-listener property, and the no-orphan shutdown. Requires `node` on PATH — the same
//! toolchain every dev machine and the CI desktop job already carry for the webview build.

use std::io::BufReader;
use std::path::PathBuf;
use std::time::Duration;

use serde_json::json;
use tempest_desktop_lib::framing::{read_frame, write_frame};
use tempest_desktop_lib::platform;
use tempest_desktop_lib::supervisor::{Supervisor, DEFAULT_CALL_TIMEOUT};

fn boundary_script() -> PathBuf {
    // devtools/ -> src-tauri/ -> desktop/ -> packages/
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let script = manifest
        .parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .expect("devtools sits three levels under packages/")
        .join("platform/server/tempest/boundary.mjs");
    assert!(script.is_file(), "boundary seam missing at {script:?}");
    script
}

fn test_socket(tag: &str) -> PathBuf {
    std::env::temp_dir().join(format!("tempest-c2-{tag}-{}.sock", std::process::id()))
}

fn spawn_boundary(tag: &str) -> (std::sync::Arc<Supervisor>, PathBuf) {
    let socket = test_socket(tag);
    let supervisor = Supervisor::new(platform::spawn_config(
        PathBuf::from("node"),
        boundary_script(),
        socket.clone(),
    ));
    supervisor.start().expect("spawn + platform.ping health");
    (supervisor, socket)
}

#[test]
fn typed_lifecycle_calls_round_trip_over_the_real_socket() {
    let (supervisor, socket) = spawn_boundary("lifecycle");

    let ping = platform::ping(&supervisor).expect("typed ping");
    assert!(ping.ok);
    assert!(ping.pid > 0);
    assert!(ping.node_version.starts_with('v'), "node reports vX.Y.Z: {}", ping.node_version);

    let described = platform::describe(&supervisor).expect("typed describe");
    let names: Vec<String> = described.methods.iter().map(|m| m.to_string()).collect();
    assert_eq!(
        names,
        ["platform.ping", "platform.describe", "platform.shutdown", "platform.http"],
        "describe lists exactly the schema's method set — content, not a frozen count"
    );

    supervisor.shutdown();
    assert!(!socket.exists(), "the socket file must not outlive the sidecar");
    assert!(
        supervisor.call("platform.ping", json!({}), Duration::from_millis(200)).is_err(),
        "no live sidecar may remain after shutdown"
    );
}

#[test]
fn an_unknown_method_is_refused_with_a_diagnostic_id() {
    let (supervisor, _socket) = spawn_boundary("unknown-method");
    let err = supervisor
        .call("platform.does_not_exist", json!({}), DEFAULT_CALL_TIMEOUT)
        .expect_err("an off-contract method cannot succeed");
    let text = err.to_string();
    assert!(text.contains("invalid request"), "refusal names the cause: {text}");
    assert!(text.contains("diagnostic"), "refusal carries a diagnostic id: {text}");
    supervisor.shutdown();
}

#[test]
fn an_unknown_envelope_field_is_rejected_in_production() {
    // Below the typed client, straight at the wire: an extra top-level field must be refused
    // by the Node side's PRODUCTION validation (additionalProperties: false), proving the
    // check is in the shipped path and not in some dev mode.
    let (supervisor, socket) = spawn_boundary("extra-field");
    let mut stream = std::os::unix::net::UnixStream::connect(&socket).expect("connect");
    let rogue = json!({
        "jsonrpc": "2.0", "id": 1, "method": "platform.ping", "params": {},
        "smuggled": true
    });
    write_frame(&mut stream, &serde_json::to_vec(&rogue).expect("encode")).expect("write");
    let mut reader = BufReader::new(stream.try_clone().expect("clone"));
    let reply: serde_json::Value =
        serde_json::from_slice(&read_frame(&mut reader).expect("reply frame")).expect("json");
    let error = reply.get("error").expect("an invalid request yields an error");
    assert_eq!(error.get("code").and_then(serde_json::Value::as_i64), Some(-32600));
    let message = error.get("message").and_then(serde_json::Value::as_str).unwrap_or("");
    assert!(message.contains("unknown field"), "the refusal names the field class: {message}");
    assert!(
        error.get("diagnostic_id").and_then(serde_json::Value::as_str).is_some(),
        "every surfaced failure carries an id (L15.3)"
    );
    supervisor.shutdown();
}

#[test]
fn the_sidecar_listens_on_no_tcp_port() {
    // The C2 gate's port probe, in-process: every listener the child holds must be a Unix
    // socket. `lsof -a -p <pid> -iTCP -sTCP:LISTEN` prints nothing for a clean child.
    let (supervisor, _socket) = spawn_boundary("no-tcp");
    let ping = platform::ping(&supervisor).expect("typed ping");
    let lsof = std::process::Command::new("lsof")
        .args(["-a", "-p", &ping.pid.to_string(), "-iTCP", "-sTCP:LISTEN"])
        .output()
        .expect("lsof runs on macOS and the CI runner");
    // lsof exits 1 when NOTHING matched (the good case); anything else is the probe itself
    // failing, and an errored probe must never read as "zero listeners" (a vacuous pass).
    let code = lsof.status.code().unwrap_or(-1);
    assert!(
        code == 0 || code == 1,
        "the port probe itself failed (lsof rc {code}): {}",
        String::from_utf8_lossy(&lsof.stderr)
    );
    let listing = String::from_utf8_lossy(&lsof.stdout);
    assert!(
        listing.trim().is_empty(),
        "the platform sidecar must never open a TCP listener; lsof saw:\n{listing}"
    );
    supervisor.shutdown();
}

#[test]
fn a_crashed_platform_sidecar_is_respawned_and_serves_again() {
    let (supervisor, _socket) = spawn_boundary("respawn");
    let first_generation = supervisor.generation();
    let first_pid = platform::ping(&supervisor).expect("first ping").pid;

    // SIGKILL the child directly — the monitor must notice and respawn a fresh one.
    let killed = std::process::Command::new("kill")
        .args(["-9", &first_pid.to_string()])
        .status()
        .expect("kill(1) exists");
    assert!(killed.success(), "SIGKILL of the child must be deliverable");
    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    let second_pid = loop {
        if supervisor.generation() > first_generation {
            if let Ok(ping) = platform::ping(&supervisor) {
                break ping.pid;
            }
        }
        assert!(
            std::time::Instant::now() < deadline,
            "the platform sidecar was never respawned after SIGKILL"
        );
        std::thread::sleep(Duration::from_millis(100));
    };
    assert_ne!(second_pid, first_pid, "the respawn is a NEW process");
    supervisor.shutdown();
}

#[test]
fn a_frame_with_two_content_length_headers_is_rejected_not_guessed() {
    // framing.rs takes the LAST occurrence; a decoder taking the FIRST would let one frame
    // read as two different lengths on the two sides. The boundary refuses ambiguity by
    // dropping the connection.
    let (supervisor, socket) = spawn_boundary("dup-length");
    let mut stream = std::os::unix::net::UnixStream::connect(&socket).expect("connect");
    use std::io::Write;
    stream
        .write_all(b"Content-Length: 5\r\nContent-Length: 40\r\n\r\nhello")
        .expect("write raw bytes");
    let mut reader = BufReader::new(stream.try_clone().expect("clone"));
    let outcome = read_frame(&mut reader);
    assert!(outcome.is_err(), "the connection must be dropped, never answered: {outcome:?}");
    supervisor.shutdown();
}

#[test]
fn a_header_with_high_bytes_is_rejected_not_ascii_masked() {
    // Decoding high bytes as ASCII masks them onto valid letters, so a garbage header could
    // still spell Content-Length. framing.rs rejects non-UTF-8 headers; the boundary must
    // reject non-ASCII rather than guess.
    let (supervisor, socket) = spawn_boundary("high-bytes");
    let mut stream = std::os::unix::net::UnixStream::connect(&socket).expect("connect");
    use std::io::Write;
    let mut raw: Vec<u8> = b"Content-Leng".to_vec();
    raw.extend([0xEC, 0xF4]); // high bytes that ascii-mask onto 'l','t'
    raw.extend(b"h: 2\r\n\r\n{}");
    stream.write_all(&raw).expect("write raw bytes");
    let mut reader = BufReader::new(stream.try_clone().expect("clone"));
    let outcome = read_frame(&mut reader);
    assert!(outcome.is_err(), "the connection must be dropped, never answered: {outcome:?}");
    supervisor.shutdown();
}

#[test]
fn the_local_api_answers_over_the_full_boundary_chain() {
    // C3's integration claim, tested at the wire: platform.http → Unix socket → Node
    // validator → the local-mode seam → typed reply. The exact chain the webview rides.
    use base64::Engine as _;
    let (supervisor, _socket) = spawn_boundary("local-api");
    let request = |method: &str, path: &str| {
        supervisor
            .call(
                "platform.http",
                json!({"request": {"method": method, "path": path, "body_base64": ""}}),
                DEFAULT_CALL_TIMEOUT,
            )
            .expect("platform.http round trip")
    };

    let config = request("GET", "/api/config");
    assert_eq!(config.get("status").and_then(serde_json::Value::as_u64), Some(200));
    let body = base64::engine::general_purpose::STANDARD
        .decode(config.get("body_base64").and_then(serde_json::Value::as_str).unwrap())
        .expect("base64 body");
    let parsed: serde_json::Value = serde_json::from_slice(&body).expect("json body");
    assert_eq!(parsed.get("appTitle").and_then(serde_json::Value::as_str), Some("Tempest AI"));
    assert_eq!(
        parsed.get("registrationEnabled").and_then(serde_json::Value::as_bool),
        Some(false),
        "local mode has no registration surface"
    );

    let refresh = request("POST", "/api/auth/refresh");
    let body = base64::engine::general_purpose::STANDARD
        .decode(refresh.get("body_base64").and_then(serde_json::Value::as_str).unwrap())
        .expect("base64 body");
    let parsed: serde_json::Value = serde_json::from_slice(&body).expect("json body");
    assert_eq!(
        parsed.pointer("/user/username").and_then(serde_json::Value::as_str),
        Some("local"),
        "the implicit local principal answers the refresh"
    );
    let token = parsed.get("token").and_then(serde_json::Value::as_str).expect("token");
    assert_eq!(token.split('.').count(), 3, "a decodable JWT shape for expiry scheduling");

    let missing = request("GET", "/api/agents");
    assert_eq!(
        missing.get("status").and_then(serde_json::Value::as_u64),
        Some(404),
        "unwired routes refuse honestly instead of faking success"
    );
    supervisor.shutdown();
}
