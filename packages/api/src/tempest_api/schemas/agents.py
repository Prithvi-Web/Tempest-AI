"""Agent CRUD wire schemas (boundary A, PLAN-V3 C5). The create/update body is the vendored
builder's own `AgentCreateParams`/`AgentUpdateParams` riding through the host — `extra='allow'`
for the same reason as the chat TPayload: fields this surface does not read yet must survive
into `model_dump()` rather than being silently shed at the boundary. `AgentStore._UPDATABLE`
is the actual write filter; the schema is transport, not policy."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentIn(BaseModel):
    # `protected_namespaces=()`: upstream's field really is named `model_parameters`.
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    provider: str | None = None
    model: str | None = None
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    tools: list[Any] | None = None
    model_parameters: dict[str, Any] | None = None


class RevertIn(BaseModel):
    version_index: int
