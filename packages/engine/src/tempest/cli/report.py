"""Terminal report renderer. One producer (the bundle), many renderers — this is the CLI's.

The "NOT PROVEN" panel is the honesty of the product made visible: it must be impossible
to miss (master spec: suppressing unproven targets is the single worst failure mode)."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tempest.bundle.bundle import RunBundle
from tempest.model import Severity, Verdict

_VERDICT_STYLE = {
    Verdict.DIVERGENT: "bold red",
    Verdict.EQUIVALENT_UNDER_BUDGET: "bold green",
    Verdict.UNPROVEN: "bold yellow",
    Verdict.ERROR: "bold magenta",
}


_TIER_LABEL = {
    "T1": ("green", "T1 · container isolation"),
    "T2": ("green", "T2 · OS-native sandbox (macOS Seatbelt)"),
    "T3": ("yellow", "T3 · reduced assurance"),
    "fixture": ("cyan", "first-party fixture (trusted, in-repo corpus)"),
    "none": ("red", "no sandbox — nothing executed"),
    "unknown": ("dim", "tier not recorded"),
}


def _render_tier(bundle: RunBundle, console: Console) -> None:
    """The isolation tier, always visible — never let a degraded tier pass unnoticed (§3)."""
    tier = bundle.manifest.sandbox_tier
    colour, label = _TIER_LABEL.get(tier, ("dim", f"tier {tier}"))
    line = f"[{colour}]sandbox: {label}[/{colour}]"
    if bundle.manifest.sandbox_assurance == "reduced":
        line += " [yellow]— REDUCED ASSURANCE, see the named limitation[/yellow]"
    console.print(line)


def render_report(bundle: RunBundle, console: Console) -> None:
    m = bundle.manifest
    style = _VERDICT_STYLE[m.verdict]
    divergent = [t for t in bundle.targets if t.verdict is Verdict.DIVERGENT]
    unproven = [t for t in bundle.targets if t.verdict is Verdict.UNPROVEN]
    equivalent = [t for t in bundle.targets if t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET]

    headline = {
        Verdict.DIVERGENT: (
            f"{sum(len(t.divergences) for t in divergent)} divergence(s) across "
            f"{len(divergent)} target(s). Here they are. Here is the smallest one."
        ),
        Verdict.EQUIVALENT_UNDER_BUDGET: (
            f"{len(equivalent)} target(s) behaved identically under budget. "
            "This is not “correct” — it is what was exercised."
        ),
        Verdict.UNPROVEN: "Nothing could be exercised. Nothing is blessed.",
        Verdict.ERROR: "Tempest itself failed — see the internal trace.",
    }[m.verdict]

    console.print(
        Panel(
            f"[{style}]{m.verdict}[/{style}]\n{headline}",
            title=f"tempest · {m.repo} · {m.base_sha[:12]}..{m.head_sha[:12]}",
            border_style=style.split()[-1],
        )
    )
    _render_tier(bundle, console)
    if m.base_deps != m.head_deps:
        console.print(
            f"[yellow]dependencies changed between revisions "
            f"({m.base_deps} → {m.head_deps}) — dependency-induced divergence "
            f"is a real finding, not noise[/yellow]"
        )

    table = Table(show_lines=False, pad_edge=False)
    table.add_column("target")
    table.add_column("class")
    table.add_column("verdict")
    table.add_column("inputs", justify="right")
    table.add_column("chg-line cov", justify="right")
    table.add_column("div", justify="right")
    for t in bundle.targets:
        table.add_row(
            f"{t.module}.{t.qualname}",
            t.classification,
            f"[{_VERDICT_STYLE[t.verdict]}]{t.verdict}[/{_VERDICT_STYLE[t.verdict]}]",
            str(t.inputs_run),
            f"{t.changed_line_coverage:.0%}",
            str(len(t.divergences)),
        )
    console.print(table)

    for t in divergent:
        for d in t.divergences:
            sev = " [dim](low severity)[/dim]" if d.severity is Severity.LOW else ""
            console.print(
                Panel(
                    f"[bold]{d.divergence_class}[/bold]{sev} — {d.detail}\n"
                    f"minimized input: [bold cyan]{d.minimized_args}[/bold cyan] "
                    f"kwargs {d.minimized_kwargs}\n"
                    f"  base: {d.base_summary}\n"
                    f"  head: {d.head_summary}\n"
                    f"repro: repros/{d.repro_filename}",
                    title=f"{t.module}.{t.qualname}",
                    border_style="red",
                )
            )

    if unproven:
        lines = "\n".join(
            f"[bold]{t.module}.{t.qualname}[/bold] — {t.reason_code}: {t.reason_detail}"
            for t in unproven
        )
        console.print(
            Panel(
                lines,
                title=f"⚠ NOT PROVEN — {len(unproven)} target(s) were NOT exercised",
                border_style="yellow",
            )
        )
