//! Phase 20.6 — where the editor's two runners are configured, and what they resolve to.
//!
//! A language server and a local model are both "a program on this machine that Tempest will
//! start". Until now the only way to name either was an environment variable — `TEMPEST_LSP_
//! PYTHON`, `TEMPEST_LSP_TYPESCRIPT`, `TEMPEST_LOCAL_MODEL` — set before launching the app. The
//! handoff called that out as one of three things Phase 20 could not be called complete without,
//! and it is right: **an undiscoverable feature is one nobody has.** The owner of this product
//! does not launch apps from a shell with an env prefix, so on their machine F11 falls back
//! forever and hover is silent forever, and nothing anywhere says why.
//!
//! ## Why this is desktop-local and not a Boundary A domain type
//!
//! `commands::ProjectFile` set the precedent and its reasoning applies unchanged: nothing about
//! which binary this host spawns for a hover exists in the Pydantic model, and minting a domain
//! shape for a desktop-local capability would put a fiction in the contract. The engine neither
//! knows nor cares that a language server exists. So this is a Tauri-local type, stored beside
//! the app's other local state, and the four-boundary gate is unaffected.
//!
//! ## The environment still wins, and says so
//!
//! Settings never silently disagree with reality — that rule already governs the engine settings
//! screen, which disables a control and names the variable forcing it. The same rule here: an
//! env var overrides the stored value AND is reported as `forced_by`, so a user who set one in a
//! launcher plist can see why the box they typed in is being ignored.
//!
//! ## What this does NOT do
//!
//! It does not validate that a command is safe to run. It cannot: any program the user names is
//! a program the user has chosen to run, exactly as it was when the only way to name one was an
//! env var. What it does do is say whether the program can be FOUND, because "I typed it and
//! nothing happened" is the failure this surface exists to prevent. The residual is stated in
//! ADR-0046 rather than implied: a webview that could be made to call `update_editor_runners`
//! with attacker-chosen text would be choosing a binary this host later spawns. Nothing routes
//! model output into settings today, and the CSP forbids injected script; that is the whole of
//! the mitigation, and it is written down rather than assumed.

use std::path::{Path, PathBuf};

/// The file, inside the app's data dir. JSON because a human may need to read or repair it, and
/// because a settings file nobody can inspect is a settings file nobody can trust.
const FILE: &str = "editor-runners.json";

/// One runner, as the user typed it: a whole command line, split on whitespace at the point of
/// use exactly as the environment variables have always been.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize, specta::Type)]
#[serde(default)]
pub struct EditorRunners {
    /// The Python language server command, e.g. `pyright-langserver --stdio`.
    pub python_lsp: String,
    /// The TypeScript language server command, e.g. `typescript-language-server --stdio`.
    pub typescript_lsp: String,
    /// The local completion model command, e.g. `llama-cli -m /models/x.gguf`.
    pub local_model: String,
}

/// Which field an environment variable is forcing, and which variable it is.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
pub struct RunnerOverride {
    /// The field name as the UI knows it: `python_lsp`, `typescript_lsp`, `local_model`.
    pub field: String,
    pub variable: String,
}

/// Whether a configured command can actually be started.
///
/// Reported per runner rather than inferred from a failed hover, because the two failures look
/// identical from the outside and only one of them is the user's to fix.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
pub struct RunnerStatus {
    pub field: String,
    /// The command line in EFFECT — the env var if one is forcing, else the stored value.
    pub command: String,
    /// True when the program resolves to a file this process may EXECUTE — the execute bit is
    /// checked, not merely existence, because "found" is a claim about startability.
    pub found: bool,
}

/// Everything the settings screen needs in one round trip.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
pub struct EditorRunnersOut {
    /// The STORED document — what the text boxes should contain, never the env overlay. Showing
    /// the effective value in an editable box would make a forced setting look editable.
    pub stored: EditorRunners,
    pub forced: Vec<RunnerOverride>,
    pub status: Vec<RunnerStatus>,
    /// Where the file lives, so "where are my settings" has an answer.
    pub path: String,
}

fn path_in(data_dir: &Path) -> PathBuf {
    data_dir.join(FILE)
}

/// Read the stored document. A missing or unreadable file is the DEFAULT, never an error: a
/// fresh install has no file, and a corrupted one must not stop the editor from opening.
pub fn load(data_dir: &Path) -> EditorRunners {
    std::fs::read_to_string(path_in(data_dir))
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

/// Write the stored document, creating the data dir if it is not there yet.
pub fn save(data_dir: &Path, runners: &EditorRunners) -> std::io::Result<()> {
    std::fs::create_dir_all(data_dir)?;
    let body = serde_json::to_string_pretty(runners).map_err(std::io::Error::other)?;
    std::fs::write(path_in(data_dir), body)
}

/// The environment variable for each field, in the order the UI shows them.
const VARIABLES: [(&str, &str); 3] = [
    ("python_lsp", "TEMPEST_LSP_PYTHON"),
    ("typescript_lsp", "TEMPEST_LSP_TYPESCRIPT"),
    ("local_model", "TEMPEST_LOCAL_MODEL"),
];

fn field_of(runners: &EditorRunners, field: &str) -> String {
    match field {
        "python_lsp" => runners.python_lsp.clone(),
        "typescript_lsp" => runners.typescript_lsp.clone(),
        // Exhaustive over VARIABLES, which is the only caller.
        _ => runners.local_model.clone(),
    }
}

/// A non-empty environment override for `field`, if one is set.
fn override_for(variable: &str) -> Option<String> {
    std::env::var(variable).ok().filter(|value| !value.trim().is_empty())
}

/// The command line in effect for one field: the environment first, then the stored value.
pub fn effective(runners: &EditorRunners, field: &str) -> String {
    VARIABLES
        .iter()
        .find(|(name, _)| *name == field)
        .and_then(|(_, variable)| override_for(variable))
        .unwrap_or_else(|| field_of(runners, field))
}

/// Split a command line into a program and its arguments, or `None` when it names nothing.
pub fn parse_command(command: &str) -> Option<(String, Vec<String>)> {
    let mut parts = command.split_whitespace().map(str::to_string);
    let program = parts.next().filter(|p| !p.is_empty())?;
    Some((program, parts.collect()))
}

/// Can this program be started? An absolute or relative path is checked directly; a bare name is
/// looked up on `PATH`, which is what `Command::new` will do.
///
/// **A regular file is not an executable.** The first version checked only `is_file()`, so a
/// downloaded model wrapper still sitting at mode 644 — the single most likely thing a user
/// misconfigures — reported "found", and then `spawn` failed with a permission error the settings
/// screen had just promised would not happen. `found` is a claim about startability, so it checks
/// the execute bit.
fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::metadata(path)
            .map(|meta| meta.is_file() && meta.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

fn resolves(program: &str) -> bool {
    let candidate = Path::new(program);
    if candidate.components().count() > 1 || candidate.is_absolute() {
        return is_executable(candidate);
    }
    std::env::var_os("PATH")
        .map(|paths| std::env::split_paths(&paths).any(|dir| is_executable(&dir.join(program))))
        .unwrap_or(false)
}

/// The whole settings view, for one round trip.
pub fn describe(data_dir: &Path) -> EditorRunnersOut {
    let stored = load(data_dir);
    let mut forced = Vec::new();
    let mut status = Vec::new();
    for (field, variable) in VARIABLES {
        if override_for(variable).is_some() {
            forced.push(RunnerOverride {
                field: field.to_string(),
                variable: variable.to_string(),
            });
        }
        // ...and the arguments variable, which is not an override of the FIELD but does change
        // what gets spawned. A setting the user cannot see is a setting they cannot fix.
        if field == "local_model" && override_for("TEMPEST_LOCAL_MODEL_ARGS").is_some() {
            forced.push(RunnerOverride {
                field: field.to_string(),
                variable: "TEMPEST_LOCAL_MODEL_ARGS".to_string(),
            });
        }
        // The command as it will ACTUALLY be spawned, including the pieces that come from
        // elsewhere. `TEMPEST_LOCAL_MODEL_ARGS` changes what runs and appeared in neither
        // `forced` nor `status`, so the screen showed one command and the host ran another.
        let (command, found) = match field {
            "local_model" => match model_spec(data_dir) {
                Some(spec) => {
                    let shown = std::iter::once(spec.program.clone())
                        .chain(spec.args.iter().cloned())
                        .collect::<Vec<_>>()
                        .join(" ");
                    (shown, resolves(&spec.program))
                }
                None => (String::new(), false),
            },
            _ => {
                let command = effective(&stored, field);
                let found = parse_command(&command).is_some_and(|(p, _)| resolves(&p));
                (command, found)
            }
        };
        status.push(RunnerStatus { field: field.to_string(), command, found });
    }
    EditorRunnersOut {
        stored,
        forced,
        status,
        path: path_in(data_dir).to_string_lossy().into_owned(),
    }
}

/// The language-server specs this host will run, from settings and the environment.
pub fn server_specs(data_dir: &Path) -> Vec<crate::lsp::ServerSpec> {
    let stored = load(data_dir);
    [("python", "python_lsp"), ("typescript", "typescript_lsp")]
        .into_iter()
        .filter_map(|(language, field)| {
            let (program, args) = parse_command(&effective(&stored, field))?;
            Some(crate::lsp::ServerSpec { language: language.to_string(), program, args })
        })
        .collect()
}

/// The local model spec, or `None` when none is configured — the fresh-install state.
pub fn model_spec(data_dir: &Path) -> Option<crate::localmodel::ModelSpec> {
    let stored = load(data_dir);
    // The ENV VAR names a PROGRAM, whole — it always has, and splitting it on whitespace would
    // break every existing launcher whose model path contains a space. The SETTINGS field is a
    // command line, because that is what a text box in a settings screen is for. Two different
    // shapes, stated here rather than discovered by a user whose model stopped starting.
    let (program, mut args) = match override_for("TEMPEST_LOCAL_MODEL") {
        Some(whole) => (whole.trim().to_string(), Vec::new()),
        None => parse_command(&stored.local_model)?,
    };
    // `TEMPEST_LOCAL_MODEL_ARGS` predates this surface and still appends, so a launcher that set
    // both keeps working rather than silently losing its arguments.
    if let Ok(extra) = std::env::var("TEMPEST_LOCAL_MODEL_ARGS") {
        args.extend(extra.split_whitespace().map(str::to_string));
    }
    Some(crate::localmodel::ModelSpec { program, args })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A private data dir per test. Env vars are process-global, so the tests that set them are
    /// serialised by a mutex rather than left to race each other into a flake.
    struct Dir {
        path: PathBuf,
    }

    impl Dir {
        fn new(tag: &str) -> Self {
            let path =
                std::env::temp_dir().join(format!("tempest-runners-{}-{tag}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).expect("fixture dir");
            Self { path }
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// Serialises EVERY test in this module that touches process environment state.
    ///
    /// **Readers need this as much as writers, and getting that wrong made a flaky test.** cargo
    /// runs tests as threads in ONE process and environment variables are process-global, so a
    /// test that merely READS through `describe`/`server_specs`/`model_spec` can observe a
    /// variable another test has temporarily set. The first version put the lock inside
    /// `EnvGuard`, which covered only the setters:
    /// `only_configured_languages_produce_a_server_spec` then saw `TEMPEST_LSP_PYTHON` set by
    /// `the_environment_wins_and_is_reported_as_forcing` and read `env-server` where it expected
    /// `pyright-langserver`. It failed 2 runs in 6 — and passed the two full `make verify` runs
    /// before that, which is what makes this worse than a consistent failure.
    ///
    /// Every test takes it, including the ones that touch no environment today, so a later test
    /// that starts reading one cannot silently reopen the race.
    fn env_lock() -> std::sync::MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// Sets an env var for the duration of the guard, then restores exactly what was there.
    ///
    /// The caller must already hold `env_lock()`. The lock is NOT taken here: `std::sync::Mutex`
    /// is not reentrant, so a test that locked and then constructed a guard would deadlock.
    struct EnvGuard {
        key: &'static str,
        previous: Option<String>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let previous = std::env::var(key).ok();
            // SAFETY: every test in this module takes `env_lock()` as its first statement, so
            // no other test is reading or writing the environment while this guard lives. The
            // first version put the lock inside this guard, which serialised only the SETTERS —
            // and the readers raced, which is precisely the flake that made this comment false.
            unsafe { std::env::set_var(key, value) };
            Self { key, previous }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            match &self.previous {
                Some(value) => unsafe { std::env::set_var(self.key, value) },
                None => unsafe { std::env::remove_var(self.key) },
            }
        }
    }

    #[test]
    fn a_fresh_install_has_no_runners_and_that_is_not_an_error() {
        let _env = env_lock();
        let dir = Dir::new("fresh");
        assert_eq!(load(&dir.path), EditorRunners::default());
        let view = describe(&dir.path);
        assert_eq!(view.stored, EditorRunners::default());
        assert!(view.forced.is_empty());
        assert_eq!(view.status.len(), 3, "every runner is reported, configured or not");
        assert!(view.status.iter().all(|s| !s.found), "nothing is configured, so nothing resolves");
        assert!(view.path.ends_with(FILE));
    }

    #[test]
    fn what_is_saved_is_what_is_loaded() {
        let _env = env_lock();
        let dir = Dir::new("roundtrip");
        let runners = EditorRunners {
            python_lsp: "pyright-langserver --stdio".into(),
            typescript_lsp: String::new(),
            local_model: "/models/run.sh".into(),
        };
        save(&dir.path, &runners).expect("save");
        assert_eq!(load(&dir.path), runners);
    }

    #[test]
    fn a_corrupt_file_reads_as_defaults_rather_than_stopping_the_editor() {
        let _env = env_lock();
        // A settings file a user hand-edited into invalid JSON must not be the reason the editor
        // will not open. The screen shows the defaults; saving repairs the file.
        let dir = Dir::new("corrupt");
        std::fs::write(path_in(&dir.path), "{ not json").expect("write");
        assert_eq!(load(&dir.path), EditorRunners::default());
    }

    #[test]
    fn a_file_written_by_an_older_version_keeps_the_fields_it_has() {
        let _env = env_lock();
        // `#[serde(default)]`: a document missing a field must not fail to parse, or a later
        // release adding a runner would wipe the two the user already configured.
        let dir = Dir::new("partial");
        std::fs::write(path_in(&dir.path), r#"{"python_lsp": "pyright"}"#).expect("write");
        let loaded = load(&dir.path);
        assert_eq!(loaded.python_lsp, "pyright");
        assert_eq!(loaded.typescript_lsp, "");
    }

    #[test]
    fn the_environment_wins_and_is_reported_as_forcing() {
        let _env = env_lock();
        // The rule the engine settings screen already follows: a control that silently disagrees
        // with reality is a lie. A user who set this in a launcher plist has to be able to SEE
        // why the box they typed in is being ignored.
        let dir = Dir::new("forced");
        save(
            &dir.path,
            &EditorRunners { python_lsp: "stored-server".into(), ..Default::default() },
        )
        .expect("save");
        let _guard = EnvGuard::set("TEMPEST_LSP_PYTHON", "env-server --stdio");
        let view = describe(&dir.path);
        assert_eq!(view.stored.python_lsp, "stored-server", "the BOX still shows what was typed");
        assert_eq!(
            view.forced,
            vec![RunnerOverride {
                field: "python_lsp".into(),
                variable: "TEMPEST_LSP_PYTHON".into()
            }]
        );
        let python = view.status.iter().find(|s| s.field == "python_lsp").expect("a status");
        assert_eq!(python.command, "env-server --stdio", "the EFFECT is the environment's");
    }

    #[test]
    fn an_empty_environment_variable_does_not_count_as_forcing() {
        let _env = env_lock();
        // `FOO=` in a launcher plist is how a variable gets unset in practice. Treating it as an
        // override would blank a working configuration and report it as forced.
        let dir = Dir::new("blank-env");
        save(&dir.path, &EditorRunners { python_lsp: "stored".into(), ..Default::default() })
            .expect("save");
        let _guard = EnvGuard::set("TEMPEST_LSP_PYTHON", "   ");
        let view = describe(&dir.path);
        assert!(view.forced.is_empty());
        assert_eq!(effective(&view.stored, "python_lsp"), "stored");
    }

    #[test]
    fn a_program_that_exists_is_reported_found_and_one_that_does_not_is_not() {
        let _env = env_lock();
        // "I typed it and nothing happened" is the failure this surface exists to prevent, and
        // a missing binary is indistinguishable from a broken one from outside.
        let dir = Dir::new("resolve");
        // A file that exists but is NOT executable — mode 644, which is exactly how a
        // downloaded model wrapper arrives, and the single most likely misconfiguration.
        let not_executable = dir.path.join("not-executable.sh");
        std::fs::write(&not_executable, "#!/bin/sh\n").expect("write");
        save(
            &dir.path,
            &EditorRunners {
                python_lsp: "/bin/sh -c true".into(),
                typescript_lsp: not_executable.to_string_lossy().into_owned(),
                local_model: "sh".into(),
            },
        )
        .expect("save");
        let view = describe(&dir.path);
        let found = |field: &str| {
            view.status.iter().find(|s| s.field == field).expect("a status").found
        };
        assert!(found("python_lsp"), "an absolute path that exists and is executable resolves");
        assert!(
            !found("typescript_lsp"),
            "a file that exists but cannot be EXECUTED is not found — `found` is a claim about \
             startability, and reporting it would promise a spawn that fails on permissions"
        );
        assert!(found("local_model"), "a bare name found on PATH resolves");
    }

    #[test]
    fn a_missing_name_on_path_is_not_found() {
        let _env = env_lock();
        let dir = Dir::new("missing-name");
        save(
            &dir.path,
            &EditorRunners { python_lsp: "definitely-not-a-real-binary-xyz".into(), ..Default::default() },
        )
        .expect("save");
        let view = describe(&dir.path);
        assert!(!view.status.iter().find(|s| s.field == "python_lsp").expect("status").found);
    }

    #[test]
    fn the_env_var_names_a_whole_program_and_is_never_split() {
        let _env = env_lock();
        // It never was split, and splitting it would break every launcher whose model path
        // contains a space — the exact shape a wrapper script has, since a path with a space is
        // WHY a wrapper exists. The settings field is a command line; the env var is a program.
        let dir = Dir::new("whole-program");
        let _guard = EnvGuard::set("TEMPEST_LOCAL_MODEL", "/Users/me/My Models/run.sh");
        let spec = model_spec(&dir.path).expect("a model");
        assert_eq!(spec.program, "/Users/me/My Models/run.sh");
        assert!(spec.args.is_empty());
    }

    #[test]
    fn the_settings_field_is_a_command_line() {
        let _env = env_lock();
        let dir = Dir::new("settings-command");
        save(&dir.path, &EditorRunners { local_model: "llama-cli -m x.gguf".into(), ..Default::default() })
            .expect("save");
        let spec = model_spec(&dir.path).expect("a model");
        assert_eq!(spec.program, "llama-cli");
        assert_eq!(spec.args, vec!["-m", "x.gguf"]);
    }

    #[test]
    fn the_args_variable_is_reported_because_it_changes_what_runs() {
        let _env = env_lock();
        // It appends to the spawned command, so a screen that does not show it shows one command
        // while the host runs another. A setting the user cannot see is one they cannot fix.
        let dir = Dir::new("args-visible");
        save(&dir.path, &EditorRunners { local_model: "llama-cli".into(), ..Default::default() })
            .expect("save");
        let _guard = EnvGuard::set("TEMPEST_LOCAL_MODEL_ARGS", "--threads 4");
        let view = describe(&dir.path);
        assert!(
            view.forced.iter().any(|o| o.variable == "TEMPEST_LOCAL_MODEL_ARGS"),
            "the args variable must be reported: {:?}",
            view.forced
        );
        let status = view.status.iter().find(|s| s.field == "local_model").expect("status");
        assert_eq!(
            status.command, "llama-cli --threads 4",
            "the status shows what will ACTUALLY be spawned"
        );
    }

    #[test]
    fn a_command_line_becomes_a_program_and_its_arguments() {
        let _env = env_lock();
        assert_eq!(
            parse_command("pyright-langserver --stdio --verbose"),
            Some(("pyright-langserver".into(), vec!["--stdio".into(), "--verbose".into()]))
        );
        assert_eq!(parse_command("solo"), Some(("solo".into(), vec![])));
        // Nothing named is not a runner — not an empty program with no arguments.
        assert_eq!(parse_command(""), None);
        assert_eq!(parse_command("   \t "), None);
    }

    #[test]
    fn only_configured_languages_produce_a_server_spec() {
        let _env = env_lock();
        let dir = Dir::new("specs");
        save(
            &dir.path,
            &EditorRunners {
                python_lsp: "pyright-langserver --stdio".into(),
                typescript_lsp: String::new(),
                local_model: String::new(),
            },
        )
        .expect("save");
        let specs = server_specs(&dir.path);
        assert_eq!(specs.len(), 1, "an empty command is not a server");
        assert_eq!(specs[0].language, "python");
        assert_eq!(specs[0].program, "pyright-langserver");
        assert_eq!(specs[0].args, vec!["--stdio".to_string()]);
        assert!(model_spec(&dir.path).is_none(), "no model configured is None, not an error");
    }

    #[test]
    fn the_legacy_args_variable_still_appends() {
        let _env = env_lock();
        // `TEMPEST_LOCAL_MODEL_ARGS` predates this surface. A launcher that set both must keep
        // working rather than silently losing its arguments the day settings arrived.
        let dir = Dir::new("legacy-args");
        let _model = EnvGuard::set("TEMPEST_LOCAL_MODEL", "/models/llama-cli");
        let _guard = EnvGuard::set("TEMPEST_LOCAL_MODEL_ARGS", "-m x.gguf --threads 4");
        let spec = model_spec(&dir.path).expect("a model");
        assert_eq!(spec.program, "/models/llama-cli");
        assert_eq!(spec.args, vec!["-m", "x.gguf", "--threads", "4"]);
    }
}
