"""Building the index: order, incrementality, and what happens when nothing may execute.

States enumerated before the tests (trap 43): a structural-only build · a build with observation ·
a build with observation narrowed to a named set · a repo with no sandbox tier · a second build
over an unchanged tree · a build whose report is asked for as text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tempest.execute.sandbox import ProcessSandbox, SandboxSelection
from tempest.index import execution
from tempest.index.build import build_index
from tempest.index.store import index_for, symbol_rows

SANDBOX = ProcessSandbox()

_APP = (
    "def seen(x):\n    return x\n\n\n"
    "def also_seen(x):\n    return [x]\n\n\n"
    "def unseen(x):\n    return x\n"
)


def _fixture_selection(_repo: Path) -> SandboxSelection:
    return SandboxSelection(SANDBOX, tier="fixture", kind="process-first-party")


def _no_tier(_repo: Path) -> SandboxSelection:
    return SandboxSelection(None, tier="none", kind="none", reason="no OS-native tier available")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(_APP, encoding="utf-8")
    return root


class TestStructuralOnly:
    def test_it_indexes_without_running_anything(self, repo: Path) -> None:
        with index_for(repo) as conn:
            report = build_index(conn, repo, observe=False)
            assert report.executed is None
            assert report.structural.symbols == 3
            assert execution.latest_run(conn) is None, "nothing executed, so no run was recorded"

    def test_the_second_build_reparses_nothing(self, repo: Path) -> None:
        with index_for(repo) as conn:
            build_index(conn, repo, observe=False)
            assert build_index(conn, repo, observe=False).structural.files_reparsed == 0

    def test_the_report_says_what_it_did(self, repo: Path) -> None:
        with index_for(repo) as conn:
            text = build_index(conn, repo, observe=False).render()
            assert "3 symbols in 1 files" in text


class TestWithExecution:
    def test_only_the_named_symbols_are_run(self, repo: Path) -> None:
        """An index of what RAN is only interesting if it records what ran. A sweep of everything
        would answer "which functions have never been exercised?" with the empty set forever."""
        with index_for(repo) as conn:
            report = build_index(
                conn,
                repo,
                observe=True,
                only=frozenset({"seen", "also_seen"}),
                max_inputs=8,
                select=_fixture_selection,
            )
            assert report.executed is not None
            assert report.executed.symbols_observed == 2
            rows = {r.qualname: r.id for r in symbol_rows(conn)}
            assert execution.never_exercised(conn) == [rows["unseen"]]

    def test_the_report_names_what_could_not_be_observed(self, repo: Path) -> None:
        with index_for(repo) as conn:
            build_index(conn, repo, observe=False)
            report = build_index(
                conn,
                repo,
                observe=True,
                only=frozenset({"seen"}),
                max_inputs=8,
                select=_fixture_selection,
            )
            assert "executed 1/1 symbols" in report.render()


class TestWhenNothingMayExecute:
    def test_no_tier_leaves_the_structural_index_and_says_which_half_is_missing(
        self, repo: Path
    ) -> None:
        """L6: no tier, no execution. The index is still useful and now states exactly what it
        cannot answer, rather than answering execution questions with silence."""
        with index_for(repo) as conn:
            report = build_index(conn, repo, observe=True, select=_no_tier)
            assert report.executed is None
            assert "no OS-native tier available" in report.execution_skipped
            assert "no execution recorded" in report.render()
            assert report.structural.symbols == 3
            assert execution.latest_run(conn) is None


class TestTheReportSaysWhatItCouldNotDo:
    def test_a_file_it_could_not_read_is_named(self, repo: Path) -> None:
        """A symbol silently missing from the index makes every "never exercised" answer quietly
        wrong, so the file is reported rather than skipped."""
        (repo / "bad.py").write_bytes(b"\xff\xfe\x00 def f():")
        with index_for(repo) as conn:
            text = build_index(conn, repo, observe=False).render()
            assert "could not read bad.py" in text
            assert "NOT in the index" in text

    def test_a_symbol_that_could_not_be_observed_is_named(self, repo: Path) -> None:
        with index_for(repo) as conn:
            build_index(conn, repo, observe=False)
            report = build_index(
                conn,
                repo,
                observe=True,
                only=frozenset({"seen"}),
                max_inputs=0,
                select=_fixture_selection,
            )
            assert "seen not observed" in report.render()
            assert "no inputs could be generated" in report.render()

    def test_without_a_narrowing_set_every_function_is_a_target(self, repo: Path) -> None:
        """`only=None` is the F4 sweep: synthesising a spec for a repository means running
        everything in it, which is a different job from recording what a run touched."""
        with index_for(repo) as conn:
            report = build_index(conn, repo, observe=True, max_inputs=6, select=_fixture_selection)
            assert report.executed is not None
            assert report.executed.symbols_attempted == 3
