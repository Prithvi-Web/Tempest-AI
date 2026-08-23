"""The agent turn loop (Phase 21, F1) — a coding agent that cannot claim done.

    plan → edit (shadow, L19) → engine.prove(baseline, shadow) → verdict

**The one structural idea.** A turn does not end when the model says it is finished. It ends when
the ENGINE returns a verdict about what the model actually did. `run_task` is the only function
that produces a `ProvenChange`, it always calls `run_prove`, and `ProvenChange` cannot be
constructed without a bundle id — so "an agent-authored change reaching the user marked verified
without an actual differential run" (L16) is not a bug to avoid, it is a state with no
constructor. `test_agent_orchestrator.py` includes the adversarial forge test L16 asks for.

**What the model may and may not do.**
* It may read, search, write into the shadow, and run commands there — the six tools of
  boundary D, dispatched and bounded by `tools.Dispatcher`.
* It may NOT call `prove`. The tool is declared so the manifest stays whole, and refuses to be a
  step: a model that could invoke proving could also decline to, and L16 would be a request.
* It may not write a verdict, a confidence, or a risk (L17). Its text is narration, carried in
  `narration`, never in a field the UI reads as evidence.

**Everything is bounded (L15.4).** Turns, tool calls per turn, bytes, wall-clock, and — when a
`Meter` is supplied — money (L21). An exhausted budget ends the turn and still proves: a change
that ran out of budget half-written is exactly the change a user most needs a verdict about.

That last clause was a FALSE CLAIM for the whole of Phase 21: the sentence was written, and
`TaskSpec` had no way to supply a meter, so money was the one budget nothing enforced. A doc
comment is a claim and this project tests its claims (trap 45). `TaskSpec.meter` is real now,
every completion is charged against it before the next turn begins, and a breached cap ends the
loop the same way a model error does — the staged work is still proved and still shown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tempest.agent import contracts as contracts_mod
from tempest.agent import repair as repair_mod
from tempest.agent import rules as rules_mod
from tempest.agent import shadow as shadow_mod
from tempest.agent import turnlog as turnlog_mod
from tempest.agent.tools import (
    ASK_USER,
    ApprovalDecision,
    ApprovalRequest,
    Budgets,
    Dispatcher,
    ToolResult,
    model_facing_catalog,
)
from tempest.bundle.bundle import run_verdict
from tempest.config import TempestConfig, TempestConfigError, is_ignored
from tempest.envrepro.deps import attach_deps, fetch_enabled
from tempest.envrepro.worktree import materialize
from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.execute.runner import module_for_path, module_loads
from tempest.inference import cost as cost_mod
from tempest.inference.client import (
    DEFAULT_TIMEOUT_S,
    Cancelled,
    Message,
    ModelError,
    ToolCall,
    complete,
)
from tempest.model import Verdict
from tempest.prove import ProveConfig, run_prove, select_sandbox_for_repo

#: What the model is told about its situation. Deliberately short: the tool descriptions are the
#: contract (boundary D) and repeating them here would be a second, drifting copy.
SYSTEM_PROMPT = """You are Tempest's coding agent.

You edit code in a shadow worktree. Your edits never touch the user's working tree, and every
change you make is proved by a differential execution engine before the user sees it.

Rules that are enforced by the host, not by you:
- You cannot run the proof. It runs when your turn ends, on whatever you have written, and its
  verdict is the answer. Asking to skip it is refused.
- You never state whether a change is correct, safe, or verified. The engine decides that from
  execution. Describe what you did and why; leave the judgement alone.
- Every tool call is bounded. A refusal explains itself; read it and adapt.

Work in small steps. Read before you write. When you have finished editing, stop calling tools
and say what you changed."""


class AgentError(Exception):
    """The orchestrator could not run the task. Never used for a model's bad answer."""


class TaskAlreadyFinished(AgentError):
    """This task ran to completion already; its verdict is on disk (P2).

    Raised rather than silently re-running. A second run would build a second shadow worktree for
    a task that has one, spend model turns that were already paid for, and — because it would
    take a NEW baseline from a tree the first run may since have changed — could answer a
    different question and present it under the same task id. The recorded verdict and bundle id
    travel on the exception so a caller that just wants the answer has it without a second call.
    """

    def __init__(self, task_id: str, verdict: str, bundle_id: str) -> None:
        super().__init__(
            f"task {task_id!r} already finished with verdict {verdict} (bundle {bundle_id}) — "
            f"read the recorded run rather than running it again, or use a new task id"
        )
        self.task_id = task_id
        self.verdict = verdict
        self.bundle_id = bundle_id


@dataclass(frozen=True)
class ProvenChange:
    """A change the user may be shown. **Cannot exist without a proof** (L16).

    Every field here is an engine output. There is deliberately no field a model can write into
    and no constructor that omits `bundle_id`: the forge test in the suite tries both.
    """

    verdict: Verdict
    bundle_id: str
    bundle_dir: Path
    changed_files: tuple[str, ...]
    divergence_count: int
    baseline: str
    head: str

    def __post_init__(self) -> None:
        if not self.bundle_id:
            raise AgentError(
                "a ProvenChange without a bundle id is a verified claim without evidence (L16)"
            )
        if not isinstance(self.verdict, Verdict):
            raise AgentError(f"verdict must be an engine Verdict, got {self.verdict!r} (L17)")


@dataclass(frozen=True)
class ClassifiedDivergence:
    """One divergence, placed against the user's stated intent (F2).

    The classification is a mechanical function of the contract and the symbol's name — no model
    is consulted, which is what keeps a model from ever labelling its own change expected (L17).
    With no contract on file every divergence is UNCLASSIFIED, the honest description of a run
    nobody stated an intent for.
    """

    qualname: str
    classification: str
    detail: str


@dataclass(frozen=True)
class ToolCallRecord:
    """One dispatched call, kept so the loop is inspectable rather than a black box (F3)."""

    name: str
    arguments: dict[str, Any]
    ok: bool
    detail: str


@dataclass(frozen=True)
class AgentRun:
    """Everything one task produced. `change` is the only part that carries a claim."""

    change: ProvenChange
    #: Model prose, kept apart from evidence on purpose (L17).
    narration: tuple[str, ...]
    calls: tuple[ToolCallRecord, ...]
    turns_used: int
    #: Every divergence against the contract, if there is one (F2).
    divergences: tuple[ClassifiedDivergence, ...] = ()
    #: The repair loop's record, when one ran (F3). `None` means it never engaged — no contract,
    #: no budget, or nothing to repair. Never hide the loop: when it ran, every attempt is here.
    repair: repair_mod.RepairOutcome | None = None
    #: Set when the loop ended for a reason other than the model finishing.
    stopped_because: str = ""

    @property
    def unintended(self) -> tuple[ClassifiedDivergence, ...]:
        """Divergences the user said must not happen — F3's repair signal."""
        return tuple(d for d in self.divergences if d.classification == contracts_mod.UNINTENDED)

    @property
    def unclassified(self) -> tuple[ClassifiedDivergence, ...]:
        """Divergences nobody predicted. F2 says these are shown MOST prominently, because an
        unpredicted change is worse news than a forbidden one: somebody at least thought about
        the forbidden one."""
        return tuple(d for d in self.divergences if d.classification == contracts_mod.UNCLASSIFIED)


@dataclass(frozen=True)
class TaskSpec:
    repo: Path
    task_id: str
    prompt: str
    provider: str
    model: str | None = None
    max_turns: int = 8
    budgets: Budgets = field(default_factory=Budgets)
    grants: frozenset[str] = frozenset()
    max_inputs: int = 50
    seed: int = 0
    #: The cost ledger and its caps (L21, P11). `None` means money is not bounded for this task
    #: — an honest state for a local model, and a deliberate choice everywhere else. When it is
    #: supplied, every completion is charged BEFORE the next turn is asked for, so a cap can
    #: never be breached by a turn that was already in flight.
    meter: cost_mod.Meter | None = None
    #: Which ledger scopes this task's spending belongs to. `task` is the per-task cap; the
    #: session and day scopes are how "per session" and "per day" in L21 are enforced.
    cost_session: str = "default"
    #: Which key the TASK-scope cap is counted under. `None` means this task's own id, which is
    #: right for every task a user starts. A SUBAGENT sets it to its root's id (P4): a delegated
    #: run is part of the work the user asked for, not a new allowance, and eight children each
    #: charging their own task key would turn one per-task cap into nine (L21).
    cost_task_key: str | None = None
    #: The wall-clock bound on ONE model call (L15.4). Explicit rather than inherited: a turn
    #: loop whose only time bound is a library default is bounded by something nobody chose, and
    #: `resume_test --sleep-mid-stream` needs to be able to choose it.
    model_timeout_s: float = DEFAULT_TIMEOUT_S
    #: F3. Attempts are only spent when there IS a contract — with no stated intent there is
    #: nothing to repair against, and an agent guessing at what the user wanted is precisely what
    #: F2 exists to prevent. Set to 0 to prove once and stop.
    max_repair_attempts: int = repair_mod.DEFAULT_MAX_ATTEMPTS
    #: C5 run control. One scope threads the whole task: the turn loop polls it, the in-flight
    #: model call aborts on it (the read is bounded — trap 58), and the prove observes it at
    #: its checkpoints via `ProveConfig.cancel`. Cancellation UNWINDS as `ProveCancelled` and
    #: never mints a verdict; the turnlog's durable record is how the task resumes later. A
    #: model OUTAGE still soft-breaks and proves (L23) — a cancel is the user saying stop,
    #: which is a different fact from the model going away.
    cancel: CancelScope | None = None
    #: An AGENT's tool selection (C5, LC15). `None` means the full manifest. The subset narrows
    #: BOTH sides of boundary D — the catalog the model is shown and the dispatcher that
    #: answers it — and a name outside the manifest is a loud error at task start.
    tools_allowed: frozenset[str] | None = None
    #: C5 HITL (LC18). When present, an approval-gated call PARKS the turn on this callable —
    #: durable first (the PENDING_APPROVAL row lands before the human is asked) — and the
    #: decision is applied exactly as scoped. `None` keeps the plain refusal. The callable
    #: may raise `ProveCancelled` to unwind a park the user abandoned; anything it blocks on
    #: is the SURFACE's budget to bound.
    approver: Callable[[ApprovalRequest], ApprovalDecision] | None = None
    #: C5 steering (LC16). Polled at the TOP of each turn; every returned text becomes a
    #: user message the model sees before it is asked again, and the drain must CONSUME
    #: (a source that keeps returning the same steer re-steers every turn). `None` means
    #: this surface has no steering.
    steer_source: Callable[[], tuple[str, ...]] | None = None


@dataclass(frozen=True)
class _Staging:
    """The shadow this run works in, and whether it is the one the log describes."""

    shadow: shadow_mod.Shadow
    #: False when the recorded worktree was gone and a new one had to be built. The recorded
    #: conversation then describes edits that no longer exist anywhere, so replaying it instead
    #: of re-running it would prove an empty change while reporting a transcript full of work.
    continues_the_record: bool


def _shadow_for(spec: TaskSpec, plan: turnlog_mod.ResumePlan) -> _Staging:
    """The shadow this run works in — the existing one where there is one, a fresh one otherwise.

    A resumed task must NOT get a new baseline. The baseline is a claim about what the agent
    started from; re-deriving it from the user's tree after a restart would silently re-point the
    proof at a different starting state, hiding the agent's own edits and attributing the user's
    later ones to it.

    **A shadow with no history is an ORPHAN, and it is adopted.** A process killed between
    creating the worktree and writing its first checkpoint leaves exactly that, and the first
    version of this function then wedged the task id forever: the log said "fresh", `create` said
    "already exists", and every later attempt with that id died the same way. There is nothing to
    resume in an orphan — no turns were recorded — so the run starts over inside it, which is the
    honest reading of "the worktree exists and nothing is known about it".

    A log that says "resuming" while the worktree is gone is the other real state — someone
    deleted `.tempest/`, or the repository was re-cloned — and the answer is a fresh shadow at the
    RECORDED baseline, flagged so the caller knows the transcript no longer describes the tree.
    """
    existing = shadow_mod.attach(spec.repo, spec.task_id)
    if existing is not None and plan.consulted_the_log:
        return _Staging(shadow=existing, continues_the_record=plan.resuming)
    rebuilt = shadow_mod.create(spec.repo, spec.task_id, baseline=plan.baseline or None)
    return _Staging(shadow=rebuilt, continues_the_record=not plan.resuming)


def _repair_baseline(
    log: turnlog_mod.TurnLog, task_id: str
) -> tuple[dict[str, Verdict] | None, str | None]:
    """The proven set and contract bytes from before the FIRST repair attempt, if recorded.

    `(None, None)` means the loop has never engaged for this task, so the caller computes them.
    Restoring rather than recomputing is what stops a restart adopting a killed attempt's edits
    as the state everything is judged against.
    """
    for entry in log.history(task_id):
        if entry.stage == turnlog_mod.REPAIR_ATTEMPT and entry.payload.get("phase") == "baseline":
            proven = entry.payload.get("proven") or {}
            return (
                {str(name): Verdict(str(value)) for name, value in proven.items()},
                str(entry.payload.get("contract", "")),
            )
    return None, None


def _recorded_answer(log: turnlog_mod.TurnLog, task_id: str) -> tuple[str, str]:
    """The verdict and bundle id from the FINISHED row, for the refusal message."""
    last = log.last(task_id)
    payload = last.payload if last is not None else {}
    return str(payload.get("verdict", "")), str(payload.get("bundle_id", ""))


def _dump_history(history: list[Message]) -> list[dict[str, Any]]:
    """The conversation as plain JSON. Durable means re-readable by a process that shares no
    memory with this one, so nothing here is a Python object."""
    return [
        {
            "role": m.role,
            "content": m.content,
            "tool_result_for": m.tool_result_for,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
            ],
        }
        for m in history
    ]


def _load_history(rows: Any) -> list[Message]:
    return [
        Message(
            role=str(row["role"]),
            content=str(row["content"]),
            tool_result_for=row["tool_result_for"],
            tool_calls=tuple(
                ToolCall(id=str(c["id"]), name=str(c["name"]), arguments=dict(c["arguments"]))
                for c in row.get("tool_calls", ())
            ),
        )
        for row in rows
    ]


def _dump_calls(calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    return [
        {"name": c.name, "arguments": c.arguments, "ok": c.ok, "detail": c.detail} for c in calls
    ]


def _load_calls(rows: Any) -> list[ToolCallRecord]:
    return [
        ToolCallRecord(
            name=str(row["name"]),
            arguments=dict(row["arguments"]),
            ok=bool(row["ok"]),
            detail=str(row["detail"]),
        )
        for row in rows
    ]


def _replay_turns(
    log: turnlog_mod.TurnLog,
    task_id: str,
    history: list[Message],
    narration: list[str],
    calls: list[ToolCallRecord],
) -> tuple[str, int]:
    """Rehydrate the most complete recorded conversation, in place.

    **The LAST transcript, not the first.** A repair attempt continues the same conversation and
    records it again, so the newest row is the one that describes the tree as it now stands.
    Reading the first would replay a conversation that stops before the repair the shadow already
    contains — a transcript and a worktree telling the model two different stories.

    The lists arrive holding the fresh prompt; the recorded history REPLACES it, because the
    recorded history starts with that same prompt and continues into everything that followed.
    A log row that predates this recording — or one written by a version that stored only the
    counters — leaves the prompt alone and says how many turns it is standing in for, which is
    a smaller answer than the full transcript and an honest one.
    """
    for entry in reversed(log.history(task_id)):
        if "history" not in entry.payload and entry.stage != turnlog_mod.TURNS_DONE:
            continue
        recorded = entry.payload.get("history")
        if recorded:
            history[:] = _load_history(recorded)
        narration.extend(str(n) for n in entry.payload.get("narration", ()))
        calls.extend(_load_calls(entry.payload.get("calls", ())))
        return str(entry.payload.get("stopped", "")), int(entry.payload.get("turns", 0))
    # pragma-justification: the plan only says "do not redo the turns" when it has SEEN a
    # TURNS_DONE row, so the loop above always finds one. The line is the honest answer if a
    # future caller ever asks without that guarantee.
    return "", 0  # pragma: no cover — no TURNS_DONE row; unreachable behind plan.redo_turns


def _today() -> str:
    """The ledger's day scope. UTC, because a cap that resets at a different hour depending on
    where the laptop is would be a different cap."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _summarise(result: ToolResult) -> str:
    """What goes back to the model. Truncation is stated so a cut answer is never read as whole."""
    body = result.content
    if result.truncated:
        body += "\n[truncated by the host's budget]"
    return body


def _converse(
    spec: TaskSpec,
    history: list[Message],
    narration: list[str],
    calls: list[ToolCallRecord],
    dispatcher: Dispatcher,
    catalog: Any,
    env: dict[str, str],
    emit: Callable[[str, str], None],
    log: turnlog_mod.TurnLog,
) -> tuple[str, int]:
    """Run model turns until it stops asking for tools, errors, or spends the turn budget.

    Returns (why it stopped, turns used). Extracted from `run_task` so the repair loop can run it
    again on the SAME history and the SAME dispatcher — the call budget therefore spans the whole
    task rather than resetting per attempt, which is the only reading of "bounded" that bounds
    anything (L15.4).
    """
    stopped = ""
    turns = 0
    for turn in range(spec.max_turns):
        turns = turn + 1
        if spec.cancel is not None:
            spec.cancel.raise_if_cancelled()
        if spec.steer_source is not None:
            # Queued follow-ups land HERE, before the model is asked again (LC16): a steer
            # is a user message the model must see, never a whisper the surface interprets.
            for steer in spec.steer_source():
                history.append(Message(role="user", content=steer))
                emit("steer", steer)
        try:
            answer = complete(
                spec.provider,
                history,
                env=env,
                model=spec.model,
                system=SYSTEM_PROMPT,
                tools=catalog,
                timeout=spec.model_timeout_s,
                cancel=spec.cancel.event if spec.cancel is not None else None,
            )
        except Cancelled as exc:
            # Ordered above ModelError on purpose (Cancelled IS a ModelError): a cancel must
            # UNWIND, never soft-break into a proved partial the way an outage deliberately
            # does — the user said stop, and "stop" includes the prove.
            raise ProveCancelled("task cancelled during the model call") from exc
        except ModelError as exc:
            # A model failure ends the LOOP, never the task: whatever is already staged still
            # gets proved and shown with its real verdict (L23 — degrade explicitly).
            stopped = f"model unavailable: {exc}"
            emit("model_error", str(exc))
            break

        if spec.meter is not None:
            try:
                spend = spec.meter.spend(
                    provider=answer.provider,
                    model=answer.model,
                    input_tokens=answer.usage.input_tokens,
                    output_tokens=answer.usage.output_tokens,
                    task=spec.cost_task_key or spec.task_id,
                    session=spec.cost_session,
                    day=_today(),
                )
            except cost_mod.CostError as exc:
                # The turn that has already happened is recorded by the ledger before this
                # raises, so the cap is never breached by more than the call that discovered it.
                # The loop ends here and the shadow is still proved: a change that ran out of
                # money half-written is exactly the change a user most needs a verdict about.
                stopped = f"cost cap reached: {exc}"
                emit("cost", str(exc))
                break
            emit("cost", f"{spend.total_tokens} tokens this turn")

        if answer.text:
            narration.append(answer.text)
            emit("narration", answer.text)

        if not answer.tool_calls:
            stopped = stopped or "the model finished"
            break

        history.append(Message(role="assistant", content=answer.text, tool_calls=answer.tool_calls))
        for call in answer.tool_calls:
            if spec.cancel is not None:
                # Between tool calls too: a cancel that lands during a long command must not
                # wait for the whole batch the model asked for.
                spec.cancel.raise_if_cancelled()
            result = _dispatch_with_approval(spec, dispatcher, log, emit, call)
            calls.append(
                ToolCallRecord(
                    name=call.name,
                    arguments=dict(call.arguments),
                    ok=result.ok,
                    detail=result.content[:2000],
                )
            )
            emit("tool", f"{call.name}: {'ok' if result.ok else 'refused'}")
            history.append(
                Message(role="user", content=_summarise(result), tool_result_for=call.id)
            )
    else:
        # The `for` completed without breaking: the model never stopped asking for tools.
        stopped = f"turn budget spent ({spec.max_turns})"
    return stopped, turns


def _dispatch_with_approval(
    spec: TaskSpec,
    dispatcher: Dispatcher,
    log: turnlog_mod.TurnLog,
    emit: Callable[[str, str], None],
    call: ToolCall,
) -> ToolResult:
    """One tool call, with the C5 HITL park in front of the approval gate (LC18).

    Durable FIRST: the PENDING_APPROVAL row lands before the human is asked, so a kill
    mid-park finds the question in the log rather than a mystery. The decision is applied
    exactly as scoped — `once` grants one dispatch, `session` grants the rest of the task,
    and an always-prompt tool is re-asked regardless. `ask_user` rides the same machinery
    with an ANSWER instead of a grant. With no approver attached, the plain refusal stands
    unchanged — never a silent auto-grant.
    """
    if spec.approver is None or not dispatcher.approval_needed(call.name):
        return dispatcher.call(call.name, call.arguments)
    kind = "ask_user_question" if call.name == ASK_USER else "tool_approval"
    log.checkpoint(
        spec.task_id,
        turnlog_mod.PENDING_APPROVAL,
        tool=call.name,
        call=call.id,
        kind=kind,
        arguments=dict(call.arguments),
    )
    emit("pending_approval", call.name)
    decision = spec.approver(
        ApprovalRequest(tool=call.name, arguments=dict(call.arguments), call_id=call.id, kind=kind)
    )
    emit("approval_decision", f"{call.name}: {'approved' if decision.approved else 'refused'}")
    if kind == "ask_user_question":
        if decision.approved:
            return ToolResult(ok=True, content=decision.response_text or "")
        detail = f"the user declined to answer: {decision.reason}".rstrip(": ")
        return ToolResult(ok=False, content=detail)
    if not decision.approved:
        suffix = f": {decision.reason}" if decision.reason else ""
        return ToolResult(ok=False, content=f"{call.name} was refused by the user{suffix}")
    dispatcher.grant(call.name)
    try:
        return dispatcher.call(call.name, call.arguments)
    finally:
        if decision.scope != "session" or dispatcher.always_prompts(call.name):
            dispatcher.revoke(call.name)


def run_task(
    spec: TaskSpec,
    *,
    env: dict[str, str],
    on_event: Callable[[str, str], None] | None = None,
    resume: bool = True,
) -> AgentRun:
    """Run one agent task to a verdict.

    The proof at the end is unconditional. It runs when the model finishes, when the turn budget
    is spent, and when the model errors — because in every one of those cases there may be edits
    in the shadow, and edits without a verdict are what L16 exists to prevent.

    **P2: a task that has run before does not start over.** The durable log says what already
    happened and `plan_resume` says what is left; this function does what the plan says. A
    restarted process re-attaches to the SAME shadow worktree at the SAME baseline, replays the
    conversation it had rather than paying for it twice, and re-runs only the proof — the one
    expensive step that is a pure function of its inputs and therefore safe to redo blindly.

    `resume=False` forces a fresh run. It exists for callers that genuinely want to start over,
    and it does NOT delete the previous shadow: the caller who wants the old one gone says so.
    """
    emit = on_event or (lambda _kind, _detail: None)
    log = turnlog_mod.TurnLog(spec.repo)
    plan = (
        turnlog_mod.plan_resume(log, spec.task_id)
        if resume
        else turnlog_mod.ResumePlan(
            finished=False,
            reprove=False,
            reason="the caller asked for a fresh run",
            consulted_the_log=False,
        )
    )
    if plan.finished:
        raise TaskAlreadyFinished(spec.task_id, *_recorded_answer(log, spec.task_id))
    staging = _shadow_for(spec, plan)
    shadow = staging.shadow
    if plan.resuming and not staging.continues_the_record:
        # The recorded worktree is gone, so the edits the transcript describes are gone with it.
        # Replaying that conversation would prove an empty change while reporting a full history
        # of work — the shape of a resume that looks like it worked and did not.
        plan = replace(
            plan,
            redo_turns=True,
            reason=(
                f"{plan.reason}; the shadow worktree was rebuilt, so the recorded turns describe "
                f"edits that no longer exist and are being re-run rather than replayed"
            ),
        )
    # NOT journalled here, deliberately. `agent/journal.py` exists to make an applied change
    # UNDOABLE (L20) by capturing pre-images of files it is about to overwrite — and nothing the
    # loop does touches a file the user can see. Every edit lands in the shadow worktree, which
    # is discardable in its entirety, and `shadow.accept` already writes through the journal at
    # the moment a change reaches the user's tree (ADR-0039: one journal, one reversal path).
    # Journalling tool calls here would create a second, parallel record of things that were
    # never applied, and pre-images of files that were never at risk.
    #
    # The inspectable trail F3 needs is `AgentRun.calls`, which records every call and its
    # outcome including refusals.
    # F14: commands run at the repository's own tier, chosen the same way the proof chooses it.
    # With no tier the dispatcher refuses `run_command` and says why — never a degraded run (L19).
    selection = select_sandbox_for_repo(spec.repo)
    dispatcher = Dispatcher(
        root=shadow.path,
        budgets=spec.budgets,
        grants=spec.grants,
        sandbox=selection.sandbox,
        sandbox_tier=selection.tier,
        sandbox_reason=selection.reason or "",
        allowed=spec.tools_allowed,
    )
    catalog = model_facing_catalog(spec.tools_allowed)
    if not plan.resuming:
        log.checkpoint(
            spec.task_id, turnlog_mod.STARTED, prompt=spec.prompt, baseline=shadow.baseline
        )
    else:
        log.checkpoint(
            spec.task_id,
            turnlog_mod.RESUMED,
            reason=plan.reason,
            redo_turns=plan.redo_turns,
            baseline=shadow.baseline,
        )
        emit("resume", plan.reason)

    history: list[Message] = [Message(role="user", content=spec.prompt)]
    narration: list[str] = []
    calls: list[ToolCallRecord] = []

    if plan.redo_turns:
        stopped, turns = _converse(
            spec, history, narration, calls, dispatcher, catalog, env, emit, log
        )
        log.checkpoint(
            spec.task_id,
            turnlog_mod.TURNS_DONE,
            turns=turns,
            stopped=stopped,
            history=_dump_history(history),
            narration=narration,
            calls=_dump_calls(calls),
        )
    else:
        # The conversation already happened and its edits are on disk in the shadow. Replaying
        # it from the log costs nothing and keeps the repair loop's context intact; asking the
        # model to do it again would cost money to produce a second, different answer to a
        # question that was already settled.
        stopped, turns = _replay_turns(log, spec.task_id, history, narration, calls)
        emit("resume", f"replayed {turns} recorded turn(s) instead of asking the model again")

    proof, change, classified = _prove_and_classify(spec, shadow, emit)

    outcome = _repair_loop(
        spec=spec,
        shadow=shadow,
        history=history,
        narration=narration,
        calls=calls,
        dispatcher=dispatcher,
        catalog=catalog,
        env=env,
        emit=emit,
        first_bundle=proof.bundle,
        first_divergences=classified,
        spent_attempts=plan.repair_attempts_spent,
    )
    if outcome is not None and outcome.attempts:
        # The repair loop re-proved, so the change and classification it ended on are the current
        # truth. Reporting the FIRST proof next to a repaired tree would show the user evidence
        # about code that no longer exists.
        proof, change, classified = _prove_and_classify(spec, shadow, emit, quiet=True)

    log.checkpoint(
        spec.task_id,
        turnlog_mod.FINISHED,
        verdict=change.verdict.value,
        bundle_id=change.bundle_id,
        repaired=bool(outcome and outcome.succeeded),
    )
    emit("verdict", change.verdict.value)
    return AgentRun(
        change=change,
        narration=tuple(narration),
        calls=tuple(calls),
        turns_used=turns,
        divergences=classified,
        repair=outcome,
        stopped_because=stopped,
    )


def _prove_and_classify(
    spec: TaskSpec,
    shadow: shadow_mod.Shadow,
    emit: Callable[[str, str], None],
    *,
    quiet: bool = False,
) -> tuple[Any, ProvenChange, tuple[ClassifiedDivergence, ...]]:
    """Snapshot the shadow, prove it against the baseline, and place every divergence.

    The `ProveConfig` is built identically every time on purpose. Changing the ruler between
    measurements — a different seed, a larger input budget — is how a repair loop talks itself
    into success, so the settings come from the spec and nowhere else.
    """
    if not quiet:
        emit("proving", "the turn is over; the engine decides what it did")
    head = shadow_mod.snapshot(shadow)
    # P2: the gap between these two checkpoints is the expensive one. A process killed inside it
    # has paid for the model work and not the proof, and `plan_resume` reads exactly that.
    log = turnlog_mod.TurnLog(spec.repo)
    log.checkpoint(spec.task_id, turnlog_mod.PROVING, base=shadow.baseline, head=head)
    proof = run_prove(
        ProveConfig(
            repo=spec.repo,
            base=shadow.baseline,
            head=head,
            max_inputs=spec.max_inputs,
            seed=spec.seed,
            # C5 run control: the prove observes the task's scope at its checkpoints, so a
            # cancel mid-prove unwinds with children killed rather than running to a verdict
            # nobody is waiting for. The PROVING row is already durable — resume reproves.
            cancel=spec.cancel,
        )
    )
    change = ProvenChange(
        # The ENGINE's aggregation, imported rather than restated. An earlier draft of this file
        # computed its own worst-first rule, and it disagreed with `run_verdict` on a mixed
        # EQUIVALENT+UNPROVEN run — a second verdict rule living next to the model layer, which
        # is the one place L17 says a verdict may never be authored.
        verdict=run_verdict(proof.bundle.targets),
        bundle_id=f"{proof.bundle.manifest.base_sha[:12]}..{proof.bundle.manifest.head_sha[:12]}",
        bundle_dir=proof.bundle_dir,
        changed_files=tuple(shadow_mod.changed_files(shadow)),
        divergence_count=sum(len(t.divergences) for t in proof.bundle.targets),
        baseline=shadow.baseline,
        head=head,
    )
    log.checkpoint(
        spec.task_id,
        turnlog_mod.PROVED,
        verdict=change.verdict.value,
        bundle_id=change.bundle_id,
    )
    contract = _effective_contract(spec, shadow)
    classified = tuple(
        ClassifiedDivergence(
            qualname=target.qualname,
            classification=(
                contract.classify(target.qualname)
                if contract is not None
                else contracts_mod.UNCLASSIFIED
            ),
            detail=divergence.detail,
        )
        for target in proof.bundle.targets
        for divergence in target.divergences
    )
    return proof, change, classified


def _effective_contract(
    spec: TaskSpec, shadow: shadow_mod.Shadow
) -> contracts_mod.IntentContract | None:
    """The contract this task actually runs under: what the user asked, plus the standing rules
    that govern the files it touched (F15, P3).

    **A behavioural rule is a wall, not advice**, and this is where the difference lives. The
    rules are read from disk by the host and folded into the contract the classifier consumes,
    after the model's turn is over. Nothing the model emits is on that path, so "ignore the rules"
    is not an instruction that can be obeyed by anything — which is why F15's gate (a violation is
    blocked even when the model is told to violate it) is achievable rather than aspirational.

    Rules only ever ADD `must_not_change`. A rule that could widen `may_change` would be a way for
    an agent to grant itself permission by writing a file, and an agent can write files.
    """
    stated = contracts_mod.load(spec.repo, spec.task_id)
    try:
        rules = rules_mod.load(spec.repo)
    except rules_mod.RuleError:
        # A rules file that cannot be read is a wall the user believes is there. Refusing to run
        # is the only honest answer; falling back to "no rules" would be the silent downgrade.
        raise
    if not rules:
        return stated
    return rules_mod.apply_to(
        stated, rules, files=tuple(shadow_mod.changed_files(shadow)), intent=spec.prompt
    ).contract


def _contract_bytes(spec: TaskSpec) -> str:
    """The contract file exactly as it is on disk, or "" when there is none.

    Compared before and after every attempt. This is the cheat-1 detector, and it deliberately
    reads BYTES rather than a parsed contract: an agent that reformatted the file without
    changing its meaning has still edited the thing it was told not to touch, and a loop that
    forgave that would be teaching it where the edge is.
    """
    path = contracts_mod.path_for(spec.repo, spec.task_id)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _modules_that_stopped_loading(
    spec: TaskSpec, shadow: shadow_mod.Shadow
) -> tuple[repair_mod.BrokenModule, ...]:
    """Import every Python file the change touches and collect the ones the AGENT broke.

    **Differential, like everything else here.** A module that fails to import at head is only
    evidence against the attempt if it imported at the BASELINE. Plenty of modules do not load in
    any given environment — a third-party dependency that was never fetched, a file that was
    already broken when the user opened the editor, a package that needs an installed extra — and
    every one of them would otherwise be reported as a cheat the agent committed. So a head
    failure is re-checked against the baseline tree, and only a module that *stopped* loading is
    named. (This is the same principle the whole product runs on, arrived at the hard way: the
    first version of this check was absolute, and the review pointed out it would accuse an agent
    of breaking a file that was broken before it started.)

    **Only files the change touches**, and only files the repository has not declared out of
    scope. A loop that refused to finish until the whole tree imported would be judging the
    user's project rather than this attempt.

    Executed, in the sandbox the repo's tier selects and with the dependency attachment every
    proved worktree gets — the same conditions the proof ran under (L4/L6). There is no static
    substitute: a fatal import is syntactically perfect right up to the moment the interpreter
    disagrees. And the probe asserts the NAME it imported resolved to the FILE it is judging: a
    dotted name is not a file, and several things can answer to one first.

    With no sandbox available nothing may execute, so nothing can be checked — and an unchecked
    module is reported as broken rather than assumed sound. Fail closed: the alternative is a
    repair that passes *because* the machine could not look.
    """
    changed = _changed_python(spec, shadow)
    if not changed:
        return ()
    selection = select_sandbox_for_repo(spec.repo)
    if selection.sandbox is None:
        reason = selection.reason or "no sandbox tier is available"
        return tuple(
            repair_mod.BrokenModule(path=rel, module="", error=f"not checked: {reason}")
            for rel in changed
        )

    # The shadow gets the SAME dependency attachment every proved worktree gets. Without it the
    # two probes are not comparable: the baseline is a `materialize`d worktree the proof has
    # already run `attach_deps` on, so it has `.tempest-deps` on its sys.path and the shadow does
    # not — and then every changed file with a third-party import at module scope fails at head,
    # loads at baseline, and is reported as a cheat. A review reproduced exactly that; the
    # differential check alone did NOT save it, because the asymmetry is in the environment
    # rather than in the code (ADR-0053).
    cache = spec.repo / ".tempest" / "cache"
    attach_deps(shadow.path, cache, fetch=fetch_enabled())

    suspects: list[tuple[str, str, str]] = []
    for rel in changed:
        module = module_for_path(shadow.path, rel)
        if not (shadow.path / rel).is_file():
            suspects.append((rel, module, "the file is gone from the change's head revision"))
            continue
        probe = module_loads(shadow.path, module, selection.sandbox, expect_file=shadow.path / rel)
        if not probe.loads:
            suspects.append((rel, module, probe.error))
    if not suspects:
        return ()

    # Only now, and only for the suspects: materializing the baseline costs a worktree, so it is
    # not paid on the ordinary path where nothing is broken.
    baseline = materialize(spec.repo, shadow.baseline, cache)
    attach_deps(baseline.worktree, cache, fetch=fetch_enabled())
    broken: list[repair_mod.BrokenModule] = []
    for rel, module, error in suspects:
        before = module_loads(
            baseline.worktree, module, selection.sandbox, expect_file=baseline.worktree / rel
        )
        if before.loads:
            broken.append(repair_mod.BrokenModule(path=rel, module=module, error=error))
    return tuple(broken)


def _changed_python(spec: TaskSpec, shadow: shadow_mod.Shadow) -> list[str]:
    """The Python files this change touches, minus anything the repository ignores.

    A path the repo has declared out of scope is a path the prover never looks at, and importing
    it here would execute code the user has told this product to leave alone.
    """
    try:
        config = TempestConfig.load(spec.repo)
    except TempestConfigError:  # pragma: no cover - a broken config is already fatal upstream
        config = TempestConfig()
    return [
        rel
        for rel in shadow_mod.changed_files(shadow)
        if rel.endswith(".py") and not is_ignored(rel, config.ignore_globs)
    ]


def _needs_repair(divergences: tuple[ClassifiedDivergence, ...]) -> bool:
    return any(
        d.classification in (contracts_mod.UNINTENDED, contracts_mod.UNCLASSIFIED)
        for d in divergences
    )


def _repair_loop(
    *,
    spec: TaskSpec,
    shadow: shadow_mod.Shadow,
    history: list[Message],
    narration: list[str],
    calls: list[ToolCallRecord],
    dispatcher: Dispatcher,
    catalog: Any,
    env: dict[str, str],
    emit: Callable[[str, str], None],
    first_bundle: Any,
    first_divergences: tuple[ClassifiedDivergence, ...],
    spent_attempts: int = 0,
) -> repair_mod.RepairOutcome | None:
    """F3. Hand the agent the evidence, let it try again, re-prove, judge. Bounded.

    Returns None when the loop never engaged, which is a different fact from "it ran and failed"
    and must not be reported as one.

    **It engages only when there is a contract.** Without a stated intent every divergence is
    unclassified, and "repair" would mean guessing which of the user's own changes they did not
    want — the exact judgement F2 exists to keep a model out of.
    """
    log = turnlog_mod.TurnLog(spec.repo)
    recorded_before, recorded_contract = _repair_baseline(log, spec.task_id)
    contract = _effective_contract(spec, shadow)
    if contract is None or spec.max_repair_attempts <= 0:
        return None
    if not _needs_repair(first_divergences):
        if spent_attempts == 0:
            return None
        # A previous process ran attempts and this one finds nothing left to repair. Returning
        # None here would say "the loop never engaged", which the log disproves — and it is the
        # exact shape of the cheat the lost-target check exists for: an attempt that removed the
        # divergence by removing the symbol, followed by a restart that proves the tree after the
        # removal and sees a clean bundle. So the loop is reported, with what it can still check.
        lost = sorted(set(recorded_before or {}) - set(repair_mod.proven_targets(first_bundle)))
        return repair_mod.RepairOutcome(
            succeeded=not lost,
            attempts=(),
            reason=(
                f"{spent_attempts} repair attempt(s) ran in a process that did not survive to "
                f"judge them"
                + (
                    f"; targets that were provable before are not now: {', '.join(lost)}"
                    if lost
                    else "; nothing this process can still check is wrong"
                )
            ),
        )
    # The budget is a bound on MONEY, so it counts attempts across the whole task rather than
    # across this process. A task killed four times would otherwise spend four full budgets and
    # the record would show one (L15.4).
    remaining = spec.max_repair_attempts - spent_attempts
    if remaining <= 0:
        return repair_mod.RepairOutcome(
            succeeded=False,
            attempts=(),
            reason=(
                f"the repair budget of {spec.max_repair_attempts} attempt(s) was already spent "
                f"before this process started"
            ),
        )

    # The two differential cheat checks — "the contract changed" and "targets stopped being
    # provable" — compare against the state BEFORE the loop began. On a restart the fresh proof
    # already contains the killed attempt's edits, so recomputing them here would make whatever
    # that attempt did the innocent baseline. They are recorded once and restored (ADR-0053).
    before = (
        recorded_before if recorded_before is not None else repair_mod.proven_targets(first_bundle)
    )
    contract_before = recorded_contract if recorded_contract is not None else _contract_bytes(spec)
    if recorded_before is None:
        log.checkpoint(
            spec.task_id,
            turnlog_mod.REPAIR_ATTEMPT,
            number=0,
            phase="baseline",
            proven={name: verdict.value for name, verdict in before.items()},
            contract=contract_before,
        )
    attempts: list[repair_mod.RepairAttempt] = []
    bundle = first_bundle
    divergences = first_divergences
    reason = "the budget was spent before the divergence set matched the contract"

    for number in range(spent_attempts + 1, spent_attempts + remaining + 1):
        packet = _first_offender(bundle, divergences, contract)
        if packet is None:  # pragma: no cover - _needs_repair guarantees one exists
            break
        emit("repair", f"attempt {number}: {packet.qualname}")
        turnlog_mod.TurnLog(spec.repo).checkpoint(
            spec.task_id, turnlog_mod.REPAIR_ATTEMPT, number=number, symbol=packet.qualname
        )
        history.append(Message(role="user", content=packet.render()))
        _converse(spec, history, narration, calls, dispatcher, catalog, env, emit, log)
        # The attempt's conversation is part of the durable record. Without this a restart mid
        # repair replayed the transcript from BEFORE the attempt while the shadow already held
        # the attempt's edits, and re-ran model turns that had already been paid for.
        log.checkpoint(
            spec.task_id,
            turnlog_mod.REPAIR_ATTEMPT,
            number=number,
            symbol=packet.qualname,
            phase="conversed",
            history=_dump_history(history),
            narration=narration,
            calls=_dump_calls(calls),
        )

        proof, _change, divergences = _prove_and_classify(spec, shadow, emit, quiet=True)
        bundle = proof.bundle

        if not shadow_mod.changed_files(shadow):
            # The agent reverted its own work. Every target that was proven is now "lost" — not
            # because evidence was destroyed, but because there is no change left to have
            # evidence ABOUT. Calling that a cheat would be an accusation about an honest, if
            # useless, outcome; calling it a repair would be worse. It is its own answer.
            attempts.append(
                repair_mod.RepairAttempt(
                    number=number,
                    packet=packet,
                    unintended_after=0,
                    unclassified_after=0,
                )
            )
            return repair_mod.RepairOutcome(
                succeeded=False,
                attempts=tuple(attempts),
                reason=(
                    "the agent reverted its own change — the divergence is gone because the "
                    "work is, so there is nothing to present"
                ),
                abandoned=True,
            )

        judgement = repair_mod.judge(
            before=before,
            after_bundle=bundle,
            divergences=divergences,
            contract_before=contract_before,
            contract_after=_contract_bytes(spec),
            reverted=repair_mod.reverted_symbols(
                lost=set(before) - set(repair_mod.proven_targets(bundle)),
                first_bundle=first_bundle,
                read_source=lambda sha, path: shadow_mod.read_at(shadow, sha, path),
                baseline=shadow.baseline,
                head=shadow_mod.snapshot(shadow),
            ),
            broken=_modules_that_stopped_loading(spec, shadow),
        )
        succeeded, why = judgement.succeeded, judgement.reason
        cheat = judgement.reason if judgement.cheat else ""
        attempts.append(
            repair_mod.RepairAttempt(
                number=number,
                packet=packet,
                unintended_after=sum(
                    1 for d in divergences if d.classification == contracts_mod.UNINTENDED
                ),
                unclassified_after=sum(
                    1 for d in divergences if d.classification == contracts_mod.UNCLASSIFIED
                ),
                cheat=cheat,
            )
        )
        if succeeded:
            reason = why
            return repair_mod.RepairOutcome(succeeded=True, attempts=tuple(attempts), reason=reason)
        reason = why
        if cheat:
            # A cheat is not a failed attempt to be retried — it is the agent working on the
            # wrong problem, and giving it three more turns to keep doing that spends budget to
            # make the record worse.
            emit("repair", f"attempt {number} rejected: {cheat}")
            break

    return repair_mod.RepairOutcome(succeeded=False, attempts=tuple(attempts), reason=reason)


def _first_offender(
    bundle: Any,
    divergences: tuple[ClassifiedDivergence, ...],
    contract: contracts_mod.IntentContract,
) -> repair_mod.EvidencePacket | None:
    """The evidence packet for the first divergence the contract does not allow.

    One at a time, deliberately: the minimized repro is a fitness function, and a model handed
    five of them at once optimises for none of them.
    """
    offending = {
        d.qualname
        for d in divergences
        if d.classification in (contracts_mod.UNINTENDED, contracts_mod.UNCLASSIFIED)
    }
    for target in bundle.targets:
        if target.qualname in offending and target.divergences:
            return repair_mod.evidence_for(target, target.divergences[0], contract)
    return None
