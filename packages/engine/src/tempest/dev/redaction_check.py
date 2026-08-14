"""Phase 17 gate: `python -m tempest.dev.redaction_check --planted-secrets`.

Adversarial proof of L9 for every outbound surface: plant real-shaped secrets across every
category the redactor claims to scrub — including live environment variables of THIS process —
run the redactor, and fail if a single planted value survives. The matrix output is a sales
artifact, like the egress check (L10).
"""

import argparse
import os
import sys

from tempest.redact import RedactionContext, redact_text, scrub_traceback, secret_env_values

_PLANTED: dict[str, str] = {
    "aws-access-key": "AKIAIOSFODNN7EXAMPLE",
    "github-pat": "ghp_16C7e42F292c6912E7710c838347Ae178B4a",
    "fine-grained-pat": "github_pat_11ABCDEFG0123456789_planted",
    "api-secret-key": "sk-proj-Zx9y8W7v6U5t4S3r2Q1p0OnMlKjIhGfEdCbA",
    # Letter-segmented on purpose: a digit-realistic Slack shape trips GitHub push
    # protection (no checksum to validate against, unlike ghp_/sk- plants) — trap 19.
    "slack-token": "xoxb-PLANTED-FAKE-TEMPEST-REDACTION-FIXTURE-AAAABBBB",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.planted-signature-material",
    "hex-secret": "d3b07384d113edec49eaa6238ad5ff00d3b07384d113edec49eaa6238ad5ff00",
    "env-value": "planted-env-secret-value-31337",
    "email": "planted.person@example-corp.com",
    "repo-name": "planted-payments-monorepo",
    "home-path-user": "planted-username",
    "key-material": "PLANTEDKEYMATERIALPLANTEDKEYMATERIAL",
    "source-echo": "total = apply_planted_discount(secret_rate)",
    "frame-symbol": "charge_planted_card",
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
            f"auth: {_PLANTED['fine-grained-pat']} / {_PLANTED['api-secret-key']}",
            f"chat: {_PLANTED['slack-token']} jwt {_PLANTED['jwt']}",
            f"digest: {_PLANTED['hex-secret']} env {_PLANTED['env-value']}",
            f"mail {_PLANTED['email']} repo {_PLANTED['repo-name']}",
            f"path {home}/work/{_PLANTED['repo-name']}/deep/secret_module.py",
            key_block,
        ]
    )


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
    tb = (
        "Traceback (most recent call last):\n"
        f'  File "{home}/work/{_PLANTED["repo-name"]}/billing.py", line 7, '
        f"in {_PLANTED['frame-symbol']}\n"
        f"    {_PLANTED['source-echo']}\n"
        "ValueError: planted\n"
    )
    scrubbed = scrub_traceback(tb, context)
    haystack = redacted + "\n" + scrubbed

    survivors = {name: value for name, value in _PLANTED.items() if value in haystack}
    for name in sorted(_PLANTED):
        state = "LEAKED" if name in survivors else "contained"
        print(f"  {name:<18} {state}")
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
