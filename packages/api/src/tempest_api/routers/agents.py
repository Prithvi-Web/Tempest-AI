"""Agent CRUD + tools endpoints (PLAN-V3 C5, ADR-0075) — the boundary-A surface behind the
desktop host's `/api/agents` intercepts.

Thin by design: shapes and rules live in `agentstore.AgentStore`; this file is routing, error
mapping, and the per-data-root registry (same discipline as `routers/chat.py`). Literal routes
(`/tools`, `/categories`) are declared BEFORE `/{agent_id}` so an agent named `tools` cannot
shadow the picker — the exact collision the vendored Express router carries a warning about.
"""

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from tempest_api.agentstore import AgentStore
from tempest_api.errors import ApiError, error_responses
from tempest_api.localprove import data_dir
from tempest_api.platformstore import PlatformStore
from tempest_api.schemas import ErrorCode
from tempest_api.schemas.agents import AgentIn, RevertIn

router = APIRouter(tags=["agents"])

_REGISTRY: dict[str, AgentStore] = {}
_REGISTRY_LOCK = threading.Lock()


def _agents() -> AgentStore:
    """One `AgentStore` per data root — same lifetime rule as `routers/chat.py::_turns`."""
    root = str(data_dir())
    with _REGISTRY_LOCK:
        agents = _REGISTRY.get(root)
        if agents is None:
            agents = AgentStore(PlatformStore(Path(root) / "platform" / "store.sqlite3"))
            _REGISTRY[root] = agents
        return agents


def _or_404(found: dict[str, Any] | list[dict[str, Any]] | None, agent_id: str) -> Any:
    if found is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, f"no agent {agent_id}")
    return found


@router.get("/v1/agents/tools", operation_id="listAgentTools")
async def list_agent_tools() -> list[dict[str, Any]]:
    return AgentStore.list_tools()


@router.get("/v1/agents/categories", operation_id="listAgentCategories")
async def list_agent_categories() -> list[dict[str, Any]]:
    return AgentStore.categories()


@router.get("/v1/agents", operation_id="listAgents")
async def list_agents(
    limit: int = 100, cursor: str = "", search: str = "", category: str = ""
) -> dict[str, Any]:
    return _agents().page(limit=limit, cursor=cursor, search=search, category=category)


@router.post("/v1/agents", operation_id="createAgent", status_code=201)
async def create_agent(body: AgentIn) -> dict[str, Any]:
    return _agents().create(body.model_dump())


@router.get("/v1/agents/{agent_id}", operation_id="getAgent", responses=error_responses(404, 422))
async def get_agent(agent_id: str) -> dict[str, Any]:
    found: dict[str, Any] = _or_404(_agents().get(agent_id), agent_id)
    return found


@router.get(
    "/v1/agents/{agent_id}/expanded",
    operation_id="getExpandedAgent",
    responses=error_responses(404, 422),
)
async def get_expanded_agent(agent_id: str) -> dict[str, Any]:
    # Local single-user mode has no permission projection to strip; expanded IS the doc.
    found: dict[str, Any] = _or_404(_agents().get(agent_id), agent_id)
    return found


@router.patch(
    "/v1/agents/{agent_id}", operation_id="updateAgent", responses=error_responses(404, 422)
)
async def update_agent(agent_id: str, body: AgentIn) -> dict[str, Any]:
    # Only the fields the payload actually SENT may change: a whole-form resend with nulls
    # must not blank fields the form never rendered.
    found: dict[str, Any] = _or_404(
        _agents().update(agent_id, body.model_dump(exclude_unset=True)), agent_id
    )
    return found


@router.delete(
    "/v1/agents/{agent_id}", operation_id="deleteAgent", responses=error_responses(404, 422)
)
async def delete_agent(agent_id: str) -> dict[str, str]:
    if not _agents().delete(agent_id):
        raise ApiError(404, ErrorCode.NOT_FOUND, f"no agent {agent_id}")
    return {"message": "Agent deleted"}


@router.post(
    "/v1/agents/{agent_id}/duplicate",
    operation_id="duplicateAgent",
    status_code=201,
    responses=error_responses(404, 422),
)
async def duplicate_agent(agent_id: str) -> dict[str, Any]:
    copy: dict[str, Any] = _or_404(_agents().duplicate(agent_id), agent_id)
    # The tuple-shaped upstream answer: the agent plus its (empty, local-mode) actions.
    return {"agent": copy, "actions": []}


@router.get(
    "/v1/agents/{agent_id}/versions",
    operation_id="listAgentVersions",
    responses=error_responses(404, 422),
)
async def list_agent_versions(agent_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = _or_404(_agents().versions(agent_id), agent_id)
    return found


@router.post(
    "/v1/agents/{agent_id}/revert",
    operation_id="revertAgentVersion",
    responses=error_responses(404, 422),
)
async def revert_agent_version(agent_id: str, body: RevertIn) -> dict[str, Any]:
    found: dict[str, Any] = _or_404(_agents().revert(agent_id, body.version_index), agent_id)
    return found
