//! Rust leg of the §9b round-trip gate: NDJSON on stdin, one `{"type": T, "value": V}` per
//! line; V is deserialized into the GENERATED domain type T (strict typing is the test) and
//! re-serialized to stdout. A payload the generated types cannot represent is the drift this
//! gate exists to catch — it fails loudly with the offending payload.

use std::io::{stdin, stdout, BufRead, Write};

use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::Value;

use tempest_desktop_lib::generated::domain::{
    DivergenceDetail, HealthResponse, PageRunSummary, RunDetail, RunEventOut, TargetDetail,
};

fn reencode<T: DeserializeOwned + Serialize>(value: Value) -> Result<Value, String> {
    let typed: T = serde_json::from_value(value).map_err(|err| format!("deserialize: {err}"))?;
    serde_json::to_value(&typed).map_err(|err| format!("re-serialize: {err}"))
}

fn main() {
    let input = stdin().lock();
    let mut output = stdout().lock();
    for line in input.lines() {
        let line = line.expect("stdin read");
        if line.trim().is_empty() {
            continue;
        }
        let envelope: Value = serde_json::from_str(&line).expect("valid JSON envelope");
        let type_name = envelope["type"].as_str().unwrap_or("").to_string();
        let value = envelope["value"].clone();
        let result = match type_name.as_str() {
            "RunDetail" => reencode::<RunDetail>(value),
            "TargetDetail" => reencode::<TargetDetail>(value),
            "DivergenceDetail" => reencode::<DivergenceDetail>(value),
            "RunEventOut" => reencode::<RunEventOut>(value),
            "HealthResponse" => reencode::<HealthResponse>(value),
            "PageRunSummary" => reencode::<PageRunSummary>(value),
            other => Err(format!("unknown domain type {other:?}")),
        };
        let reply = match result {
            Ok(value) => serde_json::json!({"ok": value}),
            Err(message) => serde_json::json!({"error": message}),
        };
        serde_json::to_writer(&mut output, &reply).expect("stdout write");
        output.write_all(b"\n").expect("stdout newline");
    }
}
