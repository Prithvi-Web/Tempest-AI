"""The agent builder's persistence — LibreChat's `/api/agents` CRUD over the platform store.

C5 back half (PLAN-V3, ADR-0075/ADR-0078): the vendored client's no-code builder is adopted
whole and re-targeted; its wire shapes are answered here, from the ADR-0068 fallback document
store's `agents` collection (L33: platform data in the platform store, never a third store).

Two shapes matter and both are pinned by tests:

- **Every mutation answers the full agent doc.** The client's react-query layer merges the
  mutation result into every cached list row (`allAgentViewAndEditQueryKeys`); a partial answer
  goes stale on screen.
- **The list is the cursor envelope `{object, data, first_id, last_id, has_more, after}`** and
  `fetchAllAgentPages` walks it — `has_more` with a cursor that does not advance is an infinite
  loop in the client, not a style problem.

Tools deliberately have NO storage here: `list_tools()` is a projection of the boundary-D
manifest (`agent_tools.rs` → `agent-tools.json` → `load_manifest`), because L29's
`runtime_check --single-tool-registry` forbids a second listing source, and the picker showing
anything the dispatcher would refuse is the drift the law exists to prevent.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from tempest.agent.tools import load_manifest
from tempest_api.platformstore import PlatformStore

_COLLECTION = "agents"

#: What an update may touch. Everything else on the doc — identity, authorship, timestamps,
#: version history — is the store's to write, and a payload naming it is ignored rather than
#: obeyed (the client resends whole forms; obeying would let a stale form rewrite history).
_UPDATABLE = (
    "name",
    "description",
    "instructions",
    "additional_instructions",
    "model",
    "provider",
    "model_parameters",
    "tools",
    "tool_kwargs",
    "tool_resources",
    "conversation_starters",
    "avatar",
    "category",
    "recursion_limit",
    "end_after_tools",
    "hide_sequential_outputs",
    "artifacts",
    "support_contact",
    # Tempest extension (C5): the repository a tool-bearing agent works in. Tools act on a
    # checkout — the shadow worktree is cut from it, the proof runs against it — so an agent
    # with tools and no repository refuses to start a turn, actionably.
    "tempest_repo",
)

#: The version snapshot excludes the history itself and mutable bookkeeping.
_SNAPSHOT_EXCLUDES = frozenset({"versions"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AgentStore:
    """CRUD over the `agents` collection. One instance per data root, like `ChatTurns`."""

    def __init__(self, store: PlatformStore) -> None:
        self._store = store

    # ── writes ──────────────────────────────────────────────────────────────

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = f"agent_{uuid.uuid4().hex}"
        now = _now_iso()
        doc: dict[str, Any] = {
            "id": agent_id,
            # The client keys ACL lookups (useResourcePermissions) by the Mongo `_id` and
            # routes by `id`; local mode has one id namespace, so they are the same value.
            "_id": agent_id,
            "name": None,
            "description": None,
            "instructions": None,
            "avatar": None,
            "model": None,
            "model_parameters": {},
            "tools": [],
            "conversation_starters": [],
            "provider": str(payload.get("provider") or ""),
            "author": "local",
            "isPublic": False,
            "version": 1,
            "created_at": int(time.time() * 1000),
            "createdAt": now,
            "updatedAt": now,
        }
        for field in _UPDATABLE:
            if field in payload and payload[field] is not None:
                doc[field] = payload[field]
        doc["versions"] = [self._snapshot(doc)]
        self._store.put(_COLLECTION, agent_id, doc)
        return self._public(doc)

    def update(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        doc = self._store.get(_COLLECTION, agent_id)
        if doc is None:
            return None
        for field in _UPDATABLE:
            if field in payload:
                doc[field] = payload[field]
        return self._commit_new_version(agent_id, doc)

    def delete(self, agent_id: str) -> bool:
        return self._store.delete(_COLLECTION, agent_id)

    def duplicate(self, agent_id: str) -> dict[str, Any] | None:
        doc = self._store.get(_COLLECTION, agent_id)
        if doc is None:
            return None
        copy_payload = {k: doc.get(k) for k in _UPDATABLE if doc.get(k) is not None}
        copy_payload["name"] = f"{doc.get('name') or 'Agent'} (copy)"
        return self.create(copy_payload)

    def revert(self, agent_id: str, version_index: int) -> dict[str, Any] | None:
        """`version_index` counts NEWEST-FIRST, matching the panel the number comes from."""
        doc = self._store.get(_COLLECTION, agent_id)
        if doc is None:
            return None
        history = self._history(doc)
        if not 0 <= version_index < len(history):
            return None
        target = history[version_index]
        for field in _UPDATABLE:
            if field in target:
                doc[field] = target[field]
            else:
                doc.pop(field, None)
        return self._commit_new_version(agent_id, doc)

    # ── reads ───────────────────────────────────────────────────────────────

    def get(self, agent_id: str) -> dict[str, Any] | None:
        doc = self._store.get(_COLLECTION, agent_id)
        return None if doc is None else self._public(doc)

    def versions(self, agent_id: str) -> list[dict[str, Any]] | None:
        doc = self._store.get(_COLLECTION, agent_id)
        return None if doc is None else self._history(doc)

    def page(
        self,
        *,
        limit: int = 100,
        cursor: str = "",
        search: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        docs = self._store.list_ordered(_COLLECTION, order_by="updatedAt", descending=True)
        rows = [self._public(d) for d in docs]
        if search:
            needle = search.lower()
            rows = [
                r
                for r in rows
                if needle in str(r.get("name") or "").lower()
                or needle in str(r.get("description") or "").lower()
            ]
        if category and category != "all":
            rows = [r for r in rows if r.get("category") == category]
        start = 0
        if cursor:
            ids = [r["id"] for r in rows]
            # A cursor that no longer exists (the row was deleted) restarts the walk rather
            # than spinning: the client tolerates a re-served row, never a stuck loop.
            start = ids.index(cursor) + 1 if cursor in ids else 0
        page = rows[start : start + max(1, limit)]
        has_more = start + len(page) < len(rows)
        return {
            "object": "list",
            "data": page,
            "first_id": page[0]["id"] if page else "",
            "last_id": page[-1]["id"] if page else "",
            "has_more": has_more,
            "after": page[-1]["id"] if (page and has_more) else "",
        }

    @staticmethod
    def categories() -> list[dict[str, Any]]:
        """The marketplace's category tabs. Local mode has one world, honestly labelled."""
        return [{"value": "all", "label": "All", "description": ""}]

    @staticmethod
    def list_tools() -> list[dict[str, Any]]:
        """The builder's tool picker — a PROJECTION of the boundary-D manifest (L29).

        `pluginKey` is the dispatch name the orchestrator's `Dispatcher` resolves; showing any
        other set here would offer tools the runtime refuses or hide ones it serves.
        """
        plugins: list[dict[str, Any]] = []
        for name, spec in load_manifest().items():
            plugins.append(
                {
                    "name": name.replace("_", " ").capitalize(),
                    "pluginKey": name,
                    "description": spec.description,
                    "authenticated": True,
                    "authConfig": [],
                }
            )
        return plugins

    # ── internals ───────────────────────────────────────────────────────────

    def _commit_new_version(self, agent_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        doc["version"] = int(doc.get("version") or 0) + 1
        doc["updatedAt"] = _now_iso()
        history = list(doc.get("versions") or [])
        history.append(self._snapshot(doc))
        doc["versions"] = history
        self._store.put(_COLLECTION, agent_id, doc)
        return self._public(doc)

    @staticmethod
    def _snapshot(doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k not in _SNAPSHOT_EXCLUDES}

    @staticmethod
    def _public(doc: dict[str, Any]) -> dict[str, Any]:
        """The wire doc: everything except the history, which has its own endpoint."""
        return {k: v for k, v in doc.items() if k != "versions"}

    @staticmethod
    def _history(doc: dict[str, Any]) -> list[dict[str, Any]]:
        """Snapshots newest-first, the order the version panel renders and indexes."""
        return list(reversed(list(doc.get("versions") or [])))
