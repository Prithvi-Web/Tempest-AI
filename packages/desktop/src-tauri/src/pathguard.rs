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
#[derive(Debug, Clone, PartialEq, Eq)]
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
    /// Larger than the caller's cap. Unbounded reads are a budget violation (L15.4).
    TooLarge { bytes: u64, cap: u64 },
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
            Self::Unreadable => write!(f, "that file cannot be read (permissions)"),
            Self::NotAFile => write!(f, "not a regular file"),
            Self::TooLarge { bytes, cap } => write!(f, "{bytes} bytes exceeds the {cap}-byte cap"),
        }
    }
}

/// Path segments that carry credentials. Compared case-folded (see [`PathRefusal::Credential`]).
const DENIED_SEGMENTS: &[&str] = &[".env", ".ssh", ".aws", ".gnupg", ".netrc", "id_rsa"];
/// Suffixes that carry credentials wherever they appear.
const DENIED_SUFFIXES: &[&str] = &[".keychain", ".keychain-db", ".pem", ".p12", ".pfx"];

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
/// `root` is trusted (it is the project the user opened); `rel` is not.
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
    if !meta.is_file() {
        return Err(PathRefusal::NotAFile);
    }
    if meta.len() > max_bytes {
        return Err(PathRefusal::TooLarge {
            bytes: meta.len(),
            cap: max_bytes,
        });
    }
    Ok(resolved)
}

fn canonicalize(path: &Path) -> Result<PathBuf, PathRefusal> {
    path.canonicalize().map_err(map_io)
}

/// "Could not read" and "is not there" are different answers and are kept different — collapsing
/// them is how a permissions problem gets reported for months as a missing file.
fn map_io(err: std::io::Error) -> PathRefusal {
    match err.kind() {
        std::io::ErrorKind::NotFound => PathRefusal::NotFound,
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
    fn an_uppercase_dotenv_is_refused_because_macos_is_case_insensitive() {
        // On APFS `.ENV` opens `.env`'s bytes, so a case-sensitive denylist is bypassable on the
        // user's own machine while looking correct on Linux CI.
        let p = Project::new("dotenv-case");
        assert_eq!(
            resolve_within(&p.root, ".ENV", CAP),
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
    fn an_unreadable_directory_is_not_reported_as_missing() {
        // The state nobody sets up: the file exists, and the process cannot get to it. Reported
        // as NotFound it would send someone looking for a file that is right there.
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
    fn every_refusal_reads_as_a_sentence_and_never_leaks_the_path() {
        // The reason reaches a UI. It must explain without echoing what was asked for.
        for refusal in [
            PathRefusal::Malformed,
            PathRefusal::Absolute,
            PathRefusal::Traversal,
            PathRefusal::EscapesRoot,
            PathRefusal::Credential,
            PathRefusal::NotFound,
            PathRefusal::Unreadable,
            PathRefusal::NotAFile,
            PathRefusal::TooLarge { bytes: 9, cap: 8 },
        ] {
            let text = refusal.to_string();
            assert!(!text.is_empty(), "{refusal:?} has no message");
            assert!(!text.contains('/'), "{refusal:?} leaks a path: {text}");
        }
    }
}
