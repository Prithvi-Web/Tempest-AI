"""Phase 21 / F1: the turn loop, end to end, with a real model peer and a real proof.

Nothing here is mocked below the model. The repository is a real git repo, the edits go through
the real shadow worktree, and the verdict comes from `run_prove` executing both revisions — the
"model" is a loopback HTTP peer returning the Messages shape, which is the same pattern ADR-0024
established and the only part that may be faked (L4: every green test corresponds to real
execution).

The property under test is F1's whole claim: **the turn ends on a verdict, not on the model
saying it is finished.** So the tests drive a model that finishes early, a model that never
finishes, and a model that dies mid-turn, and assert that all three land on an engine verdict
about whatever was actually written.

States enumerated before the tests (trap 43): the model edits and stops · the model stops without
editing · the model asks for a tool that does not exist · the model asks for a tool it has no
grant for · the model exhausts the turn budget · the model exhausts the CALL budget · the model
errors mid-turn · the model tries to call `prove` · the model tries to escape the shadow · the
edit is behaviour-preserving · the edit is divergent.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import contracts
from tempest.agent.orchestrator import AgentError, ProvenChange, TaskSpec, run_task
from tempest.agent.tools import ApprovalDecision, ApprovalRequest, Budgets
from tempest.agent.turnlog import TurnLog, plan_resume
from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server
from ..helpers_first_party import mark_first_party

_BASE = "def total(xs):\n    return sum(xs)\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


@pytest.fixture(autouse=True)
def _dev() -> Iterator[None]:
    """Half of what makes the fixture repository first-party (ADR-0008); `mark_first_party`
    writes the other half and checks that both took. Set HERE rather than inherited from the
    ambient shell, so this module measures the same backend on its own that it does in CI — and
    on a MonkeyPatch of its OWN, because a test that calls `monkeypatch.undo()` to drop its own
    patch would otherwise silently drop this one with it (which is precisely how the resume
    tests lost the marker and fell back to the tier ladder mid-test)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TEMPEST_DEV", "1")
        yield


@pytest.fixture
def repo(tmp_path: Path, _dev: None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "app.py").write_text(_BASE, encoding="utf-8")
    mark_first_party(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


def _env(url: str) -> dict[str, str]:
    provider = get("anthropic")
    return {provider.env_var: "sk-test-not-a-real-key", provider.base_url_env(): url}


def _spec(repo: Path, **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": "t1",
        "prompt": "make total faster",
        "provider": "anthropic",
        "max_inputs": 6,
    }
    base.update(kw)
    return TaskSpec(**base)


class TestTheTurnEndsOnAVerdict:
    def test_an_edit_is_proved_and_the_verdict_comes_from_the_engine(self, repo: Path) -> None:
        """The headline: the model writes, then STOPS asking for tools, and the engine — not the
        model — says what the change did."""
        fake = FakeAnthropic()
        fake.tool_uses = [
            {
                "name": "write_file",
                "input": {"path": "app.py", "contents": "def total(xs):\n    return sum(xs) + 1\n"},
            }
        ]

        seen: list[tuple[str, str]] = []
        with fake_anthropic_server(fake) as url:
            # First turn writes; clearing the tool list makes the second turn a plain answer.
            def stop_after_first(kind: str, detail: str) -> None:
                seen.append((kind, detail))
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "I added one to the sum."

            run = run_task(_spec(repo), env=_env(url), on_event=stop_after_first)

        assert isinstance(run.change, ProvenChange)
        assert run.change.bundle_id, "L16: a change without a bundle cannot exist"
        assert run.change.changed_files == ("app.py",)
        assert run.change.verdict is Verdict.DIVERGENT, "sum(xs)+1 is not sum(xs)"
        assert run.change.divergence_count > 0
        assert "proving" in [k for k, _ in seen]
        assert run.narration and "added one" in run.narration[-1]

    def test_the_user_working_tree_is_untouched(self, repo: Path) -> None:
        """L19, observed rather than argued: the file the user can see still says what it said."""
        fake = FakeAnthropic()
        fake.tool_uses = [
            {"name": "write_file", "input": {"path": "app.py", "contents": "BROKEN\n"}}
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "done"

            run_task(_spec(repo), env=_env(url), on_event=stop)
        assert (repo / "app.py").read_text(encoding="utf-8") == _BASE

    def test_a_model_that_edits_nothing_is_unproven_not_equivalent(self, repo: Path) -> None:
        """Nothing was exercised, so there is nothing to claim. An empty run reading as
        EQUIVALENT would be the single most dangerous rounding error in the product."""
        fake = FakeAnthropic()
        fake.reply_text = "Nothing needed changing."
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo), env=_env(url))
        assert run.change.changed_files == ()
        assert run.change.verdict is Verdict.UNPROVEN
        assert run.stopped_because == "the model finished"

    def test_a_behaviour_preserving_edit_is_not_called_correct(self, repo: Path) -> None:
        """`EQUIVALENT_UNDER_BUDGET` is the strongest thing the engine may say, and the loop
        must not upgrade it on the way out.

        The edit is a pure refactor — same call, named result — chosen after a first draft used
        `sum(xs)` → an accumulate loop and came back DIVERGENT. That was not a flake: CPython
        special-cases `sum()` on strings (`sum() can't sum strings [use ''.join(seq) instead]`)
        while a loop raises the ordinary `unsupported operand type(s) for +: 'int' and 'str'`.
        On input `('a',)` the two really do behave differently, and the engine found it. The
        premise was wrong, not the verdict — see the test below, which keeps that case.
        """
        fake = FakeAnthropic()
        fake.tool_uses = [
            {
                "name": "write_file",
                "input": {
                    "path": "app.py",
                    "contents": "def total(xs):\n    result = sum(xs)\n    return result\n",
                },
            }
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "rewrote as a loop"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        assert run.change.verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        assert run.change.divergence_count == 0

    def test_an_edit_that_looks_equivalent_and_is_not_is_caught(self, repo: Path) -> None:
        """The case a reviewer would wave through, and the reason this product exists.

        Replacing `sum(xs)` with an accumulate loop is the textbook "obviously the same" rewrite.
        It is not: `sum()` refuses strings with its own message, so the two disagree on `('a',)`.
        No diff reader finds this. Executing both does.
        """
        fake = FakeAnthropic()
        fake.tool_uses = [
            {
                "name": "write_file",
                "input": {
                    "path": "app.py",
                    "contents": (
                        "def total(xs):\n    t = 0\n"
                        "    for x in xs:\n        t += x\n    return t\n"
                    ),
                },
            }
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "rewrote as a loop"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        assert run.change.verdict is Verdict.DIVERGENT
        assert run.change.divergence_count >= 1


class TestTheLoopIsBounded:
    def test_a_model_that_never_stops_hits_the_turn_budget_and_still_proves(
        self, repo: Path
    ) -> None:
        """The important half is "and still proves": a run that ran out of budget half-written is
        exactly the run a user most needs a verdict about."""
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "app.py"}}]
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, max_turns=2), env=_env(url))
        assert run.turns_used == 2
        assert "turn budget spent" in run.stopped_because
        assert run.change.bundle_id, "the proof still ran"

    def test_the_call_budget_refuses_rather_than_looping(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "app.py"}}]
        with fake_anthropic_server(fake) as url:
            run = run_task(
                _spec(repo, max_turns=4, budgets=Budgets(max_calls_per_turn=2)),
                env=_env(url),
            )
        refused = [c for c in run.calls if not c.ok]
        assert refused, "the budget must bite"
        assert any("call budget exhausted" in c.detail for c in refused)

    def test_a_model_error_ends_the_loop_and_still_proves(self, repo: Path) -> None:
        """L23: degrade explicitly. The peer dies after the first edit; the edit is still real,
        so it still gets a verdict rather than vanishing."""
        fake = FakeAnthropic()
        fake.tool_uses = [
            {
                "name": "write_file",
                "input": {"path": "app.py", "contents": "def total(xs):\n    return 0\n"},
            }
        ]
        with fake_anthropic_server(fake) as url:

            def die(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.status = 500

            run = run_task(_spec(repo), env=_env(url), on_event=die)
        assert "model unavailable" in run.stopped_because
        assert run.change.changed_files == ("app.py",)
        assert run.change.verdict is Verdict.DIVERGENT


class TestRunControl:
    """C5 run control: `TaskSpec.cancel` threads one `CancelScope` through the whole task —
    the turn loop polls it, the model call aborts on it, and the prove observes it at its
    checkpoints. Cancellation UNWINDS (`ProveCancelled`); it never soft-breaks into a proved
    partial the way a model outage deliberately does."""

    def test_cancel_between_turns_stops_asking_the_model(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "app.py"}}]
        scope = CancelScope()

        def cancel_on_tool(kind: str, _detail: str) -> None:
            if kind == "tool":
                scope.cancel()

        with fake_anthropic_server(fake) as url, pytest.raises(ProveCancelled):
            run_task(_spec(repo, cancel=scope), env=_env(url), on_event=cancel_on_tool)
        assert len(fake.requests) == 1, "a cancelled task kept asking the model"

    def test_cancel_mid_model_call_unwinds_rather_than_soft_breaking(self, repo: Path) -> None:
        """A model OUTAGE soft-breaks and still proves (L23). A CANCEL is the user saying stop:
        it must abort the in-flight completion within the read bound and leave no verdict —
        the turnlog's durable record is how the task resumes later, not a FINISHED row."""
        fake = FakeAnthropic()
        fake.hold_mid_reply.set()
        scope = CancelScope()
        timer = threading.Timer(0.5, lambda: scope.cancel())
        with fake_anthropic_server(fake) as url:
            timer.start()
            started = time.monotonic()
            with pytest.raises(ProveCancelled):
                run_task(_spec(repo, cancel=scope), env=_env(url))
            elapsed = time.monotonic() - started
            fake.resume.set()
        assert elapsed < 10.0, f"cancel took {elapsed:.1f}s against a stalled model reply"
        plan = plan_resume(TurnLog(repo), "t1")
        assert not plan.finished, "cancellation must never mint a verdict"

    def test_cancel_reaches_the_prove_checkpoints(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "nothing to change"
        scope = CancelScope()

        def cancel_when_proving(kind: str, _detail: str) -> None:
            if kind == "proving":
                scope.cancel()

        with fake_anthropic_server(fake) as url, pytest.raises(ProveCancelled):
            run_task(_spec(repo, cancel=scope), env=_env(url), on_event=cancel_when_proving)
        plan = plan_resume(TurnLog(repo), "t1")
        assert plan.reprove, "a task cancelled mid-prove must resume by reproving"

    def test_an_uncancelled_scope_changes_nothing(self, repo: Path) -> None:
        """The cancel field must cost nothing when nobody cancels."""
        fake = FakeAnthropic()
        fake.reply_text = "all done"
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, cancel=CancelScope()), env=_env(url))
        assert run.stopped_because == "the model finished"
        assert run.change.bundle_id


class TestToolSubset:
    """C5: an AGENT's tool selection binds the runtime, not just the picker (LC15's first
    tooth). The subset narrows BOTH sides of boundary D at once — the catalog the model is
    shown and the dispatcher that answers it — because a tool offered but refused teaches
    the model to retry, and a tool dispatched but never offered is a hole in the contract."""

    def test_the_model_is_shown_only_the_allowed_tools(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "nothing to do"
        with fake_anthropic_server(fake) as url:
            run_task(
                _spec(repo, tools_allowed=frozenset({"read_file"})),
                env=_env(url),
            )
        offered = fake.requests[0].get("tools", [])
        assert [t["name"] for t in offered] == ["read_file"]

    def test_an_unallowed_call_is_refused_and_the_tree_untouched(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [
            {"name": "write_file", "input": {"path": "app.py", "contents": "BROKEN\n"}}
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []

            run = run_task(
                _spec(repo, tools_allowed=frozenset({"read_file"})),
                env=_env(url),
                on_event=stop,
            )
        refused = [c for c in run.calls if not c.ok]
        assert refused and "toolset" in refused[0].detail
        assert run.change.changed_files == (), "the refused write must not exist"

    def test_an_unknown_allowed_name_is_a_loud_error(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with (
            fake_anthropic_server(fake) as url,
            pytest.raises(Exception, match="not in the manifest"),
        ):
            run_task(
                _spec(repo, tools_allowed=frozenset({"summon_demon"})),
                env=_env(url),
            )


class TestHumanInTheLoop:
    """C5 HITL (LC18): an approval-gated tool call PARKS the turn on `TaskSpec.approver`
    instead of refusing outright — durable first (the PENDING_APPROVAL row lands before the
    human is asked), decision applied exactly as scoped, refusal readable by the model. The
    `ask_user` tool rides the same machinery with an ANSWER instead of a grant."""

    def _approving(self, decision: ApprovalDecision) -> tuple[list[ApprovalRequest], Any]:
        asked: list[ApprovalRequest] = []

        def approver(request: ApprovalRequest) -> ApprovalDecision:
            asked.append(request)
            return decision

        return asked, approver

    def test_an_approval_runs_the_tool_and_the_park_was_durable(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "approved-run"]}}]
        asked, approver = self._approving(ApprovalDecision(approved=True))
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []

            run = run_task(_spec(repo, approver=approver), env=_env(url), on_event=stop)
        assert asked and asked[0].tool == "run_command"
        assert asked[0].kind == "tool_approval"
        ran = [c for c in run.calls if c.name == "run_command"]
        assert ran and ran[0].ok, f"the approved command must run: {ran}"
        assert "approved-run" in ran[0].detail
        # Durability: the ask was recorded BEFORE the human answered — a kill mid-park must
        # find the question in the log, not a mystery.
        rows = [c for c in TurnLog(repo).history("t1") if c.stage == "pending_approval"]
        assert rows and rows[0].payload["tool"] == "run_command"

    def test_a_rejection_reaches_the_model_with_the_reason(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "no"]}}]
        _asked, approver = self._approving(
            ApprovalDecision(approved=False, reason="not on a Friday")
        )
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []

            run = run_task(_spec(repo, approver=approver), env=_env(url), on_event=stop)
        refused = [c for c in run.calls if not c.ok]
        assert refused and "not on a Friday" in refused[0].detail

    def test_scope_once_asks_again_next_time(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "one"]}}]
        asked, approver = self._approving(ApprovalDecision(approved=True, scope="once"))
        with fake_anthropic_server(fake) as url:
            turns_seen = {"count": 0}

            def two_rounds(kind: str, _d: str) -> None:
                if kind == "tool":
                    turns_seen["count"] += 1
                    if turns_seen["count"] == 1:
                        fake.tool_uses = [
                            {"name": "run_command", "input": {"argv": ["echo", "two"]}}
                        ]
                    else:
                        fake.tool_uses = []

            run = run_task(_spec(repo, approver=approver), env=_env(url), on_event=two_rounds)
        assert len(asked) == 2, "scope=once must not silently persist"
        assert all(c.ok for c in run.calls if c.name == "run_command")

    def test_scope_session_grants_the_rest_of_the_task(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "one"]}}]
        asked, approver = self._approving(ApprovalDecision(approved=True, scope="session"))
        with fake_anthropic_server(fake) as url:
            turns_seen = {"count": 0}

            def two_rounds(kind: str, _d: str) -> None:
                if kind == "tool":
                    turns_seen["count"] += 1
                    if turns_seen["count"] == 1:
                        fake.tool_uses = [
                            {"name": "run_command", "input": {"argv": ["echo", "two"]}}
                        ]
                    else:
                        fake.tool_uses = []

            run = run_task(_spec(repo, approver=approver), env=_env(url), on_event=two_rounds)
        assert len(asked) == 1, "a session grant must not re-ask"
        assert sum(1 for c in run.calls if c.name == "run_command" and c.ok) == 2

    def test_no_approver_keeps_the_plain_refusal(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "hi"]}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        refused = [c for c in run.calls if not c.ok]
        assert refused and "requires approval" in refused[0].detail

    def test_an_approver_raising_cancellation_unwinds_the_task(self, repo: Path) -> None:
        """The park's cancellation path: the surface's approver observes the abort and
        raises; the task unwinds without a verdict, resumable like any other kill."""
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "hi"]}}]

        def approver(_request: ApprovalRequest) -> ApprovalDecision:
            raise ProveCancelled("the user stopped the turn while it was parked")

        with fake_anthropic_server(fake) as url, pytest.raises(ProveCancelled):
            run_task(_spec(repo, approver=approver), env=_env(url))

    def test_ask_user_round_trips_an_answer_into_the_transcript(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "ask_user", "input": {"question": "Blue or green?"}}]
        asked, approver = self._approving(
            ApprovalDecision(approved=True, response_text="blue, always blue")
        )
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "Blue it is."

            run = run_task(_spec(repo, approver=approver), env=_env(url), on_event=stop)
        assert asked and asked[0].kind == "ask_user_question"
        answered = [c for c in run.calls if c.name == "ask_user"]
        assert answered and answered[0].ok
        assert "blue, always blue" in answered[0].detail
        # The answer went back to the MODEL as the tool result.
        replayed = json.dumps(fake.requests[-1])
        assert "blue, always blue" in replayed

    def test_ask_user_without_an_approver_refuses_honestly(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "ask_user", "input": {"question": "Anyone there?"}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        refused = [c for c in run.calls if not c.ok]
        assert refused, "a question with nobody to ask must refuse, not invent an answer"


class TestSteering:
    """C5 steering (LC16): queued follow-ups drain at the top of each turn — the model sees
    them as user messages BEFORE it is asked again, and each drained steer is emitted so the
    surface can mark its chip applied."""

    def test_a_queued_steer_reaches_the_next_model_call(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "app.py"}}]
        queue: list[str] = []
        drained: list[str] = []

        def steer_source() -> tuple[str, ...]:
            out = tuple(queue)
            queue.clear()
            return out

        with fake_anthropic_server(fake) as url:

            def after_first_tool(kind: str, detail: str) -> None:
                if kind == "tool":
                    queue.append("actually, focus on the docstring")
                    fake.tool_uses = []
                    fake.reply_text = "Focusing on the docstring."
                if kind == "steer":
                    drained.append(detail)

            run_task(
                _spec(repo, steer_source=steer_source),
                env=_env(url),
                on_event=after_first_tool,
            )
        assert drained == ["actually, focus on the docstring"]
        second_request = json.dumps(fake.requests[-1])
        assert "focus on the docstring" in second_request, (
            "the steer must reach the model as a user message before its next turn"
        )

    def test_no_steer_source_changes_nothing(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "done"
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo), env=_env(url))
        assert run.stopped_because == "the model finished"


class TestWhatTheModelMayNotDo:
    def test_it_cannot_run_the_proof_itself(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "prove", "input": {}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "ok"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        refusal = next(c for c in run.calls if c.name == "prove")
        assert not refusal.ok
        assert "L16" in refusal.detail

    def test_it_cannot_escape_the_shadow(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [
            {"name": "write_file", "input": {"path": "../../escaped.py", "contents": "X"}}
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "ok"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        assert not run.calls[0].ok
        assert "escapes" in run.calls[0].detail
        assert not (repo.parent / "escaped.py").exists()

    def test_an_ungranted_command_is_refused(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "run_command", "input": {"argv": ["echo", "hi"]}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "ok"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        assert not run.calls[0].ok
        assert "requires approval" in run.calls[0].detail

    def test_an_unknown_tool_is_refused_without_ending_the_run(self, repo: Path) -> None:
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "rm_rf", "input": {}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "ok"

            run = run_task(_spec(repo), env=_env(url), on_event=stop)
        assert not run.calls[0].ok and "unknown tool" in run.calls[0].detail
        assert run.change.bundle_id


class TestL16IsAStateWithNoConstructor:
    """The adversarial forge test L16 asks for, in both directions it can be attacked."""

    def test_a_verified_claim_without_evidence_cannot_be_built(self) -> None:
        with pytest.raises(AgentError, match="without evidence"):
            ProvenChange(
                verdict=Verdict.EQUIVALENT_UNDER_BUDGET,
                bundle_id="",
                bundle_dir=Path("."),
                changed_files=("app.py",),
                divergence_count=0,
                baseline="a",
                head="b",
            )

    def test_a_model_authored_verdict_cannot_be_built(self) -> None:
        """L17: a verdict is an engine value. A string that merely looks like one is refused, so
        a model's text can never arrive in the field the UI reads as the answer."""
        with pytest.raises(AgentError, match="engine Verdict"):
            ProvenChange(
                verdict="VERIFIED",  # type: ignore[arg-type]
                bundle_id="real",
                bundle_dir=Path("."),
                changed_files=(),
                divergence_count=0,
                baseline="a",
                head="b",
            )

    def test_the_only_producer_of_a_proven_change_proves(self) -> None:
        """`run_task` is the sole path. If a second producer ever appears, this fails and the
        reviewer has to justify it."""
        import inspect

        from tempest.agent import orchestrator

        producers = [
            name
            for name, fn in vars(orchestrator).items()
            if inspect.isfunction(fn)
            and inspect.signature(fn).return_annotation in ("AgentRun", "ProvenChange")
        ]
        assert producers == ["run_task"]

        # `ProvenChange(` may be CONSTRUCTED in exactly one place, and that place must call the
        # engine. Checking `run_task` for the literal `run_prove(` was too shallow: extracting
        # the proof into a helper broke the test while the property it guards was untouched, and
        # a test that fails on a refactor teaches people to weaken it.
        source = inspect.getsource(orchestrator)
        constructors = [
            name
            for name, fn in vars(orchestrator).items()
            if inspect.isfunction(fn) and "ProvenChange(" in inspect.getsource(fn)
        ]
        assert constructors == ["_prove_and_classify"], (
            f"a second construction site would be a second way to claim a verdict: {constructors}"
        )
        assert "run_prove(" in inspect.getsource(orchestrator._prove_and_classify)
        assert source.count("run_prove(") == 1, "one call to the engine, not several"


class TestWhatGoesBackToTheModel:
    def test_a_truncated_tool_result_says_so_in_the_text_the_model_reads(self, repo: Path) -> None:
        """A cut answer that does not announce itself is read as a whole one, and the model then
        reasons about a file it has only seen the beginning of."""
        (repo / "big.py").write_text("# pad\n" * 400, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "big")

        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "read_file", "input": {"path": "big.py"}}]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "ok"

            run = run_task(
                _spec(repo, budgets=Budgets(max_read_bytes=40)), env=_env(url), on_event=stop
            )

        assert run.calls[0].ok and run.calls[0].name == "read_file"
        sent = fake.requests[-1]["messages"]
        result_block = sent[-1]["content"][0]["content"]
        assert "[truncated by the host's budget]" in result_block


class TestIntentContractsMeetTheProof:
    """F2 where it actually matters: a real divergence, placed against a real contract."""

    def _diverge(self, repo: Path, task_id: str = "t1") -> Any:
        """One task id per run: a shadow worktree is per-task and `shadow.create` refuses to
        reuse one, which is correct — two runs sharing a staging area would let the second
        inherit the first's edits and prove the wrong baseline."""
        fake = FakeAnthropic()
        fake.tool_uses = [
            {
                "name": "write_file",
                "input": {"path": "app.py", "contents": "def total(xs):\n    return sum(xs) + 1\n"},
            }
        ]
        with fake_anthropic_server(fake) as url:

            def stop(kind: str, _d: str) -> None:
                if kind == "tool":
                    fake.tool_uses = []
                    fake.reply_text = "changed total"

            return run_task(_spec(repo, task_id=task_id), env=_env(url), on_event=stop)

    def test_with_no_contract_every_divergence_is_unclassified(self, repo: Path) -> None:
        run = self._diverge(repo)
        assert run.divergences
        assert all(d.classification == contracts.UNCLASSIFIED for d in run.divergences)
        assert run.unclassified == run.divergences
        assert run.unintended == ()

    def test_a_permitted_symbol_reads_as_intended(self, repo: Path) -> None:
        contracts.save(
            repo, "t1", contracts.IntentContract(intent="change total", may_change=("total",))
        )
        run = self._diverge(repo)
        assert run.divergences
        assert all(d.classification == contracts.INTENDED for d in run.divergences)
        assert run.unintended == () and run.unclassified == ()

    def test_a_forbidden_symbol_reads_as_unintended_and_becomes_the_repair_signal(
        self, repo: Path
    ) -> None:
        contracts.save(
            repo,
            "t1",
            contracts.IntentContract(intent="touch nothing", must_not_change=("total",)),
        )
        run = self._diverge(repo)
        assert run.unintended, "this is what F3 repairs against"
        assert all(d.classification == contracts.UNINTENDED for d in run.unintended)

    def test_the_contract_never_changes_the_verdict(self, repo: Path) -> None:
        """The engine says WHAT happened; the contract says whether it was asked for. A contract
        that could alter a verdict would be a way to talk the engine out of its evidence."""
        without = self._diverge(repo, task_id="no-contract")
        contracts.save(
            repo,
            "with-contract",
            contracts.IntentContract(intent="change total", may_change=("total",)),
        )
        with_contract = self._diverge(repo, task_id="with-contract")
        assert without.change.verdict is with_contract.change.verdict is Verdict.DIVERGENT
        assert without.change.divergence_count == with_contract.change.divergence_count
