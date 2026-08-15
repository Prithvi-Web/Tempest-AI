"""Redaction engine (Phase 17, L9): nothing identifying leaves the machine.

One pure function over text, applied to anything outbound — crash reports, diagnostic
bundles, telemetry payloads. Categories (master prompt §17): private-key blocks, values of
secret-looking environment variables, repo names, credential-shaped tokens, email addresses,
home-anchored file paths (the basename survives for debugging; the identifying middle does
not), and — via `scrub_traceback` — source-line echoes and frame symbol names.

The proof is adversarial: `tempest.dev.redaction_check --planted-secrets` and the pytest
suite plant real-shaped secrets and assert zero survive (failure-mode #4: test the scrubber
with planted secrets, never by reading the code). Markers ([REDACTED:*], [PATH], [REPO],
[REPO_URL], [EMAIL], [symbol]) are chosen so a second pass is a no-op — redaction is
idempotent.
"""

import re
from dataclasses import dataclass

_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_CREDENTIALS = (
    re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),  # AWS key ids (incl. temporary)
    re.compile(r"\b(?:IQoJ|FQoG|FwoG)[A-Za-z0-9+/=]{50,}"),  # AWS STS session-token blob
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub classic PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),  # GitHub fine-grained PAT
    re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe secret/restricted keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),  # API secret keys (sk-…)
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack tokens
    # JWTs, including alg=none tokens whose signature segment is legitimately EMPTY.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),  # long hex (digests used as secrets)
)
# Repo identity travels in git remotes too — including repos that live OUTSIDE $HOME, where
# the home rule cannot reach. These run BEFORE the email rule, which would otherwise eat
# `git@host` and leave `owner/repo` standing.
_REPO_URLS = (
    re.compile(r"\b(?:ssh://)?git@[\w.-]+[:/][\w.+-]+/[\w.+-]+"),  # scp-like / ssh remotes
    # The remnant an EARLIER pass leaves when it ate `git@host` as an email address (crash
    # records scrubbed at write time re-enter the redactor at bundle time).
    re.compile(r"\[EMAIL\][:/][\w.+-]+/[\w.+-]+"),
    re.compile(r"\bhttps?://[^\s'\"]+\.git\b"),  # any https git remote
    re.compile(  # owner/repo on the big well-known hosts, with or without .git
        r"\bhttps?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org)"
        r"/[\w.+-]+/[\w.+-]+"
    ),
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
    # URLs before repo names: a context repo name inside a remote URL must not break the
    # URL match by leaving a bracketed marker mid-pattern.
    for pattern in _REPO_URLS:
        out = pattern.sub("[REPO_URL]", out)
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
    joined = "\n".join(lines) + ("\n" if tb.endswith("\n") else "")
    # Full-text second pass: secrets that SPAN lines — a PEM block inside an exception
    # message, a multi-line env value — are invisible to the per-line pass above.
    # Idempotency makes the double scrub free.
    return redact_text(joined, context)


def secret_env_values() -> tuple[str, ...]:
    """Values of secret-looking environment variables in this process — always redacted."""
    import os

    sensitive = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSPHRASE", re.IGNORECASE)
    return tuple(
        value for name, value in os.environ.items() if sensitive.search(name) and len(value) >= 6
    )


def env_repo_names() -> tuple[str, ...]:
    """Repo names this machine knows, provided by the layer that actually tracks them: the
    API layer exports TEMPEST_REDACT_REPO_NAMES (colon-separated) for engine processes it
    spawns. The engine must never import tempest_api to ask (layering), so the environment
    is the channel."""
    import os

    return tuple(n for n in os.environ.get("TEMPEST_REDACT_REPO_NAMES", "").split(":") if n)


def production_context() -> RedactionContext:
    """THE context every production outbound surface builds — crash records (crashlog), the
    diagnostic bundle (diagnose), the sync strip. The redaction_check gate proves leakage
    against this exact builder, so the configuration the proof greenlights is the
    configuration production runs — never a hand-wired twin."""
    from pathlib import Path

    return RedactionContext(
        repo_names=env_repo_names(),
        env_secret_values=secret_env_values(),
        home_dir=str(Path.home()),
    )
