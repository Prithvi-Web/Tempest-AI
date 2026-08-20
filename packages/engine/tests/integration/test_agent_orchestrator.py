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

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import contracts
from tempest.agent.orchestrator import AgentError, ProvenChange, TaskSpec, run_task
from tempest.agent.tools import Budgets
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    (root / "app.py").write_text(_BASE, encoding="utf-8")
    (root / ".tempest-first-party").write_text("", encoding="utf-8")
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
