//! Tempest desktop shell: spawn the bundled engine sidecar under full supervision (owned
//! process group, health checks, crash restart) and speak JSON-RPC 2.0 over its stdio —
//! no TCP socket ever listens (CLAUDE.md §9b Boundary A). The webview reaches the sidecar
//! only through typed Tauri commands (Boundary B).

pub mod framing;
pub mod supervisor;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

use supervisor::{SpawnConfig, Supervisor, DEFAULT_CALL_TIMEOUT};

/// Bundled beside the app binary in production; staged by build-server.sh in dev.
fn sidecar_program() -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|err| format!("current_exe: {err}"))?;
    let beside = exe
        .parent()
        .ok_or_else(|| "app binary has no parent directory".to_string())?
        .join("tempest-server");
    if beside.exists() {
        return Ok(beside);
    }
    let staged = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("binaries")
        .join(format!("tempest-server-{}", env!("TEMPEST_TARGET_TRIPLE")));
    if staged.exists() {
        return Ok(staged);
    }
    Err(format!(
        "tempest-server sidecar not found beside {exe:?} nor at {staged:?} — run \
         packages/desktop/build-server.sh"
    ))
}

/// Boundary B stepping stone: one generic bridge command, replaced by per-operation typed
/// commands + generated bindings in the tri-boundary contract step.
#[tauri::command]
fn sidecar_call(
    state: tauri::State<'_, Arc<Supervisor>>,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    state.call(&method, params, DEFAULT_CALL_TIMEOUT).map_err(|err| err.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let data_dir = app.path().app_data_dir().expect("app data dir must resolve");
            std::fs::create_dir_all(&data_dir)?;
            let program = sidecar_program().map_err(std::io::Error::other)?;
            let supervisor = Supervisor::new(SpawnConfig {
                program,
                args: vec![
                    "--stdio".into(),
                    "--data-dir".into(),
                    data_dir.to_string_lossy().into_owned(),
                ],
            });
            let handle = app.handle().clone();
            supervisor.set_listener(Arc::new(move |state: &str| {
                let _ = handle.emit("sidecar-state", state.to_string());
            }));
            app.manage(Arc::clone(&supervisor));
            // Health-wait happens off the main thread — the window appears immediately and the
            // UI shows sidecar state from the events above until the first ping succeeds.
            std::thread::spawn(move || {
                if let Err(err) = supervisor.start() {
                    eprintln!("[tempest] sidecar failed to start: {err}");
                }
            });

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Tempest")
                .inner_size(1180.0, 800.0)
                .min_inner_size(760.0, 520.0)
                .build()?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar_call])
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                // Blocking sweep: after this, no sidecar or runner process exists (L11).
                app.state::<Arc<Supervisor>>().shutdown();
            }
        });
}
