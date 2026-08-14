"""`tempest` CLI entry point. Commands land per phase (docs/PLAN.md); `prove` arrives in Phase 1."""

import typer

import tempest

app = typer.Typer(
    name="tempest",
    help="Tempest AI — behavioral proof agent. Executes diffs; reports divergence with evidence.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Tempest proves behavior; it never guesses."""


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"tempest {tempest.__version__}")
