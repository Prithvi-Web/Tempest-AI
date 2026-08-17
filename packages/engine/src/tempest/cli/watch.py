"""`tempest watch` — the continuous agent (ADR-0029, HANDOFF-WORLD-CLASS 2.4).

Poll the repo's HEAD; every NEW commit is proven incrementally against the previous one
(prev → new), so each commit gets its own verdict and its own bundle. L11 throughout: the
poll honors battery/thermal pause, Ctrl-C exits cleanly (run_prove's cancel discipline
kills children), and the machine is never saturated — one prove at a time, then back to
sleep.
"""

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from tempest.execute.powerstate import wait_while_paused
from tempest.prove import ProveConfig, ProveResult, run_prove


class WatchError(Exception):
    """The watched repo cannot be polled; the message says exactly what to fix."""


def _rev_parse(repo: Path, ref: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise WatchError(f"cannot resolve `{ref}` in {repo}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _verdict_line(sha: str, result: ProveResult) -> str:
    m = result.bundle.manifest
    divergences = sum(len(t.divergences) for t in result.bundle.targets)
    detail = f" · {divergences} divergence(s)" if divergences else ""
    return (
        f"[bold]{m.verdict}[/bold]{detail} · {sha[:12]} · "
        f"{len(result.bundle.targets)} target(s) · bundle: {result.bundle_dir}"
    )


def run_watch(
    repo: Path,
    *,
    interval: float,
    max_inputs: int | None,
    seed: int,
    from_ref: str | None,
    once: bool,
    console: Console,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """The loop, exposed for tests: `sleeper` is injected so the interrupt and idle arms
    are drivable deterministically; every prove is the real engine."""
    last = _rev_parse(repo, from_ref or "HEAD")
    console.print(
        f"[dim]watching[/dim] {repo} [dim]from[/dim] {last[:12]} "
        f"[dim]every[/dim] {interval:g}s [dim]— Ctrl-C stops[/dim]"
    )
    try:
        while True:
            # L11: never prove on battery/thermal pressure
            wait_while_paused(cancel=None, notify=None)
            head = _rev_parse(repo, "HEAD")
            if head != last:
                console.print(
                    f"[dim]new commit[/dim] {head[:12]} — proving {last[:12]}..{head[:12]}"
                )
                if max_inputs is None:
                    cfg = ProveConfig(repo=repo, base=last, head=head, seed=seed)
                else:
                    cfg = ProveConfig(
                        repo=repo, base=last, head=head, max_inputs=max_inputs, seed=seed
                    )
                result = run_prove(cfg)
                console.print(_verdict_line(head, result))
                last = head
                if once:
                    return 0
            sleeper(interval)
    except KeyboardInterrupt:
        console.print("[dim]watch stopped[/dim]")
        return 0
