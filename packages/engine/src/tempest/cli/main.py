"""`tempest` CLI entry point."""

from pathlib import Path

import typer
from rich.console import Console

import tempest
from tempest.cli import doctor as doctor_cmd
from tempest.cli.logs import logs_app
from tempest.crashlog import install_crash_capture

app = typer.Typer(
    name="tempest",
    help="Tempest AI — behavioral proof agent. Executes diffs; reports divergence with evidence.",
    no_args_is_help=True,
)
doctor_cmd.register(app)
app.add_typer(logs_app, name="logs")


@app.callback()
def main() -> None:
    """Tempest proves behavior; it never guesses."""
    install_crash_capture()  # Phase 17: unhandled crashes leave a scrubbed local record


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"tempest {tempest.__version__}")


@app.command()
def prove(
    base: str = typer.Option(..., help="Base (pre-change) git ref"),
    head: str = typer.Option("HEAD", help="Head (post-change) git ref"),
    repo: Path = typer.Option(Path.cwd(), help="Repository root"),
    max_inputs: int | None = typer.Option(
        None,
        help="Per-target input budget (default 300; overrides [budgets].max_inputs "
        "in tempest.toml)",
    ),
    seed: int = typer.Option(0, help="Deterministic generation seed"),
    float_tolerance: float | None = typer.Option(
        None,
        help="Opt-in relative float tolerance (default: exact comparison; overrides "
        "[compare].float_rel_tol in tempest.toml)",
    ),
    out: Path | None = typer.Option(None, help="Bundle output directory"),
) -> None:
    """Execute base and head side by side and report where behavior diverges — with evidence."""
    from tempest.cli.report import render_report
    from tempest.config import TempestConfig, TempestConfigError
    from tempest.envrepro.worktree import EnvReproError
    from tempest.model import ReasonCode, Verdict
    from tempest.prove import ProveConfig, run_prove
    from tempest.targets.diff import DiffError

    console = Console()
    try:
        file_cfg = TempestConfig.load(repo)
    except TempestConfigError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(2) from None
    try:
        result = run_prove(
            ProveConfig(
                repo=repo,
                base=base,
                head=head,
                max_inputs=file_cfg.effective_max_inputs(max_inputs),
                seed=seed,
                float_rel_tol=file_cfg.effective_float_rel_tol(float_tolerance),
                out=out,
                ignore_globs=file_cfg.ignore_globs,
            )
        )
    except (EnvReproError, DiffError) as exc:
        # Law L2: environment reproduction failing is UNPROVEN territory, stated plainly —
        # never a raw traceback, never a blessing.
        code = ReasonCode.ENV_REPRODUCTION_FAILED
        console.print(f"[bold red]UNPROVEN — {code}: {exc}[/bold red]")
        console.print(
            "Nothing was executed and nothing is blessed. Check that both refs exist in "
            "this repository and that it is a valid git checkout."
        )
        raise typer.Exit(2) from None
    if result.sandbox_kind == "process-first-party":
        console.print(
            "[bold yellow]⚠ first-party fixture mode: ProcessSandbox in use "
            "(trusted in-repo corpus only — ADR-0003/0008)[/bold yellow]"
        )
    render_report(result.bundle, console)
    console.print(f"bundle: {result.bundle_dir}\nzip:    {result.zip_path}")
    raise typer.Exit(1 if result.bundle.manifest.verdict is Verdict.DIVERGENT else 0)


@app.command(name="ci-comment")
def ci_comment(
    bundle: Path = typer.Option(
        ..., help="Run-bundle directory (contains manifest.json, targets.json, repros/)"
    ),
) -> None:
    """Render a run bundle as a GitHub-flavored-markdown PR comment on stdout."""
    from tempest.bundle.bundle import BundleIntegrityError, read_bundle
    from tempest.cli.ci_comment import render_ci_comment

    missing = [name for name in ("manifest.json", "targets.json") if not (bundle / name).exists()]
    if missing:
        typer.echo(
            f"error: {bundle} is not a run bundle (missing {', '.join(missing)}). "
            "Pass the directory `tempest prove` printed after `bundle:`.",
            err=True,
        )
        raise typer.Exit(2)
    try:
        parsed = read_bundle(bundle)
    except BundleIntegrityError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    typer.echo(render_ci_comment(parsed), nl=False)
