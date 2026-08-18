"""The onboarding demo repository (Phase 18): a real repo, written fresh, proven for real.

One click in an empty app must land on a real divergence in under 90 seconds — so the demo
is NOT a canned tour: the engine writes this tiny repository into the data dir, proves it
through the ordinary local-prove machinery, and every number on screen afterwards is real
evidence the user can open, re-run, and export. The seeded change is chosen to read like a
change anyone has shipped: a "harmless" rounding refactor that moves money.

The repo carries the first-party marker (ADR-0003/0008), so the process sandbox may run it
on machines without Docker — the demo must work on a fresh laptop, not just a dev box.
"""

import subprocess
import uuid
from pathlib import Path

_MARKER = "tempest-first-party-fixture-v1"

# Base: the shipped behavior. Head: the "cleanup" that changes it. One file diverges
# (rounding to cents vs raw float math), one is a true no-op refactor — so the demo run
# shows BOTH verdicts and their difference, which IS the product's vocabulary lesson.
_BASE = {
    "pricing.py": (
        "def final_price(cents: int, quantity: int) -> int:\n"
        '    """Total in cents, 3% volume discount from 10 units."""\n'
        "    total = cents * quantity\n"
        "    if quantity >= 10:\n"
        "        total -= total * 3 // 100\n"
        "    return total\n"
    ),
    "labels.py": (
        "def shelf_label(name: str, cents: int) -> str:\n"
        "    dollars = str(cents // 100)\n"
        "    rem = str(cents % 100).zfill(2)\n"
        '    return name.strip().title() + " — $" + dollars + "." + rem\n'
    ),
}
_HEAD = {
    "pricing.py": (
        "def final_price(cents: int, quantity: int) -> int:\n"
        '    """Total in cents, 3% volume discount from 10 units."""\n'
        "    total = cents * quantity\n"
        "    if quantity >= 10:\n"
        "        total = int(total * 0.97)\n"
        "    return total\n"
    ),
    "labels.py": (
        "def shelf_label(name: str, cents: int) -> str:\n"
        "    dollars, rem = divmod(cents, 100)\n"
        '    return f"{name.strip().title()} — ${dollars}.{rem:02d}"\n'
    ),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-demo",
            "GIT_AUTHOR_EMAIL": "demo@tempest.local",
            "GIT_COMMITTER_NAME": "tempest-demo",
            "GIT_COMMITTER_EMAIL": "demo@tempest.local",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def build_demo_repo(demo_root: Path) -> tuple[Path, str, str]:
    """Write a fresh demo repo under `demo_root`; returns (repo dir, base sha, head sha).

    A new directory per call: two demo runs must never share a worktree (the engine checks
    revisions out into per-run worktrees anyway, but the source repo staying pristine keeps
    the run list honest about what was proven).
    """
    # Constant LEAF name under a unique parent: the engine stamps the repo's directory name
    # into the bundle manifest, and ingest verifies manifest-vs-run identity — so the name
    # must be stable while the worktree stays fresh per click.
    repo = demo_root / f"demo-{uuid.uuid4().hex[:8]}" / "tempest-demo"
    repo.mkdir(parents=True)
    (repo / ".tempest-first-party").write_text(_MARKER + "\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    for name, body in _BASE.items():
        (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "shipped behavior", "--no-gpg-sign")
    _git(repo, "branch", "base")
    for name, body in _HEAD.items():
        (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "cleanup: simplify discount and label math", "--no-gpg-sign")
    _git(repo, "branch", "head")
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "base", "head"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo)},
    )
    base_sha, head_sha = out.stdout.split()
    return repo, base_sha, head_sha
