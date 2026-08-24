"""Every gate_audit check is proven to FAIL on a violating tree. Fixture trees carry the
five declared entry files with their signatures; collection is skipped there (a fixture has
no suite to collect) and exercised for real against this repository."""

from pathlib import Path

from tempest.dev import gate_audit

_ENTRIES: dict[str, str] = {
    "packages/engine/src/tempest/agent/orchestrator.py": "def run_task(spec):\n    pass\n",
    "packages/engine/src/tempest/agent/shadow.py": "def accept(self):\n    pass\n",
    "packages/engine/src/tempest/agent/subagents.py": (
        "def run_fleet(parent):\n    return run_task(parent)\n"
    ),
    "packages/engine/src/tempest/compose/compose.py": "def apply_selection(repo):\n    pass\n",
    "packages/api/src/tempest_api/chatturn.py": "def start_turn(payload):\n    pass\n",
    # The SIXTH door (ADR-0079 §8): a tool-bearing chat turn dispatches through `run_task`,
    # so the miniature world needs it as a DECLARED caller — exactly as `subagents.py` is.
    "packages/api/src/tempest_api/agentturn.py": (
        "def run_agent_turn(payload):\n    return run_task(payload)\n"
    ),
}


def _passing_tree(root: Path) -> None:
    (root / "packages/desktop").mkdir(parents=True)
    for rel, body in _ENTRIES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def _run(root: Path) -> int:
    return gate_audit.main(
        [
            "--enumerate-paths",
            "--require-forge-test-per-path",
            "--root",
            str(root),
            "--skip-collection",
        ]
    )


class TestPassing:
    def test_the_fixture_world_passes(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        assert _run(tmp_path) == 0

    def test_the_real_repository_passes_with_collection(self) -> None:
        """The expensive, honest one: every declared forge node must genuinely collect in
        THIS repository — a stale node id is a door whose guard quietly retired."""
        assert gate_audit.main(["--enumerate-paths", "--require-forge-test-per-path"]) == 0


class TestStaleRows:
    def test_a_vanished_entry_file_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/engine/src/tempest/agent/shadow.py").unlink()
        assert _run(tmp_path) == 1

    def test_a_moved_entry_signature_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/engine/src/tempest/compose/compose.py").write_text(
            "def apply_the_selection(repo):\n    pass\n"
        )
        assert _run(tmp_path) == 1


class TestDiscovery:
    def test_an_undeclared_proven_change_construction_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        rogue = tmp_path / "packages/api/src/tempest_api/rogue.py"
        rogue.write_text('claim = ProvenChange(bundle_id="stolen")\n')
        assert _run(tmp_path) == 1

    def test_an_undeclared_run_task_caller_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        rogue = tmp_path / "packages/api/src/tempest_api/surface.py"
        rogue.write_text("result = run_task(spec)\n")
        assert _run(tmp_path) == 1

    def test_an_undeclared_shadow_acceptance_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        rogue = tmp_path / "packages/api/src/tempest_api/door.py"
        rogue.write_text("from tempest.agent.shadow import Shadow\n\nShadow().accept()\n")
        assert _run(tmp_path) == 1

    def test_the_dev_tree_is_exempt_because_it_measures_the_runtime(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        bench = tmp_path / "packages/engine/src/tempest/dev/bench_thing.py"
        bench.parent.mkdir(parents=True, exist_ok=True)
        bench.write_text("outcome = run_task(spec)\n")
        assert _run(tmp_path) == 0
