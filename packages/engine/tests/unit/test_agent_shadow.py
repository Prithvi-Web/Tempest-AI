"""Phase 19.3 pins: the shadow worktree (L19) — the agent never writes the user's tree.

Every guard below is proven by a test that FAILS without it. The invariants are not stylistic:
L19 says agent writes are staged until accepted, and L20 says every agent action is reversible.
A shadow worktree that can escape its root, or an acceptance that can clobber uncommitted work,
breaks the promise the whole agent rests on.
"""

import subprocess
from pathlib import Path

import pytest

from tempest.agent import shadow as sw

_GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=_GIT_ENV
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real repository with one commit — no fixtures, no fakes (L4)."""
    r = tmp_path / "work"
    (r / "pkg").mkdir(parents=True)
    _git(r, "init", "-b", "main")
    (r / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (r / "README.md").write_text("# demo\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base", "--no-gpg-sign")
    return r


def _tree_state(repo: Path) -> dict[str, str]:
    """Every tracked file's bytes, so a test can assert the user's tree did not move."""
    return {
        p: (repo / p).read_text()
        for p in _git(repo, "ls-files").splitlines()
        if (repo / p).is_file()
    }


class TestCreate:
    def test_a_shadow_lives_under_dot_tempest_and_not_in_the_users_tree(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        assert s.path.is_dir()
        assert s.path.is_relative_to(repo / ".tempest" / "agent" / "worktrees")
        # The user's checkout gained nothing but the .tempest scratch directory.
        assert sorted(p.name for p in repo.iterdir() if p.name != ".git") == [
            ".tempest",
            "README.md",
            "pkg",
        ]

    def test_the_shadow_starts_as_a_faithful_copy_of_the_users_files(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        assert (s.path / "pkg" / "calc.py").read_text() == (repo / "pkg" / "calc.py").read_text()

    def test_the_baseline_includes_uncommitted_work_the_user_can_see(self, repo: Path) -> None:
        """`git stash create` snapshots the working state without mutating it.

        A baseline of bare HEAD would hand the agent a tree that differs from what the user is
        looking at — every uncommitted edit would read as an agent change.
        """
        (repo / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b + 0\n")
        before = _tree_state(repo)
        s = sw.create(repo, "task-1")
        assert (s.path / "pkg" / "calc.py").read_text() == "def add(a, b):\n    return a + b + 0\n"
        assert _tree_state(repo) == before, "creating a shadow must not touch the user's tree"

    def test_untracked_user_files_are_carried_into_the_baseline(self, repo: Path) -> None:
        (repo / "pkg" / "extra.py").write_text("X = 1\n")
        s = sw.create(repo, "task-1")
        assert (s.path / "pkg" / "extra.py").read_text() == "X = 1\n"

    def test_two_tasks_get_independent_shadows(self, repo: Path) -> None:
        a, b = sw.create(repo, "task-a"), sw.create(repo, "task-b")
        assert a.path != b.path
        sw.write(a, "pkg/calc.py", "A\n")
        assert (b.path / "pkg" / "calc.py").read_text() != "A\n"

    def test_recreating_the_same_task_id_is_refused(self, repo: Path) -> None:
        sw.create(repo, "task-1")
        with pytest.raises(sw.ShadowError, match="already exists"):
            sw.create(repo, "task-1")

    def test_a_non_repository_is_refused_with_a_reason(self, tmp_path: Path) -> None:
        with pytest.raises(sw.ShadowError, match="not a git repository"):
            sw.create(tmp_path / "nope", "task-1")


class TestWriteContainment:
    """L19's hard edge: a staged write cannot reach outside the shadow."""

    @pytest.mark.parametrize(
        "bad",
        [
            "/etc/passwd",
            "../escape.py",
            "pkg/../../escape.py",
            "pkg/./../../escape.py",
            "",
            ".git/config",
            "pkg/../.git/hooks/pre-commit",
        ],
    )
    def test_paths_that_escape_or_target_git_are_refused(self, repo: Path, bad: str) -> None:
        s = sw.create(repo, "task-1")
        with pytest.raises(sw.PathEscape):
            sw.write(s, bad, "pwned\n")

    def test_a_symlink_out_of_the_shadow_cannot_be_written_through(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        outside = repo.parent / "outside.txt"
        outside.write_text("original\n")
        (s.path / "link.txt").symlink_to(outside)
        with pytest.raises(sw.PathEscape):
            sw.write(s, "link.txt", "pwned\n")
        assert outside.read_text() == "original\n"

    def test_a_legitimate_nested_write_creates_parents(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/deep/new.py", "Y = 2\n")
        assert (s.path / "pkg" / "deep" / "new.py").read_text() == "Y = 2\n"

    def test_staged_writes_never_reach_the_users_tree(self, repo: Path) -> None:
        before = _tree_state(repo)
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        sw.write(s, "pkg/brand_new.py", "Z = 3\n")
        assert _tree_state(repo) == before
        assert not (repo / "pkg" / "brand_new.py").exists()


class TestSnapshot:
    def test_a_snapshot_is_a_real_commit_the_engine_can_prove_against(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        sha = sw.snapshot(s)
        assert len(sha) == 40
        # Resolvable from the USER's repo, which is what makes `prove base head` work unchanged.
        assert _git(repo, "rev-parse", f"{sha}^{{commit}}") == sha
        # `_git` strips, so compare without the trailing newline the blob really carries.
        assert _git(repo, "show", f"{sha}:pkg/calc.py") == "def add(a, b):\n    return a * b"

    def test_snapshotting_an_unchanged_shadow_returns_the_baseline(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        assert sw.snapshot(s) == s.baseline

    def test_changed_files_lists_exactly_what_the_agent_touched(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        sw.write(s, "pkg/new.py", "N = 1\n")
        assert sorted(sw.changed_files(s)) == ["pkg/calc.py", "pkg/new.py"]


class TestAccept:
    def test_acceptance_applies_the_staged_change_to_the_users_tree(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        sw.write(s, "pkg/new.py", "N = 1\n")
        acc = sw.accept(s)
        assert (repo / "pkg" / "calc.py").read_text() == "def add(a, b):\n    return a * b\n"
        assert (repo / "pkg" / "new.py").read_text() == "N = 1\n"
        assert sorted(acc.files) == ["pkg/calc.py", "pkg/new.py"]

    def test_partial_acceptance_applies_only_the_named_files(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "CHANGED\n")
        sw.write(s, "pkg/new.py", "N = 1\n")
        sw.accept(s, files=["pkg/new.py"])
        assert (repo / "pkg" / "new.py").exists()
        assert "CHANGED" not in (repo / "pkg" / "calc.py").read_text()

    def test_acceptance_refuses_to_clobber_a_file_the_user_edited_meanwhile(
        self, repo: Path
    ) -> None:
        """The user kept working while the agent did. Their edit wins; we refuse, loudly."""
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        (repo / "pkg" / "calc.py").write_text("USER EDITED\n")
        with pytest.raises(sw.AcceptConflict, match=r"pkg/calc\.py"):
            sw.accept(s)
        assert (repo / "pkg" / "calc.py").read_text() == "USER EDITED\n"

    def test_a_refused_acceptance_applies_nothing_at_all(self, repo: Path) -> None:
        """All-or-nothing: one conflict must not leave half the changeset applied."""
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        sw.write(s, "pkg/new.py", "N = 1\n")
        (repo / "pkg" / "calc.py").write_text("USER EDITED\n")
        with pytest.raises(sw.AcceptConflict):
            sw.accept(s)
        assert not (repo / "pkg" / "new.py").exists(), "partial application on refusal"

    def test_accepting_an_unknown_file_is_refused(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        with pytest.raises(sw.ShadowError, match="not changed"):
            sw.accept(s, files=["pkg/nope.py"])


class TestRevert:
    """L20: every agent action is reversible — journalled, not 'hopefully git has it'."""

    def test_revert_restores_the_users_tree_exactly(self, repo: Path) -> None:
        before = _tree_state(repo)
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        acc = sw.accept(s)
        assert _tree_state(repo) != before
        sw.revert(acc)
        assert _tree_state(repo) == before

    def test_revert_deletes_files_the_acceptance_created(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/brand_new.py", "N = 1\n")
        acc = sw.accept(s)
        assert (repo / "pkg" / "brand_new.py").exists()
        sw.revert(acc)
        assert not (repo / "pkg" / "brand_new.py").exists()

    def test_revert_works_on_uncommitted_user_state_not_just_git_history(self, repo: Path) -> None:
        """The pre-image is journalled because the user's baseline may never have been committed."""
        (repo / "pkg" / "calc.py").write_text("UNCOMMITTED USER WORK\n")
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        acc = sw.accept(s)
        assert (repo / "pkg" / "calc.py").read_text() == "AGENT\n"
        sw.revert(acc)
        assert (repo / "pkg" / "calc.py").read_text() == "UNCOMMITTED USER WORK\n"

    def test_reverting_twice_is_harmless(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        acc = sw.accept(s)
        sw.revert(acc)
        sw.revert(acc)  # idempotent — undo must never itself become a failure mode


class TestDiscard:
    def test_discard_removes_the_worktree_and_leaves_the_user_untouched(self, repo: Path) -> None:
        before = _tree_state(repo)
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        sw.discard(s)
        assert not s.path.exists()
        assert _tree_state(repo) == before

    def test_discard_frees_the_task_id_for_reuse(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.discard(s)
        again = sw.create(repo, "task-1")
        assert again.path.is_dir()

    def test_discarding_twice_is_harmless(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.discard(s)
        sw.discard(s)


class TestListing:
    def test_active_shadows_are_discoverable_after_a_restart(self, repo: Path) -> None:
        """The manager is stateless: the filesystem is the source of truth, not a process."""
        sw.create(repo, "task-a")
        sw.create(repo, "task-b")
        assert sorted(s.task_id for s in sw.list_shadows(repo)) == ["task-a", "task-b"]

    def test_listing_a_repo_with_no_shadows_is_empty_not_an_error(self, repo: Path) -> None:
        assert sw.list_shadows(repo) == []


class TestEdgeCases:
    """The arms the 100% gate named. Each is a real situation, not coverage theatre."""

    def test_a_task_id_with_no_usable_characters_is_refused(self, repo: Path) -> None:
        """Task ids reach both the filesystem and a git ref, so an empty slug must not pass."""
        with pytest.raises(sw.ShadowError, match="no usable characters"):
            sw.create(repo, "///")

    def test_an_untracked_symlink_is_skipped_rather_than_followed(self, repo: Path) -> None:
        """`ls-files --others` lists symlinks; copying through one would leave the repo."""
        (repo / "dangling").symlink_to(repo / "nowhere.txt")
        s = sw.create(repo, "task-1")
        assert not (s.path / "dangling").exists()
        assert (s.path / "pkg" / "calc.py").is_file(), "real files still carried across"

    def test_acceptance_refuses_when_the_user_deleted_the_file(self, repo: Path) -> None:
        """Re-creating a file the user deliberately removed would be a silent surprise."""
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        (repo / "pkg" / "calc.py").unlink()
        with pytest.raises(sw.AcceptConflict, match=r"pkg/calc\.py"):
            sw.accept(s)
        assert not (repo / "pkg" / "calc.py").exists()

    def test_revert_is_calm_when_the_user_already_deleted_the_new_file(self, repo: Path) -> None:
        """Undo must never itself become a failure mode (L20)."""
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/brand_new.py", "N = 1\n")
        acc = sw.accept(s)
        (repo / "pkg" / "brand_new.py").unlink()  # the user got there first
        sw.revert(acc)
        assert not (repo / "pkg" / "brand_new.py").exists()


class TestUntrackedFilesDoNotPoisonTheBaseline:
    """Regression: `git stash create` captures TRACKED changes only.

    The carried-over untracked files (create()) landed in the worktree but not in the baseline
    commit, so `changed_files()` reported them as agent work, `accept()` raised a false conflict
    naming a file the agent never touched, and — because acceptance is all-or-nothing — a single
    ordinary untracked file anywhere in the repo made every acceptance impossible. It also
    corrupted the proof pair F1 depends on. Found by the Phase-19 review workflow.
    """

    def test_an_untracked_file_is_not_reported_as_an_agent_change(self, repo: Path) -> None:
        (repo / "notes.md").write_text("my scratch notes\n")
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        assert sw.changed_files(s) == ["pkg/calc.py"]

    def test_acceptance_succeeds_with_an_untracked_file_present(self, repo: Path) -> None:
        (repo / "notes.md").write_text("my scratch notes\n")
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "def add(a, b):\n    return a * b\n")
        sw.accept(s)
        assert (repo / "pkg" / "calc.py").read_text() == "def add(a, b):\n    return a * b\n"
        assert (repo / "notes.md").read_text() == "my scratch notes\n"

    def test_an_untouched_shadow_still_snapshots_to_its_baseline(self, repo: Path) -> None:
        """The proof pair: prove(baseline, snapshot) must attribute nothing to the agent."""
        (repo / "notes.md").write_text("my scratch notes\n")
        s = sw.create(repo, "task-1")
        assert sw.snapshot(s) == s.baseline

    def test_the_agent_can_edit_a_file_the_user_had_not_added_yet(self, repo: Path) -> None:
        (repo / "notes.md").write_text("draft\n")
        s = sw.create(repo, "task-1")
        sw.write(s, "notes.md", "draft, improved by the agent\n")
        assert sw.changed_files(s) == ["notes.md"]
        sw.accept(s)
        assert (repo / "notes.md").read_text() == "draft, improved by the agent\n"

    def test_the_conflict_guard_still_bites_on_a_carried_untracked_file(self, repo: Path) -> None:
        """Fixing the false conflict must not remove the true one."""
        (repo / "notes.md").write_text("draft\n")
        s = sw.create(repo, "task-1")
        sw.write(s, "notes.md", "agent version\n")
        (repo / "notes.md").write_text("USER KEPT TYPING\n")
        with pytest.raises(sw.AcceptConflict, match=r"notes\.md"):
            sw.accept(s)
        assert (repo / "notes.md").read_text() == "USER KEPT TYPING\n"


class TestConflictComparisonIsExact:
    """Regression: `_git()` strips leading AND trailing whitespace, so the comparison was wrong
    in both directions — inventing conflicts on content that starts with whitespace, and missing
    real user edits that only changed surrounding whitespace (silently overwriting their work).
    """

    def test_a_file_whose_content_starts_with_a_blank_line_is_acceptable(self, repo: Path) -> None:
        (repo / "cfg.yml").write_text("\nkey: value\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "cfg", "--no-gpg-sign")
        s = sw.create(repo, "task-1")
        sw.write(s, "cfg.yml", "\nkey: other\n")
        sw.accept(s)
        assert (repo / "cfg.yml").read_text() == "\nkey: other\n"

    def test_a_whitespace_only_user_edit_is_still_a_conflict(self, repo: Path) -> None:
        """The user's trailing newline is their work; overwriting it silently is data loss."""
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        (repo / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\n")
        with pytest.raises(sw.AcceptConflict, match=r"pkg/calc\.py"):
            sw.accept(s)


class TestShadowsRebuiltFromDiskKeepTheirBaseline:
    """Regression: `list_shadows()` read the branch tip as the baseline, but `snapshot()` moves
    that branch forward — so after a restart the shadow diffed against itself, `changed_files()`
    returned [], and `accept()` silently applied nothing.
    """

    def test_a_snapshotted_shadow_survives_a_restart_with_work_intact(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        sw.snapshot(s)
        rebuilt = sw.list_shadows(repo)[0]
        assert rebuilt.baseline == s.baseline, "the baseline moved with the branch"
        assert sw.changed_files(rebuilt) == ["pkg/calc.py"]

    def test_acceptance_after_a_restart_actually_applies_the_work(self, repo: Path) -> None:
        s = sw.create(repo, "task-1")
        sw.write(s, "pkg/calc.py", "AGENT\n")
        sw.snapshot(s)
        rebuilt = sw.list_shadows(repo)[0]
        acc = sw.accept(rebuilt)
        assert acc.files == ["pkg/calc.py"]
        assert (repo / "pkg" / "calc.py").read_text() == "AGENT\n"

    def test_a_worktree_without_metadata_is_skipped_not_guessed_at(self, repo: Path) -> None:
        """A directory from an older version has no recorded baseline; inventing one from the
        branch tip is exactly the bug this metadata replaced."""
        s = sw.create(repo, "task-1")
        (repo / ".tempest" / "agent" / "meta" / "task-1.json").unlink()
        assert sw.list_shadows(repo) == []
        assert s.path.is_dir(), "the worktree itself is left alone"

    def test_corrupt_metadata_is_skipped_rather_than_trusted(self, repo: Path) -> None:
        sw.create(repo, "task-1")
        (repo / ".tempest" / "agent" / "meta" / "task-1.json").write_text('"not an object"')
        assert sw.list_shadows(repo) == []

    def test_metadata_missing_its_baseline_is_skipped(self, repo: Path) -> None:
        sw.create(repo, "task-1")
        (repo / ".tempest" / "agent" / "meta" / "task-1.json").write_text('{"task_id": "task-1"}')
        assert sw.list_shadows(repo) == []


class TestRawGitErrors:
    def test_a_failing_git_command_names_what_failed(self, repo: Path) -> None:
        """Every git wrapper surfaces the real stderr — a silent git failure would be the worst
        kind of bug here, because the caller would carry on against a tree it never inspected."""
        with pytest.raises(sw.ShadowError, match="rev-parse"):
            sw._git(repo, "rev-parse", "no-such-ref^{commit}")

    def test_reading_a_path_absent_from_the_baseline_raises(self, repo: Path) -> None:
        """`_git_bytes` must fail loudly; `_user_moved_since_baseline` relies on that signal to
        recognise a file the agent newly created."""
        s = sw.create(repo, "task-1")
        with pytest.raises(sw.ShadowError, match="git show"):
            sw._git_bytes(repo, "show", f"{s.baseline}:does/not/exist.py")


class TestAttach:
    """P2's way back in. `create` refuses to overwrite a live shadow, so a restarted process
    needs a way to pick up the one it already has — with the baseline it was created with, not a
    fresh reading of a tree that has moved on since.

    States: a live shadow · no shadow at all · a meta file whose worktree is gone · a worktree
    with no meta beside it · a meta file that parses but says nothing useful.
    """

    def test_it_returns_the_shadow_with_its_recorded_baseline(self, repo: Path) -> None:
        """The baseline must come from the RECORD, not from re-reading the tree.

        So the tree moves first: after a snapshot the branch tip has advanced and the user's
        checkout has changed, and every way of re-deriving a baseline now gives a different sha.
        Only the recorded one still matches. The first version of this test asserted equality
        against a value nothing had disturbed, and a review pointed out it held whatever the code
        did.
        """
        made = sw.create(repo, "task-1")
        sw.write(made, "app.py", "print('agent edit')\n")
        head = sw.snapshot(made)
        assert head != made.baseline, "the branch tip has moved away from the baseline"
        (repo / "user_edit.py").write_text("print('the user kept working')\n", encoding="utf-8")

        got = sw.attach(repo, "task-1")
        assert got is not None
        assert (got.path, got.branch) == (made.path, made.branch)
        assert got.baseline == made.baseline
        assert got.baseline != head

    def test_a_task_with_no_shadow_answers_none(self, repo: Path) -> None:
        assert sw.attach(repo, "never-made") is None

    def test_a_discarded_shadow_answers_none(self, repo: Path) -> None:
        sw.discard(sw.create(repo, "task-1"))
        assert sw.attach(repo, "task-1") is None

    def test_a_meta_file_whose_worktree_is_gone_answers_none(self, repo: Path) -> None:
        """Answering with it would hand the caller a path nothing lives at, and the failure would
        surface later as a confusing git error about a directory rather than a missing shadow."""
        made = sw.create(repo, "task-1")
        _git(repo, "worktree", "remove", "--force", str(made.path))
        assert sw.attach(repo, "task-1") is None

    def test_a_worktree_with_no_meta_answers_none(self, repo: Path) -> None:
        """Nothing trustworthy to rebuild from: the baseline is the one fact that cannot be
        derived, and guessing it is how a shadow ends up diffed against itself.

        And the state this creates is a WEDGE — a worktree `create` will refuse to overwrite and
        `attach` will not adopt — so the second assertion pins that it is recoverable rather than
        permanent. `discard` is the recovery, and it works on a shadow rebuilt by hand from the
        path, which is all a caller has left at that point.
        """
        made = sw.create(repo, "task-1")
        sw._meta_path(repo, sw._slug("task-1")).unlink()
        assert made.path.is_dir()
        assert sw.attach(repo, "task-1") is None
        # And it is RECOVERABLE, not a wedge: `create` reclaims a worktree of its own with no
        # metadata beside it, because that is the wreckage of a process killed between the two
        # writes and the baseline it was built from is exactly what was never recorded.
        rebuilt = sw.create(repo, "task-1")
        assert rebuilt.path == made.path
        assert sw.attach(repo, "task-1") is not None

    def test_a_directory_git_never_registered_is_also_reclaimed(self, repo: Path) -> None:
        """`git worktree remove` refuses a path it does not know about, so the fallback that
        deletes the directory outright is the arm that runs — and it has to, or `git worktree
        add` fails on a non-empty target and the task id stays wedged."""
        slug = sw._slug("task-1")
        squatter = repo / sw._WORKTREES / slug
        squatter.mkdir(parents=True)
        (squatter / "left-over.txt").write_text("wreckage\n", encoding="utf-8")
        assert sw.attach(repo, "task-1") is None

        made = sw.create(repo, "task-1")
        assert made.path == squatter
        assert not (made.path / "left-over.txt").exists()
        assert sw.attach(repo, "task-1") is not None

    def test_a_meta_file_with_no_baseline_answers_none(self, repo: Path) -> None:
        sw.create(repo, "task-1")
        sw._meta_path(repo, sw._slug("task-1")).write_text(
            '{"task_id": "task-1"}', encoding="utf-8"
        )
        assert sw.attach(repo, "task-1") is None

    def test_a_meta_file_that_is_not_an_object_answers_none(self, repo: Path) -> None:
        sw.create(repo, "task-1")
        sw._meta_path(repo, sw._slug("task-1")).write_text("[1, 2, 3]", encoding="utf-8")
        assert sw.attach(repo, "task-1") is None
