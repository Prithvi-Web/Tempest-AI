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

from tempest.cli.doctor import collect_payload
from tempest.crashlog import crash_dir
from tempest.obslog import read_records
from tempest.redact import RedactionContext, redact_text, secret_env_values
from tempest.telemetry import telemetry_path

_LOG_RECORDS = 500


def _members(context: RedactionContext) -> dict[str, str]:
    members: dict[str, str] = {
        "report.json": redact_text(json.dumps(collect_payload(), indent=2), context)
    }
    records = read_records(limit=_LOG_RECORDS)
    if records:
        lines = "\n".join(json.dumps(record) for record in records)
        members["logs.jsonl"] = redact_text(lines, context) + "\n"
    for crash in sorted(crash_dir().glob("crash-*.json")):
        members[f"crashes/{crash.name}"] = redact_text(crash.read_text(), context)
    if telemetry_path().exists():
        members["telemetry.json"] = redact_text(telemetry_path().read_text(), context)
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
        context = RedactionContext(env_secret_values=secret_env_values(), home_dir=str(Path.home()))
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
