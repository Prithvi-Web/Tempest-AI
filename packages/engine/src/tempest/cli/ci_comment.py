"""GitHub PR comment renderer — GitHub-flavored markdown, deterministic byte for byte.

One producer, many renderers (Law L7): this consumes the same run bundle as the terminal report
and the dashboard. The "Not proven" section must be impossible to miss (suppressing unproven
targets is the single worst failure mode), and the divergence sections carry the evidence:
minimized input plus a standalone repro script.
"""

from tempest.bundle.bundle import RunBundle, TargetRecord
from tempest.model import Severity, Verdict

COMMENT_MARKER = "<!-- tempest-report -->"
"""First line of every comment; CI uses it to find and update its single PR comment in place."""


def render_ci_comment(bundle: RunBundle) -> str:
    m = bundle.manifest
    divergent = [t for t in bundle.targets if t.verdict is Verdict.DIVERGENT]
    equivalent = [t for t in bundle.targets if t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET]
    unproven = [t for t in bundle.targets if t.verdict is Verdict.UNPROVEN]
    errored = [t for t in bundle.targets if t.verdict is Verdict.ERROR]

    lines: list[str] = [
        COMMENT_MARKER,
        f"## Tempest verdict: `{m.verdict}`",
        "",
        _headline(m.verdict, divergent, equivalent),
        "",
        f"`{m.repo}` · `{m.base_sha[:12]}..{m.head_sha[:12]}` · engine {m.engine_version} · "
        f"budget {m.budget_max_inputs} inputs/target",
        "",
    ]
    if m.base_deps != m.head_deps:
        lines += [
            f"> ⚠ Dependencies changed between revisions (`{m.base_deps}` → `{m.head_deps}`) — "
            "dependency-induced divergence is a real finding, not noise.",
            "",
        ]

    if bundle.targets:
        lines += _target_table(bundle.targets)
    else:
        lines += [
            "No differential targets were found between these revisions — nothing was "
            "exercised, so nothing is blessed.",
            "",
        ]

    lines += _divergence_sections(bundle, divergent)
    lines += _error_section(errored)
    lines += _not_proven_section(unproven)

    lines += [
        "---",
        "",
        "Every claim above is backed by the run bundle: minimized inputs, captured "
        "observations, and standalone repro scripts under `repros/`. Download the workflow's "
        "run-bundle artifact to replay them.",
    ]
    return "\n".join(lines) + "\n"


def _headline(
    verdict: Verdict, divergent: list[TargetRecord], equivalent: list[TargetRecord]
) -> str:
    if verdict is Verdict.DIVERGENT:
        count = sum(len(t.divergences) for t in divergent)
        return (
            f"{count} divergence(s) across {len(divergent)} target(s). "
            "Here they are. Here is the smallest one."
        )
    if verdict is Verdict.EQUIVALENT_UNDER_BUDGET:
        return (
            f"{len(equivalent)} target(s) behaved identically under budget. "
            "This is not “correct” — it is what was exercised."
        )
    if verdict is Verdict.UNPROVEN:
        return "Nothing could be exercised. Nothing is blessed."
    return "Tempest itself failed — see the internal trace."


def _target_table(targets: tuple[TargetRecord, ...]) -> list[str]:
    lines = [
        "| target | classification | verdict | inputs | changed-line cov | divergences |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for t in targets:
        verdict_cell = f"**{t.verdict}**" if t.verdict is Verdict.DIVERGENT else str(t.verdict)
        lines.append(
            f"| `{t.module}.{t.qualname}` | {t.classification} | {verdict_cell} "
            f"| {t.inputs_run} | {t.changed_line_coverage:.0%} | {len(t.divergences)} |"
        )
    lines.append("")
    return lines


def _divergence_sections(bundle: RunBundle, divergent: list[TargetRecord]) -> list[str]:
    lines: list[str] = []
    number = 0
    for t in divergent:
        for d in t.divergences:
            number += 1
            low = " (low severity)" if d.severity is Severity.LOW else ""
            lines += [
                f"### Divergence {number} — `{t.module}.{t.qualname}` · {d.divergence_class}{low}",
                "",
                d.detail,
                "",
                "Minimized input:",
                "",
                "```python",
                f"args:   {d.minimized_args}",
                f"kwargs: {d.minimized_kwargs}",
                "```",
                "",
            ]
            if d.args_literal != d.minimized_args or d.kwargs_literal != d.minimized_kwargs:
                lines += [
                    f"Found via `args {d.args_literal} · kwargs {d.kwargs_literal}`, "
                    f"shrunk in {len(d.shrink_path)} step(s).",
                    "",
                ]
            lines += [
                "| revision | observed |",
                "| --- | --- |",
                f"| base (`{bundle.manifest.base_sha[:12]}`) | {_cell(d.base_summary)} |",
                f"| head (`{bundle.manifest.head_sha[:12]}`) | {_cell(d.head_summary)} |",
                "",
            ]
            script = bundle.repro_scripts.get(d.repro_filename) if d.repro_filename else None
            if d.repro_filename is not None and script is not None:
                lines += [
                    "<details>",
                    f"<summary>Reproduction script — <code>repros/{d.repro_filename}</code>"
                    "</summary>",
                    "",
                    "```python",
                    script.rstrip("\n"),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            else:
                lines += [
                    f"Repro script `{d.repro_filename}` is missing from this bundle — "
                    "treat the divergence as unverified until re-run.",
                    "",
                ]
    return lines


def _error_section(errored: list[TargetRecord]) -> list[str]:
    if not errored:
        return []
    lines = [
        f"### Tempest error — {len(errored)} target(s)",
        "",
        "Tempest itself failed on these targets. This is a Tempest failure, "
        "not a statement about the change.",
        "",
        "| target | detail |",
        "| --- | --- |",
    ]
    for t in errored:
        detail = t.reason_detail or "internal error — see the run bundle trace"
        lines.append(f"| `{t.module}.{t.qualname}` | {_cell(detail)} |")
    lines.append("")
    return lines


def _not_proven_section(unproven: list[TargetRecord]) -> list[str]:
    if not unproven:
        return []
    lines = [
        f"### ⚠ Not proven — {len(unproven)} target(s) were NOT exercised",
        "",
        "Nothing below is blessed. Every row is a claim Tempest refused to make; "
        "each reason is actionable.",
        "",
        "| target | reason code | what blocked it |",
        "| --- | --- | --- |",
    ]
    for t in unproven:
        code = t.reason_code if t.reason_code is not None else "UNPROVEN"
        detail = t.reason_detail or "no further detail recorded"
        lines.append(f"| `{t.module}.{t.qualname}` | `{code}` | {_cell(detail)} |")
    lines.append("")
    return lines


def _cell(text: str) -> str:
    """Make free prose safe inside a GFM table cell."""
    return text.replace("|", "\\|").replace("\n", "<br>")
