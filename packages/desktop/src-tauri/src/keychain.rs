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
/// Pre-C4 storage: one item, account "anthropic". Kept readable so an existing install's
/// key survives the move to per-provider accounts; every write migrates it forward.
pub const LEGACY_ACCOUNT: &str = "anthropic";
/// C4 (ADR-0076): the account name IS the provider's environment variable, so the host
/// needs no provider registry of its own — the engine's catalog names the variable, the key
/// bridge stores under it, and `engine_env` enumerates whatever exists at spawn. One truth.
pub const ANTHROPIC_ACCOUNT: &str = "ANTHROPIC_API_KEY";

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

    /// Every account stored under `service` in the given keychains — attribute-only search,
    /// so enumeration itself never touches a secret (values are read item-by-item after).
    pub fn accounts_in(kc: &SecKeychain, service: &str) -> Result<Vec<String>, String> {
        use security_framework::item::{ItemClass, ItemSearchOptions};

        let results = match ItemSearchOptions::new()
            .class(ItemClass::generic_password())
            .service(service)
            .keychains(std::slice::from_ref(kc))
            .load_attributes(true)
            .limit(i32::MAX as i64)
            .search()
        {
            Ok(results) => results,
            Err(err) if err.code() == NOT_FOUND => return Ok(Vec::new()),
            Err(err) => return Err(format!("keychain enumeration failed: {err}")),
        };
        let mut accounts = Vec::new();
        for result in &results {
            if let Some(attributes) = result.simplify_dict() {
                if let Some(account) = attributes.get("acct") {
                    accounts.push(account.clone());
                }
            }
        }
        accounts.sort();
        Ok(accounts)
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

    pub fn accounts(service: &str) -> Result<Vec<String>, String> {
        accounts_in(&default_keychain()?, service)
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

    pub fn accounts(_service: &str) -> Result<Vec<String>, String> {
        Ok(Vec::new()) // honest: nothing is configured on this platform
    }
}

pub use imp::{accounts, clear, read, store};

/// True when the account name is a provider key variable this bridge stored — SCREAMING_CASE
/// with underscores. The one non-conforming account is the pre-C4 legacy item, mapped below.
fn is_env_account(account: &str) -> bool {
    !account.is_empty()
        && account.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
}

/// The engine-side environment for every configured provider key — consumed at each sidecar
/// spawn, so a key saved in the app applies from the next engine start (crash restarts
/// included). The account name IS the variable name; the legacy single-item install maps to
/// ANTHROPIC_API_KEY unless a migrated item already answers for it. A broken keychain must
/// never block the engine from starting: the prove path does not need a key, and Settings
/// surfaces read errors on its own query — so every failure arm here narrows to "fewer
/// variables", never to "no engine".
pub fn engine_env(service: &str) -> Vec<(String, String)> {
    let mut pairs: Vec<(String, String)> = Vec::new();
    let account_names = accounts(service).unwrap_or_default();
    for account in &account_names {
        if !is_env_account(account) {
            continue;
        }
        if let Ok(Some(key)) = read(service, account) {
            pairs.push((account.clone(), key));
        }
    }
    let has_anthropic = pairs.iter().any(|(name, _)| name == ANTHROPIC_ACCOUNT);
    if !has_anthropic && account_names.iter().any(|a| a == LEGACY_ACCOUNT) {
        if let Ok(Some(key)) = read(service, LEGACY_ACCOUNT) {
            pairs.push((ANTHROPIC_ACCOUNT.to_string(), key));
        }
    }
    pairs.sort();
    pairs
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
    fn env_account_names_are_screaming_case_and_the_legacy_item_is_not_one() {
        assert!(is_env_account("ANTHROPIC_API_KEY"));
        assert!(is_env_account("GROQ_API_KEY"));
        assert!(!is_env_account(LEGACY_ACCOUNT)); // "anthropic" maps, it never injects raw
        assert!(!is_env_account(""));
        assert!(!is_env_account("Anthropic_Api_Key"));
    }

    /// Enumeration on a TEST-OWNED keychain: every stored account comes back sorted, and
    /// the search itself is attribute-only (no auth prompt under an unsigned binary is the
    /// proof — a data-loading search would wedge exactly like the login-keychain case the
    /// module doc records).
    #[cfg(target_os = "macos")]
    #[test]
    fn accounts_enumerate_every_item_under_the_service() {
        use security_framework::os::macos::keychain::CreateOptions;

        let dir = std::env::temp_dir().join(format!("tempest-kc-enum-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("test keychain dir");
        let path = dir.join("enum.keychain");
        let kc = CreateOptions::new()
            .password("tempest-test-keychain-password")
            .create(&path)
            .expect("create test keychain");

        assert_eq!(imp::accounts_in(&kc, SERVICE).expect("empty enum"), Vec::<String>::new());
        imp::store_in(&kc, SERVICE, "GROQ_API_KEY", "gsk-PLANTED").expect("store groq");
        imp::store_in(&kc, SERVICE, "ANTHROPIC_API_KEY", PLANT).expect("store anthropic");
        imp::store_in(&kc, SERVICE, LEGACY_ACCOUNT, PLANT).expect("store legacy");
        assert_eq!(
            imp::accounts_in(&kc, SERVICE).expect("enum"),
            vec![
                "ANTHROPIC_API_KEY".to_string(),
                "GROQ_API_KEY".to_string(),
                LEGACY_ACCOUNT.to_string(),
            ]
        );
        // Another service's items never leak into this service's enumeration.
        imp::store_in(&kc, "some.other.service", "OTHER_KEY", "x").expect("store other");
        assert_eq!(imp::accounts_in(&kc, SERVICE).expect("enum again").len(), 3);

        std::fs::remove_dir_all(&dir).ok();
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

        assert_eq!(imp::read_from(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("read empty"), None);
        imp::store_in(&kc, SERVICE, ANTHROPIC_ACCOUNT, PLANT).expect("store");
        assert_eq!(
            imp::read_from(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("read back").as_deref(),
            Some(PLANT)
        );

        imp::store_in(&kc, SERVICE, ANTHROPIC_ACCOUNT, "sk-ant-api03-SECONDKEYMATERIAL-BBBB")
            .expect("overwrite");
        assert_eq!(
            imp::read_from(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("read overwritten").as_deref(),
            Some("sk-ant-api03-SECONDKEYMATERIAL-BBBB")
        );

        imp::clear_in(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("clear");
        assert_eq!(imp::read_from(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("read cleared"), None);
        imp::clear_in(&kc, SERVICE, ANTHROPIC_ACCOUNT).expect("clearing an absent item is idempotent");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
