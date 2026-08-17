"""`tempest` CLI entry point."""

import signal
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import typer
from rich.console import Console

import tempest
from tempest.cli import diagnose as diagnose_cmd
from tempest.cli import doctor as doctor_cmd
from tempest.cli.logs import logs_app
from tempest.crashlog import install_crash_capture

app = typer.Typer(
    name="tempest",
    help="Tempest AI — behavioral proof agent. Executes diffs; reports divergence with evidence.",
    no_args_is_help=True,
)
doctor_cmd.register(app)
diagnose_cmd.register(app)
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
    fetch_deps: bool = typer.Option(
        False,
        "--fetch-deps",
        help="Allow downloading dependency WHEELS once (never builds, never runs repo "
        "code); the cache makes every later run offline again",
    ),
) -> None:
    """Execute base and head side by side and report where behavior diverges — with evidence."""
    from tempest.cli.report import render_report
    from tempest.config import TempestConfig, TempestConfigError
    from tempest.envrepro.worktree import EnvReproError
    from tempest.execute.cancel import CancelScope, ProveCancelled
    from tempest.model import ReasonCode, Verdict
    from tempest.prove import ProveConfig, run_prove
    from tempest.targets.diff import DiffError

    console = Console()
    try:
        file_cfg = TempestConfig.load(repo)
    except TempestConfigError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(2) from None
    # L11 (review finding 3): one CancelScope per prove, wired to Ctrl-C. Every sandbox
    # worker registers with the scope, so a SIGINT SIGKILLs all child process groups in
    # under two seconds instead of orphaning session-leader workers past the CLI's death.
    # Signal handlers exist only on the main thread; an embedded (threaded) prove simply
    # runs without the Ctrl-C hook.
    scope = CancelScope()
    previous_handler: Callable[[int, FrameType | None], object] | int | None = None
    handler_installed = False
    if threading.current_thread() is threading.main_thread():

        def _on_sigint(signum: int, frame: FrameType | None) -> None:
            scope.cancel()  # children die now; the prove thread unwinds via ProveCancelled

        previous_handler = signal.signal(signal.SIGINT, _on_sigint)
        handler_installed = True
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
                fetch_deps=fetch_deps,
                cancel=scope,
            )
        )
    except ProveCancelled:
        console.print(
            "[bold yellow]cancelled — all sandbox workers were killed; nothing ran to "
            "completion and nothing is blessed[/bold yellow]"
        )
        raise typer.Exit(130) from None
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
    finally:
        if handler_installed:
            signal.signal(signal.SIGINT, previous_handler)
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
