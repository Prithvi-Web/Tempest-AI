"""`tempest watch` (ADR-0029) — every commit proven as it appears, every arm pinned with
REAL git repos and REAL proves (L4). The injected sleeper drives the idle and interrupt
arms deterministically; nothing about the proving path is simulated.
"""

import io
import os
import subprocess
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from tempest.cli.main import app
from tempest.cli.watch import WatchError, _rev_parse, run_watch

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base", "--no-gpg-sign")
    return repo


def _commit_change(repo: Path) -> None:
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "change", "--no-gpg-sign")


def _console() -> tuple[Console, io.StringIO]:
    sink = io.StringIO()
    return Console(file=sink, width=200, force_terminal=False), sink


class TestWatchLoop:
    def test_a_new_commit_is_proven_and_once_exits(self, tmp_path: Path) -> None:
        os.environ["TEMPEST_DEV"] = "1"
        repo = _repo(tmp_path)
        baseline = _rev_parse(repo, "HEAD")
        _commit_change(repo)  # arrives "while watching" — the baseline predates it
        console, sink = _console()
        code = run_watch(
            repo,
            interval=0.01,
            max_inputs=6,
            seed=0,
            from_ref=baseline,
            once=True,
            console=console,
        )
        out = sink.getvalue()
        assert code == 0
        assert "DIVERGENT" in out
        assert "1 divergence(s)" in out
        assert "bundle:" in out

    def test_idle_polls_sleep_then_interrupt_stops_cleanly(self, tmp_path: Path) -> None:
        os.environ["TEMPEST_DEV"] = "1"
        repo = _repo(tmp_path)
        console, sink = _console()
        sleeps: list[float] = []

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) >= 3:
                raise KeyboardInterrupt  # the user's Ctrl-C, delivered mid-sleep

        code = run_watch(
            repo,
            interval=0.5,
            max_inputs=6,
            seed=0,
            from_ref=None,
            once=False,
            console=console,
            sleeper=sleeper,
        )
        assert code == 0
        assert sleeps == [0.5, 0.5, 0.5]  # idle loop really polled, nothing was proven
        assert "watch stopped" in sink.getvalue()
        assert "DIVERGENT" not in sink.getvalue()

    def test_unresolvable_repo_names_the_fix(self, tmp_path: Path) -> None:
        with pytest.raises(WatchError, match="cannot resolve"):
            _rev_parse(tmp_path, "HEAD")

    def test_cli_command_surfaces_watch_errors(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["watch", "--repo", str(tmp_path), "--once"])
        assert result.exit_code == 2
        assert "cannot resolve" in result.output

    def test_cli_once_end_to_end(self, tmp_path: Path) -> None:
        os.environ["TEMPEST_DEV"] = "1"
        repo = _repo(tmp_path)
        baseline = _rev_parse(repo, "HEAD")
        _commit_change(repo)
        result = runner.invoke(
            app,
            [
                "watch",
                "--repo",
                str(repo),
                "--from",
                baseline,
                "--once",
                "--max-inputs",
                "6",
                "--interval",
                "0.01",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "DIVERGENT" in result.output


class TestRemainingWatchArms:
    def test_default_budget_and_continuous_mode_keep_looping(self, tmp_path: Path) -> None:
        """max_inputs None takes the default-budget arm, and once=False loops back to the
        sleeper after a prove instead of returning — the interrupt then stops it."""
        os.environ["TEMPEST_DEV"] = "1"
        repo = _repo(tmp_path)
        baseline = _rev_parse(repo, "HEAD")
        _commit_change(repo)
        console, sink = _console()
        sleeps: list[float] = []

        def sleeper(seconds: float) -> None:
            sleeps.append(seconds)
            raise KeyboardInterrupt  # first idle moment AFTER the prove

        code = run_watch(
            repo,
            interval=0.2,
            max_inputs=None,  # the default-budget arm
            seed=0,
            from_ref=baseline,
            once=False,  # continuous: prove, then loop back to sleep
            console=console,
            sleeper=sleeper,
        )
        out = sink.getvalue()
        assert code == 0
        assert "DIVERGENT" in out  # the prove really ran (default budget)
        assert sleeps == [0.2]  # and the loop came back around to the sleeper
        assert "watch stopped" in out
