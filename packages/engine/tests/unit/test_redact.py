"""Redaction engine (Phase 17, L9): planted secrets must NOT survive — proven adversarially,
never by reading the code (failure-mode #4). Structure survives; secrets do not."""

from pathlib import Path

import pytest

from tempest.redact import (
    RedactionContext,
    env_repo_names,
    production_context,
    redact_text,
    scrub_traceback,
)

PLANTED_SECRETS = [
    "AKIAIOSFODNN7EXAMPLE",  # AWS access key id
    "ASIAIOSFODNN7EXAMPLE",  # AWS temporary (STS) access key id
    "ABIAIOSFODNN7EXAMPLE",  # AWS service-bearer access key id
    "ACCAIOSFODNN7EXAMPLE",  # AWS context-specific credential id
    # STS session token: the base64 blob that travels WITH a temporary key (IQoJ… shape).
    "IQoJb3JpZ2luX2VjEPLANTEDSESSIONTOKENMATERIALPLANTEDSESSIONTOKEN//wEaCXVzLXdlc3QtMg==",
    "ghp_16C7e42F292c6912E7710c838347Ae178B4a",  # GitHub PAT
    "sk-proj-Zx9y8W7v6U5t4S3r2Q1p0OnMlKjIhGfEdCbA",  # API key
    # Anthropic-shaped key (the BYOK Settings feature stores one in the OS keychain — the
    # scrubber grows BEFORE that feature wires up, HANDOFF-WORLD-CLASS 2.1/3.2). Letter-
    # segmented like the Slack plant so no real-token scanner matches it (trap 19).
    "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC",  # Anthropic API key
    "sk_live_PLANTEDstripesecret4242",  # Stripe live secret key (underscore, not hyphen)
    "sk_test_PLANTEDstripesecret4242",  # Stripe test secret key
    "rk_live_PLANTEDstripesecret4242",  # Stripe restricted key
    # Slack-shaped plant. Deliberately NOT digit-segmented like a real token: Slack tokens
    # carry no checksum, so a realistic shape trips GitHub push protection (it did — trap 19).
    # The redactor's pattern matches this exactly as it matches the real shape.
    "xoxb-PLANTED-FAKE-TEMPEST-REDACTION-FIXTURE-AAAABBBB",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.T-secret-signature-segment",  # JWT
    "eyJhbGciOiJub25lIn0.eyJzdWIiOiJwbGFudGVkIn0.",  # alg=none JWT — empty signature segment
    "d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00",  # 64-hex secret
    "hunter2-super-secret-env-value",  # env var value (planted via context)
]

PRIVATE_KEY_BLOCK = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACBPLANTEDKEYMATERIALPLANTEDKEYMATERIALPLANTED\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def _context() -> RedactionContext:
    return RedactionContext(
        repo_names=("acme-payments-service",),
        env_secret_values=("hunter2-super-secret-env-value",),
        home_dir="/Users/prithvivinay",
    )


class TestPlantedSecretsDoNotSurvive:
    @pytest.mark.parametrize("secret", PLANTED_SECRETS)
    def test_each_planted_secret_is_removed(self, secret: str) -> None:
        text = f"before the incident we saw {secret} in the wild\nsecond line fine"
        redacted = redact_text(text, _context())
        assert secret not in redacted
        assert "second line fine" in redacted, "non-secret content must survive"

    def test_private_key_block_is_removed_entirely(self) -> None:
        text = f"log opened\n{PRIVATE_KEY_BLOCK}\nlog closed"
        redacted = redact_text(text, _context())
        assert "PLANTEDKEYMATERIAL" not in redacted
        assert "BEGIN OPENSSH PRIVATE KEY" not in redacted
        assert "log opened" in redacted and "log closed" in redacted

    def test_home_paths_lose_the_identifying_middle(self) -> None:
        text = "error at /Users/prithvivinay/Desktop/Claude Code/tempest/packages/x/mod.py"
        redacted = redact_text(text, _context())
        assert "prithvivinay" not in redacted
        assert "mod.py" in redacted, "the basename stays — needed for debugging"

    def test_repo_names_are_removed(self) -> None:
        redacted = redact_text("cloning acme-payments-service failed", _context())
        assert "acme-payments-service" not in redacted

    def test_username_is_removed_even_outside_home_paths(self) -> None:
        # Usernames leak through temp paths too (/var/folders/…/pytest-of-<user>/…).
        text = "scratch at /private/var/folders/7x/y/T/pytest-of-prithvivinay/case0/data"
        redacted = redact_text(text, _context())
        assert "prithvivinay" not in redacted
        assert "case0/data" in redacted, "the rest of the path survives"

    def test_emails_are_removed(self) -> None:
        redacted = redact_text("reported by vinay.gopinath@gmail.com today", _context())
        assert "vinay.gopinath@gmail.com" not in redacted
        assert "today" in redacted


class TestStructureSurvives:
    def test_plain_product_text_is_untouched(self) -> None:
        text = (
            "verdict DIVERGENT: 3 inputs differ; smallest is (0,)\n"
            "reason UNPROVEN(TARGET_UNREACHABLE)"
        )
        assert redact_text(text, _context()) == text

    def test_redaction_is_idempotent(self) -> None:
        text = f"key {PLANTED_SECRETS[0]} and mail a@b.co"
        once = redact_text(text, _context())
        assert redact_text(once, _context()) == once


class TestMultiLineSecrets:
    """Per-line scrubbing is blind to secrets that span lines (finding 1): a PEM key inside
    an exception message, or a multi-line env value (GITHUB_APP_PRIVATE_KEY-style), must not
    survive into a crash record via scrub_traceback."""

    def test_pem_block_inside_an_exception_message_is_scrubbed(self) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/Users/prithvivinay/repo/keys.py", line 9, in load_key\n'
            "    key = parse_key(blob)\n"
            f"ValueError: could not parse key:\n{PRIVATE_KEY_BLOCK}\n"
        )
        scrubbed = scrub_traceback(tb, _context())
        assert "PLANTEDKEYMATERIAL" not in scrubbed
        assert "BEGIN OPENSSH PRIVATE KEY" not in scrubbed
        assert "ValueError: could not parse key:" in scrubbed, "the message frame survives"
        assert "line 9" in scrubbed

    def test_multi_line_env_value_is_scrubbed_from_tracebacks(self) -> None:
        multiline = "planted-first-line-of-app-key\nplanted-second-line-of-app-key"
        context = RedactionContext(env_secret_values=(multiline,), home_dir="/Users/prithvivinay")
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/Users/prithvivinay/repo/app.py", line 3, in boot\n'
            "    connect(app_key)\n"
            f"RuntimeError: bad credential {multiline} rejected\n"
        )
        scrubbed = scrub_traceback(tb, context)
        assert "planted-first-line-of-app-key" not in scrubbed
        assert "planted-second-line-of-app-key" not in scrubbed
        assert "[REDACTED:env]" in scrubbed
        assert "rejected" in scrubbed

    def test_multi_line_env_value_is_scrubbed_from_plain_text(self) -> None:
        multiline = "planted-first-line-of-app-key\nplanted-second-line-of-app-key"
        context = RedactionContext(env_secret_values=(multiline,))
        redacted = redact_text(f"dump:\n{multiline}\nend", context)
        assert "planted-first-line" not in redacted and "planted-second-line" not in redacted


class TestGitRemoteUrls:
    """Repo identity leaks through git remotes too (finding 3): scp-like and https git URLs
    must lose host + owner/repo even when the repo path is nowhere near $HOME."""

    def test_scp_style_git_remote_is_scrubbed(self) -> None:
        text = "origin  git@github.com:acme-corp/payments-svc.git (fetch)"
        redacted = redact_text(text, _context())
        assert "acme-corp" not in redacted and "payments-svc" not in redacted
        assert "[REPO_URL]" in redacted
        assert "(fetch)" in redacted, "surrounding structure survives"

    def test_ssh_url_git_remote_is_scrubbed(self) -> None:
        text = "remote: ssh://git@gitea.internal.example/acme-corp/payments-svc failed"
        redacted = redact_text(text, _context())
        assert "acme-corp" not in redacted and "payments-svc" not in redacted
        assert "failed" in redacted

    def test_https_git_remote_is_scrubbed(self) -> None:
        redacted = redact_text(
            "cloned https://git.example-corp.internal/acme-corp/payments-svc.git ok", _context()
        )
        assert "acme-corp" not in redacted and "payments-svc" not in redacted
        assert "ok" in redacted

    def test_https_known_host_without_dot_git_is_scrubbed(self) -> None:
        redacted = redact_text("see https://gitlab.com/acme-corp/payments-svc today", _context())
        assert "acme-corp" not in redacted and "payments-svc" not in redacted
        assert "today" in redacted

    def test_email_eaten_git_host_remnant_is_scrubbed(self) -> None:
        # A crash record scrubbed at write time re-enters the redactor at bundle time — by
        # then `git@host` has already become [EMAIL], leaving `[EMAIL]:owner/repo.git`.
        redacted = redact_text("pull [EMAIL]:acme-corp/payments-svc.git failed", _context())
        assert "acme-corp" not in redacted and "payments-svc" not in redacted
        assert "failed" in redacted

    def test_repo_url_marker_is_idempotent(self) -> None:
        once = redact_text("pushed git@github.com:acme-corp/payments-svc.git", _context())
        assert redact_text(once, _context()) == once


class TestProductionContext:
    """The context production surfaces actually run (finding 3): repo names arrive from the
    env-provided source (the API layer exports TEMPEST_REDACT_REPO_NAMES — the engine must
    not import tempest_api to ask)."""

    def test_env_repo_names_reads_the_colon_separated_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_REDACT_REPO_NAMES", "acme-payments::beta-svc")
        assert env_repo_names() == ("acme-payments", "beta-svc")

    def test_env_repo_names_defaults_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_REDACT_REPO_NAMES", raising=False)
        assert env_repo_names() == ()

    def test_production_context_scrubs_env_sourced_repo_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_REDACT_REPO_NAMES", "planted-env-repo")
        monkeypatch.setenv("PLANTED_PROD_SECRET_TOKEN", "prod-ctx-planted-value-77")
        context = production_context()
        out = redact_text("cloning planted-env-repo with prod-ctx-planted-value-77", context)
        assert "planted-env-repo" not in out
        assert "prod-ctx-planted-value-77" not in out
        assert context.home_dir == str(Path.home()), "home comes from the real machine"


class TestTracebackScrubbing:
    def test_source_lines_are_dropped_paths_and_structure_stay(self) -> None:
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/Users/prithvivinay/repo/acme-payments-service/billing.py", '
            "line 42, in charge\n"
            "    total = apply_discount(secret_rate, coupon)\n"
            "ValueError: bad rate\n"
        )
        scrubbed = scrub_traceback(tb, _context())
        assert "apply_discount" not in scrubbed, "source echoes must not leave the machine (L9)"
        assert "secret_rate" not in scrubbed
        assert "line 42" in scrubbed, "frame structure survives for debugging"
        assert "billing.py" in scrubbed
        assert "prithvivinay" not in scrubbed
        assert "in charge" not in scrubbed, "frame symbol names are scrubbed too"
        assert "ValueError: bad rate" in scrubbed, "the exception type/message survives"
