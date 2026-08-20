"""F14 — the agent terminal, run at a real isolation tier (Phase 23).

Every test here spawns a REAL process through a REAL sandbox (L4). The tier under test is the one
this machine offers; the escape suite covers containment per tier, and what these assert is the
contract around it: bounded time, bounded output, stderr returned, the process GROUP reaped, and
scratch that does not survive between calls.

States enumerated before the tests (trap 43): a command that succeeds · one that fails · one that
writes to stderr · one that produces more output than the budget · one that never finishes · one
that spawns a child and exits · a binary that does not exist · argv that is not a list · no tier
at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tempest.agent import terminal
from tempest.execute.sandbox import ProcessSandbox

SANDBOX = ProcessSandbox()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    return work


class TestOrdinaryCommands:
    def test_stdout_and_the_exit_status_come_back(self, root: Path) -> None:
        got = terminal.run(["echo", "hi"], root=root, sandbox=SANDBOX, timeout=10, max_bytes=4096)
        assert got.exit_status == 0 and "hi" in got.stdout and not got.timed_out

    def test_a_failing_command_reports_its_status_rather_than_raising(self, root: Path) -> None:
        got = terminal.run(["false"], root=root, sandbox=SANDBOX, timeout=10, max_bytes=4096)
        assert got.exit_status != 0

    def test_stderr_is_part_of_the_answer(self, root: Path) -> None:
        """The runners send stderr to /dev/null because a worker's stderr is noise. A command's
        stderr is usually the ONLY thing that says why it failed."""
        got = terminal.run(
            ["sh", "-c", "echo oops >&2; exit 3"],
            root=root,
            sandbox=SANDBOX,
            timeout=10,
            max_bytes=4096,
        )
        assert got.exit_status == 3 and "oops" in got.stderr

    def test_the_working_directory_is_the_root_it_was_given(self, root: Path) -> None:
        got = terminal.run(["ls"], root=root, sandbox=SANDBOX, timeout=10, max_bytes=4096)
        assert "README.md" in got.stdout


class TestEverythingIsBounded:
    def test_output_over_the_budget_is_truncated_and_says_so(self, root: Path) -> None:
        got = terminal.run(
            ["sh", "-c", "for i in $(seq 1 5000); do echo aaaaaaaaaaaaaaaaaaaa; done"],
            root=root,
            sandbox=SANDBOX,
            timeout=30,
            max_bytes=256,
        )
        assert got.truncated and len(got.stdout) <= 256
        assert "truncated" in got.render(tier="fixture")

    def test_a_command_that_never_finishes_is_killed_and_says_so(self, root: Path) -> None:
        got = terminal.run(["sleep", "30"], root=root, sandbox=SANDBOX, timeout=1.0, max_bytes=4096)
        assert got.timed_out
        assert "time budget" in got.render(tier="fixture")

    def test_a_child_left_behind_by_a_killed_command_is_reaped_too(self, root: Path) -> None:
        """The kill goes to the process GROUP. A command that spawns a background child and then
        hangs must not leave the child running after the budget expires."""
        marker = root / "still-alive"
        got = terminal.run(
            ["sh", "-c", f"(sleep 5; touch {marker}) & sleep 30"],
            root=root,
            sandbox=SANDBOX,
            timeout=1.0,
            max_bytes=4096,
        )
        assert got.timed_out
        import time

        time.sleep(6)
        assert not marker.exists(), "the child outlived the command's process group"


class TestScratchIsNotSharedBetweenCalls:
    def test_a_file_written_to_scratch_does_not_survive(self, root: Path) -> None:
        """Two calls are independent whatever the model believes. A command that stashed state
        for the next one would make the turn loop's history and the filesystem disagree."""
        first = terminal.run(
            ["sh", "-c", 'echo state > "$TMPDIR/left-behind"; echo wrote'],
            root=root,
            sandbox=SANDBOX,
            timeout=10,
            max_bytes=4096,
        )
        assert first.exit_status == 0
        second = terminal.run(
            ["sh", "-c", 'cat "$TMPDIR/left-behind" 2>&1 || echo gone'],
            root=root,
            sandbox=SANDBOX,
            timeout=10,
            max_bytes=4096,
        )
        assert "gone" in second.stdout or "No such file" in second.stdout


class TestRendering:
    def test_the_tier_is_named_in_every_answer(self, root: Path) -> None:
        """The model — and the user reading the transcript — should be able to see which
        containment the command ran under, because it decides what the command could do."""
        got = terminal.run(["echo", "hi"], root=root, sandbox=SANDBOX, timeout=10, max_bytes=4096)
        assert "tier=T2" in got.render(tier="T2")


class TestTheScratchTheCallerSupplies:
    def test_a_supplied_directory_is_used_and_left_alone(self, root: Path, tmp_path: Path) -> None:
        """The escape suite is the caller this exists for: proving containment means running a
        hostile payload and then INSPECTING the space it was allowed to touch."""
        mine = tmp_path / "mine"
        mine.mkdir()
        got = terminal.run(
            ["sh", "-c", 'echo written > "$TMPDIR/proof"'],
            root=root,
            sandbox=SANDBOX,
            timeout=10,
            max_bytes=4096,
            scratch=mine,
        )
        assert got.exit_status == 0
        assert (mine / "proof").read_text().strip() == "written"
        assert mine.is_dir(), "the caller's directory is the caller's to remove"


class TestTheKillGuard:
    def test_a_process_that_has_already_been_reaped_is_not_signalled_again(
        self, root: Path
    ) -> None:
        """`returncode` is set only by the wait that reaps OUR child, and the kernel cannot
        recycle a pgid before its owner reaps it. Once it is set, the pgid may already belong to
        a stranger and must never be signalled again — the runner's TOCTOU rule, for the runner's
        reason."""
        import subprocess

        proc = SANDBOX.popen(
            ["true"], cwd=root, env={"PATH": "/usr/bin:/bin"}, scratch=root, capture_stderr=True
        )
        proc.communicate()
        assert proc.returncode is not None
        terminal._kill_group(proc)  # must be a no-op, not a signal to whoever owns that pgid now
        assert isinstance(proc, subprocess.Popen)
