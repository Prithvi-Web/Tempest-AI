"""C5 back half — the agent builder's CRUD surface (PLAN-V3 C5, ADR-0075/ADR-0078, LC08/LC09).

The vendored client's no-code builder speaks LibreChat's `/api/agents` wire; the desktop host
intercepts it and delegates here over boundary A. These tests pin the SHAPES the client's
react-query layer actually reads (recon'd from `data-provider/Agents`): the list envelope's
`{object, data, first_id, last_id, has_more, after}`, the full agent doc coming back from every
mutation (stale-list merge depends on it), version history growing on update, and — L29's tooth —
`GET /api/agents/tools` projecting the ONE boundary-D manifest, never a second listing source.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tempest.agent.tools import load_manifest


@pytest.fixture
def agents_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A fresh data root per test, so every test gets an empty agents collection."""
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    yield tmp_path / "appdata"


def _create(api: Any, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "name": "Docs helper",
        "description": "Answers questions about the docs",
        "instructions": "Be brief.",
        "tools": [],
    }
    payload.update(overrides)
    resp = api.client.post("/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


class TestCrudLifecycle:
    def test_create_returns_the_full_agent_the_client_merges_into_its_lists(
        self, api: Any, agents_env: Path
    ) -> None:
        agent = _create(api)
        assert agent["id"].startswith("agent_")
        assert agent["name"] == "Docs helper"
        assert agent["provider"] == "anthropic"
        assert agent["model"] == "claude-sonnet-5"
        assert agent["instructions"] == "Be brief."
        assert agent["version"] == 1
        assert agent["author"] == "local"
        assert isinstance(agent["created_at"], int), "the client type requires a number"
        assert agent["model_parameters"] == {}
        assert agent["tools"] == []
        # The version HISTORY is internal; the wire doc must not drag it around.
        assert "versions" not in agent

    def test_get_and_expanded_both_answer_the_doc(self, api: Any, agents_env: Path) -> None:
        agent = _create(api)
        got = api.client.get(f"/v1/agents/{agent['id']}")
        assert got.status_code == 200
        assert got.json()["id"] == agent["id"]
        expanded = api.client.get(f"/v1/agents/{agent['id']}/expanded")
        assert expanded.status_code == 200
        assert expanded.json()["instructions"] == "Be brief."

    def test_a_missing_agent_is_a_404_with_a_reason(self, api: Any, agents_env: Path) -> None:
        got = api.client.get("/v1/agents/agent_nope")
        assert got.status_code == 404
        assert "agent_nope" in got.text

    def test_update_bumps_the_version_and_keeps_history(self, api: Any, agents_env: Path) -> None:
        agent = _create(api)
        resp = api.client.patch(
            f"/v1/agents/{agent['id']}",
            json={"name": "Docs helper v2", "instructions": "Be thorough."},
        )
        assert resp.status_code == 200, resp.text
        updated = resp.json()
        assert updated["name"] == "Docs helper v2"
        assert updated["version"] == 2
        assert updated["provider"] == "anthropic", "unmentioned fields survive an update"

        versions = api.client.get(f"/v1/agents/{agent['id']}/versions").json()
        assert len(versions) == 2
        assert versions[0]["name"] == "Docs helper v2", "newest first"
        assert versions[1]["name"] == "Docs helper"

    def test_revert_restores_an_old_version_as_a_new_one(self, api: Any, agents_env: Path) -> None:
        agent = _create(api)
        api.client.patch(f"/v1/agents/{agent['id']}", json={"name": "Renamed"})
        resp = api.client.post(f"/v1/agents/{agent['id']}/revert", json={"version_index": 1})
        assert resp.status_code == 200, resp.text
        reverted = resp.json()
        assert reverted["name"] == "Docs helper", "the index counts newest-first, like the panel"
        assert reverted["version"] == 3, "a revert is a NEW version, never rewritten history"

    def test_delete_removes_and_answers_the_shape_the_client_reads(
        self, api: Any, agents_env: Path
    ) -> None:
        agent = _create(api)
        resp = api.client.delete(f"/v1/agents/{agent['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"message": "Agent deleted"}
        assert api.client.get(f"/v1/agents/{agent['id']}").status_code == 404
        assert api.client.delete(f"/v1/agents/{agent['id']}").status_code == 404

    def test_duplicate_copies_the_config_under_a_fresh_identity(
        self, api: Any, agents_env: Path
    ) -> None:
        agent = _create(api)
        resp = api.client.post(f"/v1/agents/{agent['id']}/duplicate")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        copy = body["agent"]
        assert body["actions"] == []
        assert copy["id"] != agent["id"]
        assert copy["instructions"] == "Be brief."
        assert copy["name"] == "Docs helper (copy)"
        assert copy["version"] == 1


class TestListEnvelope:
    def test_the_list_speaks_the_cursor_envelope_the_client_walks(
        self, api: Any, agents_env: Path
    ) -> None:
        first = _create(api, name="First")
        time.sleep(0.02)  # updatedAt granularity: ordering must be observable
        second = _create(api, name="Second")
        resp = api.client.get("/v1/agents")
        assert resp.status_code == 200
        page = resp.json()
        assert page["object"] == "list"
        names = [a["name"] for a in page["data"]]
        assert names == ["Second", "First"], "most recently touched first"
        assert page["first_id"] == second["id"]
        assert page["last_id"] == first["id"]
        assert page["has_more"] is False

    def test_paging_terminates_the_clients_fetch_all_loop(self, api: Any, agents_env: Path) -> None:
        """`fetchAllAgentPages` walks `has_more`/`after` — a static cursor spins forever."""
        made = [_create(api, name=f"a{i}") for i in range(5)]
        seen: list[str] = []
        cursor = ""
        for _ in range(10):
            url = "/v1/agents?limit=2" + (f"&cursor={cursor}" if cursor else "")
            page = api.client.get(url).json()
            seen.extend(a["id"] for a in page["data"])
            if not page["has_more"]:
                break
            assert page["after"], "has_more without a cursor is an infinite loop"
            cursor = page["after"]
        else:
            raise AssertionError("paging never terminated")
        assert sorted(seen) == sorted(a["id"] for a in made)
        assert len(seen) == len(set(seen)), "no row served twice"

    def test_search_filters_by_name_and_description(self, api: Any, agents_env: Path) -> None:
        _create(api, name="Docs helper")
        _create(api, name="Refactorer", description="rewrites code")
        page = api.client.get("/v1/agents?search=docs").json()
        assert [a["name"] for a in page["data"]] == ["Docs helper"]
        page = api.client.get("/v1/agents?search=REWRITES").json()
        assert [a["name"] for a in page["data"]] == ["Refactorer"]


class TestOneToolRegistry:
    def test_the_tools_listing_is_a_projection_of_the_boundary_d_manifest(
        self, api: Any, agents_env: Path
    ) -> None:
        """L29/LC09: `runtime_check --single-tool-registry` forbids a second listing source.
        The builder's tool picker therefore shows exactly the committed manifest — same names,
        same descriptions, nothing invented, nothing dropped."""
        resp = api.client.get("/v1/agents/tools")
        assert resp.status_code == 200
        plugins = resp.json()
        manifest = load_manifest()
        assert {p["pluginKey"] for p in plugins} == set(manifest)
        by_key = {p["pluginKey"]: p for p in plugins}
        for name, spec in manifest.items():
            assert by_key[name]["description"] == spec.description
            assert by_key[name]["name"], "a tool with no display name renders as a blank row"
            assert by_key[name]["authenticated"] is True, "local tools need no external auth"

    def test_categories_answer_the_marketplace_shape(self, api: Any, agents_env: Path) -> None:
        resp = api.client.get("/v1/agents/categories")
        assert resp.status_code == 200
        rows = resp.json()
        assert isinstance(rows, list) and rows, "an empty list renders an empty marketplace"
        assert all({"value", "label"} <= set(r) for r in rows)


class TestMissingAgentsAreNotFound:
    """Every mutation that can name an agent that is gone answers 404, not 500 and not 200.

    This is the trap the C5 session paid in full: the vendored builder reads
    `error.response.status`, and `engine_reply_passthrough` exists precisely so the ENGINE's
    own 404 survives the host seam instead of being flattened into a 502. A store method that
    returned a fabricated empty doc — or raised — instead of `None` would turn "no such agent"
    into "the backend is broken" in front of the owner, and every one of these arms was
    unexercised until the 100% combined-coverage gate named it.
    """

    def test_updating_a_missing_agent_is_a_404(self, api: Any, agents_env: Path) -> None:
        resp = api.client.patch("/v1/agents/agent_ghost", json={"name": "Renamed"})
        assert resp.status_code == 404, resp.text
        assert "agent_ghost" in resp.text

    def test_duplicating_a_missing_agent_is_a_404(self, api: Any, agents_env: Path) -> None:
        resp = api.client.post("/v1/agents/agent_ghost/duplicate")
        assert resp.status_code == 404, resp.text
        assert "agent_ghost" in resp.text

    def test_reverting_a_missing_agent_is_a_404(self, api: Any, agents_env: Path) -> None:
        resp = api.client.post("/v1/agents/agent_ghost/revert", json={"version_index": 0})
        assert resp.status_code == 404, resp.text

    def test_listing_versions_of_a_missing_agent_is_a_404(self, api: Any, agents_env: Path) -> None:
        assert api.client.get("/v1/agents/agent_ghost/versions").status_code == 404

    def test_a_duplicate_of_a_missing_agent_creates_nothing(
        self, api: Any, agents_env: Path
    ) -> None:
        """The refusal must not have a side effect: a 404 that still wrote a copy would leave
        an orphan agent named '(copy)' in the owner's list with nothing to copy from."""
        before = api.client.get("/v1/agents").json()["data"]
        api.client.post("/v1/agents/agent_ghost/duplicate")
        after = api.client.get("/v1/agents").json()["data"]
        assert [r["id"] for r in after] == [r["id"] for r in before]


class TestRevertBounds:
    def test_a_version_index_past_the_end_is_a_404_and_changes_nothing(
        self, api: Any, agents_env: Path
    ) -> None:
        """`revert` counts NEWEST-FIRST over a history that is one entry long for a fresh
        agent. Index 5 names a version that does not exist; answering 200 would hand the
        builder an unchanged doc and let it report a revert that never happened."""
        agent = _create(api, name="Bounded")
        versions = api.client.get(f"/v1/agents/{agent['id']}/versions").json()
        assert len(versions) == 1, "a fresh agent has exactly its creation snapshot"

        resp = api.client.post(
            f"/v1/agents/{agent['id']}/revert", json={"version_index": len(versions) + 4}
        )
        assert resp.status_code == 404, resp.text

        after = api.client.get(f"/v1/agents/{agent['id']}").json()
        assert after["name"] == "Bounded"
        assert len(api.client.get(f"/v1/agents/{agent['id']}/versions").json()) == 1, (
            "a refused revert must not append a version — the history is the audit trail"
        )

    def test_a_negative_version_index_is_a_404(self, api: Any, agents_env: Path) -> None:
        """`-1` is a valid Python index into the history list and would silently revert to the
        OLDEST version. The bound is `0 <= i < len`, and this is the arm that proves the lower
        half of it bites."""
        agent = _create(api, name="Bounded")
        resp = api.client.post(f"/v1/agents/{agent['id']}/revert", json={"version_index": -1})
        assert resp.status_code in (404, 422), resp.text
        assert api.client.get(f"/v1/agents/{agent['id']}").json()["name"] == "Bounded"


class TestCategoryFilter:
    def test_the_category_filter_narrows_the_list(self, api: Any, agents_env: Path) -> None:
        writer = _create(api, name="Writer", category="writing")
        coder = _create(api, name="Coder", category="code")

        rows = api.client.get("/v1/agents", params={"category": "code"}).json()["data"]
        ids = [r["id"] for r in rows]
        assert coder["id"] in ids, "the matching agent must survive the filter"
        assert writer["id"] not in ids, "a non-matching agent must be filtered out"
        assert len(ids) == 1

    def test_the_all_sentinel_filters_nothing(self, api: Any, agents_env: Path) -> None:
        """`all` is the picker's default value, not a real category — treating it as one would
        answer an empty marketplace to a user who selected 'All'."""
        writer = _create(api, name="Writer", category="writing")
        coder = _create(api, name="Coder", category="code")
        rows = api.client.get("/v1/agents", params={"category": "all"}).json()["data"]
        assert {r["id"] for r in rows} == {writer["id"], coder["id"]}

    def test_an_unmatched_category_answers_an_empty_page_not_everything(
        self, api: Any, agents_env: Path
    ) -> None:
        """The failure mode a filter has when it is wired backwards: it returns the whole list.
        An empty result here is the assertion — with a lower bound proving the agents exist."""
        _create(api, name="Writer", category="writing")
        assert len(api.client.get("/v1/agents").json()["data"]) == 1
        rows = api.client.get("/v1/agents", params={"category": "nonesuch"}).json()["data"]
        assert rows == []
