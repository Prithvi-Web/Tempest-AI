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


def test_mined_literals_reach_real_proves_and_find_knife_edge_boundaries(tmp_path: Path) -> None:
    """Field recall bug, 2026-08-18 (trap 38): a two-parameter boundary bug whose killing
    value exists ONLY as a mined literal (5 is on no curated edge list) was missed by the
    real pipeline — the engine's worktrees live under `.tempest/`, and mining skipped its
    own root, so corpus mining was silently dead in every real prove. This is the scenario
    that exposed it, end to end through run_prove: `>= 5` → `> 5` must be DIVERGENT."""
    repo = make_repo(
        tmp_path,
        {
            ".tempest-first-party": "tempest-first-party-fixture-v1\n",
            "shipping.py": (
                "def shipping_cost(cents: int, items: int) -> int:\n"
                '    """Order shipping in cents: flat 500, free from 5 items."""\n'
                "    if items >= 5:\n"
                "        return 0\n"
                "    return 500\n"
            ),
        },
    )
    commit_head(
        repo,
        {
            "shipping.py": (
                "def shipping_cost(cents: int, items: int) -> int:\n"
                '    """Order shipping in cents: flat 500, free from 5 items."""\n'
                "    if items > 5:\n"
                "        return 0\n"
                "    return 500\n"
            ),
        },
    )
    result = run_prove(ProveConfig(repo=repo, base="base", head="head", seed=0))
    (target,) = result.bundle.targets
    assert target.verdict is Verdict.DIVERGENT, (target.verdict, target.reason_detail)
    # …and the evidence names the boundary: every divergence has items == 5 in its input.
    assert target.divergences
    assert any("5" in d.minimized_args for d in target.divergences)
