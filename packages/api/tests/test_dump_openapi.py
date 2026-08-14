"""dump_openapi must emit byte-identical documents on every run (CLAUDE.md §9 zero-drift).

The script entrypoint is exercised as a real `python -m` subprocess (Law L4 — no mocks); it
inherits this environment so the child records its own coverage when the parent is measuring.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import coverage

from tempest_api.dev.dump_openapi import dump

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestDump:
    def test_dump_is_byte_deterministic(self, tmp_path: Path) -> None:
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        dump(first)
        dump(second)
        assert first.read_bytes() == second.read_bytes()
        spec = json.loads(first.read_text(encoding="utf-8"))
        assert spec["openapi"].startswith("3.")
        assert first.read_text(encoding="utf-8").endswith("\n")

    def test_module_entrypoint_writes_the_same_bytes(self, tmp_path: Path) -> None:
        out = tmp_path / "cli.json"
        env = os.environ.copy()
        if coverage.Coverage.current() is not None:
            env["COVERAGE_PROCESS_START"] = str(REPO_ROOT / "pyproject.toml")
        proc = subprocess.run(
            [sys.executable, "-m", "tempest_api.dev.dump_openapi", str(out)],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        direct = tmp_path / "direct.json"
        dump(direct)
        assert out.read_bytes() == direct.read_bytes()
