"""Redaction engine (Phase 17, L9): planted secrets must NOT survive — proven adversarially,
never by reading the code (failure-mode #4). Structure survives; secrets do not."""

import pytest

from tempest.redact import RedactionContext, redact_text, scrub_traceback

PLANTED_SECRETS = [
    "AKIAIOSFODNN7EXAMPLE",  # AWS access key id
    "ghp_16C7e42F292c6912E7710c838347Ae178B4a",  # GitHub PAT
    "sk-proj-Zx9y8W7v6U5t4S3r2Q1p0OnMlKjIhGfEdCbA",  # API key
    # Slack-shaped plant. Deliberately NOT digit-segmented like a real token: Slack tokens
    # carry no checksum, so a realistic shape trips GitHub push protection (it did — trap 19).
    # The redactor's pattern matches this exactly as it matches the real shape.
    "xoxb-PLANTED-FAKE-TEMPEST-REDACTION-FIXTURE-AAAABBBB",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.T-secret-signature-segment",  # JWT
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
