//! Tempest desktop shell: pick a free loopback port, launch the bundled engine+API sidecar
//! against the app's data directory, and open the UI with the port injected before load.
//! The sidecar is killed when the app exits — no orphan servers.

use std::net::TcpListener;
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct Sidecar(Mutex<Option<CommandChild>>);

fn free_port() -> u16 {
    // Bind port 0 on loopback, read the assignment, release it for the sidecar to claim.
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Sidecar(Mutex::new(None)))
        .setup(|app| {
            let port = free_port();
            let data_dir = app
                .path()
                .app_data_dir()
                .expect("app data dir must resolve");
            std::fs::create_dir_all(&data_dir)?;

            let (_rx, child) = app
                .shell()
                .sidecar("tempest-server")
                .expect("sidecar binary bundled")
                .args([
                    "--port",
                    &port.to_string(),
                    "--data-dir",
                    data_dir.to_string_lossy().as_ref(),
                ])
                .spawn()
                .expect("engine sidecar failed to spawn");
            app.state::<Sidecar>().0.lock().unwrap().replace(child);

            // The UI reads this before creating its API client; retries cover startup time.
            let init = format!(
                "window.__TEMPEST_API__ = 'http://127.0.0.1:{port}';"
            );
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Tempest")
                .inner_size(1180.0, 800.0)
                .min_inner_size(760.0, 520.0)
                .initialization_script(&init)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Sidecar>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
