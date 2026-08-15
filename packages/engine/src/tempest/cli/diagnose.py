"""`tempest diagnose` (Phase 17): one redacted archive the user inspects before sending.

Collects the health report, recent structured logs, crash records, and telemetry counters —
every byte passes the redaction engine on the way in (crash records were scrubbed at write
time already; a second pass is a no-op by design). Nothing is transmitted anywhere: the
command writes a local zip and shows its manifest. Sharing is the user's deliberate act."""

import json
import time
import zipfile
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from tempest.cli.doctor import outbound_payload
from tempest.crashlog import crash_dir
from tempest.obslog import read_records
from tempest.redact import RedactionContext, production_context, redact_text
from tempest.telemetry import telemetry_path

_LOG_RECORDS = 500


def _redact_value(value: object, context: RedactionContext) -> object:
    """Redact BEFORE serialization: scrubbing already-serialized JSON against raw values
    misses every secret that escaping rewrote (quotes, backslashes, newlines — finding 5)."""
    if isinstance(value, str):
        return redact_text(value, context)
    if isinstance(value, list):
        return [_redact_value(item, context) for item in value]
    if isinstance(value, dict):
        return {
            redact_text(str(key), context): _redact_value(item, context)
            for key, item in value.items()
        }
    return value


def _redact_json_text(text: str, context: RedactionContext) -> str:
    """Parse-then-redact for on-disk JSON members; an unparseable file falls back to
    raw-text redaction — still scrubbed, never skipped."""
    try:
        parsed: object = json.loads(text)
    except ValueError:
        return redact_text(text, context)
    return json.dumps(_redact_value(parsed, context), indent=2) + "\n"


def _members(context: RedactionContext) -> dict[str, str]:
    members: dict[str, str] = {
        "report.json": json.dumps(_redact_value(outbound_payload(), context), indent=2)
    }
    records = read_records(limit=_LOG_RECORDS)
    if records:
        redacted = (json.dumps(_redact_value(record, context)) for record in records)
        members["logs.jsonl"] = "\n".join(redacted) + "\n"
    for crash in sorted(crash_dir().glob("crash-*.json")):
        members[f"crashes/{crash.name}"] = _redact_json_text(crash.read_text(), context)
    if telemetry_path().exists():
        members["telemetry.json"] = _redact_json_text(telemetry_path().read_text(), context)
    return members


def _manifest(members: dict[str, str]) -> str:
    lines = [
        "Tempest diagnostic bundle — REVIEW EVERY FILE BEFORE SENDING.",
        "All contents passed the redaction engine (see docs/PRIVACY.md); nothing was",
        "transmitted anywhere by this command.",
        "",
    ]
    lines += [f"  {name}  ({len(content.encode())} bytes)" for name, content in members.items()]
    return "\n".join(lines) + "\n"


def register(app: typer.Typer) -> None:
    @app.command()
    def diagnose(
        out: Annotated[Path | None, typer.Option("--out", help="output zip path")] = None,
    ) -> None:
        """Export a redacted diagnostic bundle (local zip; inspect it before sharing)."""
        console = Console()
        # The same builder the gate proves and the crash writer uses — repo names included
        # via the env-provided source (finding 3), never a hand-wired context.
        context = production_context()
        members = _members(context)
        manifest = _manifest(members)
        default_name = f"tempest-diagnostic-{time.strftime('%Y%m%dT%H%M%S')}.zip"
        target = out if out is not None else Path(default_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("MANIFEST.txt", manifest)
            for name, content in members.items():
                archive.writestr(name, content)
        console.print(manifest)
        console.print(f"wrote {target} — inspect it before sending it to anyone.")
