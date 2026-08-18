//! Tempest desktop shell: spawn the bundled engine sidecar under full supervision (owned
//! process group, health checks, crash restart) and speak JSON-RPC 2.0 over its stdio —
//! no TCP socket ever listens (CLAUDE.md §9b Boundary A). The webview reaches the sidecar
//! only through typed Tauri commands (Boundary B).

pub mod commands;
pub mod framing;
pub mod generated;
pub mod keychain;
pub mod supervisor;
pub mod watcher;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

use supervisor::{SpawnConfig, Supervisor};

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

/// Boundary B command registry — the single list `tauri-specta` exports to
/// `packages/desktop/src/generated/bindings.ts` and the app registers as its invoke handler.
pub fn specta_builder() -> tauri_specta::Builder<tauri::Wry> {
    tauri_specta::Builder::<tauri::Wry>::new()
        .commands(tauri_specta::collect_commands![
            commands::get_health,
            commands::list_runs,
            commands::get_run,
            commands::list_run_events,
            commands::get_target,
            commands::get_divergence,
            commands::get_divergence_repro,
            commands::start_local_prove,
            commands::search_divergences,
            commands::cancel_run,
            commands::list_log_records,
            commands::ai_key_status,
            commands::set_ai_key,
            commands::clear_ai_key,
            commands::get_settings,
            commands::update_settings,
            commands::test_ai_key,
            commands::sync_push,
            commands::export_diagnostics,
            commands::reveal_in_data_dir,
            commands::get_watch_status,
            commands::start_watch,
            commands::stop_watch,
            commands::report_ui_error,
        ])
        .events(tauri_specta::collect_events![
            commands::SidecarStateEvent,
            commands::RunProgressEvent
        ])
}

pub fn run() {
    let specta = specta_builder();
    tauri::Builder::default()
        .invoke_handler(specta.invoke_handler())
        .setup(move |app| {
            specta.mount_events(app);
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
                // A keychain-stored AI key rides into every engine spawn as
                // ANTHROPIC_API_KEY (keychain.rs — L9: env only, never files/DB/logs).
                env_provider: Some(Arc::new(|| {
                    keychain::engine_env(keychain::SERVICE, keychain::ACCOUNT)
                })),
            });
            let handle = app.handle().clone();
            supervisor.set_listener(Arc::new(move |state: &str| {
                use tauri_specta::Event;
                let _ = commands::SidecarStateEvent { state: state.to_string() }.emit(&handle);
            }));
            app.manage(Arc::clone(&supervisor));
            // Central run watcher (§1.2): pushes typed RunProgressEvent for live runs so no
            // view owns a fast timer. Its emit closure is the only bridge to the event bus.
            let progress_handle = app.handle().clone();
            let run_watcher = Arc::new(watcher::RunWatcher::start(
                Arc::clone(&supervisor),
                Arc::new(move |progress: watcher::RunProgress| {
                    use tauri_specta::Event;
                    let _ = commands::RunProgressEvent {
                        run_id: progress.run_id,
                        status: progress.status,
                        verdict: progress.verdict,
                    }
                    .emit(&progress_handle);
                }),
            ));
            app.manage(Arc::clone(&run_watcher));
            // Health-wait happens off the main thread — the window appears immediately and the
            // UI shows sidecar state from the events above until the first ping succeeds.
            std::thread::spawn(move || {
                if let Err(err) = supervisor.start() {
                    eprintln!("[tempest] sidecar failed to start: {err}");
                }
            });

            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Tempest")
                .inner_size(1180.0, 800.0)
                .min_inner_size(760.0, 520.0);
            // Native macOS chrome: traffic lights inset over the sidebar, no title text —
            // the webview's fixed drag-strip keeps the window draggable (§3.1).
            #[cfg(target_os = "macos")]
            let window = window
                .title_bar_style(tauri::TitleBarStyle::Overlay)
                .hidden_title(true);
            window.build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                app.state::<Arc<watcher::RunWatcher>>().shutdown();
                // Blocking sweep: after this, no sidecar or runner process exists (L11).
                app.state::<Arc<Supervisor>>().shutdown();
            }
        });
}
