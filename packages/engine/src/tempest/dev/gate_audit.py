"""C5 gate: `python -m tempest.dev.gate_audit --enumerate-paths --require-forge-test-per-path`

Law L28: the proof gate survives adoption. Every code path by which agent-authored change
reaches a user is DECLARED below, still exists where declared, carries a forge test that
actually collects — and no undeclared path exists. Both directions, the upstream_check
ledger discipline: a stale row fails, an undeclared discovery fails.

The declared table is the enumeration L28 asks for. A row names the entry point (file +
signature, so a refactor that moves it forces a re-audit rather than a silent pass) and the
pytest node whose collection proves the adversarial coverage still exists. Rows whose path
authors NO repository change (the chat surface) say so explicitly — the row exists precisely
so the claim is auditable.

Discovery tripwires (each proven to fail on a violating tree):
- `ProvenChange(` constructed anywhere under src outside the orchestrator — a second way to
  claim a verdict.
- `run_task(` called from any src module not declared here (dev harnesses exempt by their
  tree) — a NEW product surface driving the runtime must be declared and forged.
- `.accept(` in any src module importing the shadow, outside the declared acceptance path —
  a second door into the user's tree.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "__pycache__", "target"}


@dataclass(frozen=True)
class AuditPath:
    """One declared way agent output reaches a user."""

    path_id: str
    entry_file: str
    entry_signature: str
    forge_node: str
    note: str


PATHS: tuple[AuditPath, ...] = (
    AuditPath(
        path_id="orchestrator-turn",
        entry_file="packages/engine/src/tempest/agent/orchestrator.py",
        entry_signature="def run_task(",
        forge_node=(
            "packages/engine/tests/integration/test_agent_orchestrator.py"
            "::TestL16IsAStateWithNoConstructor"
        ),
        note="the one turn loop; ProvenChange has no constructor without a bundle",
    ),
    AuditPath(
        path_id="shadow-accept",
        entry_file="packages/engine/src/tempest/agent/shadow.py",
        entry_signature="def accept(",
        forge_node=(
            "packages/engine/tests/unit/test_agent_shadow.py::TestAccept"
            "::test_acceptance_refuses_to_clobber_a_file_the_user_edited_meanwhile"
        ),
        note="the ONLY writer of the user's tree; user edits win, journalled",
    ),
    AuditPath(
        path_id="subagent-fleet",
        entry_file="packages/engine/src/tempest/agent/subagents.py",
        entry_signature="def run_fleet(",
        forge_node=(
            "packages/engine/tests/integration/test_agent_subagents.py::TestLeastPrivilege"
            "::test_a_child_may_not_widen_its_grants"
        ),
        note="each child ends on its own ProvenChange; grants never widen",
    ),
    AuditPath(
        path_id="composer-selection",
        entry_file="packages/engine/src/tempest/compose/compose.py",
        entry_signature="def apply_selection(",
        forge_node=(
            "packages/engine/tests/integration/test_compose.py::TestProvingASubset"
            "::test_a_subset_gets_its_own_verdict_from_the_engine"
        ),
        note="accepted hunks reach the user only with the engine's own verdict",
    ),
    AuditPath(
        path_id="chat-surface",
        entry_file="packages/api/src/tempest_api/chatturn.py",
        entry_signature="def start_turn(",
        forge_node=(
            "packages/api/tests/test_chat_turn.py::TestHonestFailure"
            "::test_the_chat_surface_cannot_author_a_proof_claim"
        ),
        note=(
            "authors NO repository change — no tools, no shadow, no ProvenChange; the forge "
            "test pins that vacancy so it cannot erode silently"
        ),
    ),
)

#: src files allowed to call `run_task(` — the declared runtime homes.
_RUN_TASK_HOMES = {
    "packages/engine/src/tempest/agent/orchestrator.py",
    "packages/engine/src/tempest/agent/subagents.py",
}
#: src files allowed to call `.accept(` on the shadow.
_ACCEPT_HOMES = {
    "packages/engine/src/tempest/agent/shadow.py",
}


def _repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "packages" / "desktop").is_dir():
            return candidate
    raise SystemExit("gate_audit: no repository root above " + str(start))


def _src_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for base in ("packages/engine/src", "packages/api/src"):
        top = root / base
        if not top.is_dir():
            continue
        stack = [top]
        while stack:
            current = stack.pop()
            for entry in sorted(current.iterdir()):
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in _SKIP_DIRS:
                        stack.append(entry)
                elif entry.suffix == ".py":
                    out.append(entry)
    return out


def _check_declared(root: Path, paths: tuple[AuditPath, ...], fail: list[str]) -> None:
    for row in paths:
        entry = root / row.entry_file
        if not entry.is_file():
            fail.append(f"{row.path_id}: entry file {row.entry_file} is GONE — stale row")
            continue
        if row.entry_signature not in entry.read_text(encoding="utf-8", errors="replace"):
            fail.append(
                f"{row.path_id}: '{row.entry_signature}' not found in {row.entry_file} — "
                "the path moved; re-audit rather than silently passing"
            )


def _check_forge_collection(root: Path, paths: tuple[AuditPath, ...], fail: list[str]) -> None:
    for row in paths:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--no-cov",
                "-p",
                "no:cacheprovider",
                row.forge_node,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        collected = [
            line
            for line in result.stdout.splitlines()
            if "::" in line and not line.startswith(("=", "no tests ran"))
        ]
        if result.returncode != 0 or not collected:
            fail.append(
                f"{row.path_id}: forge test does not collect ({row.forge_node}) — a "
                "declared path without a living adversarial test is an unforged door"
            )


def _check_discovery(root: Path, paths: tuple[AuditPath, ...], fail: list[str]) -> None:
    declared_files = {row.entry_file for row in paths}
    orchestrator = "packages/engine/src/tempest/agent/orchestrator.py"
    for path in _src_files(root):
        rel = str(path.relative_to(root))
        if rel.startswith("packages/engine/src/tempest/dev/"):
            # The dev gates and benches DRIVE the runtime to measure it (agent_bench,
            # redteam, resume_test) and name the tripwire strings in their own source
            # (this module included); none of them is a surface a user's change flows
            # through. Product code stays fully swept.
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "ProvenChange(" in text and rel != orchestrator:
            fail.append(
                f"{rel}: constructs ProvenChange — a second construction site is a second "
                "way to claim a verdict (L16); declare and forge it or remove it"
            )
        if "run_task(" in text and rel not in _RUN_TASK_HOMES and "def run_task" not in text:
            fail.append(
                f"{rel}: calls run_task — a product surface driving the runtime must be a "
                "declared, forged row in gate_audit.PATHS"
            )
        if (
            ".accept(" in text
            and "tempest.agent.shadow" in text
            and rel not in _ACCEPT_HOMES
            and rel not in declared_files
        ):
            fail.append(
                f"{rel}: accepts shadow changes outside the declared acceptance path — a "
                "second door into the user's tree"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enumerate-paths", action="store_true", required=True)
    parser.add_argument("--require-forge-test-per-path", action="store_true", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--skip-collection",
        action="store_true",
        help="fixture trees have no test suite to collect against (unit pins only)",
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else _repo_root(Path.cwd())
    fail: list[str] = []
    _check_declared(root, PATHS, fail)
    _check_discovery(root, PATHS, fail)
    if not args.skip_collection:
        _check_forge_collection(root, PATHS, fail)

    if fail:
        print(f"gate_audit: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"GATE-AUDIT {problem}", file=sys.stderr)
        return 1
    print(
        f"gate_audit: {len(PATHS)} declared paths, every entry anchored, every forge test "
        "collecting, zero undeclared constructions — L28 holds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
