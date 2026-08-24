//! Tempest desktop shell: spawn the bundled engine sidecar under full supervision (owned
//! process group, health checks, crash restart) and speak JSON-RPC 2.0 over its stdio —
//! no TCP socket ever listens (CLAUDE.md §9b Boundary A). The webview reaches the sidecar
//! only through typed Tauri commands (Boundary B).

pub mod agent_chat;
pub mod agent_tools;
pub mod commands;
pub mod framing;
pub mod generated;
pub mod keychain;
pub mod localmodel;
pub mod lsp;
pub mod modelserver;
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
            commands::replay_chat_turn,
            commands::list_model_catalog,
            commands::start_model_download,
            commands::get_model_download_status,
            commands::cancel_model_download,
            commands::remove_model,
            commands::model_server_status,
            commands::start_model_server,
            commands::stop_model_server,
        ])
        .events(tauri_specta::collect_events![
            commands::SidecarStateEvent,
            commands::RunProgressEvent,
            agent_chat::AgentStreamEvent
        ])
}

pub fn run() {
    platform_web::mark_process_start(std::time::Instant::now());
    let specta = specta_builder();
    tauri::Builder::default()
        // The mounted platform client's world (C3): static dist + theme seam + /api over
        // boundary E. Registered unconditionally (registration is inert without a window
        // on the scheme); the window itself is flag-gated below.
        .register_asynchronous_uri_scheme_protocol("tempest", |ctx, request, responder| {
            let app = ctx.app_handle().clone();
            let method = request.method().as_str().to_string();
            // path AND query: the key bridge routes on `?name=…`, and `uri().path()` alone
            // silently discarded every query string this protocol had ever been asked.
            let path = request
                .uri()
                .path_and_query()
                .map(|pq| pq.as_str().to_string())
                .unwrap_or_else(|| request.uri().path().to_string());
            let body = request.body().clone();
            // Off the main thread: the /api arm blocks on a boundary-E round trip.
            std::thread::spawn(move || {
                let reply = match platform_web::dist_dir(&app) {
                    Some(dist) => {
                        let supervisor =
                            app.try_state::<platform::Platform>().map(|p| Arc::clone(&p.0));
                        let engine = app.try_state::<Arc<Supervisor>>().map(|s| Arc::clone(&s));
                        platform_web::handle(
                            Some(&app),
                            supervisor.as_ref(),
                            engine.as_ref(),
                            &dist,
                            &method,
                            &path,
                            &body,
                        )
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
                env_provider: Some(Arc::new(|| keychain::engine_env(keychain::SERVICE))),
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
            // Finder-launched app cannot see through its minimal PATH). When the surface
            // cannot start, the DIAGNOSTIC surface opens with the cause and remedy on
            // screen — never a silently different app (L15.3). The pre-merge webview and
            // its TEMPEST_LEGACY_WINDOW flag are GONE (ADR-0077 close: the E2E suite now
            // drives the platform surface). TEMPEST_PLATFORM_SIDECAR=0 is the kill switch.
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
            let mut diagnostic: (&'static str, String) = ("unknown", String::new());
            if sidecar_off {
                eprintln!(
                    "[tempest] TEMPEST_PLATFORM_SIDECAR=0 — platform surface disabled, \
                     opening the diagnostic surface"
                );
                diagnostic = ("sidecar-disabled", String::new());
            } else if !dist_present {
                eprintln!(
                    "[tempest] platform client dist not found (no bundled resource, no \
                     TEMPEST_PLATFORM_WEB_DIST) — opening the diagnostic surface"
                );
                diagnostic = ("client-missing", String::new());
            } else if node.is_none() {
                eprintln!(
                    "[tempest] no Node runtime found (TEMPEST_PLATFORM_NODE, PATH, standard \
                     locations) — opening the diagnostic surface"
                );
                diagnostic = ("node-missing", String::new());
            } else if script.is_none() {
                eprintln!(
                    "[tempest] boundary.mjs is not bundled — opening the diagnostic surface"
                );
                diagnostic = ("boundary-missing", String::new());
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
                    Err(err) => {
                        eprintln!(
                            "[tempest] platform socket dir failed: {err} — opening the \
                             diagnostic surface"
                        );
                        diagnostic = ("socket-failed", err.to_string());
                    }
                }
            }

            if platform_ready {
                let window = WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::CustomProtocol(
                        "tempest://localhost/".parse().expect("static url parses"),
                    ),
                )
                .title("Tempest AI")
                .inner_size(1280.0, 860.0)
                // 800, not 760: below the client's md breakpoint (768) the sidebar becomes
                // a drawer and the overlay traffic lights would float over the chat header
                // instead of the rail inset that clears them (theme.css §7).
                .min_inner_size(800.0, 520.0);
                // Liquid glass (master prompt §12): full-bleed content under an overlay
                // titlebar, the window transparent over the NSVisualEffectView attached
                // below. The webview thins its grounds only under the `tempest-vibrancy`
                // class serve_index injects on this OS, so a failure here degrades to an
                // opaque navy pane — stated on stderr, never silent (L15.3).
                #[cfg(target_os = "macos")]
                let window = window
                    .title_bar_style(tauri::TitleBarStyle::Overlay)
                    .hidden_title(true)
                    .transparent(true);
                let window = window.build()?;
                #[cfg(target_os = "macos")]
                if let Err(err) = window_vibrancy::apply_vibrancy(
                    &window,
                    window_vibrancy::NSVisualEffectMaterial::UnderWindowBackground,
                    None,
                    None,
                ) {
                    // Withheld class = the CSS keeps opaque grounds. This runs before the
                    // webview's first navigation (setup completes first), so the page can
                    // never carry translucent grounds over a missing material.
                    platform_web::mark_vibrancy_failed();
                    eprintln!(
                        "[tempest] window vibrancy unavailable: {err} — the opaque navy \
                         ground stands"
                    );
                }
                #[cfg(not(target_os = "macos"))]
                drop(window);
            } else {
                // Every non-ready path lands here (ADR-0077 close: there is no other
                // webview to fall back to). The page names the cause and the remedy.
                let (cause, detail) = diagnostic;
                let url = format!(
                    "tempest://localhost/__tempest-diagnostic?cause={cause}&detail={}",
                    platform_web::encode_detail(&detail)
                );
                WebviewWindowBuilder::new(
                    app,
                    "main",
                    WebviewUrl::CustomProtocol(
                        url.parse().expect("slug + percent-encoded detail always parses"),
                    ),
                )
                .title("Tempest AI")
                .inner_size(760.0, 560.0)
                .min_inner_size(560.0, 420.0)
                .build()?;
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
    // ...and no model server. It is spawned into its OWN process group (so the host's death
    // signals it nothing), it is stock `llama-server` (so it has no parent-watch of its own),
    // and `Running` has no `Drop` — which per this function's own doc-comment would not run
    // anyway. Without this line, quitting left it holding 127.0.0.1:8080 and the model's
    // memory forever, with no UI remaining that could stop it.
    //
    // That is the SECOND time the argument above has been paid for in this file: the LSP
    // multiplexer rested its no-orphans case on `impl Drop` and a `pgrep` found the language
    // server still running. A comment naming a trap does not stop the next thing falling in,
    // which is why `orphan_check` now starts a model server rather than trusting this line.
    crate::modelserver::stop();
}
