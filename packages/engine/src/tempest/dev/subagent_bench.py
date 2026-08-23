"""P4's gate — eight nested subagents, eight verdicts, one budget, one cancellation.

    python -m tempest.dev.subagent_bench --depth 8

The gate P4 states is one sentence: *8 nested subagents with independent verdicts, correct budget
accounting (L21), and full cancellation propagation.* Each clause fails differently and each one
is checked against evidence rather than against the absence of an exception:

* **Independent verdicts** are checked by counting **shadow worktrees and bundle ids**, not runs.
  Eight children that happened to share a worktree would still return eight `AgentRun` objects,
  and every one of those verdicts would be about somebody else's change. So each subagent here
  makes a DIFFERENT edit, and the gate requires eight distinct bundles — evidence that can tell
  them apart — rather than eight objects that merely exist.
* **Correct budget accounting** is checked by reading the ledger **by key**. The per-task cap is
  keyed by task id, so eight children with eight ids would quietly be eight full allowances; the
  gate asserts the root's key carries the whole spend and every child key carries nothing.
* **Full cancellation propagation** is checked by cancelling a second fleet mid-flight and
  requiring that the running child comes back REFUSED — with no bundle and therefore no verdict —
  and that every child after it is refused too, on the record rather than by absence.

Real repositories, real shadow worktrees, real differential proofs. The only faked thing is the
model, which is the loopback Messages peer every agent gate uses (ADR-0024, L4).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from tempest.agent import subagents as sub
from tempest.agent.events import AgentEvent, SubagentStarted
from tempest.agent.orchestrator import TaskSpec
from tempest.dev._fake_peer import FakeAnthropic, fake_anthropic_server
from tempest.dev._first_party import mark_first_party
from tempest.execute.cancel import CancelScope
from tempest.inference import cost as cost_mod
from tempest.inference.providers import get
from tempest.model import Verdict

_BASE = "def total(xs):\n    return sum(xs)\n"

#: Enough budget that a real behaviour change is actually found. Four inputs do NOT distinguish
#: `sum(xs)` from `sum(xs) + 3` — the engine says EQUIVALENT_UNDER_BUDGET, correctly, and a gate
#: written at that budget would be measuring the sampler instead of the delegation (trap 57).
_MAX_INPUTS = 8


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-subagent",
            "GIT_AUTHOR_EMAIL": "subagent@tempest",
            "GIT_COMMITTER_NAME": "tempest-subagent",
            "GIT_COMMITTER_EMAIL": "subagent@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text(_BASE, encoding="utf-8")
    mark_first_party(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def _env(url: str) -> dict[str, str]:
    provider = get("anthropic")
    return {provider.env_var: "sk-subagent-not-a-real-key", provider.base_url_env(): url}


def _spec(repo: Path, meter: cost_mod.Meter | None = None) -> TaskSpec:
    return TaskSpec(
        repo=repo,
        task_id="root",
        prompt="the parent task",
        provider="anthropic",
        max_inputs=_MAX_INPUTS,
        max_turns=1,
        max_repair_attempts=0,
        meter=meter,
    )


def _chain(depth: int) -> sub.SubagentSpec:
    """`s1 → s2 → … → sN`: nested, not a flat list. P4 says NESTED, and a flat fan-out would
    never exercise the depth bound, the id nesting, or a grandchild's budget."""
    spec = sub.SubagentSpec(name=f"s{depth}", prompt=f"level {depth}")
    for level in range(depth - 1, 0, -1):
        spec = sub.SubagentSpec(name=f"s{level}", prompt=f"level {level}", children=(spec,))
    return spec


class _DistinctEdits:
    """A model that writes a different body for every subagent it is asked about.

    Identical edits would produce identical git commits — same content, same parent, same
    message, same second — and therefore identical bundle ids. The gate would then be unable to
    tell eight isolated proofs from one proof counted eight times.
    """

    def __init__(self, fake: FakeAnthropic) -> None:
        self.fake = fake
        self.seen = 0
        self._arm()

    def _arm(self) -> None:
        # 1-based: `sum(xs) + 0` preserves behaviour, and a fixture meant to produce N
        # divergences would quietly produce N-1 and an EQUIVALENT.
        body = f"def total(xs):\n    return sum(xs) + {self.seen + 1}\n"
        self.fake.tool_uses = [
            {"name": "write_file", "input": {"path": "app.py", "contents": body}}
        ]

    def __call__(self, event: AgentEvent) -> None:
        if isinstance(event, SubagentStarted):
            self.seen += 1
            self._arm()


def _worktrees(repo: Path) -> list[str]:
    root = repo / ".tempest" / "agent" / "worktrees"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def _nested(depth: int) -> list[Check]:
    """The headline: `depth` nested subagents, each with its own worktree, bundle and verdict."""
    checks: list[Check] = []
    with TemporaryDirectory(prefix="tempest-subagents-") as tmp:
        repo = _repo(Path(tmp))
        meter = cost_mod.Meter(repo)
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _spec(repo, meter),
                [_chain(depth)],
                env=_env(url),
                on_event=_DistinctEdits(fake),
                max_depth=depth,
                max_subagents=depth,
            )

        ran = [s for s in out.walk() if s.run is not None]
        checks.append(
            Check(
                f"{depth} nested subagents all ran",
                out.spawned == depth and len(ran) == depth,
                f"spawned {out.spawned}, {len(ran)} produced a run",
            )
        )
        checks.append(
            Check(
                "nothing was refused, so nothing was silently dropped",
                out.refusals == (),
                f"{len(out.refusals)} refusal(s)",
            )
        )
        checks.append(
            Check(
                "each subagent got its OWN shadow worktree",
                len(_worktrees(repo)) == depth,
                f"{len(_worktrees(repo))} worktree(s) for {depth} subagent(s)",
            )
        )
        bundles = {s.run.change.bundle_id for s in ran if s.run is not None}
        checks.append(
            Check(
                "each verdict rests on its OWN bundle",
                len(bundles) == depth,
                f"{len(bundles)} distinct bundle id(s)",
            )
        )
        verdicts = out.verdicts()
        checks.append(
            Check(
                "every verdict came from the ENGINE and found the real change",
                len(verdicts) == depth and set(verdicts) == {Verdict.DIVERGENT},
                f"{sorted({v.value for v in verdicts})}",
            )
        )
        checks.append(
            Check(
                "the nesting is real, not a flat fan-out",
                [s.depth for s in out.walk()] == list(range(1, depth + 1)),
                f"depths {[s.depth for s in out.walk()]}",
            )
        )

        # L21: one pool. The per-task cap is keyed by task id, so N children with N ids would be
        # N full allowances — the arithmetic that makes a fleet dangerous.
        root_spend = meter.totals(cost_mod.SCOPE_TASK, "root").total_tokens
        own_keys = [s.task_id for s in ran]
        leaked = {k: meter.totals(cost_mod.SCOPE_TASK, k).total_tokens for k in own_keys}
        checks.append(
            Check(
                "every subagent charged the ROOT's task key (L21)",
                root_spend == 2 * depth and not any(leaked.values()),
                f"root={root_spend} tokens, per-child keys={sorted(set(leaked.values()))}",
            )
        )
    return checks


def _cancellation() -> list[Check]:
    """Cancellation reaches the child that is RUNNING, not merely the ones queued behind it."""
    checks: list[Check] = []
    with TemporaryDirectory(prefix="tempest-subagents-cancel-") as tmp:
        repo = _repo(Path(tmp))
        scope = CancelScope()
        fake = FakeAnthropic()
        edits = _DistinctEdits(fake)

        def cancel_on_the_first(event: AgentEvent) -> None:
            edits(event)
            if isinstance(event, SubagentStarted) and event.task_id.startswith("root/n0"):
                scope.cancel()

        with fake_anthropic_server(fake) as url:
            out = sub.run_fleet(
                _spec(repo),
                [sub.SubagentSpec(name=f"n{i}", prompt="x") for i in range(3)],
                env=_env(url),
                on_event=cancel_on_the_first,
                cancel=scope,
            )
        checks.append(
            Check(
                "a cancelled fleet produces NO verdicts",
                out.verdicts() == (),
                "no bundle, no verdict — including for the child that was mid-proof",
            )
        )
        checks.append(
            Check(
                "every subagent is on the record as refused, not missing",
                len(out.runs) == 3 and all(s.refused == sub.REFUSED_CANCELLED for s in out.runs),
                f"{[s.refused for s in out.runs]}",
            )
        )
        checks.append(
            Check(
                "the fleet says why it stopped",
                out.stopped_because == sub.REFUSED_CANCELLED,
                out.stopped_because or "(nothing)",
            )
        )

    with TemporaryDirectory(prefix="tempest-subagents-precancel-") as tmp:
        repo = _repo(Path(tmp))
        scope = CancelScope()
        scope.cancel()
        out = sub.run_fleet(_spec(repo), [_chain(3)], env={}, cancel=scope)
        checks.append(
            Check(
                "a fleet cancelled before it starts stages nothing at all",
                out.spawned == 0 and _worktrees(repo) == [],
                f"spawned={out.spawned}, worktrees={_worktrees(repo)}",
            )
        )
        checks.append(
            Check(
                "cancellation reaches the GRANDCHILDREN, not just the top level",
                {s.refused for s in out.walk()} == {sub.REFUSED_CANCELLED}
                and len(list(out.walk())) == 3,
                f"{[(s.task_id, s.refused) for s in out.walk()]}",
            )
        )
    return checks


def _least_privilege() -> list[Check]:
    with TemporaryDirectory(prefix="tempest-subagents-grants-") as tmp:
        repo = _repo(Path(tmp))
        parent = TaskSpec(
            repo=repo,
            task_id="root",
            prompt="p",
            provider="anthropic",
            grants=frozenset({"read_file"}),
            max_inputs=_MAX_INPUTS,
            max_turns=1,
        )
        out = sub.run_fleet(
            parent,
            [sub.SubagentSpec(name="greedy", prompt="x", grants=frozenset({"run_command"}))],
            env={},
        )
        return [
            Check(
                "a subagent may not grant itself what the parent was never given",
                out.spawned == 0 and out.runs[0].refused == sub.REFUSED_GRANTS,
                out.runs[0].refused or "it ran",
            )
        ]


def run(depth: int) -> list[Check]:
    return _nested(depth) + _cancellation() + _least_privilege()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=8, help="how deep to nest (P4's gate is 8)")
    args = parser.parse_args(argv)
    if args.depth < 1:
        print("subagent_bench: --depth must be at least 1", file=sys.stderr)
        return 2

    checks = run(args.depth)
    print(f"{'invariant':<66} status")
    for check in checks:
        print(f"{check.name:<66} {'PASS' if check.ok else 'FAIL'}  {check.detail[:60]}")
    failed = [c for c in checks if not c.ok]
    print("")
    print(f"subagent_bench: {len(checks) - len(failed)}/{len(checks)} invariants held")
    print("")
    print(
        "NOT proved here: a MODEL choosing to delegate. Subagents are an execution primitive for\n"
        "F7 and F17; exposing them as a tool the model can call is a boundary-D change with its\n"
        "own approval semantics, and it belongs with the fleet UI that would supervise it."
    )
    for check in failed:
        print(f"SUBAGENT-BENCH {check.name}: {check.detail}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
