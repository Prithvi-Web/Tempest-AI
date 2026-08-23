"""C5 back half — agent turns through the ONE runtime (LC08/LC14, ADR-0075, L28/L29/L31).

The re-target's teeth: a chat turn addressed to an agent WITH tools dispatches through
`run_task` — the same loop, the same shadow worktree, the same engine verdict as every other
entry point — while a persona agent (no tools) streams like plain chat with its instructions
as the system prompt. Every test drives the REAL public surface (start → ledger → frames →
final) against a real loopback peer and, for the tool path, a real git repository (L4).

The forge test at the bottom is this path's `gate_audit` anchor: the chat surface never
stores or surfaces a verdict of its own — the reserved vocabulary lives in the ENGINE's
records alone (L31), and the model's narration reaching the user as narration is exactly
L17's line between text and evidence.
"""

import json
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from tempest.dev._first_party import mark_first_party
from tempest_api.routers import chat as chat_router


class AgentPeer:
    """An OpenAI-wire peer speaking BOTH shapes: scripted non-stream replies for the
    orchestrator's `complete()` calls, and a plain streamed answer for persona turns.

    `script` is consumed one entry per non-stream request; each entry is either
    `{"text": ...}` or `{"text": ..., "tool_calls": [{"name": ..., "arguments": {...}}]}`.
    An exhausted script answers plain text — the model "finishing".
    """

    def __init__(self) -> None:
        self.script: list[dict[str, Any]] = []
        self.stream_chunks: list[str] = ["Hel", "lo"]
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def next_reply(self) -> dict[str, Any]:
        with self._lock:
            return self.script.pop(0) if self.script else {"text": "all done"}


def _completion_body(reply: dict[str, Any]) -> bytes:
    calls = [
        {
            "id": f"call_{index}",
            "type": "function",
            "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}))},
        }
        for index, c in enumerate(reply.get("tool_calls", []))
    ]
    message: dict[str, Any] = {"role": "assistant", "content": reply.get("text", "")}
    if calls:
        message["tool_calls"] = calls
    return json.dumps(
        {
            "choices": [
                {"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7},
        }
    ).encode()


@pytest.fixture
def agent_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AgentPeer]:
    peer = AgentPeer()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw)
            peer.requests.append(body)
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in peer.stream_chunks:
                    frame = json.dumps({"choices": [{"delta": {"content": chunk}}]})
                    self.wfile.write(b"data: " + frame.encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")
                return
            payload = _completion_body(peer.next_reply())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setenv("TEMPEST_DEV", "1")
    monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_OLLAMA", f"http://127.0.0.1:{server.server_port}/v1")
    chat_router._REGISTRY.clear()
    try:
        yield peer
    finally:
        chat_router._REGISTRY.clear()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
        "HOME": str(root),
    }
    subprocess.run(
        ["git", "-C", str(root), "init", "-b", "main"], check=True, capture_output=True, env=env
    )
    (root / "app.py").write_text("def total(xs):\n    return sum(xs)\n", encoding="utf-8")
    mark_first_party(root)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "base"], check=True, capture_output=True, env=env
    )
    return root


def _make_agent(api: Any, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": "Ollama (local)",
        "model": "test-model",
        "name": "Turn agent",
        "instructions": "Answer like a lighthouse keeper.",
    }
    payload.update(overrides)
    resp = api.client.post("/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _start(api: Any, agent_id: str, text: str = "Do the thing") -> dict[str, Any]:
    resp = api.client.post(
        "/v1/chat/turns",
        json={"text": text, "endpoint": "agents", "agent_id": agent_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _wait_terminal(api: Any, stream_id: str, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = api.client.get(f"/v1/chat/turns/{stream_id}/events?after=0").json()
        if payload["status"] not in ("active", "unknown"):
            return payload  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError(f"turn {stream_id} still active after {timeout}s")


def _frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [event["frame"] for event in payload["events"]]


_RESERVED = ("DIVERGENT", "EQUIVALENT_UNDER_BUDGET", "UNPROVEN", "WEAK_EVIDENCE")


class TestPersonaAgents:
    def test_a_toolless_agent_streams_with_its_instructions(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        agent = _make_agent(api)
        ack = _start(api, agent["id"], "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        final = _frames(payload)[-1]
        assert final["final"] is True
        assert final["responseMessage"]["text"] == "Hello"[:0] + "Hello"
        # The persona reached the wire: the streamed request carries the instructions.
        streamed = [r for r in agent_env.requests if r.get("stream")]
        assert streamed, "the persona turn must stream like plain chat"
        assert "lighthouse keeper" in json.dumps(streamed[0])

    def test_an_unknown_agent_is_a_400_not_a_mystery(self, api: Any, agent_env: AgentPeer) -> None:
        resp = api.client.post(
            "/v1/chat/turns",
            json={"text": "hi", "endpoint": "agents", "agent_id": "agent_nope"},
        )
        assert resp.status_code == 400
        assert "agent_nope" in resp.text


class TestToolBearingTurns:
    def test_the_turn_dispatches_through_the_one_runtime(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The headline: the model writes through the ORCHESTRATOR (shadow worktree, real
        prove, durable turnlog) and the chat shows narration — never a verdict of its own."""
        agent = _make_agent(
            api,
            tools=["read_file", "write_file"],
            tempest_repo=str(repo),
        )
        agent_env.script = [
            {
                "text": "Editing now.",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "app.py",
                            "contents": "def total(xs):\n    return sum(xs) + 1\n",
                        },
                    }
                ],
            },
            {"text": "I added one to the sum."},
        ]
        ack = _start(api, agent["id"], "Make total bigger")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        final = _frames(payload)[-1]
        assert "added one" in final["responseMessage"]["text"]

        # THROUGH the runtime, observably: the repo's turnlog holds this task, FINISHED by
        # the engine, and the user's tree is untouched (L19).
        turnlog = repo / ".tempest" / "agent" / "turns.sqlite3"
        assert turnlog.exists(), "no turnlog — the turn did not go through run_task"
        assert (repo / "app.py").read_text(encoding="utf-8").endswith("sum(xs)\n")

    def test_a_tool_outside_the_agents_selection_is_refused(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC15's first tooth: the agent's tool SELECTION binds the runtime, not just the
        picker. A model asking for an unselected tool gets a refusal it can read."""
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Trying to write.",
                "tool_calls": [
                    {"name": "write_file", "arguments": {"path": "app.py", "contents": "x = 1\n"}}
                ],
            },
            {"text": "It refused me."},
        ]
        ack = _start(api, agent["id"], "Write something")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        assert (repo / "app.py").read_text(encoding="utf-8").endswith("sum(xs)\n"), (
            "the unselected tool must not have run"
        )

    def test_tools_without_a_repository_refuse_actionably(
        self, api: Any, agent_env: AgentPeer
    ) -> None:
        agent = _make_agent(api, tools=["read_file"])
        ack = _start(api, agent["id"])
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "error"
        final = _frames(payload)[-1]
        text = json.dumps(final)
        assert "repository" in text.lower(), f"the refusal must name the missing piece: {text}"


def _wait_pending(api: Any, stream_id: str, timeout: float = 30.0) -> dict[str, Any]:
    """Poll the ledger until the park's `on_pending_action` frame appears; return its data."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = api.client.get(f"/v1/chat/turns/{stream_id}/events?after=0").json()
        for frame in _frames(payload):
            if frame.get("event") == "on_pending_action":
                assert payload["status"] == "active", "a parked turn must still be ACTIVE"
                data: dict[str, Any] = frame["data"]
                return data
        if payload["status"] not in ("active", "unknown"):
            raise AssertionError(f"turn settled without parking: {payload['status']}")
        time.sleep(0.05)
    raise AssertionError("the pending-action frame never arrived")


class TestHumanInTheLoopWire:
    """LC18 over the real wire: park → on_pending_action frame → POST resume → completion.
    The client's contract (recon'd from ApprovalContext/useResumableSSE): the pending payload
    joins by tool_call_id, resume answers {status:'resuming'}, a stale actionId is a 409 and
    an undecided batch a 400."""

    def _gated_agent(self, api: Any, repo: Path) -> dict[str, Any]:
        return _make_agent(
            api,
            tools=["read_file", "run_command"],
            tempest_repo=str(repo),
        )

    def _park(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = self._gated_agent(api, repo)
        agent_env.script = [
            {
                "text": "Running it.",
                "tool_calls": [
                    {"name": "run_command", "arguments": {"argv": ["echo", "hitl-ran"]}}
                ],
            },
            {"text": "Command finished."},
        ]
        ack = _start(api, agent["id"], "Run echo")
        pending = _wait_pending(api, ack["streamId"])
        return ack, pending

    def test_approval_round_trips_and_the_command_runs(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._park(api, agent_env, repo)
        request = pending["payload"]["action_requests"][0]
        assert request["name"] == "run_command"
        assert pending["payload"]["review_configs"][0]["tool_call_id"] == request["tool_call_id"]

        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "resuming"
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        # The command's output went back to the MODEL as the tool result.
        assert "hitl-ran" in json.dumps(agent_env.requests[-1])

    def test_a_rejection_resumes_with_the_refusal(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._park(api, agent_env, repo)
        request = pending["payload"]["action_requests"][0]
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [
                    {
                        "tool_call_id": request["tool_call_id"],
                        "decision": "reject",
                        "reason": "not in this repo",
                    }
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        replayed = json.dumps(agent_env.requests[-1])
        assert "refused by the user" in replayed and "not in this repo" in replayed

    def test_a_stale_action_id_is_409_and_undecided_is_400(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._park(api, agent_env, repo)
        request = pending["payload"]["action_requests"][0]
        stale = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={"actionId": "appr_gone", "decisions": []},
        )
        assert stale.status_code == 409
        undecided = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={"actionId": pending["actionId"], "decisions": []},
        )
        assert undecided.status_code == 400
        # Clean up: approve so the worker thread finishes rather than waiting out its expiry.
        api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )
        _wait_terminal(api, ack["streamId"])

    def test_status_carries_the_pending_action_for_reload(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._park(api, agent_env, repo)
        status = api.client.get(f"/v1/chat/turns/{ack['streamId']}").json()
        assert status["active"] is True
        assert status["pendingAction"]["actionId"] == pending["actionId"]
        request = pending["payload"]["action_requests"][0]
        api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )
        _wait_terminal(api, ack["streamId"])

    def test_cancel_while_parked_aborts_promptly(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, _pending = self._park(api, agent_env, repo)
        started = time.monotonic()
        resp = api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        assert resp.status_code == 200
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "aborted"
        assert time.monotonic() - started < 5.0, "the park must observe the abort, not sit it out"

    def test_ask_user_round_trips_an_answer(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        agent = _make_agent(api, tools=["read_file", "ask_user"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "One question first.",
                "tool_calls": [{"name": "ask_user", "arguments": {"question": "Blue or green?"}}],
            },
            {"text": "Blue it is."},
        ]
        ack = _start(api, agent["id"], "Paint it")
        pending = _wait_pending(api, ack["streamId"])
        assert pending["payload"]["type"] == "ask_user_question"
        assert pending["payload"]["question"]["question"] == "Blue or green?"
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={"actionId": pending["actionId"], "answer": "blue, always blue"},
        )
        assert resp.status_code == 200, resp.text
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        assert "blue, always blue" in json.dumps(agent_env.requests[-1])


class TestSteeringWire:
    """LC16/LC17 over the wire: queue → drain into the next turn → applied frame; reclaim
    by cancel; honest refusals in the client's own vocabulary (top-level `code`, which is
    what useSteering switches on to degrade gracefully)."""

    def _parked_agent_turn(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = _make_agent(api, tools=["read_file", "run_command"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Running it.",
                "tool_calls": [{"name": "run_command", "arguments": {"argv": ["echo", "ok"]}}],
            },
            {"text": "Done."},
        ]
        ack = _start(api, agent["id"], "Run it")
        pending = _wait_pending(api, ack["streamId"])
        return ack, pending

    def _approve(self, api: Any, ack: dict[str, Any], pending: dict[str, Any]) -> None:
        request = pending["payload"]["action_requests"][0]
        api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )

    def test_a_queued_steer_drains_into_the_next_turn(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer",
            json={"text": "also check the README", "clientSteerId": "cs-1"},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert body["steerId"].startswith("steer_")
        assert body["position"] == 1

        self._approve(api, ack, pending)
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        assert "also check the README" in json.dumps(agent_env.requests[-1]), (
            "the steer must reach the model's next turn"
        )
        applied = [f for f in _frames(payload) if f.get("event") == "on_steer_applied"]
        assert applied and applied[0]["data"]["part"]["steer"] == "also check the README"
        assert applied[0]["data"]["clientSteerId"] == "cs-1"

    def test_reclaim_removes_an_unconsumed_steer(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        queued = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "never mind"}
        ).json()
        removed = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer/cancel",
            json={"steerId": queued["steerId"]},
        )
        assert removed.status_code == 200
        assert removed.json()["removed"] is True
        self._approve(api, ack, pending)
        payload = _wait_terminal(api, ack["streamId"])
        assert "never mind" not in json.dumps(agent_env.requests[-1])
        assert not [f for f in _frames(payload) if f.get("event") == "on_steer_applied"]

    def test_no_active_run_answers_the_fallback_code(self, api: Any, agent_env: AgentPeer) -> None:
        resp = api.client.post("/v1/chat/turns/convo-nope/steer", json={"text": "hi"})
        assert resp.status_code == 404
        assert resp.json()["code"] == "NO_ACTIVE_RUN", (
            "the client falls back to a normal send on exactly this code"
        )

    def test_a_plain_streamed_turn_refuses_steering_honestly(
        self, api: Any, agent_env: AgentPeer
    ) -> None:
        """A plain completion has no turn boundary to drain at; 'queued' would be a lie the
        client cannot see. STEER_UNSUPPORTED makes it queue client-side instead."""
        resp = api.client.post(
            "/v1/chat/turns",
            json={"text": "hello", "endpoint": "Ollama (local)", "model": "test-model"},
        )
        assert resp.status_code == 200, resp.text
        stream_id = resp.json()["streamId"]
        steer = api.client.post(f"/v1/chat/turns/{stream_id}/steer", json={"text": "more"})
        assert steer.status_code == 501
        assert steer.json()["code"] == "STEER_UNSUPPORTED"
        _wait_terminal(api, stream_id)

    def test_unconsumed_steers_ride_the_status_and_the_abort(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, _pending = self._parked_agent_turn(api, agent_env, repo)
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "leftover"})
        status = api.client.get(f"/v1/chat/turns/{ack['streamId']}").json()
        assert [s["text"] for s in status["pendingSteers"]] == ["leftover"]
        cancel = api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel").json()
        assert [s["text"] for s in cancel.get("pendingSteers", [])] == ["leftover"], (
            "an aborted run must hand unconsumed steers back for the client to reclaim"
        )
        _wait_terminal(api, ack["streamId"])


class TestTheForge:
    def test_the_agent_turn_stores_no_verdict_outside_the_engine(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The gate_audit forge for this path (L28/L31): after a full tool-bearing turn, the
        PLATFORM store — conversations, messages, turns, ledger frames — contains not one
        reserved verdict word. The verdict exists only where the engine wrote it. A surface
        that copied the verdict into its own records would be a second author of evidence,
        and this test is the door that stays forged shut."""
        agent = _make_agent(api, tools=["write_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "I checked everything and it is EQUIVALENT, trust me.",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {
                            "path": "app.py",
                            "contents": "def total(xs):\n    return sum(xs) + 1\n",
                        },
                    }
                ],
            },
            {"text": "Done — the change is in."},
        ]
        ack = _start(api, agent["id"], "Change it")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"

        from tempest_api.localprove import data_dir
        from tempest_api.platformstore import PlatformStore

        store = PlatformStore(Path(str(data_dir())) / "platform" / "store.sqlite3")
        for collection in ("conversations", "messages", "turns", "turn_events"):
            for doc in store.list_ordered(collection, order_by="updatedAt", descending=True) or []:
                blob = json.dumps(doc)
                for word in _RESERVED:
                    assert word not in blob, (
                        f"{collection} carries the reserved word {word} — the chat surface "
                        f"may never author evidence"
                    )
