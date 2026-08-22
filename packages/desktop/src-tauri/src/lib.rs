//! Tempest desktop shell: spawn the bundled engine sidecar under full supervision (owned
//! process group, health checks, crash restart) and speak JSON-RPC 2.0 over its stdio —
//! no TCP socket ever listens (CLAUDE.md §9b Boundary A). The webview reaches the sidecar
//! only through typed Tauri commands (Boundary B).

pub mod agent_tools;
pub mod commands;
pub mod framing;
pub mod generated;
pub mod keychain;
pub mod localmodel;
pub mod lsp;
pub mod pathguard;
pub mod platform;
pub mod platform_web;
pub mod runners;
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
            commands::compose_change,
            commands::search_divergences,
            commands::divergences_for_symbol,
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
            commands::start_demo_prove,
            commands::read_project_file,
            commands::local_completion,
            commands::lsp_hover,
            commands::get_editor_runners,
            commands::update_editor_runners,
        ])
        .events(tauri_specta::collect_events![
            commands::SidecarStateEvent,
            commands::RunProgressEvent
        ])
}

pub fn run() {
    let specta = specta_builder();
    tauri::Builder::default()
        // The mounted platform client's world (C3): static dist + theme seam + /api over
        // boundary E. Registered unconditionally (registration is inert without a window
        // on the scheme); the window itself is flag-gated below.
        .register_asynchronous_uri_scheme_protocol("tempest", |ctx, request, responder| {
            let app = ctx.app_handle().clone();
            let method = request.method().as_str().to_string();
            let path = request.uri().path().to_string();
            let body = request.body().clone();
            // Off the main thread: the /api arm blocks on a boundary-E round trip.
            std::thread::spawn(move || {
                let reply = match platform_web::dist_dir(&app) {
                    Some(dist) => {
                        let supervisor =
                            app.try_state::<platform::Platform>().map(|p| Arc::clone(&p.0));
                        platform_web::handle(supervisor.as_ref(), &dist, &method, &path, &body)
                    }
                    None => tauri::http::Response::builder()
                        .status(503)
                        .header("content-type", "text/plain; charset=utf-8")
                        .body(
                            b"no platform client dist: the bundled resource is missing and \
                              TEMPEST_PLATFORM_WEB_DIST is unset or not a directory"
                                .to_vec(),
                        )
                        .expect("static response"),
                };
                responder.respond(reply);
            });
        })
        .invoke_handler(specta.invoke_handler())
        .setup(move |app| {
            specta.mount_events(app);
            let data_dir = app.path().app_data_dir().expect("app data dir must resolve");
            std::fs::create_dir_all(&data_dir)?;
            let program = sidecar_program().map_err(std::io::Error::other)?;
            // Phase 20.2: the multiplexer owns every language-server process for the app's
            // lifetime. Managed state rather than a global so ONE thing owns them — NOT because
            // `Drop` runs at exit, which it does not (see `sweep_on_exit`); that belief is what
            // left language servers orphaned on every quit.
            // `Arc` so a command can clone a handle and take it onto the BLOCKING POOL:
            // `tauri::State` borrows, and blocking work must not hold a tokio worker.
            app.manage(Arc::new(std::sync::Mutex::new(lsp::Multiplexer::new(
                runners::server_specs(&data_dir),
            ))));
            // The data dir is managed so the runner commands can find the settings file without
            // re-resolving it, and so a test can point them somewhere else.
            app.manage(commands::DataDir(data_dir.clone()));
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
                transport: supervisor::Transport::Stdio,
                rpc_prefix: "rpc",
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

            // ONE window (owner decision, PLAN-V3 C3): the merged platform client is the
            // product surface, on by default. It needs two things this machine must provide
            // until a Node runtime is bundled: the built client (bundled resource, or
            // TEMPEST_PLATFORM_WEB_DIST for development) and a Node interpreter
            // (TEMPEST_PLATFORM_NODE, then PATH, then the standard install locations a
            // Finder-launched app cannot see through its minimal PATH). The pre-merge
            // desktop webview survives only as an explicit TEMPEST_LEGACY_WINDOW=1 escape
            // hatch while its views are absorbed, and as the fallback when the platform
            // surface cannot start — every fallback names its cause on stderr, never a
            // silently different app (L15.3). TEMPEST_PLATFORM_SIDECAR=0 is the kill switch.
            let legacy_forced = std::env::var("TEMPEST_LEGACY_WINDOW").as_deref() == Ok("1");
            let sidecar_off = std::env::var("TEMPEST_PLATFORM_SIDECAR").as_deref() == Ok("0");
            let dist_present = platform_web::dist_dir(app.handle()).is_some();
            let node = platform::resolve_node();
            let script = app
                .path()
                .resolve(
                    "platform/server/tempest/boundary.mjs",
                    tauri::path::BaseDirectory::Resource,
                )
                .ok()
                .filter(|p| p.is_file());
            let mut platform_ready = false;
            if legacy_forced {
                eprintln!(
                    "[tempest] TEMPEST_LEGACY_WINDOW=1 — opening the pre-merge desktop webview"
                );
            } else if sidecar_off {
                eprintln!("[tempest] TEMPEST_PLATFORM_SIDECAR=0 — platform surface disabled");
            } else if !dist_present {
                eprintln!(
                    "[tempest] platform client dist not found (no bundled resource, no \
                     TEMPEST_PLATFORM_WEB_DIST) — falling back to the legacy window"
                );
            } else if node.is_none() {
                eprintln!(
                    "[tempest] no Node runtime found (TEMPEST_PLATFORM_NODE, PATH, standard \
                     locations) — falling back to the legacy window"
                );
            } else if script.is_none() {
                eprintln!(
                    "[tempest] boundary.mjs is not bundled — falling back to the legacy window"
                );
            } else if let (Some(node), Some(script)) = (node, script) {
                // prepare_socket creates the private per-user 0700 socket directory
                // and sweeps dead siblings; the supervisor itself never touches dirs.
                // An explicit TEMPEST_PLATFORM_SOCKET wins: the orphan gate names the
                // path itself so its later file assertion is a pairing, not a
                // duplicated constant that could drift.
                let socket = match std::env::var("TEMPEST_PLATFORM_SOCKET") {
                    Ok(explicit) if !explicit.is_empty() => Ok(PathBuf::from(explicit)),
                    _ => platform::prepare_socket(),
                };
                match socket {
                    Ok(socket) => {
                        let platform_supervisor =
                            Supervisor::new(platform::spawn_config(node, script, socket));
                        app.manage(platform::Platform(Arc::clone(&platform_supervisor)));
                        std::thread::spawn(move || {
                            if let Err(err) = platform_supervisor.start() {
                                eprintln!("[tempest] platform sidecar failed to start: {err}");
                            }
                        });
                        platform_ready = true;
                    }
                    Err(err) => eprintln!(
                        "[tempest] platform socket dir failed: {err} — falling back to the \
                         legacy window"
                    ),
                }
            }

            if platform_ready {
                WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::CustomProtocol(
                        "tempest://localhost/".parse().expect("static url parses"),
                    ),
                )
                .title("Tempest AI")
                .inner_size(1280.0, 860.0)
                .min_inner_size(760.0, 520.0)
                .build()?;
            } else {
                let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                    .title("Tempest AI")
                    .inner_size(1180.0, 800.0)
                    .min_inner_size(760.0, 520.0);
                // Native macOS chrome: traffic lights inset over the sidebar, no title text —
                // the webview's fixed drag-strip keeps the window draggable (§3.1).
                #[cfg(target_os = "macos")]
                let window = window
                    .title_bar_style(tauri::TitleBarStyle::Overlay)
                    .hidden_title(true);
                window.build()?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                sweep_on_exit(app);
            }
        });
}

/// Everything this app owns a process for, stopped before the process ends (L11).
///
/// **`Drop` is not a shutdown mechanism here, and believing it was cost a real defect.** On macOS
/// `tao`'s event loop ends in `process::exit`, and tauri's own `App::run` documents that it
/// "never returns... the process is exited directly using `std::process::exit`" — which runs no
/// destructors, so no `Drop` of any managed state ever executes. The sidecar sweep was always
/// explicit here for that reason; the LSP multiplexer was not, and rested its entire no-orphans
/// argument on `impl Drop`. A `pgrep` after quitting found the language server still running.
///
/// Taken as a named function rather than written inline so it can be exercised: the closure above
/// is one call, and `sweep_on_exit` is what a test can hand a live multiplexer to.
fn sweep_on_exit<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    app.state::<Arc<watcher::RunWatcher>>().shutdown();
    // Blocking sweep: after this, no sidecar or runner process exists (L11).
    app.state::<Arc<Supervisor>>().shutdown();
    // The platform sidecar (boundary E) is a second supervised child with the same guarantee.
    if let Some(platform) = app.try_state::<platform::Platform>() {
        platform.0.shutdown();
    }
    // ...and no language server, which is a process this app started and therefore owns.
    if let Ok(mut mux) = app.state::<Arc<std::sync::Mutex<lsp::Multiplexer>>>().lock() {
        mux.shutdown_all();
    }
}
