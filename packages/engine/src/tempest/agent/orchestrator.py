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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tempest.agent import contracts as contracts_mod
from tempest.agent import repair as repair_mod
from tempest.agent import shadow as shadow_mod
from tempest.agent import turnlog as turnlog_mod
from tempest.agent.tools import Budgets, Dispatcher, ToolResult, model_facing_catalog
from tempest.bundle.bundle import run_verdict
from tempest.inference.client import Message, ModelError, complete
from tempest.model import Verdict
from tempest.prove import ProveConfig, run_prove

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
    #: F3. Attempts are only spent when there IS a contract — with no stated intent there is
    #: nothing to repair against, and an agent guessing at what the user wanted is precisely what
    #: F2 exists to prevent. Set to 0 to prove once and stop.
    max_repair_attempts: int = repair_mod.DEFAULT_MAX_ATTEMPTS


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
        try:
            answer = complete(
                spec.provider,
                history,
                env=env,
                model=spec.model,
                system=SYSTEM_PROMPT,
                tools=catalog,
            )
        except ModelError as exc:
            # A model failure ends the LOOP, never the task: whatever is already staged still
            # gets proved and shown with its real verdict (L23 — degrade explicitly).
            stopped = f"model unavailable: {exc}"
            emit("model_error", str(exc))
            break

        if answer.text:
            narration.append(answer.text)
            emit("narration", answer.text)

        if not answer.tool_calls:
            stopped = stopped or "the model finished"
            break

        history.append(Message(role="assistant", content=answer.text, tool_calls=answer.tool_calls))
        for call in answer.tool_calls:
            result = dispatcher.call(call.name, call.arguments)
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


def run_task(
    spec: TaskSpec,
    *,
    env: dict[str, str],
    on_event: Callable[[str, str], None] | None = None,
) -> AgentRun:
    """Run one agent task to a verdict.

    The proof at the end is unconditional. It runs when the model finishes, when the turn budget
    is spent, and when the model errors — because in every one of those cases there may be edits
    in the shadow, and edits without a verdict are what L16 exists to prevent.
    """
    emit = on_event or (lambda _kind, _detail: None)
    shadow = shadow_mod.create(spec.repo, spec.task_id)
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
    dispatcher = Dispatcher(root=shadow.path, budgets=spec.budgets, grants=spec.grants)
    catalog = model_facing_catalog()
    log = turnlog_mod.TurnLog(spec.repo)
    log.checkpoint(spec.task_id, turnlog_mod.STARTED, prompt=spec.prompt, baseline=shadow.baseline)

    history: list[Message] = [Message(role="user", content=spec.prompt)]
    narration: list[str] = []
    calls: list[ToolCallRecord] = []

    stopped, turns = _converse(spec, history, narration, calls, dispatcher, catalog, env, emit)
    log.checkpoint(spec.task_id, turnlog_mod.TURNS_DONE, turns=turns, stopped=stopped)

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
    contract = contracts_mod.load(spec.repo, spec.task_id)
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


def _contract_bytes(spec: TaskSpec) -> str:
    """The contract file exactly as it is on disk, or "" when there is none.

    Compared before and after every attempt. This is the cheat-1 detector, and it deliberately
    reads BYTES rather than a parsed contract: an agent that reformatted the file without
    changing its meaning has still edited the thing it was told not to touch, and a loop that
    forgave that would be teaching it where the edge is.
    """
    path = contracts_mod.path_for(spec.repo, spec.task_id)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


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
) -> repair_mod.RepairOutcome | None:
    """F3. Hand the agent the evidence, let it try again, re-prove, judge. Bounded.

    Returns None when the loop never engaged, which is a different fact from "it ran and failed"
    and must not be reported as one.

    **It engages only when there is a contract.** Without a stated intent every divergence is
    unclassified, and "repair" would mean guessing which of the user's own changes they did not
    want — the exact judgement F2 exists to keep a model out of.
    """
    contract = contracts_mod.load(spec.repo, spec.task_id)
    if contract is None or spec.max_repair_attempts <= 0:
        return None
    if not _needs_repair(first_divergences):
        return None

    before = repair_mod.proven_targets(first_bundle)
    contract_before = _contract_bytes(spec)
    attempts: list[repair_mod.RepairAttempt] = []
    bundle = first_bundle
    divergences = first_divergences
    reason = "the budget was spent before the divergence set matched the contract"

    for number in range(1, spec.max_repair_attempts + 1):
        packet = _first_offender(bundle, divergences, contract)
        if packet is None:  # pragma: no cover - _needs_repair guarantees one exists
            break
        emit("repair", f"attempt {number}: {packet.qualname}")
        turnlog_mod.TurnLog(spec.repo).checkpoint(
            spec.task_id, turnlog_mod.REPAIR_ATTEMPT, number=number, symbol=packet.qualname
        )
        history.append(Message(role="user", content=packet.render()))
        _converse(spec, history, narration, calls, dispatcher, catalog, env, emit)

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
            )

        succeeded, why = repair_mod.judge(
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
        )
        cheat = "" if succeeded or "remain" in why else why
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
