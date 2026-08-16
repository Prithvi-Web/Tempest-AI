//! OS-keychain storage for the user's Anthropic API key (HANDOFF-WORLD-CLASS §3.2, L9).
//!
//! The key lives ONLY in the macOS Keychain. The webview is told `{configured, last4}` and
//! nothing more; the engine receives the key through its spawn environment
//! (`ANTHROPIC_API_KEY`) so the sidecar's own `secret_env_values()` redaction covers it in
//! every outbound surface — never the DB, settings files, logs, bundles, or telemetry.
//! The redaction gate plants this exact key shape and proves zero leakage (24/24).
//!
//! Production uses the DEFAULT (login) keychain. Tests use a TEMPORARY keychain they create
//! and unlock themselves — an unsigned test binary touching the login keychain summons an
//! authorization dialog no headless run can answer (it wedged cargo test at 0% CPU when
//! first tried), while a test-owned keychain exercises the identical Security.framework
//! paths promptless. Non-macOS builds compile with an honest "unavailable" implementation.

pub const SERVICE: &str = "com.prithvi.tempest.ai-key";
pub const ACCOUNT: &str = "anthropic";

/// Minimal shape sanity for an Anthropic key. Deliberately loose (prefix + charset) — the
/// real validity test is the synthesis call itself, which is not wired yet; this only stops
/// obvious paste accidents (a URL, an email, an empty string) from entering the keychain.
pub fn looks_like_anthropic_key(key: &str) -> bool {
    let rest = match key.strip_prefix("sk-ant-") {
        Some(rest) => rest,
        None => return false,
    };
    rest.len() >= 16 && rest.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

pub fn last4(key: &str) -> String {
    key.chars().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect()
}

#[cfg(target_os = "macos")]
mod imp {
    use security_framework::os::macos::keychain::SecKeychain;

    const NOT_FOUND: i32 = -25300; // errSecItemNotFound — the one "no item" answer

    fn default_keychain() -> Result<SecKeychain, String> {
        SecKeychain::default().map_err(|err| format!("keychain unavailable: {err}"))
    }

    pub fn store_in(kc: &SecKeychain, service: &str, account: &str, key: &str) -> Result<(), String> {
        kc.set_generic_password(service, account, key.as_bytes())
            .map_err(|err| format!("keychain write failed: {err}"))
    }

    pub fn read_from(kc: &SecKeychain, service: &str, account: &str) -> Result<Option<String>, String> {
        match kc.find_generic_password(service, account) {
            Ok((password, _item)) => String::from_utf8(password.as_ref().to_vec())
                .map(Some)
                .map_err(|_| "keychain item is not valid UTF-8".to_string()),
            Err(err) if err.code() == NOT_FOUND => Ok(None),
            Err(err) => Err(format!("keychain read failed: {err}")),
        }
    }

    pub fn clear_in(kc: &SecKeychain, service: &str, account: &str) -> Result<(), String> {
        match kc.find_generic_password(service, account) {
            Ok((_password, item)) => {
                item.delete();
                Ok(())
            }
            Err(err) if err.code() == NOT_FOUND => Ok(()), // clearing is idempotent
            Err(err) => Err(format!("keychain delete failed: {err}")),
        }
    }

    pub fn store(service: &str, account: &str, key: &str) -> Result<(), String> {
        store_in(&default_keychain()?, service, account, key)
    }

    pub fn read(service: &str, account: &str) -> Result<Option<String>, String> {
        read_from(&default_keychain()?, service, account)
    }

    pub fn clear(service: &str, account: &str) -> Result<(), String> {
        clear_in(&default_keychain()?, service, account)
    }
}

#[cfg(not(target_os = "macos"))]
mod imp {
    const UNAVAILABLE: &str = "the OS keychain integration currently ships for macOS only — \
         the key is never stored anywhere weaker as a fallback";

    pub fn store(_service: &str, _account: &str, _key: &str) -> Result<(), String> {
        Err(UNAVAILABLE.to_string())
    }

    pub fn read(_service: &str, _account: &str) -> Result<Option<String>, String> {
        Ok(None) // honest: nothing is configured on this platform
    }

    pub fn clear(_service: &str, _account: &str) -> Result<(), String> {
        Err(UNAVAILABLE.to_string())
    }
}

pub use imp::{clear, read, store};

/// The engine-side environment for a configured key — consumed at every sidecar spawn, so a
/// key saved in Settings applies from the next engine start (crash restarts included).
pub fn engine_env(service: &str, account: &str) -> Vec<(String, String)> {
    match read(service, account) {
        Ok(Some(key)) => vec![("ANTHROPIC_API_KEY".to_string(), key)],
        // A broken keychain must never block the engine from starting: the prove path does
        // not need the key; Settings surfaces the read error on its own query.
        Ok(None) | Err(_) => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const PLANT: &str = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC";

    #[test]
    fn key_shape_gate_accepts_real_shapes_and_rejects_paste_accidents() {
        assert!(looks_like_anthropic_key(PLANT));
        assert!(!looks_like_anthropic_key(""));
        assert!(!looks_like_anthropic_key("sk-ant-short"));
        assert!(!looks_like_anthropic_key("sk-proj-abcdefghijklmnopqrstuvwx")); // wrong vendor
        assert!(!looks_like_anthropic_key("https://console.anthropic.com/keys"));
        assert!(!looks_like_anthropic_key("sk-ant-api03-has a space in it padpadpad"));
    }

    #[test]
    fn last4_is_the_tail_the_ui_shows() {
        assert_eq!(last4("sk-ant-api03-XXXX-WXYZ"), "WXYZ");
        assert_eq!(last4("abc"), "abc"); // shorter than 4 stays whole, never panics
    }

    /// Real Security.framework roundtrip on a TEST-OWNED keychain (created + unlocked here,
    /// deleted on drop) — identical code paths to production's default-keychain calls, but
    /// promptless under an unsigned test binary (see the module doc).
    #[cfg(target_os = "macos")]
    #[test]
    fn keychain_roundtrip_store_read_overwrite_clear() {
        use security_framework::os::macos::keychain::CreateOptions;

        let dir = std::env::temp_dir().join(format!("tempest-kc-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("test keychain dir");
        let path = dir.join("test.keychain");
        let kc = CreateOptions::new()
            .password("tempest-test-keychain-password")
            .create(&path)
            .expect("create test keychain");

        assert_eq!(imp::read_from(&kc, SERVICE, ACCOUNT).expect("read empty"), None);
        imp::store_in(&kc, SERVICE, ACCOUNT, PLANT).expect("store");
        assert_eq!(
            imp::read_from(&kc, SERVICE, ACCOUNT).expect("read back").as_deref(),
            Some(PLANT)
        );

        imp::store_in(&kc, SERVICE, ACCOUNT, "sk-ant-api03-SECONDKEYMATERIAL-BBBB")
            .expect("overwrite");
        assert_eq!(
            imp::read_from(&kc, SERVICE, ACCOUNT).expect("read overwritten").as_deref(),
            Some("sk-ant-api03-SECONDKEYMATERIAL-BBBB")
        );

        imp::clear_in(&kc, SERVICE, ACCOUNT).expect("clear");
        assert_eq!(imp::read_from(&kc, SERVICE, ACCOUNT).expect("read cleared"), None);
        imp::clear_in(&kc, SERVICE, ACCOUNT).expect("clearing an absent item is idempotent");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
