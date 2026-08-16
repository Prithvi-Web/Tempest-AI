"""Phase 17 gate: `python -m tempest.dev.redaction_check --planted-secrets`.

Adversarial proof of L9 for every outbound surface: plant real-shaped secrets across every
category the redactor claims to scrub — including live environment variables of THIS process —
run the redactor, and fail if a single planted value survives. Two legs: a hand-wired context
exercising every category, and the REAL production context builder (the one crashlog and
diagnose call), fed its repo names through the env source — so the configuration this proof
greenlights is the configuration production runs. The matrix output is a sales artifact, like
the egress check (L10).
"""

import argparse
import os
import sys

from tempest.redact import (
    RedactionContext,
    production_context,
    redact_text,
    scrub_traceback,
    secret_env_values,
)

_PLANTED: dict[str, str] = {
    "aws-access-key": "AKIAIOSFODNN7EXAMPLE",
    "aws-temp-key": "ASIAIOSFODNN7PLANTED",
    "aws-sts-session-token": (
        "IQoJb3JpZ2luX2VjEPLANTEDSESSIONTOKENMATERIALPLANTEDSESSIONTOKEN//wEaCXVzLXdlc3QtMg=="
    ),
    "github-pat": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
    "fine-grained-pat": "github_pat_11ABCDEFG0123456789_planted",
    "api-secret-key": "sk-proj-Zx9y8W7v6U5t4S3r2Q1p0OnMlKjIhGfEdCbA",
    # The BYOK key shape the Settings keychain feature handles (letter-segmented — trap 19).
    "anthropic-api-key": "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC",
    "stripe-secret-key": "sk_live_PLANTEDPLANTEDPLANTED01",
    "stripe-restricted-key": "rk_live_PLANTEDPLANTEDPLANTED01",
    # Letter-segmented on purpose: a digit-realistic Slack shape trips GitHub push
    # protection (no checksum to validate against, unlike ghp_/sk- plants) — trap 19.
    "slack-token": "xoxb-PLANTED-FAKE-TEMPEST-REDACTION-FIXTURE-AAAABBBB",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.planted-signature-material",
    "jwt-alg-none": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJwbGFudGVkIn0.",
    "hex-secret": "d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00",
    "env-value": "planted-env-secret-value-31337",
    "email": "planted.person@example-corp.com",
    "repo-name": "planted-payments-monorepo",
    "git-ssh-remote": "git@planted-host.example:planted-org/planted-repo.git",
    # Checked as a bare substring so a PARTIAL url leak (host eaten, owner/repo left) fails.
    "git-owner-repo": "planted-org/planted-repo",
    "home-path-user": "planted-username",
    "key-material": "PLANTEDKEYMATERIALPLANTEDKEYMATERIAL",
    "exception-key-material": "PLANTEDEXCKEYMATERIALPLANTEDEXCKEYMATERIAL",
    "source-echo": "total = apply_planted_discount(secret_rate)",
    "frame-symbol": "charge_planted_card",
    # Proven through the REAL production context builder, repo name via the env source.
    "prod-env-repo-name": "planted-env-sourced-repo",
}


def _corpus(home: str) -> str:
    key_block = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        f"{_PLANTED['key-material']}\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    return "\n".join(
        [
            f"boot: token {_PLANTED['aws-access-key']} then {_PLANTED['github-pat']}",
            f"sts: {_PLANTED['aws-temp-key']} with {_PLANTED['aws-sts-session-token']}",
            f"auth: {_PLANTED['fine-grained-pat']} / {_PLANTED['api-secret-key']}",
            f"stripe: {_PLANTED['stripe-secret-key']} and {_PLANTED['stripe-restricted-key']}",
            f"chat: {_PLANTED['slack-token']} jwt {_PLANTED['jwt']}",
            f"anon jwt: {_PLANTED['jwt-alg-none']} accepted",
            f"digest: {_PLANTED['hex-secret']} env {_PLANTED['env-value']}",
            f"mail {_PLANTED['email']} repo {_PLANTED['repo-name']}",
            f"remote {_PLANTED['git-ssh-remote']} mirrored at",
            f"https://github.com/{_PLANTED['git-owner-repo']}.git for review",
            f"path {home}/work/{_PLANTED['repo-name']}/deep/secret_module.py",
            key_block,
        ]
    )


def _traceback_leg(home: str, context: RedactionContext) -> str:
    """The crash-record shape, including a multi-line PEM inside the exception message —
    the leak per-line scrubbing missed (finding 1)."""
    tb = (
        "Traceback (most recent call last):\n"
        f'  File "{home}/work/{_PLANTED["repo-name"]}/billing.py", line 7, '
        f"in {_PLANTED['frame-symbol']}\n"
        f"    {_PLANTED['source-echo']}\n"
        "ValueError: could not load key:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        f"{_PLANTED['exception-key-material']}\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    return scrub_traceback(tb, context)


def _production_leg() -> str:
    """The ACTUAL production context path: repo names arrive via TEMPEST_REDACT_REPO_NAMES
    (the env source the API layer feeds), through the same builder crashlog and diagnose
    call — proving the config production runs, not a hand-wired twin (finding 3)."""
    os.environ["TEMPEST_REDACT_REPO_NAMES"] = f"{_PLANTED['prod-env-repo-name']}:other-repo"
    context = production_context()
    corpus = (
        f"prove of {_PLANTED['prod-env-repo-name']} failed; env carried {_PLANTED['env-value']}"
    )
    return redact_text(corpus, context)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planted-secrets", action="store_true", required=True)
    parser.parse_args(argv)

    # The env leg is live: the value is planted into THIS process's environment and must be
    # picked up by secret_env_values(), not hand-fed to the context.
    os.environ["TEMPEST_CHECK_PLANTED_API_KEY"] = _PLANTED["env-value"]
    home = f"/Users/{_PLANTED['home-path-user']}"
    context = RedactionContext(
        repo_names=(_PLANTED["repo-name"],),
        env_secret_values=secret_env_values(),
        home_dir=home,
    )

    redacted = redact_text(_corpus(home), context)
    scrubbed = _traceback_leg(home, context)
    haystack = redacted + "\n" + scrubbed + "\n" + _production_leg()

    survivors = {name: value for name, value in _PLANTED.items() if value in haystack}
    for name in sorted(_PLANTED):
        state = "LEAKED" if name in survivors else "contained"
        print(f"  {name:<22} {state}")
    total, leaked = len(_PLANTED), len(survivors)
    print(f"redaction_check: {total - leaked}/{total} planted secrets contained", end="")
    if survivors:
        print(" — FAIL")
        for name, value in sorted(survivors.items()):
            print(f"LEAKED {name}: {value!r}", file=sys.stderr)
        return 1
    print(" — zero leakage (L9 proven, not promised)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
