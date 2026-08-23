"""Chat-turn wire schemas (boundary A). The START body is the vendored client's own TPayload
riding through the host verbatim — modeled with `extra='allow'` so fields this surface does
not read yet (spec, promptPrefix, files, …) survive into `model_dump()` for the turn engine
to consult as they come into scope, rather than being silently shed at the boundary."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class StartChatTurnRequest(BaseModel):
    # `protected_namespaces=()` because upstream's field really is named `model_parameters`,
    # and renaming the wire to appease a lint would break the one client we serve.
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    text: str = ""
    endpoint: str
    conversationId: str | None = None
    parentMessageId: str | None = None
    messageId: str | None = None
    isRegenerate: bool = False
    model_parameters: dict[str, Any] | None = None


class ChatTurnAck(BaseModel):
    streamId: str
    conversationId: str
    generationCreatedAt: int
    status: str
    generationProtocolVersion: int


class TurnEventOut(BaseModel):
    seq: int
    frame: dict[str, Any]


class TurnEventsOut(BaseModel):
    streamId: str
    status: str
    events: list[TurnEventOut]


class ChatTurnStatusOut(BaseModel):
    active: bool
    conversationId: str
    generationProtocolVersion: int
    status: str | None = None
    streamId: str | None = None
    generationCreatedAt: int | None = None
    #: The vendored status contract's own name for the epoch; served beside the long form
    #: so no host has to translate.
    createdAt: int | None = None


class ActiveTurnsOut(BaseModel):
    activeJobIds: list[str]


class CancelTurnOut(BaseModel):
    success: bool
    generationProtocolVersion: int
    aborted: str | None = None
    settled: bool | None = None


class ConversationsOut(BaseModel):
    conversations: list[dict[str, Any]]
    nextCursor: str | None = None
