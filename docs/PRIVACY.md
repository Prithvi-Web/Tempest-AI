# Tempest AI — Privacy: what leaves your machine, and what provably cannot

**Short answer: nothing leaves your machine unless you personally hand it over.** Tempest is
local-first (L8); source code never leaves the machine without explicit, per-repo, opt-in
consent (L9); and egress is *tested*, not promised — CI proves zero outbound connections in
local mode (L10, `tempest.dev.egress_check --expect-zero`).

## The outbound-candidate surfaces (Phase 17)

Only three artifacts are even *designed* to be shareable, and each one passes the redaction
engine (`tempest.redact`) before it exists on disk or in an archive:

| Artifact | Command | Contents | Redaction |
|---|---|---|---|
| Diagnostic bundle | `tempest diagnose` | health report, recent structured logs, crash records, telemetry counters | every byte re-redacted at packaging; the manifest is printed for review; the command transmits nothing |
| Crash records | written automatically to `<data_dir>/crashes/` | exception type + scrubbed traceback + version | scrubbed **at write time** — the raw traceback never touches disk |
| Telemetry counters | `<data_dir>/telemetry.json`, **opt-in only** (`TEMPEST_TELEMETRY=1`, default OFF) | run counts, verdict/tier/UNPROVEN-reason distributions, total duration | counters only by construction — no paths, repos, or source exist in the schema |

No network transmission exists for any of these today. Sharing means you attach the file
yourself. Automated, opt-in transmission arrives only with the self-hosted team sync server
(Phase 13) and its own redaction-at-the-boundary gate.

## What the redaction engine scrubs

Private-key blocks; values of secret-looking environment variables (`*KEY*`, `*TOKEN*`,
`*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*`, `*PASSPHRASE*`); credential-shaped tokens (AWS
keys, GitHub PATs, `sk-…` API keys, Slack tokens, JWTs, long hex); email addresses; repo
names; home-anchored file paths (the basename survives for debugging, the identifying middle
does not); your username anywhere it appears — including temp paths outside `$HOME`; and, in
tracebacks, source-line echoes and frame symbol names (frame structure and the exception
type/message survive).

## The proof, not the promise

- `python -m tempest.dev.redaction_check --planted-secrets` — plants real-shaped secrets in
  every category (including a live environment variable of the running process) and fails if
  one survives. Runs in `make verify` and CI. Current result: **14/14 contained, zero leakage**.
- `packages/engine/tests/unit/test_redact.py` + `test_diagnose.py` — the same adversarial
  proof at unit level, including "no planted secret and no username in any archive member".
- The redactor is idempotent: re-redacting output changes nothing, so double-processing is
  safe and cheap.

## What never exists at all

No accounts, no cloud storage, no LLM verdicts, no API keys shipped with the product (BYOK,
ADR-0006). The engine runs your code inside a deny-default sandbox with **no network**
(ADR-0015), so the code under test cannot exfiltrate either.
