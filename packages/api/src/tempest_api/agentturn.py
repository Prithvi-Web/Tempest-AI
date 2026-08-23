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


@dataclasses.dataclass
class ApprovalBox:
    """One park: the wire-shaped pending action, the request it answers, and the slot the
    resume writes into. Lives on the job so `resolve_approval` and `status` can reach it."""

    action_id: str
    request: ApprovalRequest
    pending: dict[str, Any]
    decided: threading.Event = dataclasses.field(default_factory=threading.Event)
    decision: ApprovalDecision | None = None


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

    def emit(kind: str, detail: str) -> None:
        if kind != "narration":
            return
        chunk = detail if not collected else f"\n\n{detail}"
        collected.append(chunk)
        job.append(
            chatwire.message_delta_frame(response_message_id=job.response_message_id, text=chunk)
        )
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
                base_index = len(job.steers_applied)
                job.steers_applied.extend(drained)
        if not drained:
            return ()
        for offset, row in enumerate(drained):
            job.append(
                {
                    "event": "on_steer_applied",
                    "data": {
                        "steerId": row["steerId"],
                        "clientSteerId": row.get("clientSteerId"),
                        # Content-part slot: the narration text is part 0; steers follow.
                        "index": base_index + offset + 1,
                        "part": {
                            "type": "steer",
                            "steer": row["text"],
                            "createdAt": row["createdAt"],
                        },
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
    with job.lock:
        steer_parts = [
            {"type": "steer", "steer": row["text"], "createdAt": row["createdAt"]}
            for row in job.steers_applied
        ]
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
        extra_parts=steer_parts,
    )
