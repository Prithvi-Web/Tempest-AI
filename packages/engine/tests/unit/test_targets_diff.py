"""Stage 1a: diff parsing against real git repos — no fabricated diffs (Law L4)."""

import subprocess
from pathlib import Path

from tempest.targets.diff import FileDiff, changed_files


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
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
    return result.stdout


def make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    return repo


def commit_head(repo: Path, files: dict[str, str], delete: list[str] | None = None) -> None:
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    for name in delete or []:
        (repo / name).unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")


class TestChangedFiles:
    def test_modified_python_file_reports_head_and_base_lines(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "def f(x):\n    return x + 1\n"})
        commit_head(repo, {"m.py": "def f(x):\n    return x + 2\n"})
        diffs = changed_files(repo, "base", "head")
        assert [d.path for d in diffs] == ["m.py"]
        d = diffs[0]
        assert d.changed_head_lines == {2}
        assert d.changed_base_lines == {2}
        assert d.status == "modified"

    def test_added_file_has_only_head_lines(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        commit_head(repo, {"n.py": "def g():\n    return 7\n"})
        diffs = changed_files(repo, "base", "head")
        added = next(d for d in diffs if d.path == "n.py")
        assert added.status == "added"
        assert added.changed_head_lines == {1, 2}
        assert added.changed_base_lines == set()

    def test_deleted_file_reported(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n", "gone.py": "def h():\n    return 1\n"})
        commit_head(repo, {}, delete=["gone.py"])
        diffs = changed_files(repo, "base", "head")
        deleted = next(d for d in diffs if d.path == "gone.py")
        assert deleted.status == "deleted"
        assert deleted.changed_head_lines == set()

    def test_non_python_files_are_excluded(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n", "notes.txt": "a\n"})
        commit_head(repo, {"notes.txt": "b\n", "m.py": "x = 2\n"})
        diffs = changed_files(repo, "base", "head")
        assert [d.path for d in diffs] == ["m.py"]

    def test_multi_hunk_changes_collect_all_lines(self, tmp_path: Path) -> None:
        base = "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n"
        head = "def a():\n    return 10\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 30\n"
        repo = make_repo(tmp_path, {"m.py": base})
        commit_head(repo, {"m.py": head})
        (d,) = changed_files(repo, "base", "head")
        assert d.changed_head_lines == {2, 10}

    def test_identical_revisions_produce_no_diffs(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path, {"m.py": "x = 1\n"})
        _git(repo, "branch", "head")
        assert changed_files(repo, "base", "head") == []

    def test_filediff_is_frozen_value_object(self) -> None:
        d = FileDiff(
            path="a.py",
            status="modified",
            changed_head_lines=frozenset({1}),
            changed_base_lines=frozenset(),
        )
        assert d == FileDiff(
            path="a.py",
            status="modified",
            changed_head_lines=frozenset({1}),
            changed_base_lines=frozenset(),
        )
