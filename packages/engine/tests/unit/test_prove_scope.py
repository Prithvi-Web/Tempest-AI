"""Failure-mode §14.1 defense: changed files Tempest cannot execute yet must surface as
UNPROVEN records — never vanish from the run. A mixed .py/.ts PR whose TS half is invisible
would be silent scope-narrowing, the worst failure mode of the product."""

import os
import shutil
from pathlib import Path

from tempest.model import Lang, Verdict
from tempest.prove import ProveConfig, run_prove
from tempest.targets.ts_sidecar import default_sidecar_dir

from .test_targets_diff import commit_head, make_repo

_MARKER = "tempest-first-party-fixture-v1"


def test_changed_ts_file_is_surfaced_unproven_never_silently_skipped(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        {
            "core.py": "def double(x: int) -> int:\n    return x * 2\n",
            "app.ts": "export const rate = (n: number): number => n * 2;\n",
        },
    )
    (repo / ".tempest-first-party").write_text(_MARKER + "\n")
    commit_head(
        repo,
        {
            "core.py": "def double(x: int) -> int:\n    return x * 2 + 1\n",
            "app.ts": "export const rate = (n: number): number => n * 3;\n",
        },
    )
    os.environ["TEMPEST_DEV"] = "1"
    result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=6, seed=0))

    by_path = {t.file_path: t for t in result.bundle.targets}
    assert "app.ts" in by_path, "changed TS file must appear in the run, not vanish"
    ts = by_path["app.ts"]
    assert ts.lang is Lang.TYPESCRIPT
    ts_runnable = (
        shutil.which("node") is not None
        and (default_sidecar_dir() / "node_modules" / "ts-morph").exists()
    )
    if ts_runnable:
        # ADR-0028 (wave 1): the seeded arrow-const change is now genuinely PROVEN —
        # §14.1's bar rose from "surfaced honestly" to "executed".
        assert ts.verdict is Verdict.DIVERGENT, (ts.reason_code, ts.reason_detail)
    else:
        # Without node/sidecar the record still surfaces, UNPROVEN with the fix named.
        assert ts.verdict is Verdict.UNPROVEN
        assert ts.reason_detail
    # The Python half of the PR is still proven normally alongside the TS record.
    assert by_path["core.py"].verdict is Verdict.DIVERGENT
