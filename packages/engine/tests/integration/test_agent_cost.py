"""L21 for the agent turn loop: money is bounded, and a breached cap still ends on a verdict.

The module docstring claimed this for the whole of Phase 21 while `TaskSpec` had no way to supply
a meter — money was the one budget nothing enforced. A doc comment is a claim and this project
tests its claims (trap 45), so these are the tests that make the sentence true.

Every run here is a real repository, a real shadow, a real proof and a real loopback model. The
ledger is the engine's own, on disk.

States enumerated before the tests (trap 43): no meter at all · a meter with no caps · a token cap
that is not reached · a token cap reached mid-loop · a cap already spent before the task starts ·
a per-session cap · charges recorded for a turn that then breached.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tempest.agent.orchestrator import TaskSpec, run_task
from tempest.inference import cost as cost_mod
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

_BASE = "def total(xs):\n    return sum(xs)\n"
_CHANGED = "def total(xs):\n    return sum(xs) + 1\n"


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


class _Editing:
    """A model that writes on every turn it is given, so the turn budget is what stops it."""

    def __init__(self, fake: FakeAnthropic) -> None:
        fake.tool_uses = [{"name": "write_file", "input": {"path": "app.py", "contents": _CHANGED}}]

    def __call__(self, _kind: str, _detail: str) -> None:
        return None


def _spec(repo: Path, **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": "task",
        "prompt": "add one to total",
        "provider": "anthropic",
        "max_inputs": 6,
        "max_turns": 4,
        "max_repair_attempts": 0,
    }
    base.update(kw)
    return TaskSpec(**base)


class TestWithoutAMeter:
    def test_money_is_simply_not_bounded_and_nothing_pretends_otherwise(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo), env=_env(url), on_event=_Editing(fake))
        assert run.change.bundle_id
        assert not (repo / ".tempest" / "cost").exists(), "no meter, no ledger"


class TestWithAMeter:
    def test_every_turn_is_charged_to_the_ledger(self, repo: Path) -> None:
        meter = cost_mod.Meter(repo)
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, meter=meter), env=_env(url), on_event=_Editing(fake))
        spent = meter.totals(cost_mod.SCOPE_TASK, "task")
        assert spent.total_tokens > 0
        assert spent.total_tokens == 2 * run.turns_used, "the fake peer reports 1 in, 1 out"

    def test_a_cap_that_is_not_reached_changes_nothing(self, repo: Path) -> None:
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_TASK: cost_mod.Budget(max_total_tokens=1000)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, meter=meter), env=_env(url), on_event=_Editing(fake))
        assert run.stopped_because == "turn budget spent (4)"

    def test_a_breached_cap_ends_the_loop_and_STILL_proves_what_was_staged(
        self, repo: Path
    ) -> None:
        """The half of L21 that matters most. A change that ran out of money half-written is
        exactly the change a user most needs a verdict about — throwing it away would be the
        product failing at the one thing it exists for."""
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_TASK: cost_mod.Budget(max_total_tokens=3)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, meter=meter), env=_env(url), on_event=_Editing(fake))

        assert run.stopped_because.startswith("cost cap reached")
        assert "max_total_tokens" in run.stopped_because or "token" in run.stopped_because
        assert run.change.bundle_id, "the staged work was still proved"
        assert run.change.verdict is Verdict.DIVERGENT
        assert "app.py" in run.change.changed_files
        assert run.turns_used < 4, "it stopped early rather than spending the whole turn budget"

    def test_the_turn_that_discovered_the_cap_is_itself_recorded(self, repo: Path) -> None:
        """The ledger is written before the check raises, so a cap is never breached by more
        than the one call that found it — and never silently un-recorded."""
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_TASK: cost_mod.Budget(max_total_tokens=3)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run_task(_spec(repo, meter=meter), env=_env(url), on_event=_Editing(fake))
        assert meter.totals(cost_mod.SCOPE_TASK, "task").total_tokens > 0

    def test_a_budget_already_spent_stops_the_first_turn(self, repo: Path) -> None:
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_TASK: cost_mod.Budget(max_total_tokens=1)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run = run_task(_spec(repo, meter=meter), env=_env(url), on_event=_Editing(fake))
        assert run.stopped_because.startswith("cost cap reached")
        assert run.turns_used == 1
        assert run.change.bundle_id, "even a task that bought nothing ends on a verdict"

    def test_a_session_cap_binds_across_tasks(self, repo: Path) -> None:
        """ "per task, per session, per day" — the session scope is how the second one is real."""
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_SESSION: cost_mod.Budget(max_total_tokens=3)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            run_task(
                _spec(repo, task_id="first", meter=meter, max_turns=1),
                env=_env(url),
                on_event=_Editing(fake),
            )
            second = run_task(
                _spec(repo, task_id="second", meter=meter, max_turns=1),
                env=_env(url),
                on_event=_Editing(fake),
            )
        assert second.stopped_because.startswith("cost cap reached")
