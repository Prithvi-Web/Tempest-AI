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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from tempest.agent.orchestrator import AgentError, TaskSpec, run_task
from tempest.agent.tools import ToolError
from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.inference import providers as registry
from tempest_api import chatwire

if TYPE_CHECKING:  # a runtime import would be a cycle; only the types are needed here
    from tempest_api.chatturn import ChatTurns, _Job


class AgentTurnRejected(RuntimeError):
    """A turn that cannot start, with a reason the user can act on (L15.3)."""


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
    )
