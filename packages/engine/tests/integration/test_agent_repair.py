"""F3 end to end: the agent breaks something, gets the evidence, and tries again — for real.

`test_repair_judgement.py` pins the judgement as a pure function. This file runs the whole loop:
a real git repo, a real shadow worktree, a real differential proof after every attempt, and a
loopback model peer scripted to behave a particular way. The cheats are the point — each of the
three the spec names is driven here as an actual sequence of edits, not as a constructed verdict.

States enumerated before the tests (trap 43): no contract, so the loop never engages · a contract
with nothing to repair · a genuine repair on the first attempt · a repair that never succeeds and
spends its budget · the agent deleting the divergent path · the agent breaking the module so the
target cannot be proved · the agent restoring the symbol byte-for-byte while breaking the
module around it · a repair that legitimately adds a working import · the agent reverting its
own work · a zero attempt budget.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import contracts
from tempest.agent.orchestrator import TaskSpec, run_task
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

_BASE = "def total(xs):\n    return sum(xs)\n"
_DIVERGENT = "def total(xs):\n    return sum(xs) + 1\n"
#: A real change that is behaviourally identical — the shape a genuine repair takes. Restoring
#: the file byte-for-byte would leave nothing to prove, which is a different outcome entirely
#: (see the abandonment test).
_REPAIRED = "def total(xs):\n    result = sum(xs)\n    return result\n"


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


def _write(contents: str) -> dict[str, Any]:
    return {"name": "write_file", "input": {"path": "app.py", "contents": contents}}


class _Script:
    """A model that performs a fixed sequence of edits, one per conversation turn.

    Each entry is the tool call for that turn; when the script runs out the model answers in
    prose, which is how a turn ends. This is the smallest thing that can drive a multi-attempt
    repair loop deterministically.
    """

    def __init__(self, fake: FakeAnthropic, edits: list[dict[str, Any] | None]) -> None:
        self.fake = fake
        self.edits = list(edits)
        self.fake.tool_uses = [self.edits[0]] if self.edits and self.edits[0] else []
        if not self.fake.tool_uses:
            self.fake.reply_text = "nothing to do"

    def __call__(self, kind: str, _detail: str) -> None:
        if kind != "tool":
            return
        self.edits.pop(0)
        nxt = self.edits[0] if self.edits else None
        if nxt:
            self.fake.tool_uses = [nxt]
        else:
            self.fake.tool_uses = []
            self.fake.reply_text = "done"


def _spec(repo: Path, task_id: str, **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": task_id,
        "prompt": "speed up total",
        "provider": "anthropic",
        "max_inputs": 6,
        # ONE model turn per conversation, so one edit per attempt. With a larger budget the
        # scripted model spends its whole script inside the FIRST conversation and the initial
        # proof already sees the repaired file — the repair loop then has nothing to do and the
        # test passes for the wrong reason.
        "max_turns": 1,
    }
    base.update(kw)
    return TaskSpec(**base)


def _forbid_total(repo: Path, task_id: str) -> None:
    contracts.save(
        repo,
        task_id,
        contracts.IntentContract(
            intent="speed it up; behaviour must not change", must_not_change=("total",)
        ),
    )


class TestWhenTheLoopDoesNotEngage:
    def test_with_no_contract_there_is_nothing_to_repair_against(self, repo: Path) -> None:
        """Every divergence is unclassified, and "repair" would mean guessing which of the
        user's own changes they did not want — the judgement F2 keeps a model out of."""
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "no-contract"), env=_env(url), on_event=script)
        assert run.repair is None, "None means it never ran — not that it ran and failed"
        assert run.change.verdict is Verdict.DIVERGENT

    def test_a_zero_budget_means_prove_once_and_stop(self, repo: Path) -> None:
        _forbid_total(repo, "no-budget")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(
                _spec(repo, "no-budget", max_repair_attempts=0), env=_env(url), on_event=script
            )
        assert run.repair is None
        assert run.unintended, "the violation is still reported, just not repaired"

    def test_nothing_to_repair_leaves_the_loop_unused(self, repo: Path) -> None:
        contracts.save(
            repo,
            "allowed",
            contracts.IntentContract(intent="change total", may_change=("total",)),
        )
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "allowed"), env=_env(url), on_event=script)
        assert run.repair is None, "the divergence was asked for; there is nothing to fix"


class TestAGenuineRepair:
    def test_the_agent_is_given_the_evidence_and_fixes_it(self, repo: Path) -> None:
        """The headline: break it, receive the minimized repro, fix it, re-prove, succeed."""
        _forbid_total(repo, "fixes")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(_REPAIRED), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "fixes"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert run.repair.succeeded, run.repair.reason
        assert not run.repair.cheated
        assert len(run.repair.attempts) == 1, "one attempt was enough"
        assert run.change.verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        assert run.unintended == (), "the reported state is the REPAIRED one"

    def test_the_model_actually_received_the_minimized_repro(self, repo: Path) -> None:
        """The evidence packet is the fitness function. If it never reaches the model, the loop
        is just retrying and hoping."""
        _forbid_total(repo, "evidence")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(_REPAIRED), None])
        with fake_anthropic_server(fake) as url:
            run_task(_spec(repo, "evidence"), env=_env(url), on_event=script)

        sent = " ".join(
            str(m.get("content"))
            for r in fake.requests
            for m in r["messages"]  # type: ignore[union-attr]
        )
        assert "A change you made diverged" in sent
        assert 'must_not_change = "total"' in sent
        assert "before your change" in sent and "after your change" in sent

    def test_every_attempt_is_kept_and_visible(self, repo: Path) -> None:
        """F3: never hide the loop."""
        _forbid_total(repo, "visible")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(_DIVERGENT), _write(_REPAIRED), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(
                _spec(repo, "visible", max_repair_attempts=3),
                env=_env(url),
                on_event=script,
            )
        assert run.repair is not None
        assert [a.number for a in run.repair.attempts] == list(
            range(1, len(run.repair.attempts) + 1)
        )
        assert all(a.packet.qualname == "total" for a in run.repair.attempts)


class TestTheBudgetIsReal:
    def test_an_agent_that_never_fixes_it_spends_the_budget_and_says_so(self, repo: Path) -> None:
        _forbid_total(repo, "stubborn")
        fake = FakeAnthropic()
        # Never repairs: rewrites the same divergent body every time.
        script = _Script(fake, [_write(_DIVERGENT)] * 8 + [None])
        with fake_anthropic_server(fake) as url:
            run = run_task(
                _spec(repo, "stubborn", max_repair_attempts=2),
                env=_env(url),
                on_event=script,
            )
        assert run.repair is not None
        assert not run.repair.succeeded
        assert len(run.repair.attempts) == 2, "exactly the budget, not one more"
        assert run.change.verdict is Verdict.DIVERGENT
        assert run.unintended, "the violation is still reported honestly at the end"


class TestTheThreeCheats:
    """One test per cheat the spec names, driven as real edits against a real proof."""

    def test_deleting_the_divergent_path_is_not_a_repair(self, repo: Path) -> None:
        """Cheat 2. Nothing diverges because nothing runs."""
        _forbid_total(repo, "deletes")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write("# nothing here any more\n"), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "deletes"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert not run.repair.succeeded
        assert run.repair.cheated
        assert "stopped being provable" in run.repair.reason

    def test_making_the_target_unprovable_is_not_a_repair(self, repo: Path) -> None:
        """Cheat 3. The symbol is still there; the engine can no longer run it. A membership
        check over target NAMES would pass this one — only counting conclusive verdicts sees it.

        The reason names the BROKEN IMPORT rather than the lost target (ADR-0051). Both are
        true; the import is the one a person can act on, and the lost target is its symptom.
        """
        _forbid_total(repo, "breaks")
        broken = "import nonexistent_module_xyz\n\n\ndef total(xs):\n    return sum(xs) + 1\n"
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(broken), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "breaks"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert not run.repair.succeeded
        assert run.repair.cheated
        assert "no longer loads" in run.repair.reason
        assert "nonexistent_module_xyz" in run.repair.reason

    def test_cheat_4_restoring_the_symbol_while_breaking_the_module_around_it(
        self, repo: Path
    ) -> None:
        """The §0 defect, end to end (ADR-0051).

        Every static signal says this was repaired. `total` is restored BYTE FOR BYTE, so
        `reverted_symbols` correctly excuses it. It is no longer a changed symbol, so the bundle
        is empty and there is nothing left to diverge. The contract is untouched. And the module
        does not import, so none of it runs.

        This is the case that made `repair_bench` count a cheat as a success. Only executing the
        import sees it — the file parses perfectly.
        """
        _forbid_total(repo, "restores-and-breaks")
        sneaky = "import no_such_module_xyz\n\n\ndef total(xs):\n    return sum(xs)\n"
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(sneaky), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "restores-and-breaks"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert not run.repair.succeeded, "this is the false success the load probe exists to end"
        assert run.repair.cheated
        assert "no longer loads" in run.repair.reason
        assert "app.py" in run.repair.reason
        # The failing import by NAME. Without this the assertions above are satisfied by the
        # fail-closed message the no-sandbox path produces, so the test would pass on a machine
        # where nothing executed at all — a green result about a probe that never ran (trap 47).
        assert "no_such_module_xyz" in run.repair.reason

    def test_a_repair_that_adds_a_working_import_is_not_punished_for_it(self, repo: Path) -> None:
        """The regression the obvious fix would have caused (trap 48).

        "Refuse any module-level change" and "require the whole file to be unchanged" both catch
        the cheat above and both break this: an ordinary repair that needs a standard-library
        import. The rule is whether the module LOADS, not whether it changed.
        """
        _forbid_total(repo, "adds-an-import")
        with_import = "import builtins\n\n\ndef total(xs):\n    return builtins.sum(xs)\n"
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(with_import), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "adds-an-import"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert run.repair.succeeded, run.repair.reason
        assert not run.repair.cheated

    def test_the_contract_is_not_even_reachable_from_the_agents_tools(self, repo: Path) -> None:
        """Cheat 1, closed by construction rather than by detection.

        `write_file` is confined to the SHADOW worktree; the contract classification reads the
        file in the USER's repo. So an agent writing to `.tempest/contracts/...` edits a file
        nothing consults. The byte-comparison in `judge` is defence in depth for a path that does
        not currently exist — which is the right order: make it unreachable, then check anyway.
        """
        _forbid_total(repo, "sneaky")
        before = contracts.path_for(repo, "sneaky").read_text(encoding="utf-8")
        permissive = 'intent = "anything goes"\nmay_change = ["total"]\n'
        fake = FakeAnthropic()
        script = _Script(
            fake,
            [
                _write(_DIVERGENT),
                {
                    "name": "write_file",
                    "input": {
                        "path": ".tempest/contracts/sneaky.toml",
                        "contents": permissive,
                    },
                },
                None,
            ],
        )
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "sneaky"), env=_env(url), on_event=script)

        assert contracts.path_for(repo, "sneaky").read_text(encoding="utf-8") == before
        assert run.repair is not None and not run.repair.succeeded
        assert run.unintended, "the divergence is still unintended; the contract still says so"


class TestAbandonmentIsItsOwnAnswer:
    def test_reverting_the_change_is_neither_a_repair_nor_a_cheat(self, repo: Path) -> None:
        """Every target that was proven is gone — but because there is no change left to have
        evidence about, not because evidence was destroyed. Calling that a cheat would be an
        accusation about an honest, if useless, outcome."""
        _forbid_total(repo, "reverts")
        fake = FakeAnthropic()
        script = _Script(fake, [_write(_DIVERGENT), _write(_BASE), None])
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, "reverts"), env=_env(url), on_event=script)

        assert run.repair is not None
        assert not run.repair.succeeded
        assert not run.repair.cheated
        assert "reverted its own change" in run.repair.reason
        assert run.change.changed_files == ()
