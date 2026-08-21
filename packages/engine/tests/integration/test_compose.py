"""F12's engine half — splitting a change, attributing behaviour to it, and proving a subset.

Real git repositories, real `git diff`, real `git apply`, real proofs (L4).

The property the composer's third column rests on: **a hunk's verdict is about that hunk**. A
column that showed the whole change's verdict against every row would be worse than no column —
it would let a reader accept one hunk on evidence produced by another.

States enumerated before the tests (trap 43): a one-hunk change · two hunks in one file · hunks in
two files · a hunk that touches no executable symbol · a hunk whose file has no head source · a
change with no hunks at all · accepting all of them · accepting one of two · accepting none · a
hunk that will not apply · ids that survive a re-diff · a divergent hunk beside an equivalent one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.bundle.bundle import TargetRecord
from tempest.compose import compose
from tempest.model import Lang, TargetClassification, Verdict
from tempest.prove import ProveConfig, run_prove

from ..helpers_first_party import mark_first_party

#: The two changes are deliberately far apart. `git diff --unified=3` COALESCES changes closer
#: together than twice its context, so a fixture with them six lines apart produces ONE hunk and
#: every "two hunks" assertion below fails for a reason that is about git's output format rather
#: than about the composer. The spacers are what make this a two-hunk change (trap 59).
_BASE = """def total(xs):
    return sum(xs)


def label(name):
    return name


def spacer_one():
    return 1


def spacer_two():
    return 2


def spacer_three():
    return 3


CONSTANT = 1
"""

_HEAD = _BASE.replace("return sum(xs)", "return sum(xs) + 1").replace(
    "CONSTANT = 1", "CONSTANT = 2"
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def _dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_DEV", "1")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "app.py").write_text(_BASE, encoding="utf-8")
    mark_first_party(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    (root / "app.py").write_text(_HEAD, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "head")
    return root


def _refs(repo: Path) -> tuple[str, str]:
    return _git(repo, "rev-parse", "HEAD~1"), _git(repo, "rev-parse", "HEAD")


class TestSplitting:
    def test_a_change_becomes_applyable_pieces_each_naming_its_lines(self, repo: Path) -> None:
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        assert len(hunks) == 2, "the function body and the constant are separate hunks"
        assert {h.path for h in hunks} == {"app.py"}
        assert all(h.patch.startswith("diff --git ") for h in hunks), "each carries its own header"
        assert all(h.head_lines for h in hunks)

    def test_ids_are_stable_across_a_re_diff(self, repo: Path) -> None:
        """A UI remembers accept/reject by id. An id that moved when the diff was recomputed would
        silently re-ask a question the user already answered — or worse, apply their answer to a
        different hunk."""
        base, head = _refs(repo)
        first = compose.hunks_for(repo, base, head)
        second = compose.hunks_for(repo, base, head)
        assert [h.id for h in first] == [h.id for h in second]
        assert len({h.id for h in first}) == len(first), "distinct hunks, distinct ids"

    def test_a_change_with_nothing_matching_produces_no_hunks(self, repo: Path) -> None:
        base, head = _refs(repo)
        assert compose.hunks_for(repo, base, head, patterns=("*.rs",)) == ()

    def test_two_files_each_get_their_own_hunks(self, repo: Path) -> None:
        (repo / "other.py").write_text("def second():\n    return 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "add other")
        (repo / "other.py").write_text("def second():\n    return 2\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "change other")
        base, head = _git(repo, "rev-parse", "HEAD~3"), _git(repo, "rev-parse", "HEAD")
        hunks = compose.hunks_for(repo, base, head)
        assert {h.path for h in hunks} == {"app.py", "other.py"}


class TestAttribution:
    def _proved(self, repo: Path) -> tuple[Any, tuple[compose.Hunk, ...], dict[str, str]]:
        base, head = _refs(repo)
        result = run_prove(ProveConfig(repo=repo, base=base, head=head, max_inputs=8, seed=0))
        hunks = compose.hunks_for(repo, base, head)
        return result.bundle, hunks, {"app.py": _HEAD}

    def test_the_divergent_hunk_carries_the_divergence_and_the_other_does_not(
        self, repo: Path
    ) -> None:
        """The whole point of the third column. `total` diverged; the constant did not, and a
        column that reported the change's verdict on both rows would be evidence laundering."""
        bundle, hunks, sources = self._proved(repo)
        impacts = {i.hunk.summary: i for i in compose.impact(hunks, bundle.targets, sources)}
        diverging = [i for i in impacts.values() if i.verdict is Verdict.DIVERGENT]
        assert len(diverging) == 1
        assert diverging[0].qualnames == ("total",)
        assert diverging[0].divergence_count >= 1

    def test_a_hunk_that_changes_no_executable_symbol_is_unproven_with_a_reason(
        self, repo: Path
    ) -> None:
        """`CONSTANT = 2` is a real change and nothing executed it. Blank would invite optimism;
        EQUIVALENT would be a lie."""
        bundle, hunks, sources = self._proved(repo)
        impacts = compose.impact(hunks, bundle.targets, sources)
        constants = [i for i in impacts if not i.qualnames]
        assert len(constants) == 1
        assert constants[0].verdict is Verdict.UNPROVEN
        assert "no executable symbol" in constants[0].reason

    def test_a_hunk_whose_file_has_no_head_source_is_reported_not_skipped(self, repo: Path) -> None:
        """A row missing from the composer is a change the user cannot see they are accepting."""
        bundle, hunks, _ = self._proved(repo)
        impacts = compose.impact(hunks, bundle.targets, {})
        assert len(impacts) == len(hunks)
        assert all(i.verdict is Verdict.UNPROVEN for i in impacts)
        assert all("no head source" in i.reason for i in impacts)

    def test_no_targets_at_all_is_unproven_not_equivalent(self, repo: Path) -> None:
        _, hunks, sources = self._proved(repo)
        impacts = compose.impact(hunks, (), sources)
        assert {i.verdict for i in impacts} == {Verdict.UNPROVEN}


class TestProvingASubset:
    def test_accepting_every_hunk_reproduces_the_whole_change(self, repo: Path) -> None:
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        selection = compose.apply_selection(repo, base, hunks, "all")
        assert selection.rejected_by_git == ()
        tree_all = _git(repo, "rev-parse", f"{selection.head}^{{tree}}")
        assert tree_all == _git(repo, "rev-parse", f"{head}^{{tree}}")

    def test_accepting_one_hunk_produces_a_tree_that_is_neither_end(self, repo: Path) -> None:
        """The reason a subset is PROVED rather than filtered: this tree is a change no other
        proof in the run ever executed."""
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        chosen = next(h for h in hunks if "sum(xs) + 1" in h.patch)
        compose.apply_selection(repo, base, (chosen,), "one")
        worktree = repo / ".tempest" / "compose" / "one"
        text = (worktree / "app.py").read_text(encoding="utf-8")
        assert "sum(xs) + 1" in text, "the accepted hunk is in"
        assert "CONSTANT = 1" in text, "the rejected hunk is not"

    def test_a_subset_gets_its_own_verdict_from_the_engine(self, repo: Path) -> None:
        base, _ = _refs(repo)
        hunks = compose.hunks_for(repo, base, _git(repo, "rev-parse", "HEAD"))
        constant_only = next(h for h in hunks if "CONSTANT = 2" in h.patch)
        selection = compose.apply_selection(repo, base, (constant_only,), "constant")
        result = run_prove(
            ProveConfig(repo=repo, base=base, head=selection.head, max_inputs=8, seed=0)
        )
        assert result.bundle.manifest.verdict is not Verdict.DIVERGENT, (
            "the constant alone changes no behaviour any target executes"
        )

    def test_accepting_nothing_is_an_empty_change_not_an_error(self, repo: Path) -> None:
        base, _ = _refs(repo)
        selection = compose.apply_selection(repo, base, (), "none")
        assert selection.accepted == ()
        tree = _git(repo, "rev-parse", f"{selection.head}^{{tree}}")
        assert tree == _git(repo, "rev-parse", f"{base}^{{tree}}")

    def test_a_hunk_that_will_not_apply_is_reported_never_dropped(self, repo: Path) -> None:
        """A selection that silently lost a piece is a selection the user did not make."""
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        bogus = compose.Hunk(
            id="bogus",
            path="app.py",
            patch=(
                "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
                "@@ -900,1 +900,1 @@\n-nothing like this exists\n+replacement\n"
            ),
            head_lines=frozenset({900}),
            base_lines=frozenset({900}),
        )
        selection = compose.apply_selection(repo, base, (*hunks, bogus), "bogus")
        assert [h.id for h in selection.rejected_by_git] == ["bogus"]


def _record(qualname: str, verdict: Verdict, coverage: float = 1.0) -> TargetRecord:
    """A target record with only the fields attribution reads. Built by hand because the states
    that matter here — ERROR, and a hunk whose every target was equivalent — are hard to provoke
    from a real proof and easy to state directly."""
    return TargetRecord(
        file_path="app.py",
        module="app",
        qualname=qualname,
        lang=Lang.PYTHON,
        classification=TargetClassification.PURE_CANDIDATE,
        verdict=verdict,
        reason_code=None,
        reason_detail=None,
        inputs_run=4,
        equivalent_inputs=4,
        unprovable_inputs=0,
        changed_line_coverage=coverage,
        divergences=(),
    )


class TestTheParserOnShapesGitReallyEmits:
    """`_split` against hand-written diffs. The states below are awkward to provoke from a real
    repository and trivial to state as text, and the parser is the piece a malformed diff would
    take down silently."""

    def test_a_deletion_only_hunk_has_no_head_lines_and_says_so(self) -> None:
        diff = (
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
            "@@ -8,2 +7,0 @@\n-CONSTANT = 1\n-TRAILER = 2\n"
        )
        (hunk,) = compose._split(diff)
        assert hunk.head_lines == frozenset()
        assert hunk.base_lines == {8, 9}
        assert hunk.summary.endswith("deletion only")
        assert compose.symbols_touched("x = 1\n", hunk) == ()

    def test_the_no_newline_marker_does_not_shift_the_line_count(self) -> None:
        """`\\ No newline at end of file` is git's note about the PREVIOUS line, not a line of its
        own. Counting it would push every later line number off by one and attribute the change
        to the wrong symbol."""
        diff = (
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
            "@@ -1,1 +1,2 @@\n-old\n\\ No newline at end of file\n+new\n+second\n"
        )
        (hunk,) = compose._split(diff)
        assert hunk.head_lines == {1, 2}
        assert hunk.base_lines == {1}

    def test_a_line_before_the_first_hunk_is_ignored_not_mistaken_for_content(self) -> None:
        diff = (
            "diff --git a/app.py b/app.py\nsimilarity index 90%\n--- a/app.py\n+++ b/app.py\n"
            "@@ -1,1 +1,1 @@\n-old\n+new\n"
        )
        (hunk,) = compose._split(diff)
        assert hunk.head_lines == {1}

    def test_a_diff_git_can_not_produce_is_an_error_not_an_empty_answer(self, repo: Path) -> None:
        with pytest.raises(compose.ComposeError, match="git diff"):
            compose.hunks_for(repo, "no-such-ref", "HEAD")


class TestSummarisingSeveralTargets:
    """A hunk usually owns more than one symbol, and the summary must not dilute evidence."""

    def _one_hunk(self, repo: Path) -> tuple[compose.Hunk, ...]:
        base, head = _refs(repo)
        return (next(h for h in compose.hunks_for(repo, base, head) if "sum(xs) + 1" in h.patch),)

    def test_all_equivalent_reads_as_equivalent_under_budget(self, repo: Path) -> None:
        hunks = self._one_hunk(repo)
        (result,) = compose.impact(
            hunks, (_record("total", Verdict.EQUIVALENT_UNDER_BUDGET),), {"app.py": _HEAD}
        )
        assert result.verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        assert result.changed_line_coverage == 1.0

    def test_one_divergent_among_equivalents_reads_as_DIVERGENT(self, repo: Path) -> None:
        """Averaging would be a way to dilute evidence."""
        hunks = self._one_hunk(repo)
        (result,) = compose.impact(
            hunks,
            (
                _record("total", Verdict.EQUIVALENT_UNDER_BUDGET),
                _record("total", Verdict.DIVERGENT),
            ),
            {"app.py": _HEAD},
        )
        assert result.verdict is Verdict.DIVERGENT

    def test_one_unproven_among_equivalents_reads_as_UNPROVEN(self, repo: Path) -> None:
        """ "Some of this could not be run" is the fact a reader needs BEFORE they accept it, not
        a footnote under a reassuring word."""
        hunks = self._one_hunk(repo)
        (result,) = compose.impact(
            hunks,
            (_record("total", Verdict.EQUIVALENT_UNDER_BUDGET), _record("total", Verdict.UNPROVEN)),
            {"app.py": _HEAD},
        )
        assert result.verdict is Verdict.UNPROVEN

    def test_an_engine_failure_is_reported_as_ERROR(self, repo: Path) -> None:
        hunks = self._one_hunk(repo)
        (result,) = compose.impact(
            hunks,
            (_record("total", Verdict.EQUIVALENT_UNDER_BUDGET), _record("total", Verdict.ERROR)),
            {"app.py": _HEAD},
        )
        assert result.verdict is Verdict.ERROR

    def test_a_symbol_the_proof_never_recorded_says_so(self, repo: Path) -> None:
        hunks = self._one_hunk(repo)
        (result,) = compose.impact(hunks, (_record("other", Verdict.DIVERGENT),), {"app.py": _HEAD})
        assert result.verdict is Verdict.UNPROVEN
        assert "no record for it" in result.reason


class TestRerunningASelection:
    def test_the_same_branch_name_twice_rebuilds_rather_than_failing(self, repo: Path) -> None:
        """A composer re-proves on every toggle. If the second run tripped over the first run's
        worktree the feature would work exactly once."""
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        first = compose.apply_selection(repo, base, hunks[:1], "again")
        second = compose.apply_selection(repo, base, hunks, "again")
        assert first.head != second.head
        assert second.rejected_by_git == ()


class TestTheCallGraphClosure:
    """`affected` is where an incremental prover is wrong or right.

    Carrying a verdict forward is only honest when nothing the target can REACH has changed.
    Same-bytes is not enough: a function whose source never moved behaves differently when a
    module it imports did, which is why F12 says *call-graph-affected* and not *changed files*.
    """

    def test_a_file_that_imports_a_changed_one_is_affected(self) -> None:
        graph = compose.import_graph(
            {"a.py": "import b\n", "b.py": "import c\n", "c.py": "X = 1\n"}
        )
        assert graph["a.py"] == {"b.py"}
        assert compose.affected({"c.py"}, graph) == {"a.py", "b.py", "c.py"}

    def test_the_closure_is_a_fixed_point_not_one_hop(self) -> None:
        """A→B→C with C changed: a single pass marks B and leaves A carrying a stale verdict."""
        graph = compose.import_graph(
            {"a.py": "import b\n", "b.py": "import c\n", "c.py": "X = 1\n"}
        )
        assert "a.py" in compose.affected({"c.py"}, graph), "two hops away, still affected"

    def test_an_unrelated_file_is_not_dragged_in(self) -> None:
        graph = compose.import_graph({"a.py": "import b\n", "b.py": "X = 1\n", "z.py": "Y = 2\n"})
        assert compose.affected({"b.py"}, graph) == {"a.py", "b.py"}

    def test_from_imports_and_submodules_both_count(self) -> None:
        graph = compose.import_graph(
            {"pkg/mod.py": "X = 1\n", "user.py": "from pkg.mod import X\n"}
        )
        assert graph["user.py"] == {"pkg/mod.py"}

    def test_a_file_we_cannot_parse_depends_on_EVERYTHING(self) -> None:
        """An unknown dependency has to be treated as a dependency on everything. The alternative
        is carrying a verdict past a change we could not see."""
        graph = compose.import_graph({"broken.py": "def (:\n", "a.py": "X = 1\n"})
        assert graph["broken.py"] == {"a.py"}
        assert "broken.py" in compose.affected({"a.py"}, graph)

    def test_an_import_of_something_outside_the_change_is_ignored(self) -> None:
        graph = compose.import_graph({"a.py": "import os\nimport json\n"})
        assert graph["a.py"] == set()


class TestIncrementalReproof:
    def _selections(self, repo: Path) -> tuple[str, compose.Selection, compose.Selection]:
        base, head = _refs(repo)
        hunks = compose.hunks_for(repo, base, head)
        fn = next(h for h in hunks if "sum(xs) + 1" in h.patch)
        const = next(h for h in hunks if "CONSTANT = 2" in h.patch)
        return (
            base,
            compose.apply_selection(repo, base, (fn,), "prev"),
            compose.apply_selection(repo, base, (fn, const), "next"),
        )

    def test_changed_between_sees_only_what_the_toggle_moved(self, repo: Path) -> None:
        _, previous, new = self._selections(repo)
        assert compose.changed_between(repo, previous.head, new.head) == {"app.py"}

    def test_a_toggle_that_changes_nothing_re_proves_nothing(self, repo: Path) -> None:
        """Two selections with the same bytes. Re-running the engine here would spend a proof to
        rediscover what the previous run already established."""
        base, previous, _ = self._selections(repo)
        same = compose.apply_selection(repo, base, previous.accepted, "same")
        called: list[object] = []

        def never(cfg: object) -> object:  # pragma: no cover — the assertion is that it is not
            called.append(cfg)
            raise AssertionError("the engine was run for a toggle that changed no bytes")

        step = compose.reprove(
            repo, base, previous.head, same.head, (), prove=never, all_paths=("app.py",)
        )
        assert called == []
        assert step.reproved == () and step.carried == ("app.py",)
        assert step.bundle_id == ""

    def test_a_real_toggle_re_proves_the_affected_file_and_carries_the_rest(
        self, repo: Path
    ) -> None:
        (repo / "other.py").write_text("def untouched():\n    return 7\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "add an unrelated file")
        base = _git(repo, "rev-parse", "HEAD~2")
        head = _git(repo, "rev-parse", "HEAD")
        hunks = compose.hunks_for(repo, base, head)
        fn = next(h for h in hunks if "sum(xs) + 1" in h.patch)
        const = next(h for h in hunks if "CONSTANT = 2" in h.patch)
        previous = compose.apply_selection(repo, base, (fn,), "prev2")
        new = compose.apply_selection(repo, base, (fn, const), "next2")

        carried_record = _record("untouched", Verdict.EQUIVALENT_UNDER_BUDGET)
        step = compose.reprove(
            repo,
            base,
            previous.head,
            new.head,
            (carried_record,),
            prove=run_prove,
            max_inputs=6,
            all_paths=("app.py", "other.py"),
        )
        assert step.reproved == ("app.py",)
        assert step.carried == ("other.py",)
        assert step.bundle_id, "the re-proved half names the bundle it came from"

    def test_a_carried_record_is_only_kept_for_a_file_that_was_carried(self, repo: Path) -> None:
        """The record above is for `app.py`, which WAS re-proved. Keeping it would put two
        verdicts on one file — the fresh one and a stale one wearing the same name."""
        base, previous, new = self._selections(repo)
        stale = _record("total", Verdict.EQUIVALENT_UNDER_BUDGET)
        step = compose.reprove(
            repo,
            base,
            previous.head,
            new.head,
            (stale,),
            prove=run_prove,
            max_inputs=6,
            all_paths=("app.py",),
        )
        assert stale not in step.records
        assert all(r.file_path == "app.py" for r in step.records)
