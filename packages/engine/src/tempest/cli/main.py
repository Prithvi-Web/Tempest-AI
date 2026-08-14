"""`tempest` CLI entry point."""

from pathlib import Path

import typer
from rich.console import Console

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


@app.command()
def prove(
    base: str = typer.Option(..., help="Base (pre-change) git ref"),
    head: str = typer.Option("HEAD", help="Head (post-change) git ref"),
    repo: Path = typer.Option(Path.cwd(), help="Repository root"),
    max_inputs: int = typer.Option(300, help="Per-target input budget"),
    seed: int = typer.Option(0, help="Deterministic generation seed"),
    float_tolerance: float | None = typer.Option(
        None, help="Opt-in relative float tolerance (default: exact comparison)"
    ),
    out: Path | None = typer.Option(None, help="Bundle output directory"),
) -> None:
    """Execute base and head side by side and report where behavior diverges — with evidence."""
    from tempest.cli.report import render_report
    from tempest.model import Verdict
    from tempest.prove import ProveConfig, run_prove

    console = Console()
    result = run_prove(
        ProveConfig(
            repo=repo,
            base=base,
            head=head,
            max_inputs=max_inputs,
            seed=seed,
            float_rel_tol=float_tolerance,
            out=out,
        )
    )
    if result.sandbox_kind == "process-first-party":
        console.print(
            "[bold yellow]⚠ first-party fixture mode: ProcessSandbox in use "
            "(trusted in-repo corpus only — ADR-0003/0008)[/bold yellow]"
        )
    render_report(result.bundle, console)
    console.print(f"bundle: {result.bundle_dir}\nzip:    {result.zip_path}")
    raise typer.Exit(1 if result.bundle.manifest.verdict is Verdict.DIVERGENT else 0)
