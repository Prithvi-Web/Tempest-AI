"""`tempest logs` — view the structured engine log (`tempest.jsonl` + rotated backups).

Self-contained sub-app; `cli/main.py` owns registration. Options use the Annotated form so
no function call sits in a parameter default (ruff B008 stays enforceable for this file).
"""

import json
from typing import Annotated

import typer

logs_app = typer.Typer(
    name="logs",
    help="Structured engine logs — newest last, straight from the local JSON-lines file.",
    no_args_is_help=True,
)


@logs_app.callback()
def main() -> None:
    """Read-only viewer over `log_dir()/tempest.jsonl`; nothing here mutates the log."""


@logs_app.command()
def show(
    limit: Annotated[int, typer.Option(help="Maximum records to print (newest kept)")] = 50,
    level: Annotated[
        str | None,
        typer.Option(help="Minimum level, case-insensitive (DEBUG, INFO, WARNING, ERROR, ...)"),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print raw JSON lines instead of human-readable text")
    ] = False,
) -> None:
    """Print the newest engine log records, one per line, newest last."""
    from tempest.obslog import read_records

    try:
        records = read_records(limit=limit, level=level)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    for record in records:
        if json_output:
            typer.echo(json.dumps(record, ensure_ascii=False, default=str))
        else:
            ts = record.get("ts", "?")
            lvl = record.get("level", "?")
            component = record.get("component", "?")
            message = record.get("message", "")
            typer.echo(f"{ts} {lvl} [{component}] {message}")
