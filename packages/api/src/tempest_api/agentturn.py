"""Tool-bearing agent turns — the chat surface's delegation into the ONE runtime (C5, L29).

This module is the declared `gate_audit` path for agent-authored change reaching a user
through chat: `run_agent_turn` builds a `TaskSpec` from the agent document and hands the turn
to `run_task` — the same loop, the same shadow worktree, the same engine verdict as every
other entry point. There is deliberately NO model-calling loop here and no frame vocabulary
beyond narration: what the model says streams as narration (L17), the engine's verdict stays
in the engine's records (turnlog + bundle, in the repository), and the platform store never
carries a verdict word — the forge test sweeps it to prove that.

Collaboration contract: this module is `chatturn`'s same-package worker for one job kind. It
drives the job's frame ledger and terminal commit through `ChatTurns`' own helpers
(`_flush_if_due`, `_finish`) so there is exactly one durability discipline, not a copy.
"""

from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tempest.agent.events import (
    AgentEvent,
    Narration,
    Proving,
    ToolCallFinished,
    ToolCallStarted,
    TurnUsage,
)
from tempest.agent.orchestrator import AgentError, TaskSpec, run_task
from tempest.agent.tools import ApprovalDecision, ApprovalRequest, ToolError
from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.inference import providers as registry
from tempest_api import chatwire

if TYPE_CHECKING:  # a runtime import would be a cycle; only the types are needed here
    from tempest_api.chatturn import ChatTurns, _Job


class AgentTurnRejected(RuntimeError):
    """A turn that cannot start, with a reason the user can act on (L15.3)."""


#: A parked question is not an open-ended lease (L15.4): past this, the ask resolves as an
#: honest refusal ("expired unanswered") and the turn continues with it on the record. The
#: CANCEL path stays live throughout — the park polls the scope every quarter second.
_APPROVAL_EXPIRY_S = 1800.0

#: LC19's activity headers, keyed by tool. Mechanical on purpose: a model-written label is a
#: model writing into a UI field (L17), and a generated one costs a model call per batch.
_ACTIVITY_LABELS = {
    "read_file": "Reading the repository",
    "list_dir": "Reading the repository",
    "search_text": "Searching the repository",
    "write_file": "Editing in the shadow worktree",
    "run_command": "Running commands",
    "prove": "Proving the change",
    "ask_user": "Waiting on you",
}


@dataclasses.dataclass
class ApprovalBox:
    """One park: the wire-shaped pending action, the request it answers, and the slot the
    resume writes into. Lives on the job so `resolve_approval` and `status` can reach it."""

    action_id: str
    request: ApprovalRequest
    pending: dict[str, Any]
    decided: threading.Event = dataclasses.field(default_factory=threading.Event)
    decision: ApprovalDecision | None = None


def context_usage_frame(
    provider: registry.Provider,
    event: TurnUsage,
    *,
    response_message_id: str,
    tool_count: int,
) -> dict[str, Any] | None:
    """The context gauge's frame (LC21) — or None, honestly, when the denominator is unknown.

    `messageTokens` is the provider's OWN prompt count for the turn (measured, L21); the
    un-decomposed components are zeros, which the client sums — never invented estimates.
    A provider row without a documented `context_window` produces NO frame: the gauge renders
    indeterminate, because a wrong maximum is worse than no maximum.
    """
    window = provider.context_window
    if window is None or event.input_tokens <= 0:
        return None
    remaining = max(0, window - event.input_tokens)
    return {
        "event": "on_context_usage",
        "data": {
            "runId": response_message_id,
            "breakdown": {
                "maxContextTokens": window,
                "instructionTokens": 0,
                "systemMessageTokens": 0,
                "dynamicInstructionTokens": 0,
                "toolSchemaTokens": 0,
                "summaryTokens": 0,
                "toolCount": tool_count,
                "messageCount": 0,
                "messageTokens": event.input_tokens,
                "availableForMessages": remaining,
            },
            "remainingContextTokens": remaining,
        },
    }


def _pending_payload(request: ApprovalRequest) -> dict[str, Any]:
    """The client's `HumanInterruptPayload`, discriminated on `type`; the join key is
    tool_call_id, never position (the client's own doc comment warns about parallel calls)."""
    if request.kind == "ask_user_question":
        options = [
            {"label": str(o), "value": str(o)} for o in (request.arguments.get("options") or [])
        ]
        question: dict[str, Any] = {"question": str(request.arguments.get("question") or "")}
        if options:
            question["options"] = options
        return {
            "type": "ask_user_question",
            "question": question,
            "tool_call_id": request.call_id,
        }
    return {
        "type": "tool_approval",
        "action_requests": [
            {
                "name": request.tool,
                "arguments": request.arguments,
                "tool_call_id": request.call_id,
            }
        ],
        "review_configs": [
            {
                "action_name": request.tool,
                "tool_call_id": request.call_id,
                "allowed_decisions": ["approve", "reject"],
            }
        ],
    }


def spec_for(
    job: _Job,
    agent: dict[str, Any],
    provider: registry.Provider,
    model: str,
    prompt: str,
    *,
    meter: Any,
    cancel: CancelScope,
) -> TaskSpec:
    """The `TaskSpec` an agent document resolves to — split out so tests can pin the mapping.

    One TURN is one TASK: the shadow is fresh from the current baseline each time, and the
    designed acceptance flow (composer / shadow.accept) is how work lands between turns.
    The task id carries the generation so a regenerate on the same stream is a new task.
    """
    repo = str(agent.get("tempest_repo") or "")
    if not repo or not Path(repo).is_dir():
        raise AgentTurnRejected(
            "this agent has tools, and tools need a repository to work in — none is "
            "configured. Set `tempest_repo` on the agent (PATCH /api/agents/{id}); the "
            "builder's repository picker arrives with the conversation platform."
        )
    tools = [str(t) for t in (agent.get("tools") or [])]
    return TaskSpec(
        repo=Path(repo),
        task_id=f"chat-{job.stream_id[:12]}-{job.generation_created_at}",
        prompt=prompt,
        provider=provider.id,
        model=model,
        meter=meter,
        cost_session="platform-chat",
        cost_task_key=job.conversation_id,
        cancel=cancel,
        tools_allowed=frozenset(tools) if tools else None,
        # Grants stay EMPTY on this path for now: a tool whose policy needs approval meets
        # a refusal, never a silent auto-grant. The HITL pending-approval stage (the next
        # C5 item) is what turns that refusal into a question.
        grants=frozenset(),
    )


def run_agent_turn(
    turns: ChatTurns,
    job: _Job,
    agent: dict[str, Any],
    provider: registry.Provider,
    model: str,
    user_message: dict[str, Any],
    conversation: dict[str, Any],
    endpoint: str,
) -> None:
    """The thread body for one tool-bearing turn. Mirrors `_run_turn`'s outcome contract:
    every exit — answer, refusal, cancellation, defect — lands in `ChatTurns._finish`."""
    collected: list[str] = []
    error_text: str | None = None
    aborted = False
    scope = CancelScope()
    job.cancel_scope = scope
    if job.cancel.is_set():  # a cancel that raced the spawn still wins
        scope.cancel()

    # ONE content-part allocator for everything beyond the narration text (part 0): tool
    # steps, steer chips and activity labels share the index space, in arrival order, and
    # `job.extra_parts` mirrors the allocation so the PERSISTED message renders what the
    # live stream rendered.
    state: dict[str, int] = {"next_index": 1}
    open_steps: dict[str, tuple[str, int, str, dict[str, Any]]] = {}
    last_label: dict[str, str] = {"label": ""}

    def allocate(part: dict[str, Any]) -> int:
        index = state["next_index"]
        state["next_index"] += 1
        job.extra_parts.append(part)
        return index

    def emit_label(label: str, call_id: str) -> None:
        """LC19's activity headers, MECHANICALLY derived from the tool kind — no model
        writes a label (L17), and none of the reserved verdict vocabulary appears (L31)."""
        if label == last_label["label"]:
            return
        last_label["label"] = label
        part = {"type": "activity_label", "activity_label": label, "tool_call_ids": [call_id]}
        index = allocate(part)
        job.append({"event": "on_activity_label", "data": {"index": index, "part": part}})

    def emit(event: AgentEvent) -> None:
        if isinstance(event, Narration):
            chunk = event.text if not collected else f"\n\n{event.text}"
            collected.append(chunk)
            job.append(
                chatwire.message_delta_frame(
                    response_message_id=job.response_message_id, text=chunk
                )
            )
        elif isinstance(event, ToolCallStarted):
            emit_label(_ACTIVITY_LABELS.get(event.name, "Working"), event.call_id)
            index = state["next_index"]
            state["next_index"] += 1
            step_id = f"step_{job.response_message_id}_{index}"
            open_steps[event.call_id] = (step_id, index, event.name, event.arguments)
            job.extra_parts.append({"type": "tool_call", "tool_call": {}})  # filled on finish
            job.append(
                {
                    "event": "on_run_step",
                    "data": {
                        "id": step_id,
                        "index": index,
                        "type": "tool_calls",
                        "runId": job.response_message_id,
                        "usage": None,
                        "stepDetails": {
                            "type": "tool_calls",
                            "tool_calls": [
                                {
                                    "type": "tool_call",
                                    "name": event.name,
                                    "args": event.arguments,
                                    "id": event.call_id,
                                }
                            ],
                        },
                    },
                }
            )
        elif isinstance(event, ToolCallFinished):
            opened = open_steps.pop(event.call_id, None)
            if opened is None:  # pragma: no cover — every finish follows its start
                return
            step_id, index, name, arguments = opened
            tool_call = {
                "type": "tool_call",
                "name": name,
                "args": arguments,
                "id": event.call_id,
                "output": event.detail,
            }
            # The persisted mirror of this step, at the slot reserved when it opened.
            job.extra_parts[index - 1] = {"type": "tool_call", "tool_call": tool_call}
            job.append(
                {
                    "event": "on_run_step_completed",
                    "data": {"result": {"id": step_id, "index": index, "tool_call": tool_call}},
                }
            )
        elif isinstance(event, TurnUsage):
            job.append(
                chatwire.token_usage_frame(
                    response_message_id=job.response_message_id,
                    provider=event.provider,
                    model=event.model,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                )
            )
            gauge = context_usage_frame(
                provider,
                event,
                response_message_id=job.response_message_id,
                tool_count=len(agent.get("tools") or []),
            )
            if gauge is not None:
                job.append(gauge)
        elif isinstance(event, Proving):
            part = {"type": "activity_label", "activity_label": "Proving the change"}
            index = allocate(part)
            job.append({"event": "on_activity_label", "data": {"index": index, "part": part}})
        else:
            return
        turns._flush_if_due(job)

    def approver(request: ApprovalRequest) -> ApprovalDecision:
        """PARK the turn on the client (C5 HITL, LC18): publish `on_pending_action`, hold the
        status ACTIVE (the poller keeps the live feed open through the park), and wait for
        `resolve_approval` — observing the cancel scope every quarter second and expiring
        into an honest refusal rather than leasing the thread forever."""
        box = ApprovalBox(
            action_id=f"appr_{uuid.uuid4().hex[:12]}",
            request=request,
            pending={},
        )
        box.pending = {
            "actionId": box.action_id,
            "streamId": job.stream_id,
            "conversationId": job.conversation_id,
            "runId": job.response_message_id,
            "responseMessageId": job.response_message_id,
            "createdAt": int(time.time() * 1000),
            "payload": _pending_payload(request),
        }
        job.approval_box = box
        job.append({"event": "on_pending_action", "data": box.pending})
        turns._flush_if_due(job)
        deadline = time.monotonic() + _APPROVAL_EXPIRY_S
        try:
            while not box.decided.wait(0.25):
                if scope.cancelled:
                    raise ProveCancelled("the turn was stopped while parked on an approval")
                if time.monotonic() >= deadline:
                    return ApprovalDecision(
                        approved=False,
                        reason="the approval request expired unanswered (30 minutes)",
                    )
        finally:
            job.approval_box = None
        decision = box.decision
        if decision is None:  # pragma: no cover — decided is set only after the slot fills
            raise AgentError("an approval was signalled decided with no decision recorded")
        return decision

    def steer_source() -> tuple[str, ...]:
        """Drain queued follow-ups (LC16) — consumed under the job lock, then published as
        `on_steer_applied` frames (outside the lock: `append` takes it too) so the client's
        chips flip from pending to applied."""
        with job.lock:
            drained = list(job.steers)
            if drained:
                job.steers.clear()
                job.steers_applied.extend(drained)
        if not drained:
            return ()
        for row in drained:
            part = {"type": "steer", "steer": row["text"], "createdAt": row["createdAt"]}
            index = allocate(part)
            job.append(
                {
                    "event": "on_steer_applied",
                    "data": {
                        "steerId": row["steerId"],
                        "clientSteerId": row.get("clientSteerId"),
                        "index": index,
                        "part": part,
                    },
                }
            )
        turns._flush_if_due(job)
        return tuple(str(row.get("text") or "") for row in drained)

    try:
        spec = spec_for(
            job,
            agent,
            provider,
            model,
            str(user_message.get("text") or ""),
            meter=turns._meter,
            cancel=scope,
        )
        spec = dataclasses.replace(spec, approver=approver, steer_source=steer_source)
        run_task(spec, env=turns._env_provider(), on_event=emit)
    except ProveCancelled:
        aborted = True
    except AgentTurnRejected as exc:
        error_text = str(exc)
    except (AgentError, ToolError) as exc:
        error_text = str(exc)
    except Exception as exc:  # a defect in us, surfaced in-band rather than swallowed
        error_text = f"the agent turn failed inside Tempest: {exc!r}"
    # usage=None on purpose: the ORCHESTRATOR already metered every completion through
    # `TaskSpec.meter`; a second spend here would double-charge the turn.
    turns._finish(
        job,
        conversation,
        user_message,
        collected,
        None,
        model,
        endpoint,
        provider,
        aborted=aborted,
        error=error_text,
        extra_parts=list(job.extra_parts),
    )
