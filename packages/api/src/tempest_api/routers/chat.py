"""Chat-turn + conversation endpoints (PLAN-V3 C5, ADR-0078) — the boundary-A surface behind
the desktop host's `/api/agents/chat*`, `/api/convos` and `/api/messages` intercepts.

Same decoupling as local prove: the start answers immediately, the turn runs on its own
thread, and the ledger is polled — here at token cadence by the host's stream poller."""

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from tempest.inference import cost
from tempest_api.chatturn import ChatTurns, TurnConflict, TurnRejected
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
    StartChatTurnRequest,
    TurnEventsOut,
)

router = APIRouter(tags=["chat"])

_REGISTRY: dict[str, ChatTurns] = {}


def _turns() -> ChatTurns:
    """One `ChatTurns` per data root, created on first use. Keyed by the resolved directory
    so tests pointing `TEMPEST_DATA_DIR` at fresh roots get fresh worlds."""
    root = str(data_dir())
    turns = _REGISTRY.get(root)
    if turns is None:
        turns = ChatTurns(
            PlatformStore(Path(root) / "platform" / "store.sqlite3"),
            env_provider=lambda: dict(os.environ),
            meter=cost.Meter(repo=Path(root) / "platform"),
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


@router.get("/v1/chat/conversations", operation_id="listConversations")
async def list_conversations() -> ConversationsOut:
    docs = await asyncio.to_thread(_turns().conversations)
    return ConversationsOut(conversations=docs, nextCursor=None)


@router.get(
    "/v1/chat/conversations/{conversation_id}/messages",
    operation_id="getConversationMessages",
)
async def get_conversation_messages(conversation_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_turns().messages_for, conversation_id)
