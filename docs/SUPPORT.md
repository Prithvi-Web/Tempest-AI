# Tempest AI — Support runbook (Phase 17)

## First line: the self-check

Every support thread starts with two copy-pasteable commands:

```
tempest doctor            # sandbox tier, execution smoke, disk, power — honest exit code
tempest diagnose          # writes a redacted zip; the user reviews it before sharing
```

`tempest logs show --limit 100` (add `--level error`, `--json`) reads the structured engine
log with its rotated history.

## Escalation path

1. **doctor FAIL lines** — actionable locally (no sandbox → install/start Docker or unset
   `TEMPEST_NO_SEATBELT`; no disk headroom → free space; data dir unwritable → permissions).
2. **A run stuck "paused"** — the run ledger names the reason (battery/thermal, L11). Plug
   in, or set `TEMPEST_NO_POWER_PAUSE=1` to opt out of the courtesy pause.
3. **Crash records present** (`<data_dir>/crashes/`) — already scrubbed; ask for the
   diagnostic bundle, never for raw logs or source.
4. **Engine bug suspected** — reproduce with the CLI (`tempest prove …`), attach the bundle
   from `tempest diagnose`, and file with the exact `reason_code` shown. Verdict semantics
   are contractual (L2): `UNPROVEN` with a reason is a *result*, not a malfunction.

## Known limitations (kept honest, kept current)

- Real-world proof rate is unmeasured until the live-PR gate + design partners (Phase 18).
- Instance methods are `UNPROVEN(TARGET_UNREACHABLE)` — no constructor synthesis yet.
- TypeScript changes surface as `UNPROVEN(RECORD_REPLAY_UNAVAILABLE)` (execution half of
  Phase 3 pending).
- Linux/Windows T2 sandbox backends and the desktop webview E2E suite are CI-leg follow-ups
  (`docs/PLAN-DESKTOP.md`).
- Crash/telemetry transmission does not exist; sharing is manual by design until Phase 13.
