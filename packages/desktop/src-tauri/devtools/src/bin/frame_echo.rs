//! Test peer for the supervisor: a real process speaking the real frame protocol (nothing is
//! mocked — Law L4), with just enough verbs to exercise health, echo, latency, crash, and
//! shutdown paths. Accepts and ignores the production sidecar's CLI arguments.

use std::collections::HashMap;
use std::io::{stdin, stdout, BufReader, Write};

use serde_json::{json, Value};
use tempest_desktop_lib::framing::{read_frame, write_frame, FrameError};

fn main() {
    let mut reader = BufReader::new(stdin().lock());
    let mut writer = stdout().lock();
    let mut run_probes: HashMap<i64, u64> = HashMap::new();
    loop {
        let frame = match read_frame(&mut reader) {
            Ok(frame) => frame,
            Err(FrameError::Eof) => return,
            Err(err) => {
                eprintln!("frame_echo: {err}");
                return;
            }
        };
        let request: Value = match serde_json::from_slice(&frame) {
            Ok(value) => value,
            Err(err) => {
                eprintln!("frame_echo: bad json: {err}");
                return;
            }
        };
        let id = request.get("id").cloned().unwrap_or(Value::Null);
        let method = request.get("method").and_then(Value::as_str).unwrap_or("");
        let params = request.get("params").cloned().unwrap_or_else(|| json!({}));
        let result = match method {
            "rpc.ping" => json!({"pong": true}),
            "getHealth" => json!({"status": "ok"}),
            "echo" => params,
            "sleep" => {
                let ms = params.get("ms").and_then(Value::as_u64).unwrap_or(0);
                std::thread::sleep(std::time::Duration::from_millis(ms));
                json!({"slept_ms": ms})
            }
            "getRun" => {
                // Run-watcher fuel: a run is PENDING for its first two probes, then lands
                // COMPLETE/DIVERGENT — the real getRun answer shape, minus the detail the
                // watcher's probe deserializer ignores anyway.
                let run_id = params.get("run_id").and_then(Value::as_i64).unwrap_or(0);
                let calls = run_probes.entry(run_id).or_insert(0);
                *calls += 1;
                if *calls <= 2 {
                    json!({"id": run_id, "status": "PENDING", "verdict": null})
                } else {
                    json!({"id": run_id, "status": "COMPLETE", "verdict": "DIVERGENT"})
                }
            }
            "env" => {
                // Proof surface for SpawnConfig::env_provider: what did THIS process inherit?
                let name = params.get("name").and_then(Value::as_str).unwrap_or("");
                json!({"value": std::env::var(name).ok()})
            }
            "die" => std::process::exit(3), // crash without responding — restart-path fuel
            "rpc.shutdown" => {
                respond(&mut writer, &id, json!({"ok": true}));
                return;
            }
            other => {
                let error = json!({"code": -32601, "message": format!("unknown {other}")});
                let response = json!({"jsonrpc": "2.0", "id": id, "error": error});
                write_frame(&mut writer, &serde_json::to_vec(&response).unwrap())
                    .expect("write error frame");
                continue;
            }
        };
        respond(&mut writer, &id, result);
    }
}

fn respond(writer: &mut impl Write, id: &Value, result: Value) {
    let response = json!({"jsonrpc": "2.0", "id": id, "result": result});
    write_frame(writer, &serde_json::to_vec(&response).unwrap()).expect("write frame");
}
