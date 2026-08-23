"""P4 — subagents: delegated work with its own worktree, its own verdict, and no new budget.

A subagent is not a second agent. It is the SAME agent doing a narrower piece of the same task,
and everything that makes the parent's answer trustworthy has to survive the delegation:

* **Its own shadow worktree.** A child's task id is `parent/name`, which `shadow.create` slugs
  into a distinct worktree. Two subagents editing the same tree would make both verdicts
  meaningless — neither could say which change its evidence was about.
* **Its own verdict.** Every child runs the whole loop and ends on a `ProvenChange` from
  `run_prove`, exactly as a top-level task does. There is no aggregate verdict here and there is
  deliberately no code to compute one: "the fleet succeeded" is a claim no bundle backs, and L1
  says a claim without an artifact does not get made. `verdicts()` returns what each child
  actually found and leaves the reading to the caller.
* **No new budget.** Money is the failure mode that makes fleets dangerous, and it is not
  hypothetical arithmetic: the per-task cap is keyed by task id, so eight children with eight ids
  would be eight full allowances. Every child therefore charges the ROOT's key through
  `TaskSpec.cost_task_key`, and the fleet bounds how many children may exist at all. L21 is one
  pool, not one pool per delegation.
* **Cancellation that reaches the grandchildren.** The whole tree runs inside ONE `CancelScope`,
  which `runner._spawn` picks up through its context variable. Cancelling kills the worker
  processes of whatever is executing and refuses every subagent not yet started — with a reason,
  never by silently returning fewer results than were asked for.

**Least privilege is enforced, not documented.** A child may narrow its grants and may never
widen them. A delegation that could hand itself a capability the user never gave the parent is a
privilege-escalation primitive with a friendly name.

**Why this is a primitive and not a model tool.** F7 (de-slop) and F17 (fleet) need to run an
independently-proven subagent per atomic step; that is a caller deciding to delegate, not a model
deciding to. Letting the MODEL spawn subagents is a boundary-D change — a new tool in
`agent_tools.rs` with its own approval semantics — and it belongs with F17, where the fleet UI
that would supervise it also lives. ADR-0059 records that split rather than leaving it implied.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace

from tempest.agent.orchestrator import AgentError, AgentRun, TaskSpec, run_task
from tempest.execute.cancel import CancelScope, ProveCancelled, cancel_scope
from tempest.model import Verdict

#: How deep delegation may nest. A subagent that can delegate can recurse, and a recursion whose
#: only bound is the budget spends the whole budget discovering it has no bound.
DEFAULT_MAX_DEPTH = 4

#: How many subagents one fleet may run in total, across every level. P4's gate is eight.
DEFAULT_MAX_SUBAGENTS = 8

#: Refusal reasons. These are values rather than prose so a caller can branch on them, and every
#: one of them means "this subagent did NOT run" — never "it ran and found nothing".
REFUSED_DEPTH = "max depth reached"
REFUSED_COUNT = "max subagents reached"
REFUSED_CANCELLED = "cancelled"
REFUSED_GRANTS = "grants wider than the parent's"


class SubagentError(AgentError):
    """A fleet that cannot be run as described — a bad name, a duplicate, an impossible bound."""


@dataclass(frozen=True)
class SubagentSpec:
    """One delegated piece of work, and the pieces it delegates in turn.

    Only the fields a delegation may legitimately change are here. Everything else — repository,
    provider, model, input budget, seed, meter, timeout — is inherited from the parent, because a
    child that could re-point any of them would not be a subagent of that task any more.
    """

    name: str
    prompt: str
    children: tuple[SubagentSpec, ...] = ()
    #: A child may NARROW what it is allowed to do. `None` inherits the parent's grants; any
    #: explicit set must be a subset of them.
    grants: frozenset[str] | None = None
    max_turns: int | None = None
    max_repair_attempts: int | None = None


@dataclass(frozen=True)
class SubagentRun:
    """What one delegated piece produced — or the reason it produced nothing."""

    name: str
    task_id: str
    depth: int
    #: `None` exactly when `refused` is set. There is no third state: a subagent either ran to a
    #: verdict or is on the record as not having run, with a reason.
    run: AgentRun | None = None
    refused: str = ""
    children: tuple[SubagentRun, ...] = ()

    def __post_init__(self) -> None:
        if (self.run is None) == (not self.refused):
            raise SubagentError(
                f"subagent {self.name!r} is in neither state: a run without a refusal, or a "
                f"refusal without a run, is the only pair that can be reported honestly"
            )

    @property
    def verdict(self) -> Verdict | None:
        """This subagent's own verdict, or `None` if it never ran."""
        return None if self.run is None else self.run.change.verdict

    def walk(self) -> Iterator[SubagentRun]:
        """This subagent and every descendant, parents before children."""
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class FleetOutcome:
    """Every subagent of one parent task, and why the fleet stopped if it did.

    There is no `succeeded` field and no aggregate verdict. Eight independent proofs do not
    compose into a ninth claim, and inventing one would be exactly the "verified without a
    differential run" that L16 forbids.
    """

    runs: tuple[SubagentRun, ...] = ()
    #: How many subagents were STARTED. A child cancelled mid-proof was started and is counted
    #: here, and is still on the record as refused: it consumed work but produced no bundle, so
    #: there is nothing it may be said to have found.
    spawned: int = 0
    stopped_because: str = ""

    def walk(self) -> Iterator[SubagentRun]:
        for run in self.runs:
            yield from run.walk()

    def verdicts(self) -> tuple[Verdict, ...]:
        """Each subagent's own verdict, in tree order, skipping the ones that never ran."""
        return tuple(s.verdict for s in self.walk() if s.verdict is not None)

    @property
    def refusals(self) -> tuple[SubagentRun, ...]:
        return tuple(s for s in self.walk() if s.refused)


@dataclass
class _Fleet:
    """The mutable bookkeeping one `run_fleet` call needs; never crosses the public surface."""

    parent: TaskSpec
    env: dict[str, str]
    on_event: Callable[[str, str], None] | None
    max_depth: int
    max_subagents: int
    scope: CancelScope
    spawned: int = 0
    stopped: str = ""

    def emit(self, kind: str, detail: str) -> None:
        if self.on_event is not None:
            self.on_event(kind, detail)


def _validate(specs: Sequence[SubagentSpec], *, where: str) -> None:
    names: set[str] = set()
    for spec in specs:
        if not spec.name or not spec.name.strip():
            raise SubagentError(f"a subagent of {where} has no name; its worktree would be unnamed")
        if "/" in spec.name or spec.name in (".", ".."):
            raise SubagentError(
                f"subagent name {spec.name!r} would forge a task id path segment — names are "
                f"joined to the parent's id with '/' and must not contain one"
            )
        if spec.name in names:
            raise SubagentError(
                f"two subagents of {where} are both named {spec.name!r}; they would share a "
                f"shadow worktree, and neither verdict would be about a change it could name"
            )
        names.add(spec.name)


def _child_spec(fleet: _Fleet, parent: TaskSpec, spec: SubagentSpec, task_id: str) -> TaskSpec:
    """The parent's spec, narrowed. Everything not listed here is inherited deliberately."""
    return replace(
        parent,
        task_id=task_id,
        prompt=spec.prompt,
        grants=parent.grants if spec.grants is None else spec.grants,
        max_turns=parent.max_turns if spec.max_turns is None else spec.max_turns,
        max_repair_attempts=(
            parent.max_repair_attempts
            if spec.max_repair_attempts is None
            else spec.max_repair_attempts
        ),
        # The root's key, not this child's id: one task cap for the whole delegation (L21).
        cost_task_key=fleet.parent.cost_task_key or fleet.parent.task_id,
        # The FLEET's scope, always: a fleet cancel must abort the child that is mid-model-call
        # (C5 run control), not only the children queued behind it. Before this, propagation
        # reached spawned processes (the ContextVar registration) but a child blocked inside
        # `complete()` ran its call to the end.
        cancel=fleet.scope,
    )


def _refuse(spec: SubagentSpec, task_id: str, depth: int, reason: str) -> SubagentRun:
    """A subagent that did not run, with every descendant refused for the same reason.

    Refusing the subtree rather than dropping it is the point: a fleet that returns eight results
    when nine were asked for has lost one silently, and a caller counting results would read the
    loss as success.
    """
    return SubagentRun(
        name=spec.name,
        task_id=task_id,
        depth=depth,
        refused=reason,
        children=tuple(
            _refuse(child, f"{task_id}/{child.name}", depth + 1, reason) for child in spec.children
        ),
    )


def _run_one(fleet: _Fleet, parent: TaskSpec, spec: SubagentSpec, depth: int) -> SubagentRun:
    # Unique by construction, so there is no second uniqueness check here to go stale: a task id
    # is its parent's id joined to a name that `_validate` has already proved unique among its
    # siblings and free of '/'. Distinct paths through the tree therefore cannot spell the same
    # string, and a guard that can never fire is dead code, not defence.
    task_id = f"{parent.task_id}/{spec.name}"
    if depth > fleet.max_depth:
        return _refuse(spec, task_id, depth, REFUSED_DEPTH)
    if fleet.scope.cancelled:
        fleet.stopped = fleet.stopped or REFUSED_CANCELLED
        return _refuse(spec, task_id, depth, REFUSED_CANCELLED)
    if fleet.spawned >= fleet.max_subagents:
        fleet.stopped = fleet.stopped or REFUSED_COUNT
        return _refuse(spec, task_id, depth, REFUSED_COUNT)
    if spec.grants is not None and not spec.grants <= parent.grants:
        # Least privilege, enforced. A delegation that can widen its own grants is an escalation
        # primitive, and the fact that the caller wrote it does not make it the user's decision.
        return _refuse(spec, task_id, depth, REFUSED_GRANTS)

    child = _child_spec(fleet, parent, spec, task_id)
    fleet.spawned += 1
    fleet.emit("subagent", f"{task_id} (depth {depth})")
    try:
        run = run_task(child, env=fleet.env, on_event=fleet.on_event)
    except ProveCancelled:
        # The scope killed this child's workers mid-proof. That is a refusal, not a verdict:
        # there is no bundle, so there is nothing this run may be said to have found.
        fleet.stopped = fleet.stopped or REFUSED_CANCELLED
        return _refuse(spec, task_id, depth, REFUSED_CANCELLED)

    return SubagentRun(
        name=spec.name,
        task_id=task_id,
        depth=depth,
        run=run,
        children=_run_level(fleet, child, spec.children, depth + 1),
    )


def _run_level(
    fleet: _Fleet, parent: TaskSpec, specs: Sequence[SubagentSpec], depth: int
) -> tuple[SubagentRun, ...]:
    _validate(specs, where=parent.task_id)
    return tuple(_run_one(fleet, parent, spec, depth) for spec in specs)


def run_fleet(
    parent: TaskSpec,
    children: Sequence[SubagentSpec],
    *,
    env: dict[str, str],
    on_event: Callable[[str, str], None] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_subagents: int = DEFAULT_MAX_SUBAGENTS,
    cancel: CancelScope | None = None,
) -> FleetOutcome:
    """Run a tree of subagents under `parent`, each to its own verdict.

    Depth-first, one at a time. Concurrency is not an oversight: two subagents proving at once
    contend for the same cores, and a verdict is a measurement — `resume_test` already refuses to
    make wall-clock claims under load for exactly this reason. F17 is where a scheduler that
    understands machine capacity belongs.

    Raises `SubagentError` for a fleet that cannot be described honestly (a duplicate name, a
    name that would forge a path). Everything that is merely *not allowed* — too deep, too many,
    cancelled, over-granted — comes back as a refusal on the record instead.
    """
    if max_subagents < 0 or max_depth < 1:
        raise SubagentError(
            f"a fleet bounded at depth {max_depth} / {max_subagents} subagents cannot run anything"
        )
    scope = cancel if cancel is not None else CancelScope()
    fleet = _Fleet(
        parent=parent,
        env=env,
        on_event=on_event,
        max_depth=max_depth,
        max_subagents=max_subagents,
        scope=scope,
    )
    with cancel_scope(scope):
        runs = _run_level(fleet, parent, children, 1)
    return FleetOutcome(runs=runs, spawned=fleet.spawned, stopped_because=fleet.stopped)
