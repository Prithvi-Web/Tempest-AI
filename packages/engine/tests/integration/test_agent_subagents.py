"""P4 — subagents, and the four properties that make a delegation trustworthy.

Nothing here is mocked below the model. Every subagent builds a real shadow worktree, makes a
real edit and ends on a real `run_prove` verdict; the "model" is the loopback Messages peer that
ADR-0024 established.

The gate P4 states is one line — *8 nested subagents with independent verdicts, correct budget
accounting (L21), and full cancellation propagation* — and each clause is a separate failure the
tests have to be able to see:

* an independent verdict needs an independent WORKTREE, so the tests count worktrees, not runs;
* correct budget accounting means eight children share ONE per-task cap, so the tests read the
  ledger by key rather than trusting a total;
* full propagation means a cancelled fleet leaves nothing running AND nothing silently dropped,
  so the tests assert on refusals as hard as on results.

States enumerated before the tests (trap 43): one child · two siblings · a nested grandchild ·
eight nested · one more than the bound · deeper than the bound · cancelled before the first ·
cancelled between children · a child asking for wider grants · a child narrowing its own ·
duplicate sibling names · a name that would forge a path · a refused subtree · a fleet with no
children at all.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import subagents as sub
from tempest.agent.orchestrator import TaskSpec
from tempest.execute.cancel import CancelScope
from tempest.inference import cost as cost_mod
from tempest.inference.providers import get
from tempest.model import Verdict

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server
from ..helpers_first_party import mark_first_party

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


@pytest.fixture(autouse=True)
def _dev() -> Iterator[None]:
    """Half of what makes the fixture repository first-party (ADR-0008); `mark_first_party`
    writes the other half and checks that both took. On a MonkeyPatch of its own, so a test that
    calls `monkeypatch.undo()` cannot drop it (ADR-0058)."""
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


def _parent(repo: Path, **kw: Any) -> TaskSpec:
    base: dict[str, Any] = {
        "repo": repo,
        "task_id": "root",
        "prompt": "the parent task",
        "provider": "anthropic",
        # 8, not 4. `sum(xs) + 3` and `sum(xs) + 4` are DIVERGENT changes that a four-input
        # budget does not happen to catch — the first four generated inputs do not distinguish
        # them — and the engine correctly says EQUIVALENT_UNDER_BUDGET, which is exactly what
        # that verdict means ("this is not 'correct'", L2). A fixture that expects DIVERGENT
        # must give the generator enough budget to find it, or it is testing the sampler.
        "max_inputs": 8,
        "max_turns": 1,
        "max_repair_attempts": 0,
    }
    base.update(kw)
    return TaskSpec(**base)


class _Editing:
    """A model that writes the same divergent body on every turn it is given."""

    def __init__(self, fake: FakeAnthropic) -> None:
        fake.tool_uses = [{"name": "write_file", "input": {"path": "app.py", "contents": _CHANGED}}]

    def __call__(self, _kind: str, _detail: str) -> None:
        return None


class _DistinctEditing:
    """A model that writes a DIFFERENT body for every subagent.

    Not decoration. A bundle id is `baseline..head`, and a git commit over identical content with
    an identical parent, message and second IS the same commit — so eight subagents making the
    same edit legitimately share seven bundles, and a test asserting "eight distinct bundles"
    would fail for a reason that has nothing to do with isolation. Making each edit distinct is
    what turns "each has its own verdict" into a claim the evidence can actually distinguish.
    """

    def __init__(self, fake: FakeAnthropic) -> None:
        self.fake = fake
        self.seen = 0
        self._arm()

    def _arm(self) -> None:
        # 1-based: `sum(xs) + 0` is behaviour-PRESERVING, and a fixture meant to produce
        # eight divergences would have quietly produced seven and an EQUIVALENT.
        body = f"def total(xs):\n    return sum(xs) + {self.seen + 1}\n"
        self.fake.tool_uses = [
            {"name": "write_file", "input": {"path": "app.py", "contents": body}}
        ]

    def __call__(self, kind: str, _detail: str) -> None:
        if kind == "subagent":
            self.seen += 1
            self._arm()


def _chain(depth: int, prefix: str = "s") -> sub.SubagentSpec:
    """A nest `depth` levels deep: s1 → s2 → … → s<depth>."""
    spec = sub.SubagentSpec(name=f"{prefix}{depth}", prompt=f"level {depth}")
    for level in range(depth - 1, 0, -1):
        spec = sub.SubagentSpec(name=f"{prefix}{level}", prompt=f"level {level}", children=(spec,))
    return spec


def _worktrees(repo: Path) -> list[str]:
    root = repo / ".tempest" / "agent" / "worktrees"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


class TestOneDelegation:
    def test_a_subagent_ends_on_its_own_engine_verdict(self, repo: Path) -> None:
        """The whole of P4 in one assertion: the child is not "done", it is PROVED."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [sub.SubagentSpec(name="one", prompt="make it diverge")],
                env=_env(url),
                on_event=_Editing(fake),
            )
        assert out.spawned == 1
        child = out.runs[0]
        assert child.task_id == "root/one"
        assert child.run is not None
        assert child.run.change.bundle_id, "L16: a change without a bundle cannot exist"
        assert child.verdict is Verdict.DIVERGENT
        assert out.verdicts() == (Verdict.DIVERGENT,)

    def test_a_fleet_with_no_children_runs_nothing_and_says_so(self, repo: Path) -> None:
        out = sub.run_fleet(_parent(repo), [], env={})
        assert out.runs == () and out.spawned == 0 and out.stopped_because == ""
        assert out.verdicts() == () and out.refusals == ()

    def test_a_fleet_with_no_observer_still_runs(self, repo: Path) -> None:
        """`on_event=None` is the ordinary case for a programmatic caller — F7 delegating one
        refactor step per subagent has nobody to notify. The fleet must not require an observer
        to do its work, and the child must still end on a verdict."""
        fake = FakeAnthropic()
        fake.tool_uses = [{"name": "write_file", "input": {"path": "app.py", "contents": _CHANGED}}]
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo), [sub.SubagentSpec(name="quiet", prompt="x")], env=_env(url)
            )
        assert out.spawned == 1
        assert out.runs[0].verdict is Verdict.DIVERGENT

    def test_the_child_inherits_the_repository_and_narrows_only_the_prompt(
        self, repo: Path
    ) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo, grants=frozenset({"read_file"})),
                [sub.SubagentSpec(name="one", prompt="a narrower job")],
                env=_env(url),
                on_event=_Editing(fake),
            )
        assert out.runs[0].run is not None
        assert out.runs[0].run.change.changed_files == ("app.py",)


class TestEachOneHasItsOwnWorktree:
    def test_two_siblings_do_not_share_a_shadow(self, repo: Path) -> None:
        """Sharing one would make both verdicts meaningless: neither could say which change its
        evidence was about."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [sub.SubagentSpec(name="a", prompt="a"), sub.SubagentSpec(name="b", prompt="b")],
                env=_env(url),
                on_event=_DistinctEditing(fake),
            )
        assert out.spawned == 2
        assert len(_worktrees(repo)) == 2, "one worktree per subagent, never one between them"
        bundles = {s.run.change.bundle_dir for s in out.walk() if s.run is not None}
        assert len(bundles) == 2, "two subagents, two bundles"

    def test_eight_nested_subagents_each_get_a_worktree_and_a_verdict(self, repo: Path) -> None:
        """P4's gate, exactly as written: eight, NESTED, each with its own verdict."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [_chain(8)],
                env=_env(url),
                on_event=_DistinctEditing(fake),
                max_depth=8,
                max_subagents=8,
            )
        assert out.spawned == 8
        assert out.refusals == (), "nothing was refused, so nothing was quietly dropped"
        assert len(out.verdicts()) == 8
        assert set(out.verdicts()) == {Verdict.DIVERGENT}, [
            (s.task_id, s.verdict) for s in out.walk()
        ]
        assert len(_worktrees(repo)) == 8, "eight independent shadows"
        assert [s.depth for s in out.walk()] == list(range(1, 9))
        ids = [s.task_id for s in out.walk()]
        assert ids[0] == "root/s1" and ids[-1].endswith("/s8")
        bundles = {s.run.change.bundle_id for s in out.walk() if s.run is not None}
        assert len(bundles) == 8, "eight edits, eight bundles — no child proved another's change"
        assert all(
            s.run is not None and s.run.change.changed_files == ("app.py",) for s in out.walk()
        )


class TestTheBoundsAreReal:
    def test_one_more_than_the_bound_is_refused_and_recorded(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [sub.SubagentSpec(name=f"n{i}", prompt="x") for i in range(3)],
                env=_env(url),
                on_event=_Editing(fake),
                max_subagents=2,
            )
        assert out.spawned == 2
        assert [s.refused for s in out.runs] == ["", "", sub.REFUSED_COUNT]
        assert out.stopped_because == sub.REFUSED_COUNT
        assert out.verdicts() == (Verdict.DIVERGENT, Verdict.DIVERGENT)

    def test_deeper_than_the_bound_is_refused_with_its_whole_subtree(self, repo: Path) -> None:
        """A refused subagent takes its descendants with it — returning fewer results than were
        asked for, with no reason attached, is how a fleet loses work silently."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [_chain(4)],
                env=_env(url),
                on_event=_Editing(fake),
                max_depth=2,
            )
        assert out.spawned == 2
        refused = [s for s in out.walk() if s.refused]
        assert [s.name for s in refused] == ["s3", "s4"]
        assert {s.refused for s in refused} == {sub.REFUSED_DEPTH}
        assert all(s.run is None for s in refused)

    def test_a_fleet_that_could_never_run_anything_is_an_error_not_an_empty_result(
        self, repo: Path
    ) -> None:
        with pytest.raises(sub.SubagentError, match="cannot run anything"):
            sub.run_fleet(_parent(repo), [], env={}, max_depth=0)


class TestMoneyIsONEPool:
    def test_every_subagent_charges_the_ROOT_task_key(self, repo: Path) -> None:
        """The arithmetic that makes fleets dangerous. The per-task cap is keyed by task id, so
        eight children with eight ids would be eight full allowances (L21)."""
        meter = cost_mod.Meter(repo)
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo, meter=meter),
                [_chain(3)],
                env=_env(url),
                on_event=_Editing(fake),
            )
        assert out.spawned == 3
        root = meter.totals(cost_mod.SCOPE_TASK, "root")
        assert root.total_tokens == 6, "three children, one turn each, 1 in + 1 out per turn"
        for child_key in ("root/s1", "root/s1/s2", "root/s1/s2/s3"):
            assert meter.totals(cost_mod.SCOPE_TASK, child_key).total_tokens == 0, (
                f"{child_key} opened its own allowance — that is eight caps, not one"
            )

    def test_a_cap_the_fleet_shares_stops_the_later_children(self, repo: Path) -> None:
        meter = cost_mod.Meter(
            repo, budgets={cost_mod.SCOPE_TASK: cost_mod.Budget(max_total_tokens=3)}
        )
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo, meter=meter),
                [sub.SubagentSpec(name=f"n{i}", prompt="x") for i in range(3)],
                env=_env(url),
                on_event=_Editing(fake),
            )
        stopped = [s.run.stopped_because for s in out.walk() if s.run is not None]
        assert stopped[0] == "turn budget spent (1)", "the first child fits inside the cap"
        assert all(s.startswith("cost cap reached") for s in stopped[1:]), stopped
        assert all(s.run is not None and s.run.change.bundle_id for s in out.walk()), (
            "a child that ran out of money half-written is still proved and still shown"
        )


class TestCancellationReachesTheGrandchildren:
    def test_a_scope_cancelled_up_front_refuses_every_subagent(self, repo: Path) -> None:
        scope = CancelScope()
        scope.cancel()
        out = sub.run_fleet(_parent(repo), [_chain(3)], env={}, cancel=scope)
        assert out.spawned == 0
        assert {s.refused for s in out.walk()} == {sub.REFUSED_CANCELLED}
        assert out.stopped_because == sub.REFUSED_CANCELLED
        assert _worktrees(repo) == [], "nothing was staged, so nothing was left behind"

    def test_cancelling_mid_flight_kills_the_running_child_and_refuses_the_rest(
        self, repo: Path
    ) -> None:
        """The running child is REFUSED, not given a verdict. Its worker processes were killed
        mid-proof, so there is no bundle — and without a bundle there is nothing it may be said
        to have found (L1/L16). A fleet that reported the interrupted child as EQUIVALENT would
        be inventing the most dangerous possible answer out of an absence of evidence.
        """
        scope = CancelScope()
        fake = FakeAnthropic()
        editing = _Editing(fake)

        def cancel_after_the_first(kind: str, detail: str) -> None:
            editing(kind, detail)
            if kind == "subagent" and detail.startswith("root/n0"):
                scope.cancel()

        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo),
                [sub.SubagentSpec(name=f"n{i}", prompt="x") for i in range(3)],
                env=_env(url),
                on_event=cancel_after_the_first,
                cancel=scope,
            )
        assert out.spawned == 1, "one child was started; the other two never were"
        assert [s.refused for s in out.runs] == [sub.REFUSED_CANCELLED] * 3
        assert out.verdicts() == (), "no bundle, no verdict — for any of them"
        assert out.stopped_because == sub.REFUSED_CANCELLED


class TestLeastPrivilege:
    def test_a_child_may_not_widen_its_grants(self, repo: Path) -> None:
        """A delegation that can hand itself a capability the user never gave the parent is an
        escalation primitive with a friendly name."""
        out = sub.run_fleet(
            _parent(repo, grants=frozenset({"read_file"})),
            [sub.SubagentSpec(name="greedy", prompt="x", grants=frozenset({"run_command"}))],
            env={},
        )
        assert out.spawned == 0
        assert out.runs[0].refused == sub.REFUSED_GRANTS
        assert out.runs[0].run is None

    def test_a_child_may_narrow_them(self, repo: Path) -> None:
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _parent(repo, grants=frozenset({"read_file", "run_command"})),
                [sub.SubagentSpec(name="modest", prompt="x", grants=frozenset({"read_file"}))],
                env=_env(url),
                on_event=_Editing(fake),
            )
        assert out.spawned == 1 and out.runs[0].refused == ""


class TestAFleetThatCannotBeDescribedIsRefusedOutright:
    def test_two_siblings_with_one_name_would_share_a_worktree(self, repo: Path) -> None:
        with pytest.raises(sub.SubagentError, match="both named"):
            sub.run_fleet(
                _parent(repo),
                [
                    sub.SubagentSpec(name="same", prompt="a"),
                    sub.SubagentSpec(name="same", prompt="b"),
                ],
                env={},
            )

    @pytest.mark.parametrize("name", ["a/b", "..", ".", "", "  "])
    def test_a_name_that_would_forge_a_task_id_is_refused(self, repo: Path, name: str) -> None:
        with pytest.raises(sub.SubagentError):
            sub.run_fleet(_parent(repo), [sub.SubagentSpec(name=name, prompt="x")], env={})

    def test_a_result_that_is_neither_a_run_nor_a_refusal_cannot_be_constructed(self) -> None:
        """The forge test. Both states at once, or neither, would let a caller read "it ran and
        found nothing" off a subagent that never started."""
        with pytest.raises(sub.SubagentError, match="neither state"):
            sub.SubagentRun(name="x", task_id="root/x", depth=1)
        with pytest.raises(sub.SubagentError, match="neither state"):
            sub.SubagentRun(name="x", task_id="root/x", depth=1, run=None, refused="")
