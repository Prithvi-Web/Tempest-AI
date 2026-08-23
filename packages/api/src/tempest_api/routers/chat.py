"""Chat-turn + conversation endpoints (PLAN-V3 C5, ADR-0078) — the boundary-A surface behind
the desktop host's `/api/agents/chat*`, `/api/convos` and `/api/messages` intercepts.

Same decoupling as local prove: the start answers immediately, the turn runs on its own
thread, and the ledger is polled — here at token cadence by the host's stream poller."""

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tempest.inference import cost
from tempest_api.agentstore import AgentStore
from tempest_api.chatturn import (
    GENERATION_PROTOCOL_VERSION,
    ApprovalInvalid,
    ApprovalStale,
    ChatTurns,
    SteerInvalid,
    SteerNoRun,
    SteerUnsupported,
    TurnConflict,
    TurnRejected,
)
from tempest_api.errors import ApiError, error_responses
from tempest_api.localprove import data_dir
from tempest_api.platformstore import PlatformStore
from tempest_api.schemas import ErrorCode
from tempest_api.schemas.chat import (
    ActiveTurnsOut,
    CancelTurnOut,
    ChatTurnAck,
    ChatTurnStatusOut,
    ConversationsOut,
    ResumeApprovalRequest,
    StartChatTurnRequest,
    SteerCancelRequest,
    SteerRequest,
    TurnEventsOut,
)

router = APIRouter(tags=["chat"])

_REGISTRY: dict[str, ChatTurns] = {}
_REGISTRY_LOCK = threading.Lock()


def _turns() -> ChatTurns:
    """One `ChatTurns` per data root, created on first use. Keyed by the resolved directory
    so tests pointing `TEMPEST_DATA_DIR` at fresh roots get fresh worlds. The lock matters:
    two instances over one store would give the dead-turn reconciler a second world in which
    a living job is invisible — the exact check-then-act class start_turn's reservation
    kills one layer below."""
    root = str(data_dir())
    with _REGISTRY_LOCK:
        turns = _REGISTRY.get(root)
        if turns is None:
            store = PlatformStore(Path(root) / "platform" / "store.sqlite3")
            turns = ChatTurns(
                store,
                env_provider=lambda: dict(os.environ),
                meter=cost.Meter(repo=Path(root) / "platform"),
                # The agents ENDPOINT resolves documents from the same store (C5): one world,
                # whichever router touched it first.
                agents=AgentStore(store),
            )
            _REGISTRY[root] = turns
        return turns


@router.post(
    "/v1/chat/turns",
    operation_id="startChatTurn",
    responses=error_responses(400, 409, 422),
)
async def start_chat_turn(body: StartChatTurnRequest) -> ChatTurnAck:
    try:
        ack = await asyncio.to_thread(_turns().start_turn, body.model_dump())
    except TurnRejected as exc:
        raise ApiError(400, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    except TurnConflict as exc:
        raise ApiError(409, ErrorCode.IDEMPOTENCY_CONFLICT, str(exc)) from exc
    return ChatTurnAck(**ack)


@router.get("/v1/chat/turns", operation_id="listActiveChatTurns")
async def list_active_chat_turns() -> ActiveTurnsOut:
    return ActiveTurnsOut(activeJobIds=await asyncio.to_thread(_turns().active_ids))


@router.get("/v1/chat/turns/{stream_id}/events", operation_id="listChatTurnEvents")
async def list_chat_turn_events(stream_id: str, after: int = 0) -> TurnEventsOut:
    payload = await asyncio.to_thread(_turns().events_after, stream_id, after)
    return TurnEventsOut(**payload)


@router.get("/v1/chat/turns/{stream_id}", operation_id="getChatTurnStatus")
async def get_chat_turn_status(stream_id: str) -> ChatTurnStatusOut:
    return ChatTurnStatusOut(**await asyncio.to_thread(_turns().status, stream_id))


@router.post("/v1/chat/turns/{stream_id}/cancel", operation_id="cancelChatTurn")
async def cancel_chat_turn(
    stream_id: str, generation_created_at: int | None = None
) -> CancelTurnOut:
    """`generation_created_at` is the epoch guard: a stale tab's abort names the turn it
    watched, and a successor turn on the same conversation-scoped id survives it."""
    payload = await asyncio.to_thread(
        lambda: _turns().cancel_turn(stream_id, generation_created_at=generation_created_at)
    )
    return CancelTurnOut(**payload)


@router.post(
    "/v1/chat/turns/{stream_id}/resume",
    operation_id="resolveChatApproval",
    responses=error_responses(400, 409, 422),
)
async def resolve_chat_approval(stream_id: str, body: ResumeApprovalRequest) -> dict[str, Any]:
    """Answer a parked approval (C5 HITL). The continuation rides the EXISTING stream —
    this returns the client's `{status: 'resuming'}` ack and opens nothing."""
    try:
        return await asyncio.to_thread(_turns().resolve_approval, stream_id, body.model_dump())
    except ApprovalStale as exc:
        # 409 is the client's terminal signal (submit locks); the code is the closest
        # frozen member — the vendored client switches on the STATUS, never this string.
        raise ApiError(409, ErrorCode.IDEMPOTENCY_CONFLICT, str(exc)) from exc
    except ApprovalInvalid as exc:
        raise ApiError(400, ErrorCode.VALIDATION_ERROR, str(exc)) from exc


def _steer_refusal(status: int, code: str, message: str) -> JSONResponse:
    """The steer family's refusals carry a TOP-LEVEL `code` — the exact field the vendored
    client's useSteering switches on to degrade gracefully (NO_ACTIVE_RUN → plain send;
    STEER_UNSUPPORTED → client-side queue). The ApiError envelope would hide it."""
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "error": message,
            "generationProtocolVersion": GENERATION_PROTOCOL_VERSION,
        },
    )


@router.post("/v1/chat/turns/{stream_id}/steer", operation_id="steerChatTurn", status_code=202)
async def steer_chat_turn(stream_id: str, body: SteerRequest) -> JSONResponse:
    """Queue a follow-up for the live agent turn (C5, LC16). 202: queued, not applied —
    the drain happens at the loop's next turn boundary and publishes on_steer_applied."""
    try:
        payload = await asyncio.to_thread(_turns().queue_steer, stream_id, body.model_dump())
    except SteerNoRun as exc:
        return _steer_refusal(404, "NO_ACTIVE_RUN", str(exc))
    except SteerUnsupported as exc:
        return _steer_refusal(501, "STEER_UNSUPPORTED", str(exc))
    except SteerInvalid as exc:
        return _steer_refusal(400, "EMPTY_TEXT", str(exc))
    return JSONResponse(status_code=202, content=payload)


@router.post("/v1/chat/turns/{stream_id}/steer/cancel", operation_id="cancelChatSteer")
async def cancel_chat_steer(stream_id: str, body: SteerCancelRequest) -> JSONResponse:
    try:
        payload = await asyncio.to_thread(_turns().cancel_steer, stream_id, body.model_dump())
    except SteerNoRun as exc:
        return _steer_refusal(404, "NO_ACTIVE_RUN", str(exc))
    return JSONResponse(status_code=200, content=payload)


@router.get("/v1/chat/conversations", operation_id="listConversations")
async def list_conversations() -> ConversationsOut:
    docs = await asyncio.to_thread(_turns().conversations)
    return ConversationsOut(conversations=docs, nextCursor=None)


@router.get(
    "/v1/chat/conversations/{conversation_id}",
    operation_id="getConversation",
    responses=error_responses(404),
)
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    doc = await asyncio.to_thread(_turns().conversation, conversation_id)
    if doc is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"no conversation {conversation_id}")
    return doc


@router.get(
    "/v1/chat/conversations/{conversation_id}/messages",
    operation_id="getConversationMessages",
)
async def get_conversation_messages(conversation_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_turns().messages_for, conversation_id)
