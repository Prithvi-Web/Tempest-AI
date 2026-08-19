//! One place where "may this path be read?" is decided.
//!
//! Phase 20.1. The editor is the first caller; Phase 21's orchestrator dispatch for the
//! `read_file` agent tool is the second. There is deliberately ONE module rather than one per
//! caller: `agent_tools::ReadFileArgs` documents that absolute paths, `..` traversal and the
//! credential denylist "are rejected by the orchestrator, not by the model", and a rule stated in
//! two implementations is a rule that can disagree with itself — the same reasoning that put the
//! Agent Tool Protocol behind a generated contract (ADR-0035).
//!
//! The checks run cheapest-first, and the last of them is the one that is easy to miss: the
//! denylist is applied to the RESOLVED path as well as the requested one, because a symlink named
//! `notes.txt` pointing at `.env` passes every lexical check ever written.

use std::path::{Component, Path, PathBuf};

/// Why a path was refused. Each variant names a decision, never a filesystem detail: the message
/// reaches a UI, and "no" plus a reason is a product surface (L7).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, specta::Type)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum PathRefusal {
    /// Empty, or containing an interior NUL — not a path this product will interpret.
    Malformed,
    /// Absolute paths name a machine, not a project.
    Absolute,
    /// A `..` component. Rejected outright rather than normalised: a rule you can evaluate by
    /// reading it is worth more than one that needs a whiteboard.
    Traversal,
    /// Resolved to somewhere outside the project root — a symlink pointing out.
    EscapesRoot,
    /// A credential-bearing path (`.env`, `.ssh`, keychains). Matched case-insensitively because
    /// macOS filesystems are case-insensitive by default, so `.ENV` opens `.env`'s bytes.
    Credential,
    NotFound,
    /// Present, but this process may not traverse to it — a different fact from "not there".
    Unreadable,
    /// A directory, device, or socket. Only regular files are readable here.
    NotAFile,
    /// More than one directory entry points at these bytes. A hard link IS the file — there is
    /// no link target to inspect and `canonicalize` returns the innocent name you asked with —
    /// so a name-based denylist cannot see it at all. A review probe read `.env` through a hard
    /// link named `notes.txt` and every check above passed. A file with more than one name
    /// therefore cannot be judged by the name it was requested under, and is refused.
    HardLinked,
    /// Not valid UTF-8 — an editor buffer is text, and showing a binary as replacement
    /// characters would invite someone to "save" it back and destroy the file.
    NotText,
    /// The root named is not a project. Containment is only as strong as the root it confines
    /// to, so a caller cannot widen the guard by naming `/` and asking for `etc/passwd`.
    NotAProject,
    /// Larger than the caller's cap. Unbounded reads are a budget violation (L15.4).
    TooLarge {
        // u64 in Rust, because a file's size is a u64 and the message must state it truthfully.
        // NOT on the wire: specta forbids BigInt-style types, and the `f64` workaround exported
        // `bytes: number | null` — a null this code can never emit, i.e. a contract that lies in
        // the one place the project generates contracts to stop lying. The numbers already reach
        // the UI inside `message`; sending them twice, once wrongly typed, bought nothing.
        #[serde(skip)]
        bytes: u64,
        #[serde(skip)]
        cap: u64,
    },
}

impl std::fmt::Display for PathRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed => write!(f, "not a usable path"),
            Self::Absolute => write!(f, "absolute paths are not project paths"),
            Self::Traversal => write!(f, "`..` is not allowed in a project path"),
            Self::EscapesRoot => write!(f, "that path resolves outside the project"),
            Self::Credential => write!(f, "that path holds credentials and is never read"),
            Self::NotFound => write!(f, "no such file in the project"),
            Self::Unreadable => write!(f, "that file could not be opened"),
            Self::NotAFile => write!(f, "not a regular file"),
            Self::TooLarge { bytes, cap } => write!(f, "{bytes} bytes exceeds the {cap}-byte cap"),
            Self::NotAProject => write!(f, "that folder is not a project Tempest can open"),
            Self::NotText => write!(f, "that file is not text"),
            Self::HardLinked => write!(f, "that file has more than one name and cannot be vouched for"),
        }
    }
}

/// Path segments that carry credentials. Compared case-folded (see [`PathRefusal::Credential`]).
const DENIED_SEGMENTS: &[&str] = &[
    // $HOME-shaped secrets that a project can still contain
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    "id_rsa",
    // ssh-keygen has defaulted to ed25519 for years; naming only id_rsa denies the legacy key
    // and passes the modern one.
    "id_ed25519",
    "id_ecdsa",
    // ...and the ones that live in the project root the guard is pointed at. `.git` is the
    // sharpest: the NotAProject check GUARANTEES it is present under every accepted root, and
    // `.git/config` carries remote URLs with embedded tokens.
    ".git",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
];
/// Suffixes that carry credentials wherever they appear.
const DENIED_SUFFIXES: &[&str] = &[".keychain", ".keychain-db", ".pem", ".p12", ".pfx", ".key"];

fn is_credential_segment(segment: &str) -> bool {
    let lower = segment.to_ascii_lowercase();
    if DENIED_SEGMENTS.iter().any(|d| lower == *d) {
        return true;
    }
    // `.env.local`, `.env.production` — the family, not just the bare name.
    if lower.starts_with(".env") {
        return true;
    }
    DENIED_SUFFIXES.iter().any(|d| lower.ends_with(d))
}

fn any_credential_component(path: &Path) -> bool {
    path.components().any(|c| match c {
        Component::Normal(os) => os.to_str().is_some_and(is_credential_segment),
        _ => false,
    })
}

/// Resolve `rel` inside `root`, or refuse with a reason.
///
/// **Neither argument is trusted.** An earlier version of this comment said "`root` is trusted
/// (it is the project the user opened)" — it is not: `root` arrives from `?repo=` in the webview
/// URL, exactly as `repo_path` does for `start_local_prove`, and nothing has asked a human about
/// it. That is why the root must itself be a git working tree: containment is only as strong as
/// the thing it confines to, and a caller free to name `/` has no containment at all.
pub fn resolve_within(root: &Path, rel: &str, max_bytes: u64) -> Result<PathBuf, PathRefusal> {
    // Cheapest and most certain first: these need no filesystem at all, so a hostile path is
    // rejected before it can cause a single syscall.
    if rel.is_empty() || rel.contains('\0') {
        return Err(PathRefusal::Malformed);
    }
    let requested = Path::new(rel);
    for component in requested.components() {
        match component {
            Component::ParentDir => return Err(PathRefusal::Traversal),
            Component::Prefix(_) | Component::RootDir => return Err(PathRefusal::Absolute),
            Component::CurDir | Component::Normal(_) => {}
        }
    }
    if any_credential_component(requested) {
        return Err(PathRefusal::Credential);
    }

    // Containment is only as strong as the root, and the root arrives from the webview — the
    // same place `start_local_prove` gets `repo_path`. Every root this product works with is a
    // git working tree (shadow worktrees, prove, watch all assume it), and `/` is not one, so
    // requiring it removes "name a bigger root" as a way to widen the guard.
    if !root.join(".git").exists() {
        return Err(PathRefusal::NotAProject);
    }

    // The root is trusted but not necessarily canonical — on macOS `/tmp` is a symlink to
    // `/private/tmp`, so comparing against the pretty form would call every path an escape.
    let canonical_root = canonicalize(root)?;
    let resolved = canonicalize(&canonical_root.join(requested))?;

    // Containment is judged AFTER resolution, which is what makes a symlink pointing out of the
    // project visible at all.
    let Ok(inside) = resolved.strip_prefix(&canonical_root) else {
        return Err(PathRefusal::EscapesRoot);
    };
    // ...and the denylist is applied again to what the path RESOLVED to. A symlink named
    // `notes.txt` pointing at `.env` satisfies every lexical check above, lands inside the root,
    // and is a perfectly ordinary regular file. This line is the only thing that sees it.
    if any_credential_component(inside) {
        return Err(PathRefusal::Credential);
    }

    let meta = std::fs::metadata(&resolved).map_err(map_io)?;
    check_metadata(&meta, max_bytes)?;
    Ok(resolved)
}

/// The checks that depend on the file itself rather than on its name.
///
/// Taken separately so they can be applied to an OPEN HANDLE as well as to a path: `open_within`
/// re-runs them on the descriptor it is about to read, which is the only way the size and link
/// count it enforces describe the bytes it actually returns.
fn check_metadata(meta: &std::fs::Metadata, max_bytes: u64) -> Result<(), PathRefusal> {
    use std::os::unix::fs::MetadataExt;
    if !meta.is_file() {
        return Err(PathRefusal::NotAFile);
    }
    if meta.nlink() > 1 {
        return Err(PathRefusal::HardLinked);
    }
    if meta.len() > max_bytes {
        return Err(PathRefusal::TooLarge {
            bytes: meta.len(),
            cap: max_bytes,
        });
    }
    Ok(())
}

/// Resolve `rel` inside `root` and return its text, or refuse with a reason.
///
/// Reading lives beside resolving so there is one refusal vocabulary rather than two: a caller
/// that had to combine `resolve_within` with its own `read_to_string` would invent its own words
/// for "that file is not text", and the UI would learn both.
pub fn read_within(root: &Path, rel: &str, max_bytes: u64) -> Result<String, PathRefusal> {
    open_within(root, rel, max_bytes).map(|opened| opened.text)
}

/// What a caller gets when a file is opened: where it actually landed, and its text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenedFile {
    /// The RESOLVED path. A caller that reports the requested path instead would let a symlink
    /// show one name while displaying another file's contents.
    pub path: PathBuf,
    pub text: String,
}

/// Resolve and read in one pass. Callers that need both take this rather than calling
/// [`resolve_within`] and [`read_within`] in turn, which would walk and canonicalise the path
/// twice — real syscalls against a 40 ms open-file budget.
pub fn open_within(root: &Path, rel: &str, max_bytes: u64) -> Result<OpenedFile, PathRefusal> {
    use std::io::Read;
    let path = resolve_within(root, rel, max_bytes)?;
    // Open ONCE and judge the descriptor. `resolve_within` validated a path; between that and a
    // second `fs::read(&path)` the name could point somewhere else, and the size and link count
    // just checked would describe a file that is no longer the one being read. Everything below
    // is asked of the handle.
    let mut file = std::fs::File::open(&path).map_err(map_io)?;
    check_metadata(&file.metadata().map_err(map_io)?, max_bytes)?;
    // The CAP binds the read, not just the stat. Checking metadata and then reading to EOF meant
    // a file that grew between the two returned arbitrarily many bytes into the webview — the
    // size gate applied to a number, never to the bytes. Read one past the cap so exceeding it
    // is detectable rather than silently truncated into a corrupt buffer.
    let mut bytes = Vec::new();
    let allowed = max_bytes.saturating_add(1);
    std::io::Read::take(&mut file, allowed)
        .read_to_end(&mut bytes)
        .map_err(map_io)?;
    if bytes.len() as u64 > max_bytes {
        return Err(PathRefusal::TooLarge {
            bytes: bytes.len() as u64,
            cap: max_bytes,
        });
    }
    // `from_utf8` rather than `from_utf8_lossy`: lossy conversion produces a buffer that LOOKS
    // editable and would destroy the file if saved back.
    let text = String::from_utf8(bytes).map_err(|_| PathRefusal::NotText)?;
    Ok(OpenedFile { path, text })
}

fn canonicalize(path: &Path) -> Result<PathBuf, PathRefusal> {
    path.canonicalize().map_err(map_io)
}

/// "Could not read" and "is not there" are different answers and are kept different — collapsing
/// them is how a permissions problem gets reported for months as a missing file.
fn map_io(err: std::io::Error) -> PathRefusal {
    match err.kind() {
        // ENOTDIR — a component of the path is not a directory — is "there is no such file
        // there", not a permissions problem. Reporting it as Unreadable sent the reader looking
        // for a file that was never there.
        std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory => PathRefusal::NotFound,
        _ => PathRefusal::Unreadable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    /// A real project tree on a real filesystem — L4: no mocks where behaviour is the subject.
    struct Project {
        root: PathBuf,
    }

    impl Project {
        fn new(tag: &str) -> Self {
            let root = std::env::temp_dir()
                .join(format!("tempest-pathguard-{}-{}", std::process::id(), tag));
            let _ = fs::remove_dir_all(&root);
            fs::create_dir_all(&root).expect("temp project root");
            // A project is a git working tree; the fixture is one, because the guard checks.
            fs::create_dir_all(root.join(".git")).expect("fixture .git");
            // The root itself may be a symlink (/tmp -> /private/tmp on macOS), so the fixture
            // canonicalises: containment is judged against the resolved root, not the pretty one.
            let root = root.canonicalize().expect("canonical root");
            Self { root }
        }
        fn write(&self, rel: &str, body: &str) -> PathBuf {
            let path = self.root.join(rel);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).expect("parent");
            }
            fs::write(&path, body).expect("write fixture");
            path
        }
    }

    impl Drop for Project {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    const CAP: u64 = 1024 * 1024;

    // ----------------------------------------------------------------------------- allowed
    #[test]
    fn an_ordinary_project_file_resolves() {
        let p = Project::new("ordinary");
        let want = p.write("src/main.py", "print('hi')\n");
        assert_eq!(resolve_within(&p.root, "src/main.py", CAP), Ok(want));
    }

    #[test]
    fn a_name_with_spaces_and_unicode_resolves() {
        let p = Project::new("unicode");
        let want = p.write("notes/héllo wörld.md", "# hi\n");
        assert_eq!(resolve_within(&p.root, "notes/héllo wörld.md", CAP), Ok(want));
    }

    #[test]
    fn a_symlink_that_stays_inside_the_project_resolves() {
        let p = Project::new("symlink-inside");
        let target = p.write("src/real.py", "x = 1\n");
        std::os::unix::fs::symlink(&target, p.root.join("link.py")).expect("symlink");
        assert_eq!(resolve_within(&p.root, "link.py", CAP), Ok(target));
    }

    // ----------------------------------------------------------------------------- refused
    #[test]
    fn an_absolute_path_is_refused() {
        let p = Project::new("absolute");
        assert_eq!(
            resolve_within(&p.root, "/etc/passwd", CAP),
            Err(PathRefusal::Absolute)
        );
    }

    #[test]
    fn a_traversal_component_is_refused() {
        let p = Project::new("traversal");
        assert_eq!(
            resolve_within(&p.root, "../secrets.txt", CAP),
            Err(PathRefusal::Traversal)
        );
    }

    #[test]
    fn traversal_is_refused_even_when_it_normalises_back_inside() {
        let p = Project::new("traversal-inside");
        p.write("src/main.py", "x\n");
        // `src/../src/main.py` is harmless once normalised — and still refused, because a rule
        // that needs normalisation to evaluate is a rule that gets normalisation wrong somewhere.
        assert_eq!(
            resolve_within(&p.root, "src/../src/main.py", CAP),
            Err(PathRefusal::Traversal)
        );
    }

    #[test]
    fn a_symlink_pointing_out_of_the_project_is_refused() {
        let p = Project::new("symlink-escape");
        let outside = std::env::temp_dir().join(format!("tempest-outside-{}", std::process::id()));
        fs::write(&outside, "secret\n").expect("outside file");
        std::os::unix::fs::symlink(&outside, p.root.join("escape.txt")).expect("symlink");
        let verdict = resolve_within(&p.root, "escape.txt", CAP);
        let _ = fs::remove_file(&outside);
        assert_eq!(verdict, Err(PathRefusal::EscapesRoot));
    }

    #[test]
    fn a_dotenv_is_refused() {
        let p = Project::new("dotenv");
        p.write(".env", "SECRET=1\n");
        assert_eq!(
            resolve_within(&p.root, ".env", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn the_dotenv_family_is_refused() {
        let p = Project::new("dotenv-family");
        p.write(".env.production", "SECRET=1\n");
        assert_eq!(
            resolve_within(&p.root, ".env.production", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn the_credential_denylist_is_case_folded() {
        // Renamed from `..._because_macos_is_case_insensitive`, which named a filesystem property
        // this test cannot observe: it creates no `.env`, so the refusal comes from the lexical
        // fold and would be identical on a case-SENSITIVE filesystem. What is pinned here is the
        // fold itself. The reason the fold exists is macOS: on APFS `.ENV` opens `.env`'s bytes,
        // so a case-sensitive denylist is bypassable on the developer's own machine while looking
        // correct on Linux CI. The deliberate consequence is that a file genuinely named `.ENV`
        // on Linux is also refused — a false refusal this project accepts, because a path spelled
        // that way is a secret in every case anyone has produced.
        let p = Project::new("dotenv-case");
        for spelling in [".ENV", ".Env", ".SSH/id_rsa", "ID_RSA"] {
            assert_eq!(
                resolve_within(&p.root, spelling, CAP),
                Err(PathRefusal::Credential),
                "{spelling}"
            );
        }
    }

    #[test]
    fn a_case_insensitive_filesystem_cannot_be_used_to_reach_a_real_dotenv() {
        // The property the old name CLAIMED, actually exercised: a real `.env` on disk, opened
        // through a differently-cased spelling. On macOS this resolves to the same inode; the
        // fold must refuse it before the filesystem gets the chance to be helpful.
        let p = Project::new("dotenv-case-real");
        p.write(".env", "SECRET=1\n");
        assert_eq!(
            read_within(&p.root, ".ENV", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn a_nested_dotenv_is_refused() {
        let p = Project::new("dotenv-nested");
        p.write("config/.env", "SECRET=1\n");
        assert_eq!(
            resolve_within(&p.root, "config/.env", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn an_ssh_key_is_refused() {
        let p = Project::new("ssh");
        p.write(".ssh/id_rsa", "-----BEGIN\n");
        assert_eq!(
            resolve_within(&p.root, ".ssh/id_rsa", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn a_keychain_is_refused() {
        let p = Project::new("keychain");
        p.write("login.keychain-db", "binary\n");
        assert_eq!(
            resolve_within(&p.root, "login.keychain-db", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn a_symlink_whose_target_is_denylisted_is_refused() {
        // The state a lexical denylist cannot see: the requested name is innocent, the resolved
        // path is not, and the file is a regular file living inside the project root.
        let p = Project::new("symlink-to-secret");
        let secret = p.write(".env", "SECRET=1\n");
        std::os::unix::fs::symlink(&secret, p.root.join("notes.txt")).expect("symlink");
        assert_eq!(
            resolve_within(&p.root, "notes.txt", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn an_empty_path_is_refused() {
        let p = Project::new("empty");
        assert_eq!(resolve_within(&p.root, "", CAP), Err(PathRefusal::Malformed));
    }

    #[test]
    fn an_interior_nul_is_refused() {
        let p = Project::new("nul");
        assert_eq!(
            resolve_within(&p.root, "src/ma\0in.py", CAP),
            Err(PathRefusal::Malformed)
        );
    }

    #[test]
    fn a_directory_is_refused() {
        let p = Project::new("dir");
        p.write("src/main.py", "x\n");
        assert_eq!(
            resolve_within(&p.root, "src", CAP),
            Err(PathRefusal::NotAFile)
        );
    }

    #[test]
    fn a_missing_file_is_refused() {
        let p = Project::new("missing");
        assert_eq!(
            resolve_within(&p.root, "nope.py", CAP),
            Err(PathRefusal::NotFound)
        );
    }

    #[test]
    fn a_file_over_the_cap_is_refused_with_both_numbers() {
        let p = Project::new("toolarge");
        p.write("big.txt", &"x".repeat(2048));
        assert_eq!(
            resolve_within(&p.root, "big.txt", 1024),
            Err(PathRefusal::TooLarge {
                bytes: 2048,
                cap: 1024
            })
        );
    }

    #[test]
    fn a_file_exactly_at_the_cap_is_allowed() {
        let p = Project::new("atcap");
        let want = p.write("exact.txt", &"x".repeat(1024));
        assert_eq!(resolve_within(&p.root, "exact.txt", 1024), Ok(want));
    }

    #[test]
    fn a_folder_that_is_not_a_project_is_refused() {
        // Without this, a caller widens the guard simply by naming a bigger root: containment
        // succeeds against `/`, and `etc/passwd` is neither denylisted nor an escape.
        let plain = std::env::temp_dir().join(format!("tempest-notaproj-{}", std::process::id()));
        let _ = fs::remove_dir_all(&plain);
        fs::create_dir_all(&plain).expect("plain dir");
        fs::write(plain.join("readme.md"), "hi\n").expect("file");
        let verdict = resolve_within(&plain, "readme.md", CAP);
        let _ = fs::remove_dir_all(&plain);
        assert_eq!(verdict, Err(PathRefusal::NotAProject));
    }

    #[test]
    fn an_unreadable_directory_is_not_reported_as_missing() {
        // The state nobody sets up: the file exists, and the process cannot get to it. Reported
        // as NotFound it would send someone looking for a file that is right there.
        // Root ignores permission bits, so this assertion is meaningless when the suite runs as
        // root (some CI containers do). Skipping is honest; asserting would be a test that
        // passes for a reason unrelated to what it names — the failure mode this repo hunts.
        if unsafe { libc::geteuid() } == 0 {
            return;
        }
        let p = Project::new("locked");
        p.write("locked/secret.txt", "x\n");
        let dir = p.root.join("locked");
        fs::set_permissions(&dir, <fs::Permissions as std::os::unix::fs::PermissionsExt>::from_mode(0o000))
            .expect("lock dir");
        let verdict = resolve_within(&p.root, "locked/secret.txt", CAP);
        fs::set_permissions(&dir, <fs::Permissions as std::os::unix::fs::PermissionsExt>::from_mode(0o755))
            .expect("unlock dir");
        assert_eq!(verdict, Err(PathRefusal::Unreadable));
    }

    #[test]
    fn reading_returns_the_files_text() {
        let p = Project::new("read-text");
        p.write("src/main.py", "print('hi')\n");
        assert_eq!(
            read_within(&p.root, "src/main.py", CAP),
            Ok("print('hi')\n".to_string())
        );
    }

    #[test]
    fn reading_a_binary_file_is_refused_rather_than_mangled() {
        // Invalid UTF-8 rendered as replacement characters looks editable, and saving it back
        // would destroy the file. Refusing is the only honest answer an editor can give.
        let p = Project::new("read-binary");
        let path = p.root.join("logo.png");
        fs::write(&path, [0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE, 0x00, 0x01]).expect("binary");
        assert_eq!(read_within(&p.root, "logo.png", CAP), Err(PathRefusal::NotText));
    }

    #[test]
    fn reading_applies_every_guard_that_resolving_does() {
        // The read path must not be a second, weaker door into the same building.
        let p = Project::new("read-guarded");
        p.write(".env", "SECRET=1\n");
        assert_eq!(read_within(&p.root, ".env", CAP), Err(PathRefusal::Credential));
        assert_eq!(
            read_within(&p.root, "../outside.txt", CAP),
            Err(PathRefusal::Traversal)
        );
        assert_eq!(
            read_within(&p.root, "/etc/passwd", CAP),
            Err(PathRefusal::Absolute)
        );
    }

    #[test]
    fn opening_reports_where_the_path_actually_landed() {
        // A symlink must not let the editor title one file while showing another's bytes.
        let p = Project::new("open-resolved");
        let target = p.write("src/real.py", "x = 1\n");
        std::os::unix::fs::symlink(&target, p.root.join("alias.py")).expect("symlink");
        let opened = open_within(&p.root, "alias.py", CAP).expect("opens");
        assert_eq!(opened.path, target, "the resolved path is reported, not the alias");
        assert_eq!(opened.text, "x = 1\n");
    }

    #[test]
    fn every_refusal_reads_as_a_sentence_and_never_leaks_the_path() {
        // The reason reaches a UI. It must explain without echoing what was asked for.
        for refusal in every_variant() {
            let text = refusal.to_string();
            assert!(!text.is_empty(), "{refusal:?} has no message");
            assert!(!text.contains('/'), "{refusal:?} leaks a path: {text}");
        }
    }

    /// Every variant, by construction.
    ///
    /// The test above used to iterate a hand-written array of NINE literals while the enum had
    /// twelve — and the three it missed (`NotAProject`, `NotText`, `HardLinked`) were the three
    /// added after it was written. A list that claims to be universal has to be enforced as one:
    /// the `match` below is exhaustive, so the compiler refuses to build until a new variant is
    /// added here as well.
    fn every_variant() -> Vec<PathRefusal> {
        let all = vec![
            PathRefusal::Malformed,
            PathRefusal::Absolute,
            PathRefusal::Traversal,
            PathRefusal::EscapesRoot,
            PathRefusal::Credential,
            PathRefusal::NotFound,
            PathRefusal::Unreadable,
            PathRefusal::NotAFile,
            PathRefusal::HardLinked,
            PathRefusal::NotText,
            PathRefusal::NotAProject,
            PathRefusal::TooLarge { bytes: 9, cap: 8 },
        ];
        for refusal in &all {
            // Exhaustiveness sentinel — when this stops compiling, add the variant above too.
            match refusal {
                PathRefusal::Malformed
                | PathRefusal::Absolute
                | PathRefusal::Traversal
                | PathRefusal::EscapesRoot
                | PathRefusal::Credential
                | PathRefusal::NotFound
                | PathRefusal::Unreadable
                | PathRefusal::NotAFile
                | PathRefusal::HardLinked
                | PathRefusal::NotText
                | PathRefusal::NotAProject
                | PathRefusal::TooLarge { .. } => {}
            }
        }
        all
    }

    #[test]
    fn a_hard_link_to_a_denylisted_file_is_refused() {
        // The state that defeated the name-based denylist entirely. A hard link IS the file:
        // both names are directory entries for one inode, there is no target to follow, and
        // `canonicalize("notes.txt")` answers "notes.txt". A review probe read SECRET=hunter2
        // through exactly this before the link count was checked.
        let p = Project::new("hardlink");
        let secret = p.write(".env", "SECRET=hunter2\n");
        fs::hard_link(&secret, p.root.join("notes.txt")).expect("hard link");
        assert_eq!(
            read_within(&p.root, "notes.txt", CAP),
            Err(PathRefusal::HardLinked)
        );
    }

    #[test]
    fn an_ordinary_file_with_one_name_is_not_mistaken_for_a_hard_link() {
        let p = Project::new("hardlink-negative");
        let want = p.write("src/main.py", "x = 1\n");
        assert_eq!(resolve_within(&p.root, "src/main.py", CAP), Ok(want));
    }

    #[test]
    fn the_git_directory_is_refused_although_the_guard_requires_it() {
        // `.git` is present under EVERY accepted root — that is how a project is recognised —
        // and `.git/config` carries remote URLs with embedded tokens.
        let p = Project::new("gitdir");
        p.write(".git/config", "[remote]\n  url = https://x:token@example.com\n");
        assert_eq!(
            read_within(&p.root, ".git/config", CAP),
            Err(PathRefusal::Credential)
        );
    }

    #[test]
    fn the_modern_ssh_key_names_are_refused_too() {
        let p = Project::new("ssh-modern");
        for name in [".ssh/id_ed25519", ".ssh/id_ecdsa", ".git-credentials", ".npmrc"] {
            assert_eq!(
                resolve_within(&p.root, name, CAP),
                Err(PathRefusal::Credential),
                "{name}"
            );
        }
    }

    #[test]
    fn a_git_worktree_is_a_project_even_though_its_dot_git_is_a_file() {
        // Tempest's own agent shadows ARE git worktrees, and in a worktree `.git` is a FILE
        // holding a gitdir pointer, not a directory. The guard uses `exists()`, true for both.
        // Pinned because the natural refactor to `is_dir()` would silently make every shadow
        // unreadable to Phase 21's agent, with no test to notice.
        let p = Project::new("worktree");
        fs::remove_dir_all(p.root.join(".git")).expect("drop the dir");
        fs::write(p.root.join(".git"), "gitdir: /elsewhere\n").expect(".git file");
        let want = p.write("src/main.py", "x = 1\n");
        assert_eq!(resolve_within(&p.root, "src/main.py", CAP), Ok(want));
    }
}
