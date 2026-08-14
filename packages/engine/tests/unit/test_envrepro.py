"""Stage 2: git-worktree materialization with normalized environments (Law L3 groundwork)."""

from pathlib import Path

from tempest.envrepro.worktree import MaterializedEnv, materialize, remove

from .test_targets_diff import commit_head, make_repo


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
