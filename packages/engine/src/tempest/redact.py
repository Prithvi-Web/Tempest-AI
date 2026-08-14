"""Redaction engine (Phase 17, L9): nothing identifying leaves the machine.

One pure function over text, applied to anything outbound — crash reports, diagnostic
bundles, telemetry payloads. Categories (master prompt §17): private-key blocks, values of
secret-looking environment variables, repo names, credential-shaped tokens, email addresses,
home-anchored file paths (the basename survives for debugging; the identifying middle does
not), and — via `scrub_traceback` — source-line echoes and frame symbol names.

The proof is adversarial: `tempest.dev.redaction_check --planted-secrets` and the pytest
suite plant real-shaped secrets and assert zero survive (failure-mode #4: test the scrubber
with planted secrets, never by reading the code). Markers ([REDACTED:*], [PATH], [REPO],
[EMAIL], [symbol]) are chosen so a second pass is a no-op — redaction is idempotent.
"""

import re
from dataclasses import dataclass

_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_CREDENTIALS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub classic PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),  # GitHub fine-grained PAT
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),  # API secret keys (sk-…)
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),  # JWT
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),  # long hex (digests used as secrets)
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_FRAME_SYMBOL = re.compile(r'^(\s*File "[^"]*", line \d+), in \S+$')


@dataclass(frozen=True)
class RedactionContext:
    """What this machine considers identifying: its repos, its secret env values, its home."""

    repo_names: tuple[str, ...] = ()
    env_secret_values: tuple[str, ...] = ()
    home_dir: str | None = None


def redact_text(text: str, context: RedactionContext) -> str:
    out = _KEY_BLOCK.sub("[REDACTED:key]", text)
    for value in context.env_secret_values:
        if value:
            out = out.replace(value, "[REDACTED:env]")
    for repo in context.repo_names:
        if repo:
            out = out.replace(repo, "[REPO]")
    for pattern in _CREDENTIALS:
        out = pattern.sub("[REDACTED:credential]", out)
    out = _EMAIL.sub("[EMAIL]", out)
    if context.home_dir:
        home_path = re.compile(re.escape(context.home_dir.rstrip("/")) + r"[^\s'\"]*")
        out = home_path.sub(lambda m: "[PATH]/" + m.group(0).rstrip("/").rsplit("/", 1)[-1], out)
        # The bare username leaks through paths OUTSIDE home too (temp dirs, /var/folders):
        # scrub it wherever it appears. Privacy outranks fidelity for a common-word username.
        username = context.home_dir.rstrip("/").rsplit("/", 1)[-1]
        if username:
            out = re.sub(rf"(?<!\w){re.escape(username)}(?!\w)", "[USER]", out)
    return out


def scrub_traceback(tb: str, context: RedactionContext) -> str:
    """Frame structure (file basenames, line numbers, exception type/message) survives;
    source-line echoes and frame symbol names do not (L9 — source never leaves)."""
    lines: list[str] = []
    after_frame_header = False
    for line in tb.splitlines():
        stripped = line.lstrip()
        if after_frame_header and not stripped.startswith('File "'):
            lines.append("    [source line removed]")
            after_frame_header = False
            continue
        after_frame_header = stripped.startswith('File "')
        redacted = redact_text(line, context)
        lines.append(_FRAME_SYMBOL.sub(r"\1, in [symbol]", redacted))
    return "\n".join(lines) + ("\n" if tb.endswith("\n") else "")


def secret_env_values() -> tuple[str, ...]:
    """Values of secret-looking environment variables in this process — always redacted."""
    import os

    sensitive = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSPHRASE", re.IGNORECASE)
    return tuple(
        value for name, value in os.environ.items() if sensitive.search(name) and len(value) >= 6
    )
