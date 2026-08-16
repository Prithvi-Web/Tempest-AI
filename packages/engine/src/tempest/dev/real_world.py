"""Real-world proof-rate measurement (HANDOFF-WORLD-CLASS 2.2) — the number that decides
everything. Runs the REAL engine against real open-source repos across real release pairs
and renders the honest table for docs/METRICS.md: verdict counts, proof rate, and the
UNPROVEN reason distribution (which IS the engine roadmap, stated as evidence).

Not a verify gate: it needs network clones and real wall-clock. Run it deliberately:

    TEMPEST_NO_POWER_PAUSE=1 uv run python -m tempest.dev.real_world spec.toml --out table.md

Spec format (TOML):

    [[repos]]
    name = "packaging"
    url = "https://github.com/pypa/packaging"
    base = "24.1"     # any git ref; resolved and recorded as exact SHAs
    head = "24.2"
"""

import argparse
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tempest.bundle.bundle import TargetRecord
from tempest.model import Verdict
from tempest.prove import ProveConfig, run_prove

_DEFAULT_WORK_DIR = Path.home() / ".cache" / "tempest-real-world"
_PROVEN = (Verdict.DIVERGENT, Verdict.EQUIVALENT_UNDER_BUDGET)


@dataclass(frozen=True)
class RepoResult:
    name: str
    url: str
    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str
    sandbox_tier: str
    records: tuple[TargetRecord, ...]


def render_real_world_table(results: list[RepoResult]) -> str:
    """The honest markdown. Rates are computed from the records themselves — nothing is
    estimated, and a repo with zero Python targets says so instead of dividing by it."""
    lines: list[str] = []
    lines.append(
        "| Repo | Base → Head | Tier | Targets | DIVERGENT | EQUIVALENT | UNPROVEN "
        "| ERROR | Proof rate |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    total_by_verdict: Counter[Verdict] = Counter()
    grand_total = 0
    for r in results:
        by_verdict = Counter(t.verdict for t in r.records)
        total = len(r.records)
        proven = sum(by_verdict[v] for v in _PROVEN)
        total_by_verdict.update(by_verdict)
        grand_total += total
        rate = f"{proven}/{total} ({round(100 * proven / total)}%)" if total else "0/0 (n/a)"
        lines.append(
            f"| {r.name} | {r.base_ref} `{r.base_sha[:12]}` → {r.head_ref} "
            f"`{r.head_sha[:12]}` | {r.sandbox_tier} | {total} "
            f"| {by_verdict[Verdict.DIVERGENT]} | {by_verdict[Verdict.EQUIVALENT_UNDER_BUDGET]} "
            f"| {by_verdict[Verdict.UNPROVEN]} | {by_verdict[Verdict.ERROR]} | {rate} |"
        )
    grand_proven = sum(total_by_verdict[v] for v in _PROVEN)
    overall = (
        f"{grand_proven}/{grand_total} ({round(100 * grand_proven / grand_total)}%)"
        if grand_total
        else "0/0 (n/a)"
    )
    lines.append(
        f"| **overall** |  |  | **{grand_total}** | **{total_by_verdict[Verdict.DIVERGENT]}** "
        f"| **{total_by_verdict[Verdict.EQUIVALENT_UNDER_BUDGET]}** "
        f"| **{total_by_verdict[Verdict.UNPROVEN]}** | **{total_by_verdict[Verdict.ERROR]}** "
        f"| **{overall}** |"
    )

    unproven = [t for r in results for t in r.records if t.verdict is Verdict.UNPROVEN]
    if unproven:
        lines.append("")
        lines.append("UNPROVEN reason distribution (the engine roadmap, as evidence):")
        lines.append("")
        lines.append("| reason_code | count | example target | example detail |")
        lines.append("|---|---|---|---|")
        by_reason: dict[str, list[TargetRecord]] = {}
        for t in unproven:
            by_reason.setdefault(t.reason_code.value if t.reason_code else "?", []).append(t)
        for reason, records in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            example = records[0]
            detail = (example.reason_detail or "").split("\n")[0][:100]
            lines.append(
                f"| {reason} | {len(records)} | `{example.module}.{example.qualname}` | {detail} |"
            )
    return "\n".join(lines) + "\n"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _materialize_clone(work_dir: Path, name: str, url: str) -> Path:
    clone = work_dir / name
    if not clone.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{name}] cloning {url}…", flush=True)
        subprocess.run(
            ["git", "clone", "--quiet", url, str(clone)], check=True, capture_output=True
        )
    else:
        print(f"[{name}] reusing clone; fetching tags…", flush=True)
        _git(clone, "fetch", "--tags", "--quiet")
    return clone


def _measure_repo(
    work_dir: Path, name: str, url: str, base: str, head: str, max_inputs: int
) -> RepoResult:
    clone = _materialize_clone(work_dir, name, url)
    base_sha = _git(clone, "rev-parse", f"{base}^{{commit}}")
    head_sha = _git(clone, "rev-parse", f"{head}^{{commit}}")
    print(f"[{name}] proving {base} ({base_sha[:12]}) → {head} ({head_sha[:12]})…", flush=True)
    result = run_prove(
        ProveConfig(
            repo=clone,
            base=base_sha,
            head=head_sha,
            max_inputs=max_inputs,
            seed=0,
            out=work_dir / "bundles" / f"{name}-{base_sha[:12]}-{head_sha[:12]}",
        )
    )
    py_records = tuple(t for t in result.bundle.targets if t.lang.value == "PYTHON")
    print(
        f"[{name}] {len(py_records)} python targets, verdict {result.bundle.manifest.verdict} "
        f"(tier {result.sandbox_tier})",
        flush=True,
    )
    return RepoResult(
        name=name,
        url=url,
        base_ref=base,
        head_ref=head,
        base_sha=base_sha,
        head_sha=head_sha,
        sandbox_tier=result.sandbox_tier,
        records=py_records,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="TOML file with [[repos]] entries")
    parser.add_argument("--work-dir", type=Path, default=_DEFAULT_WORK_DIR)
    parser.add_argument("--max-inputs", type=int, default=30)
    parser.add_argument("--out", type=Path, default=None, help="also write the table here")
    args = parser.parse_args(argv)

    spec = tomllib.loads(args.spec.read_text(encoding="utf-8"))
    results: list[RepoResult] = []
    for entry in spec["repos"]:
        results.append(
            _measure_repo(
                args.work_dir,
                entry["name"],
                entry["url"],
                entry["base"],
                entry["head"],
                args.max_inputs,
            )
        )
    table = render_real_world_table(results)
    print()
    print(table)
    if args.out is not None:
        args.out.write_text(table, encoding="utf-8")
        print(f"table written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
