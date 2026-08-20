"""P2 — the durable turn log, and what a restarted process is told to do about it.

The property is L15.5: crash mid-operation loses nothing. A turn costs money (model calls) and
minutes (a differential proof), so the log exists to make sure neither is paid twice and neither
is forgotten.

The one design idea worth testing hardest: **a checkpoint records what HAPPENED, never what is
about to.** Nothing is written in advance, so every row survives a crash as a fact rather than as
an intention. `PROVING` and `PROVED` are separate rows because the gap between them is the
expensive one, and a process that dies in it has done the first and not the second.

States enumerated before the tests (trap 43): no history · started only · turns done · died
inside the proof · proof finished · a repair attempt in flight · finished · an unknown stage ·
two tasks in one repository · a log reopened by a second process · a payload that must round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tempest.agent import turnlog
from tempest.agent.turnlog import TurnLog, TurnLogError, plan_resume


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestTheLogIsDurableAndAppendOnly:
    def test_a_checkpoint_is_readable_by_a_SEPARATE_log_object(self, repo: Path) -> None:
        """The point of durability: a *different process* — modelled here by a second object over
        the same file — must see what the first one committed. A value cached in memory would
        pass a weaker test and fail the real one."""
        TurnLog(repo).checkpoint("t1", turnlog.STARTED, prompt="fix it")
        reopened = TurnLog(repo)
        assert [c.stage for c in reopened.history("t1")] == [turnlog.STARTED]
        assert reopened.history("t1")[0].payload == {"prompt": "fix it"}

    def test_entries_keep_their_order(self, repo: Path) -> None:
        log = TurnLog(repo)
        for stage in (turnlog.STARTED, turnlog.TURNS_DONE, turnlog.PROVING, turnlog.PROVED):
            log.checkpoint("t1", stage)
        assert [c.stage for c in log.history("t1")] == [
            turnlog.STARTED,
            turnlog.TURNS_DONE,
            turnlog.PROVING,
            turnlog.PROVED,
        ]
        assert [c.seq for c in log.history("t1")] == sorted(c.seq for c in log.history("t1"))

    def test_two_tasks_in_one_repository_do_not_mix(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("a", turnlog.STARTED)
        log.checkpoint("b", turnlog.STARTED)
        log.checkpoint("a", turnlog.FINISHED)
        assert [c.stage for c in log.history("a")] == [turnlog.STARTED, turnlog.FINISHED]
        assert [c.stage for c in log.history("b")] == [turnlog.STARTED]

    def test_a_payload_round_trips(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.PROVED, verdict="DIVERGENT", bundle_id="a..b", count=3)
        assert log.last("t1") is not None
        assert log.last("t1").payload == {  # type: ignore[union-attr]
            "verdict": "DIVERGENT",
            "bundle_id": "a..b",
            "count": 3,
        }

    def test_an_unknown_stage_is_refused_rather_than_stored(self, repo: Path) -> None:
        """A stage the resumption logic does not know would make it guess, and a log that makes
        a restarted process guess is worse than no log."""
        with pytest.raises(TurnLogError, match="unknown stage"):
            TurnLog(repo).checkpoint("t1", "almost_done")
        assert TurnLog(repo).history("t1") == []

    def test_a_task_with_no_history_answers_none_not_an_error(self, repo: Path) -> None:
        assert TurnLog(repo).last("never-run") is None
        assert TurnLog(repo).history("never-run") == []

    def test_the_log_lives_beside_the_agents_other_state(self, repo: Path) -> None:
        TurnLog(repo).checkpoint("t1", turnlog.STARTED)
        assert (repo / turnlog.TURNLOG_PATH).is_file()
        assert ".tempest" in str(turnlog.TURNLOG_PATH)


class TestWhatARestartedProcessIsToldToDo:
    def test_a_fresh_task_is_simply_run(self, repo: Path) -> None:
        plan = plan_resume(TurnLog(repo), "brand-new")
        assert not plan.finished and not plan.reprove
        assert "fresh task" in plan.reason

    def test_a_task_killed_INSIDE_the_proof_is_re_proved(self, repo: Path) -> None:
        """The expensive gap. The model work is recorded and paid for; the verdict is not. A
        proof is a pure function of (baseline, head, budget, seed), so redoing exactly that step
        cannot change the answer — which is what makes it safe to redo blindly."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED)
        log.checkpoint("t1", turnlog.TURNS_DONE, turns=2)
        log.checkpoint("t1", turnlog.PROVING, base="aaa", head="bbb")

        plan = plan_resume(log, "t1")
        assert plan.reprove and not plan.finished
        assert "interrupted inside the proof" in plan.reason

    def test_a_task_whose_proof_LANDED_is_not_re_proved(self, repo: Path) -> None:
        """One row later and the answer is different: the verdict exists, so spending minutes to
        recompute it would be the loss this module prevents."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.PROVING, base="aaa", head="bbb")
        log.checkpoint("t1", turnlog.PROVED, verdict="DIVERGENT", bundle_id="a..b")

        plan = plan_resume(log, "t1")
        assert not plan.reprove and not plan.finished
        assert "proved" in plan.reason

    def test_a_finished_task_is_not_run_again(self, repo: Path) -> None:
        """Re-running would spend money and minutes to recompute a recorded answer — and would
        try to create a second shadow worktree for a task that already has one, which
        `shadow.create` refuses outright."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.PROVED, verdict="DIVERGENT")
        log.checkpoint("t1", turnlog.FINISHED, verdict="DIVERGENT", bundle_id="a..b")

        plan = plan_resume(log, "t1")
        assert plan.finished and not plan.reprove
        assert "already finished" in plan.reason

    def test_a_task_killed_after_starting_but_before_any_turn(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="x")
        plan = plan_resume(log, "t1")
        assert not plan.finished and not plan.reprove
        assert "started" in plan.reason

    def test_a_task_killed_during_a_repair_attempt(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.PROVED, verdict="DIVERGENT")
        log.checkpoint("t1", turnlog.REPAIR_ATTEMPT, number=1, symbol="total")
        plan = plan_resume(log, "t1")
        assert not plan.finished and not plan.reprove
        assert "repair_attempt" in plan.reason

    def test_the_LAST_stage_decides_not_the_presence_of_an_earlier_one(self, repo: Path) -> None:
        """A task that proved, then started a second proof for a repair, and died — PROVING is
        the last row, so it re-proves. Reading "has it ever proved?" would answer no-reprove and
        lose the second proof's work."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.PROVING, base="a", head="b")
        log.checkpoint("t1", turnlog.PROVED, verdict="DIVERGENT")
        log.checkpoint("t1", turnlog.REPAIR_ATTEMPT, number=1, symbol="total")
        log.checkpoint("t1", turnlog.PROVING, base="a", head="c")

        assert plan_resume(log, "t1").reprove


class TestWhatTheRestartMaySkip:
    """The plan has to say what to redo, not just that something is left. Model turns cost money
    and cannot be repeated identically; a proof is a pure function and is safe to redo blindly.
    Those are different facts and the plan carries both.
    """

    def test_a_fresh_task_redoes_everything_and_is_not_resuming(self, repo: Path) -> None:
        plan = plan_resume(TurnLog(repo), "never-seen")
        assert plan.redo_turns and not plan.resuming and plan.baseline == ""

    def test_turns_recorded_means_the_model_is_not_asked_again(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="abc123")
        log.checkpoint("t1", turnlog.TURNS_DONE, turns=2, stopped="the model finished")
        log.checkpoint("t1", turnlog.PROVING, base="abc123", head="def456")
        plan = plan_resume(log, "t1")
        assert plan.resuming and plan.reprove and not plan.redo_turns
        assert plan.baseline == "abc123"

    def test_a_crash_before_the_turns_finished_redoes_them(self, repo: Path) -> None:
        """STARTED alone means the conversation never completed. Its edits, if any, are in the
        shadow — but nothing says the model was done, so the honest answer is to ask again."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="abc123")
        plan = plan_resume(log, "t1")
        assert plan.resuming and plan.redo_turns
        assert "the model turns never completed" in plan.reason

    def test_a_crash_inside_the_proof_before_the_turns_finished_redoes_both(
        self, repo: Path
    ) -> None:
        """Contrived but real: a proof row with no TURNS_DONE above it. The turn flag is asked of
        the whole history, so the absence is seen rather than assumed away by the last stage."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="abc123")
        log.checkpoint("t1", turnlog.PROVING, base="abc123", head="def456")
        plan = plan_resume(log, "t1")
        assert plan.reprove and plan.redo_turns

    def test_a_task_resumed_twice_still_knows_its_turns_are_done(self, repo: Path) -> None:
        """A RESUMED row lands on top of the history. Reading only the LAST stage to decide
        whether the model already ran would ask for the whole conversation again on the second
        restart — the expensive answer, arrived at by looking at the wrong row."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="abc123")
        log.checkpoint("t1", turnlog.TURNS_DONE, turns=1, stopped="done")
        log.checkpoint("t1", turnlog.RESUMED, reason="first restart", redo_turns=False)
        log.checkpoint("t1", turnlog.PROVING, base="abc123", head="def456")
        assert not plan_resume(log, "t1").redo_turns

    def test_the_baseline_comes_from_the_FIRST_started_row(self, repo: Path) -> None:
        """One task has one baseline and possibly several attempts at it. Reading the newest row
        would let the answer drift with every restart, and a proof against a drifting baseline
        answers a different question each time."""
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="first")
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="second")
        assert plan_resume(log, "t1").baseline == "first"

    def test_a_started_row_with_no_baseline_answers_empty_rather_than_guessing(
        self, repo: Path
    ) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p")
        assert plan_resume(log, "t1").baseline == ""

    def test_a_finished_task_reports_its_baseline_and_asks_for_no_work(self, repo: Path) -> None:
        log = TurnLog(repo)
        log.checkpoint("t1", turnlog.STARTED, prompt="p", baseline="abc123")
        log.checkpoint("t1", turnlog.TURNS_DONE, turns=1, stopped="done")
        log.checkpoint("t1", turnlog.FINISHED, verdict="DIVERGENT", bundle_id="a..b")
        plan = plan_resume(log, "t1")
        assert plan.finished and not plan.reprove and not plan.redo_turns
        assert plan.baseline == "abc123" and plan.resuming

    def test_resumed_is_a_stage_the_log_accepts(self, repo: Path) -> None:
        log = TurnLog(repo)
        entry = log.checkpoint("t1", turnlog.RESUMED, reason="why", redo_turns=False)
        assert entry.stage == turnlog.RESUMED
        assert log.history("t1")[-1].payload["redo_turns"] is False
