"""Stage 2: git-worktree materialization with normalized environments (Law L3 groundwork)."""

from pathlib import Path

import pytest

from tempest.envrepro import worktree as worktree_mod
from tempest.envrepro.worktree import MaterializedEnv, materialize, remove

from .test_targets_diff import _git, commit_head, make_repo


class TestMaterialize:
    def test_worktree_contains_the_revisions_content(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "VALUE = 'base'\n"})
        commit_head(repo, {"m.py": "VALUE = 'head'\n"})
        cache = tmp_path / "cache"
        base = materialize(repo, "base", cache)
        head = materialize(repo, "head", cache)
        assert (base.worktree / "m.py").read_text() == "VALUE = 'base'\n"
        assert (head.worktree / "m.py").read_text() == "VALUE = 'head'\n"
        assert base.worktree != head.worktree

    def test_env_is_normalized_and_identical_across_revisions(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        base = materialize(repo, "base", cache)
        head = materialize(repo, "head", cache)
        for env in (base, head):
            assert env.env["LC_ALL"] == "C.UTF-8"
            assert env.env["TZ"] == "UTC"
            assert env.env["PYTHONHASHSEED"] == "0"
        assert base.env == head.env

    def test_resolved_sha_is_recorded(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        assert len(env.revision) == 40

    def test_no_lockfile_fingerprint_is_explicit(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        assert env.deps_fingerprint == "no-lockfile"

    def test_lockfile_changes_the_fingerprint(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n", "uv.lock": "lock-a\n"})
        commit_head(repo, {"uv.lock": "lock-b\n"})
        cache = tmp_path / "cache"
        base = materialize(repo, "base", cache)
        head = materialize(repo, "head", cache)
        assert base.deps_fingerprint != head.deps_fingerprint
        assert base.deps_fingerprint != "no-lockfile"

    def test_materialize_is_idempotent(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        first = materialize(repo, "head", cache)
        second = materialize(repo, "head", cache)
        assert first.worktree == second.worktree
        assert (second.worktree / "m.py").read_text() == "x = 2\n"

    def test_remove_cleans_up_the_worktree(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        remove(repo, env)
        assert not env.worktree.exists()

    def test_materialized_env_is_a_value_object(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        assert isinstance(env, MaterializedEnv)
        assert env.python.exists()


class TestACacheEntryNobodyFinishedWriting:
    """ADR-0052. `git worktree add` makes the directory and THEN checks files out into it, so a
    process killed part-way leaves a real directory holding a partial tree. The old reuse rule
    was `if not worktree.exists()`, which adopted the wreck and kept adopting it: every later run
    in that repository died on a source file that was simply not there.

    Found by `resume_test --kill-mid-proof` on its first run — a `SIGKILL` during a proof left
    exactly this, and the restart it was testing crashed on it.

    States: a complete entry · a directory with no marker · a directory with a partial checkout ·
    a marker whose worktree git no longer knows about · a removed entry.
    """

    def test_a_finished_checkout_is_marked_ready(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        marker = env.worktree.with_name(env.worktree.name + ".ready")
        assert marker.is_file() and marker.read_text().strip() == env.revision

    def test_an_unmarked_directory_is_discarded_and_rebuilt(self, tmp_path: Path) -> None:
        """The exact crash shape: the tree is there and the file inside it is not."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        env = materialize(repo, "head", cache)
        (env.worktree / "m.py").unlink()
        env.worktree.with_name(env.worktree.name + ".ready").unlink()

        again = materialize(repo, "head", cache)
        assert again.worktree == env.worktree
        assert (again.worktree / "m.py").read_text() == "x = 2\n"

    def test_a_directory_git_never_registered_is_still_cleared(self, tmp_path: Path) -> None:
        """`git worktree remove` refuses a path it does not know about, so the fallback that
        deletes the directory outright is the arm that runs here — and it has to, or the
        rebuild fails on a non-empty target."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        sha = materialize(repo, "head", cache).revision
        remove(repo, materialize(repo, "head", cache))

        squatter = cache / "worktrees" / sha[:12]
        squatter.mkdir(parents=True, exist_ok=True)
        (squatter / "junk.txt").write_text("left over\n", encoding="utf-8")

        rebuilt = materialize(repo, "head", cache)
        assert (rebuilt.worktree / "m.py").read_text() == "x = 2\n"
        assert not (rebuilt.worktree / "junk.txt").exists()

    def test_removing_an_entry_takes_its_marker_with_it(self, tmp_path: Path) -> None:
        """A marker left behind would claim a checkout that is no longer there — the same lie in
        the other direction, and a worse one, because the directory would not exist at all."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        env = materialize(repo, "head", tmp_path / "cache")
        remove(repo, env)
        assert not env.worktree.with_name(env.worktree.name + ".ready").exists()

    def test_a_marker_whose_worktree_is_gone_rebuilds_rather_than_handing_back_a_ghost(
        self, tmp_path: Path
    ) -> None:
        """The same lie in the other direction, and the worse one: the marker says "this checkout
        finished" about a directory that is not there, so the caller is handed a path with nothing
        at it and dies on the first file it reads. Found by the review of the marker fix itself
        (trap 48)."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        env = materialize(repo, "head", cache)
        _git(repo, "worktree", "remove", "--force", str(env.worktree))
        assert env.worktree.with_name(env.worktree.name + ".ready").is_file()
        assert not env.worktree.exists()

        again = materialize(repo, "head", cache)
        assert (again.worktree / "m.py").read_text() == "x = 2\n"

    def test_a_plain_file_squatting_the_cache_path_is_removed(self, tmp_path: Path) -> None:
        """`shutil.rmtree` refuses a non-directory, so a file or symlink left where a worktree
        belongs would survive a rmtree-only cleanup and then break `git worktree add`."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        sha = materialize(repo, "head", cache).revision
        remove(repo, materialize(repo, "head", cache))

        squatter = cache / "worktrees" / sha[:12]
        squatter.parent.mkdir(parents=True, exist_ok=True)
        squatter.write_text("not a worktree at all\n", encoding="utf-8")

        rebuilt = materialize(repo, "head", cache)
        assert rebuilt.worktree.is_dir()
        assert (rebuilt.worktree / "m.py").read_text() == "x = 2\n"

    def test_a_complete_entry_is_reused_rather_than_rebuilt(self, tmp_path: Path) -> None:
        """The marker must not turn the cache into a no-op cache. A file written INTO a ready
        worktree survives the next materialize, which is what "reused" means."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        first = materialize(repo, "head", cache)
        (first.worktree / "witness.txt").write_text("still here\n", encoding="utf-8")
        second = materialize(repo, "head", cache)
        assert (second.worktree / "witness.txt").read_text() == "still here\n"


class TestOnlyOneProcessRebuildsAnEntry:
    """The race the marker opened, and the review caught.

    With the old rule a second process REUSED a half-written tree — silently wrong. With the
    marker and no lock it would DISCARD the tree the first process was still checking out —
    loudly wrong, and someone else's work. So a rebuild happens under an exclusive create.
    """

    def test_a_held_lock_makes_a_second_caller_wait_for_the_marker(self, tmp_path: Path) -> None:
        """Simulated by taking the lock by hand and then completing the entry the way the holder
        would: the waiting caller must adopt that result rather than tear it down."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        env = materialize(repo, "head", cache)
        lock = env.worktree.with_name(env.worktree.name + ".lock")
        lock.write_text("999999", encoding="utf-8")

        # The entry is complete, so the waiting path returns immediately without touching it.
        again = materialize(repo, "head", cache)
        assert (again.worktree / "m.py").read_text() == "x = 2\n"
        assert lock.is_file(), "somebody else's lock is not ours to remove"
        lock.unlink()

    def test_a_stale_lock_is_reclaimed_rather_than_waited_on_forever(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A process that dies holding the lock must not stop the cache working for good."""
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        env = materialize(repo, "head", cache)
        ready = env.worktree.with_name(env.worktree.name + ".ready")
        ready.unlink()
        lock = env.worktree.with_name(env.worktree.name + ".lock")
        lock.write_text("999999", encoding="utf-8")
        monkeypatch.setattr(worktree_mod, "_LOCK_STALE_S", -1.0)

        rebuilt = materialize(repo, "head", cache)
        assert (rebuilt.worktree / "m.py").read_text() == "x = 2\n"
        assert not lock.exists(), "the rebuild released the lock it reclaimed"

    def test_a_lock_that_is_never_released_is_given_up_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"m.py": "x = 2\n"})
        cache = tmp_path / "cache"
        env = materialize(repo, "head", cache)
        env.worktree.with_name(env.worktree.name + ".ready").unlink()
        lock = env.worktree.with_name(env.worktree.name + ".lock")
        lock.write_text("999999", encoding="utf-8")
        monkeypatch.setattr(worktree_mod, "_LOCK_WAIT_S", 0.0)

        rebuilt = materialize(repo, "head", cache)
        assert (rebuilt.worktree / "m.py").read_text() == "x = 2\n"
