"""The MCP tool surface, called in-process (F16).

`mcp_check` drives the server over a real pipe and is the gate. These call the handlers directly,
so the states that are awkward to reach over a wire — a repository that is not a repository, a
bundle with no divergence, a contract that classifies — get pinned cheaply.

Every proof here is real (L4): real git repositories, real execution, real bundles.

States enumerated before the tests (trap 43): the handshake · an unknown method · an unknown tool
· a call with no arguments object · a behaviour change · a no-op refactor · a bundle with no
divergence · a contract that forbids · a contract that permits · no contract at all.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tempest.agent import contracts as contracts_mod
from tempest.mcp import server as server_mod
from tempest.mcp.protocol import METHOD_NOT_FOUND, Request, RpcError

from ..helpers_first_party import mark_first_party

_BASE = "def total(xs):\n    return sum(xs)\n"
_DIVERGENT = "def total(xs):\n    return sum(xs) + 1\n"
_REFACTOR = "def total(xs):\n    result = sum(xs)\n    return result\n"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )
    return done.stdout.strip()


def _repo(tmp_path: Path, head: str) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text(_BASE, encoding="utf-8")
    mark_first_party(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text(head, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _call(name: str, **arguments: Any) -> dict[str, Any]:
    result = server_mod.handle(
        Request(id=1, method="tools/call", params={"name": name, "arguments": arguments})
    )
    return json.loads(result["content"][0]["text"])  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def _dev() -> Iterator[None]:
    """Half of what makes the fixture repository first-party (ADR-0008); `mark_first_party`
    writes the other half and checks that both took. Set HERE rather than inherited from the
    ambient shell, so this module measures the same backend on its own that it does in CI — and
    on a MonkeyPatch of its OWN, because a test that calls `monkeypatch.undo()` to drop its own
    patch would otherwise silently drop this one with it (which is precisely how the resume
    tests lost the marker and fell back to the tier ladder mid-test)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TEMPEST_DEV", "1")
        mp.setenv("TEMPEST_NO_POWER_PAUSE", "1")
        yield


class TestTheSurface:
    def test_the_handshake_names_the_protocol_and_the_server(self) -> None:
        got = server_mod.handle(Request(id=1, method="initialize", params={}))
        assert got["protocolVersion"] == server_mod.PROTOCOL_VERSION
        assert got["serverInfo"]["name"] == "tempest"
        assert got["capabilities"] == {"tools": {}}

    def test_the_advertised_list_and_the_handlers_match_in_both_directions(self) -> None:
        """The same rule boundary D holds the agent tools to: a tool advertised and not
        implemented wastes a caller's turn, and one implemented and not advertised is invisible."""
        advertised = {t["name"] for t in server_mod.handle(Request(1, "tools/list", {}))["tools"]}
        assert advertised == set(server_mod._HANDLERS)

    def test_mutation_score_is_NOT_advertised_because_it_does_not_exist_yet(self) -> None:
        """F16 names it; F9 (Phase 24) has not been built. Declaring a tool that always refuses
        would spend a caller's turn to tell them so."""
        assert "mutation_score" not in server_mod._HANDLERS

    def test_an_unknown_method_is_refused_by_name(self) -> None:
        with pytest.raises(RpcError) as caught:
            server_mod.handle(Request(1, "resources/list", {}))
        assert caught.value.code == METHOD_NOT_FOUND

    def test_a_call_without_an_arguments_object_is_refused(self) -> None:
        with pytest.raises(RpcError, match="arguments"):
            server_mod.handle(Request(1, "tools/call", {"name": "prove"}))

    def test_ping_answers_empty(self) -> None:
        assert server_mod.handle(Request(1, "ping", {})) == {}

    def test_an_unknown_tool_names_the_ones_that_exist(self) -> None:
        """A model that asked for the wrong tool should be able to fix its next call from the
        refusal alone — the alternative is a turn spent guessing."""
        with pytest.raises(RpcError) as caught:
            server_mod.handle(Request(1, "tools/call", {"name": "mutation_score", "arguments": {}}))
        assert caught.value.code == METHOD_NOT_FOUND
        assert "mutation_score" in caught.value.message
        assert "prove" in caught.value.message


class TestTheEntryPoint:
    """`python -m tempest.mcp` is what a client spawns, so it is exercised the way a client
    would: as a module, over a real (empty) stream."""

    def test_main_serves_until_its_input_ends_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.stdout", io.StringIO())
        assert server_mod.main() == 0

    def test_the_module_entry_point_runs_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io
        import runpy

        monkeypatch.setattr(
            "sys.stdin", io.StringIO('{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n')
        )
        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        with pytest.raises(SystemExit) as caught:
            runpy.run_module("tempest.mcp", run_name="__main__")
        assert caught.value.code == 0
        assert json.loads(out.getvalue())["result"] == {}


class TestProve:
    def test_a_behaviour_change_is_DIVERGENT_with_the_input_that_shows_it(
        self, tmp_path: Path
    ) -> None:
        repo, base, head = _repo(tmp_path, _DIVERGENT)
        got = _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)
        assert got["verdict"] == "DIVERGENT"
        (target,) = got["targets"]
        assert target["qualname"] == "total"
        assert target["divergences"][0]["minimized_args"]
        assert Path(got["bundle_dir"]).is_dir()

    def test_a_no_op_refactor_is_not_reported_as_a_change(self, tmp_path: Path) -> None:
        """The other half of being useful. An oracle that called every edit a change would be
        ignored within a day."""
        repo, base, head = _repo(tmp_path, _REFACTOR)
        assert _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)["verdict"] == (
            "EQUIVALENT_UNDER_BUDGET"
        )

    def test_a_missing_revision_says_which_argument(self, tmp_path: Path) -> None:
        repo, base, _head = _repo(tmp_path, _DIVERGENT)
        with pytest.raises(RpcError, match="'head'"):
            _call("prove", repo=str(repo), base=base)


class TestTheEvidenceTools:
    def test_minimize_repro_returns_the_smallest_input_and_its_script(self, tmp_path: Path) -> None:
        repo, base, head = _repo(tmp_path, _DIVERGENT)
        proved = _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)
        got = _call("minimize_repro", bundle_dir=proved["bundle_dir"], qualname="total")
        assert got["divergences"][0]["repro_script"], "a repro nobody can run is not a repro"

    def test_minimize_repro_on_a_clean_bundle_refuses_rather_than_inventing_one(
        self, tmp_path: Path
    ) -> None:
        repo, base, head = _repo(tmp_path, _REFACTOR)
        proved = _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)
        with pytest.raises(RpcError, match="no divergence"):
            _call("minimize_repro", bundle_dir=proved["bundle_dir"])

    def test_a_contract_classifies_the_divergences(self, tmp_path: Path) -> None:
        repo, base, head = _repo(tmp_path, _DIVERGENT)
        proved = _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)
        contracts_mod.save(
            repo,
            "task",
            contracts_mod.IntentContract(intent="speed it up", must_not_change=("total",)),
        )
        got = _call(
            "check_intent_contract",
            bundle_dir=proved["bundle_dir"],
            repo=str(repo),
            task_id="task",
        )
        assert got["contract"]["must_not_change"] == ["total"]
        assert {d["classification"] for d in got["divergences"]} == {contracts_mod.UNINTENDED}

    def test_with_no_contract_everything_is_UNCLASSIFIED_rather_than_approved(
        self, tmp_path: Path
    ) -> None:
        repo, base, head = _repo(tmp_path, _DIVERGENT)
        proved = _call("prove", repo=str(repo), base=base, head=head, max_inputs=8)
        got = _call("check_intent_contract", bundle_dir=proved["bundle_dir"])
        assert got["contract"] is None
        assert {d["classification"] for d in got["divergences"]} == {contracts_mod.UNCLASSIFIED}

    def test_explain_behavior_cites_an_observation_for_every_claim(self, tmp_path: Path) -> None:
        repo, _base, _head = _repo(tmp_path, _DIVERGENT)
        got = _call("explain_behavior", repo=str(repo), qualname="total", max_inputs=10)
        assert got["claims"] and all(c["observations"] for c in got["claims"])
        assert "observation" in got["markdown"]
