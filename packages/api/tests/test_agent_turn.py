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

from tempest.agent.events import CostCapReached, ModelUnavailable
from tempest.agent.orchestrator import AgentError
from tempest.dev._first_party import mark_first_party
from tempest_api import agentturn as agentturn_mod
from tempest_api.agentturn import _stop_note
from tempest_api.routers import chat as chat_router


class AgentPeer:
    """An OpenAI-wire peer speaking BOTH shapes: scripted non-stream replies for the
    orchestrator's `complete()` calls, and a plain streamed answer for persona turns.

    `script` is consumed one entry per non-stream request; each entry is either
    `{"text": ...}` or `{"text": ..., "tool_calls": [{"name": ..., "arguments": {...}}]}`.
    An exhausted script answers plain text — the model "finishing".
    """

    def __init__(self) -> None:
        #: Answer the ANTHROPIC wire instead of the OpenAI one.
        self.wire_anthropic = False
        self.script: list[dict[str, Any]] = []
        self.stream_chunks: list[str] = ["Hel", "lo"]
        self.requests: list[dict[str, Any]] = []
        #: Answer HTTP 503 once this many non-stream completions have been served. `None`
        #: never fails. This is how a mid-turn provider OUTAGE is produced — the condition
        #: `_converse` soft-breaks on (L23) and the surface has to report.
        self.fail_after: int | None = None
        self.completions = 0
        self._lock = threading.Lock()

    def next_reply(self) -> dict[str, Any] | None:
        """`None` means "answer 503" — the provider died mid-turn."""
        with self._lock:
            if self.fail_after is not None and self.completions >= self.fail_after:
                return None
            self.completions += 1
            return self.script.pop(0) if self.script else {"text": "all done"}


def _anthropic_completion_body(reply: dict[str, Any]) -> bytes:
    """The Anthropic wire's non-stream shape. Needed because `anthropic` is the ONLY provider
    that documents a context window, and the gauge is emitted only where one is documented
    (ADR-0079 §6: a wrong maximum is worse than no maximum)."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": reply.get("text", "")}]
    for index, call in enumerate(reply.get("tool_calls", [])):
        blocks.append(
            {
                "type": "tool_use",
                "id": f"call_{index}",
                "name": call["name"],
                "input": call.get("arguments", {}),
            }
        )
    return json.dumps(
        {"content": blocks, "usage": {"input_tokens": 11, "output_tokens": 5}}
    ).encode()


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
            reply = peer.next_reply()
            if reply is None:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                body = b'{"error":{"message":"upstream is down"}}'
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            payload = (
                _anthropic_completion_body(reply)
                if peer.wire_anthropic
                else _completion_body(reply)
            )
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
    monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_ANTHROPIC", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
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

#: The ONLY fields in the platform store where a reserved verdict word may legitimately
#: appear: the carriers of MODEL NARRATION. L17 puts model text in explanation fields; L31
#: forbids it in any field a verdict, confidence or risk is read from. Measured against the
#: real store rather than reasoned about — a planted claim lands in exactly these five.
#:
#: The previous version of this forge swept `json.dumps(doc)` for the words and scripted the
#: model to say bare "EQUIVALENT", which is not in `_RESERVED`: it planted a claim it could
#: not detect, and would have gone red on the real word purely because narration is stored
#: verbatim. Both halves were wrong in the same place — a blob sweep cannot tell an authored
#: verdict from a quoted one, so it had to be weakened until it proved nothing.
_NARRATION_FIELDS = frozenset(
    {
        "messages::text",
        "messages::content[].text.value",
        "turn_events::frame.data.delta.content[].text",
        "turn_events::frame.responseMessage.text",
        "turn_events::frame.responseMessage.content[].text.value",
    }
)


def _strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a stored document, with the field path that reached it."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value, f"{path}[]")
    elif isinstance(node, str):
        yield path, node


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


class TestTheRepositoryAgentsWorkIn:
    """`tempest_repo` — the field the builder now has, and the refusals a person can act on.

    The builder's Repository field landed in ADR-0083 and this refusal did not move with it:
    it said "none is configured" for a path that WAS configured, told the user the picker
    "arrives with the conversation platform" when they had just typed into it, and pointed a
    non-coder at `PATCH /api/agents/{id}`. Found by an adversarial audit of the real-app path
    (ADR-0087).
    """

    def test_a_path_with_a_tilde_is_the_path_a_person_typed(
        self, api: Any, agent_env: AgentPeer, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`pathlib` does not expand `~`, so a tilde path was stored happily by the builder
        and then refused here as though nothing had been set. Home is where the user's code
        lives; a field that rejects the way they write it is the field's problem."""
        monkeypatch.setenv("HOME", str(repo.parent))
        agent = _make_agent(
            api,
            tools=["read_file"],
            tempest_repo=f"  ~/{repo.name}  ",  # whitespace too: a paste carries it
        )
        agent_env.script = [{"text": "Read it."}]
        payload = _wait_terminal(api, _start(api, agent["id"])["streamId"])
        assert payload["status"] == "complete", _frames(payload)[-1]

    def test_a_folder_that_is_not_there_says_WHICH_folder(
        self, api: Any, agent_env: AgentPeer
    ) -> None:
        """The two refusals are different problems and must read differently: nothing set at
        all, versus a path that points nowhere. The second one quotes the path back, because
        "no repository" for a path the user can see in the field is a refusal that names the
        wrong thing."""
        agent = _make_agent(api, tools=["read_file"], tempest_repo="/nope/not/a/folder")
        payload = _wait_terminal(api, _start(api, agent["id"])["streamId"])
        text = json.dumps(_frames(payload))
        assert "/nope/not/a/folder" in text, text[:400]
        assert "no folder there" in text
        assert "builder" in text, "the way out names the surface that has the field"
        # The stale instructions are gone: no REST endpoint, and no claim the picker is unbuilt.
        assert "PATCH /api/agents" not in text
        assert "arrives with the conversation platform" not in text

    def test_no_repository_at_all_points_at_the_builder(
        self, api: Any, agent_env: AgentPeer
    ) -> None:
        agent = _make_agent(api, tools=["read_file"])
        payload = _wait_terminal(api, _start(api, agent["id"])["streamId"])
        text = json.dumps(_frames(payload))
        assert "none is configured" in text
        assert "builder" in text
        assert "PATCH /api/agents" not in text


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
        frames = _frames(payload)
        final = frames[-1]
        assert "added one" in final["responseMessage"]["text"]

        # THROUGH the runtime, observably: the repo's turnlog holds this task, FINISHED by
        # the engine, and the user's tree is untouched (L19).
        turnlog = repo / ".tempest" / "agent" / "turns.sqlite3"
        assert turnlog.exists(), "no turnlog — the turn did not go through run_task"
        assert (repo / "app.py").read_text(encoding="utf-8").endswith("sum(xs)\n")

        # The C5 frame vocabulary (LC19/LC21): the tool call renders as a RUN STEP that
        # opens and completes with its output; real token counts ride on_token_usage; a
        # mechanical activity header labels the batch — and the persisted message carries
        # the same parts the stream showed.
        steps = [f for f in frames if f.get("event") == "on_run_step"]
        tool_steps = [
            f for f in steps if f["data"].get("stepDetails", {}).get("type") == "tool_calls"
        ]
        assert tool_steps, "a tool call must open a run step"
        opened = tool_steps[0]["data"]["stepDetails"]["tool_calls"][0]
        assert opened["name"] == "write_file"
        completed = [f for f in frames if f.get("event") == "on_run_step_completed"]
        assert completed and completed[0]["data"]["result"]["tool_call"]["name"] == "write_file"
        assert "output" in completed[0]["data"]["result"]["tool_call"]
        usage = [f for f in frames if f.get("event") == "on_token_usage"]
        assert usage and usage[0]["data"]["input_tokens"] == 5
        labels = [f for f in frames if f.get("event") == "on_activity_label"]
        assert any("shadow worktree" in f["data"]["part"]["activity_label"] for f in labels), (
            "the write batch must wear its mechanical header"
        )
        parts = final["responseMessage"]["content"]
        mirrored = [p for p in parts if p.get("type") == "tool_call"]
        assert mirrored, "the persisted message must mirror the streamed run step"
        # The outer `type` discriminator is written at ToolCallStarted time as an EMPTY
        # placeholder, so asserting only on it is satisfied by a mirror that was never
        # filled in — a reload would show a blank card where the stream showed the call.
        # The contract (ADR-0079: `_finish(extra_parts=…)` persists the same parts the
        # stream showed) is about the CONTENT and the slot, so assert the content.
        body = mirrored[0]["tool_call"]
        assert body.get("name") == "write_file"
        assert body.get("args", {}).get("path") == "app.py"
        assert body.get("id") == opened["id"], (
            "the persisted mirror must carry the same call id the stream published"
        )
        assert body.get("output"), "a finished call's persisted mirror must carry its output"
        # The gauge stays HONESTLY silent here: the ollama row documents no context window,
        # and an invented denominator would be worse than an indeterminate gauge (LC21).
        assert not [f for f in frames if f.get("event") == "on_context_usage"]

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

        # The user's tree being unchanged proves NOTHING here: under L19 an agent write lands
        # in the shadow worktree, so that assertion is equally true when the forbidden tool
        # RUNS (trap 60 — an assertion satisfied by the absence of what it measures). The
        # refusal has to be read where it actually appears: the tool call's own output.
        completed = [f for f in _frames(payload) if f.get("event") == "on_run_step_completed"]
        assert completed, "the refused call must still open and complete a run step"
        refused = completed[0]["data"]["result"]["tool_call"]
        assert refused["name"] == "write_file"
        assert "not part of this agent's toolset" in refused["output"], (
            f"the refusal must name the reason the model can act on; got {refused['output']!r}"
        )
        assert "read_file" in refused["output"], (
            "the refusal must list what the agent DOES offer, or the model cannot recover"
        )

    def test_the_two_stop_notes_read_differently_and_carry_the_real_reason(self) -> None:
        """An outage is transient and worth retrying; a cap is a decision the user made and
        has to change. A single generic "something went wrong" for both would be an apology
        with no content, which is precisely what L23 forbids — so each note names its own
        condition, carries the provider's own words, and says what the user can do next.

        The other half of the contract: neither note may borrow the reserved verdict
        vocabulary (L31). These sentences say why the LOOP stopped, never what the change
        does — the engine's verdict for whatever was staged is computed exactly as usual.
        """
        outage = _stop_note(ModelUnavailable(message="anthropic: HTTP 503 upstream is down"))
        capped = _stop_note(CostCapReached(message="session cap reached at $5.00"))

        assert "unavailable" in outage.lower()
        assert "HTTP 503 upstream is down" in outage, "the provider's own words must survive"
        assert "try again" in outage.lower()

        assert "cost cap" in capped.lower()
        assert "session cap reached at $5.00" in capped
        assert "raise the cap" in capped.lower()

        assert outage != capped, "two different conditions must not read identically"
        for note in (outage, capped):
            assert "still proved" in note, (
                "the user must be told the staged work still got its verdict (L23)"
            )
            for reserved in ("DIVERGENT", "EQUIVALENT_UNDER_BUDGET", "UNPROVEN", "ERROR"):
                assert reserved not in note, f"L31: {reserved!r} is the engine's word, not a note's"

    def test_a_midturn_provider_outage_is_reported_not_swallowed(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """L23/L15.3: the loop ends, the shadow is still proved — and the user is TOLD why.

        `_converse` handles a mid-turn `ModelError` by emitting `ModelUnavailable` and
        soft-breaking, deliberately, so whatever is already staged still gets proved and
        shown with its real verdict. `run_task` then returns NORMALLY. The surface's `emit`
        ended in a bare `else: return`, so that event was dropped on the floor: the turn
        persisted as `status: complete, error: false` carrying only turn 1's narration, and
        a user whose provider had just died was shown a finished, error-free answer that
        silently stopped early. A catch that continues without surfacing is a build failure
        (L15.3), and this was its quietest form — nothing was even caught.
        """
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Let me look at app.py.",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "app.py"}}],
            },
        ]
        agent_env.fail_after = 1  # turn 2's completion meets a 503

        ack = _start(api, agent["id"], "Explain total")
        payload = _wait_terminal(api, ack["streamId"])
        frames = _frames(payload)
        final = frames[-1]
        text = final["responseMessage"]["text"]

        assert "Let me look at app.py." in text, (
            "the partial answer the model DID give must survive — the turn was proved"
        )
        assert "unavailable" in text.lower(), (
            f"the turn stopped because the provider died and must say so; got {text!r}"
        )
        assert "503" in text or "upstream" in text.lower(), (
            "the reason must be specific enough to act on (L23), not a generic apology"
        )

        # It has to arrive LIVE too, not only on reload: a user watching the stream sees the
        # tokens stop, and a note that only appears in the persisted message is a note they
        # never read.
        deltas = "".join(
            str(f["data"]["delta"]["content"][0]["text"])
            for f in frames
            if f.get("event") == "on_message_delta"
        )
        assert "unavailable" in deltas.lower(), (
            "the outage note must ride the stream, not appear only after a reload"
        )

    def test_ask_user_outside_the_agents_selection_is_refused_not_asked(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC15's tooth applied to the ONE tool that bypasses the dispatcher.

        `tools.py` advertises the selection as "defense in depth beside the filtered catalog,
        so a model that hallucinates an unoffered tool still meets a refusal, never a
        handler". That promise is enforced inside `Dispatcher.call` — and
        `_dispatch_with_approval`'s `ask_user_question` branch RETURNS BEFORE IT, so for
        `ask_user` the promise was false: an agent whose selection excludes `ask_user` could
        still interrupt the user with a question, and the user's typed answer was injected
        into the model's transcript. A guard's argument is not a proof of the guard (trap 45).

        The model text that asks is attacker-reachable — repository bytes read through
        `read_file` are untrusted input — so this is a capability boundary, not a nicety.
        """
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "I need to check something with you.",
                "tool_calls": [
                    {"name": "ask_user", "arguments": {"question": "Should I use tabs?"}}
                ],
            },
            {"text": "Understood, carrying on."},
        ]
        ack = _start(api, agent["id"], "Do the thing")
        payload = _wait_terminal(api, ack["streamId"])

        frames = _frames(payload)
        assert not [f for f in frames if f.get("event") == "on_pending_action"], (
            "an agent that was never given ask_user must not be able to park the turn and "
            "put a question in front of the user"
        )
        assert payload["status"] == "complete", payload.get("status")
        completed = [f for f in frames if f.get("event") == "on_run_step_completed"]
        assert completed, "the refused call must still complete a run step the model can read"
        refused = completed[0]["data"]["result"]["tool_call"]
        assert refused["name"] == "ask_user"
        assert "not part of this agent's toolset" in refused["output"], (
            f"ask_user must meet the same refusal as any other unselected tool; "
            f"got {refused['output']!r}"
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

    def test_resuming_a_turn_that_is_no_longer_running_is_a_409(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """A tab that was left open on an approval and comes back after the run ended must be
        told its decision is stale — the client locks its submit on exactly this."""
        ack, pending = self._park(api, agent_env, repo)
        request = pending["payload"]["action_requests"][0]
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        _wait_terminal(api, ack["streamId"])

        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )
        assert resp.status_code == 409, resp.text

    def test_a_decision_verb_outside_approve_or_reject_is_refused(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The resume body is client-authored. A verb this action does not offer must be a
        loud 400 rather than a silent fall-through to some default — an unrecognised verb
        treated as "approve" would run a tool nobody approved."""
        ack, pending = self._park(api, agent_env, repo)
        request = pending["payload"]["action_requests"][0]
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "maybe-later"}],
            },
        )
        assert resp.status_code == 400, resp.text
        assert "approve or reject" in resp.text

        # The turn is still parked and still answerable — a bad body must not kill the run.
        good = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={
                "actionId": pending["actionId"],
                "decisions": [{"tool_call_id": request["tool_call_id"], "decision": "approve"}],
            },
        )
        assert good.status_code == 200, good.text
        assert _wait_terminal(api, ack["streamId"])["status"] == "complete"

    def test_an_ask_user_answer_may_arrive_under_the_answers_map(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The vendored form posts `{answers: {<fieldId>: value}}` for a multi-question form;
        the single-question shape posts `{answer}`. Both are the same decision and both must
        reach the model."""
        agent = _make_agent(api, tools=["ask_user"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "One question.",
                "tool_calls": [{"name": "ask_user", "arguments": {"question": "Which module?"}}],
            },
            {"text": "Thanks."},
        ]
        ack = _start(api, agent["id"], "Decide")
        pending = _wait_pending(api, ack["streamId"])
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={"actionId": pending["actionId"], "answers": {"q1": "the totals module"}},
        )
        assert resp.status_code == 200, resp.text
        _wait_terminal(api, ack["streamId"])
        assert "the totals module" in json.dumps(agent_env.requests[-1])

    def test_an_empty_ask_user_answer_is_refused(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """A blank answer is not an answer. Accepting it would hand the model an empty string
        as though the user had said something, and the model cannot tell the difference."""
        agent = _make_agent(api, tools=["ask_user"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "One question.",
                "tool_calls": [{"name": "ask_user", "arguments": {"question": "Which module?"}}],
            },
            {"text": "Thanks."},
        ]
        ack = _start(api, agent["id"], "Decide")
        pending = _wait_pending(api, ack["streamId"])
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/resume",
            json={"actionId": pending["actionId"], "answer": "   "},
        )
        assert resp.status_code == 400, resp.text
        assert "answer is required" in resp.text
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        _wait_terminal(api, ack["streamId"])

    def test_an_agent_naming_a_provider_outside_the_catalog_is_refused_at_start(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """An agent document is data, and its provider can go stale — a provider removed from
        the catalog, or a document written by an older build. The turn refuses at the entry
        checkpoint with a reason naming the agent and the provider, rather than starting and
        failing somewhere further in."""
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        store = api.client.patch(f"/v1/agents/{agent['id']}", json={"provider": "NoSuchProvider"})
        assert store.status_code == 200, store.text
        resp = api.client.post(
            "/v1/chat/turns",
            json={"agent_id": agent["id"], "text": "go", "endpoint": "agents"},
        )
        assert resp.status_code == 400, resp.text
        assert "NoSuchProvider" in resp.text and "not in the catalog" in resp.text

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

    def test_an_interrupted_tool_step_persists_the_card_the_stream_showed(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """A step that OPENS and never finishes must not persist as an empty placeholder.

        `emit` reserves the persisted mirror of a tool step when the step opens
        (`{"type": "tool_call", "tool_call": {}}`, filled on `ToolCallFinished`). Any exit
        between the two — an abort, an unanswered park, an outage — left that empty part in
        the message, and the vendored Part renderer drops a tool_call with no payload
        entirely: the live stream showed a tool card, the reload showed nothing, and the
        history quietly disagreed with what the user had watched.

        Removing the part instead would shift every later index away from the one the stream
        already published, so it is FILLED with the call as issued and an empty output —
        which is the truth: started, never came back.
        """
        ack, _pending = self._park(api, agent_env, repo)
        assert api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel").status_code == 200
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "aborted"

        final = _frames(payload)[-1]
        parts = final["responseMessage"]["content"]
        cards = [p for p in parts if p.get("type") == "tool_call"]
        assert cards, "the interrupted step must still persist a card"
        for card in cards:
            body = card["tool_call"]
            assert body, f"an EMPTY tool_call part reached the store: {card!r}"
            assert body.get("name"), "the persisted card must name the call the stream showed"
            assert "args" in body and "id" in body
            assert body.get("output") == "", (
                "an interrupted call has no output, and must not invent one"
            )

    def test_every_model_call_reports_its_own_usage_under_a_distinct_key(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """C5 made ONE runId span MANY model calls, which breaks the client's usage fold.

        `useUsageHandler` keys on `runId != null && seq != null ? `${runId}:${seq}` :
        JSON.stringify(data)`, and upstream's own doc for the field says what it is for:
        "keeps identical payloads from distinct model calls unique". `token_usage_frame`
        never set it, so the key degraded to the payload — and two calls in one turn
        reporting the same counts folded into ONE. The turn under-reported its own spend
        (L21), and identical counts are not a corner case: the scripted peer produces them
        every time, and small tool-loop turns land on the same numbers routinely.
        """
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Looking.",
                "tool_calls": [{"name": "read_file", "arguments": {"path": "app.py"}}],
            },
            {"text": "Done looking."},
        ]
        ack = _start(api, agent["id"], "Look at it")
        payload = _wait_terminal(api, ack["streamId"])
        usage = [f for f in _frames(payload) if f.get("event") == "on_token_usage"]

        assert len(usage) >= 2, (
            f"a tool-bearing turn makes at least two model calls; got {len(usage)} usage "
            f"frames, so this test would be vacuous"
        )
        run_ids = {f["data"]["runId"] for f in usage}
        assert len(run_ids) == 1, "the whole turn is one run — that is why seq is needed"

        keys = [(f["data"]["runId"], f["data"].get("seq")) for f in usage]
        assert all(seq is not None for _run, seq in keys), (
            "a usage frame with no seq folds under its payload, and identical payloads merge"
        )
        assert len(set(keys)) == len(keys), (
            f"two model calls shared a fold key and would collapse into one: {keys}"
        )

        # The scripted peer reports the SAME counts every call, which is exactly the case
        # that folds — so this turn is the failing shape, not a lucky one.
        payloads = [(f["data"]["input_tokens"], f["data"]["output_tokens"]) for f in usage]
        assert len(set(payloads)) == 1, (
            f"expected identical counts from the scripted peer (the folding case); got {payloads}"
        )

    def test_the_activity_header_follows_the_calls_it_covers(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC19 against the vendored grouper's ACTUAL contract.

        `groupSequentialToolCalls` walks content in index order, accumulates groupable tool
        calls, and on reaching an ACTIVITY_LABEL claims `currentBlock.slice(claimStart)` —
        the parts BEFORE the label. Upstream publishes labels from its post-batch hook, so a
        label always follows its batch.

        Tempest emitted the header FIRST, which made `claimed.length === 0` on every batch
        and took the grouper's "Orphan label" branch: the header rendered as a standalone
        line and the tool calls after it were flushed with no `labelPart`. Spec 24 stayed
        green throughout, because `getByText("Running commands")` is just as visible on an
        orphan as on a real header — the assertion could not tell a grouped header from a
        floating one.

        So the invariant is positional, and this is where it can be asserted precisely.
        """
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Reading two files.",
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "app.py"}},
                    {"name": "read_file", "arguments": {"path": "app.py"}},
                ],
            },
            {"text": "Both read."},
        ]
        ack = _start(api, agent["id"], "Read them")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"

        parts = _frames(payload)[-1]["responseMessage"]["content"]
        kinds = [p.get("type") for p in parts]
        # A BATCH header is a label that names the calls it covers; the phase label the
        # `Proving` event publishes carries no `tool_call_ids` and heads no tool group.
        header_at = [
            i
            for i, k in enumerate(kinds)
            if k == "activity_label" and parts[i].get("tool_call_ids")
        ]
        calls_at = [i for i, k in enumerate(kinds) if k == "tool_call"]
        assert header_at, f"no batch header was persisted at all: {kinds}"
        assert calls_at, f"no tool call was persisted at all: {kinds}"

        label_at = header_at
        header = parts[header_at[0]]
        covered = header.get("tool_call_ids") or []
        assert covered, "a header that covers no call cannot be claimed by the grouper"

        # The positional contract: every call the header names sits BEFORE it.
        ids_before = [
            parts[i]["tool_call"].get("id")
            for i in calls_at
            if i < label_at[0] and isinstance(parts[i].get("tool_call"), dict)
        ]
        for call_id in covered:
            assert call_id in ids_before, (
                f"header at index {label_at[0]} names {call_id!r}, which is not among the "
                f"calls that precede it ({ids_before}) — the grouper would claim nothing and "
                f"render this header as an orphan"
            )

        # Both calls are the same kind, so they are ONE batch under ONE header.
        assert len(header_at) == 1, f"one batch must wear one header, got {len(header_at)}"
        assert len(covered) == 2, f"the header must cover both calls, got {covered}"

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

    def test_a_steer_with_no_text_is_a_400_the_client_can_read(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """A whitespace-only steer steers nothing, and the refusal code is TOP-LEVEL because
        that is the field the client's degrade switch reads (the ApiError envelope hides it)."""
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        resp = api.client.post(f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "   "})
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "EMPTY_TEXT"
        self._approve(api, ack, pending)
        _wait_terminal(api, ack["streamId"])

    def test_a_redelivered_steer_replays_its_ack_instead_of_queueing_twice(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The deliver/retry path: a client that loses the 202 re-sends the same
        `clientSteerId`, and must get the ORIGINAL ack back rather than steering the model
        twice with one instruction."""
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        first = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer",
            json={"text": "use tabs", "clientSteerId": "cs-dup"},
        ).json()
        # A DIFFERENT id first: the dedupe scan must walk past a non-matching row and queue
        # normally, rather than treating any queued steer as a duplicate of any other.
        other = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer",
            json={"text": "and check the README", "clientSteerId": "cs-other"},
        )
        assert other.status_code == 202
        assert other.json()["steerId"] != first["steerId"]
        assert other.json()["position"] == 2

        second = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer",
            json={"text": "use tabs", "clientSteerId": "cs-dup"},
        )
        assert second.status_code == 202
        assert second.json()["steerId"] == first["steerId"], "the ack must be the ORIGINAL"
        assert second.json()["position"] == first["position"]

        self._approve(api, ack, pending)
        payload = _wait_terminal(api, ack["streamId"])
        applied = [f for f in _frames(payload) if f.get("event") == "on_steer_applied"]
        texts = [f["data"]["part"]["steer"] for f in applied]
        assert texts == ["use tabs", "and check the README"], (
            f"one instruction applied once, both in order; got {texts}"
        )

    def test_reclaiming_one_steer_keeps_the_others(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        keep = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "keep me"}
        ).json()
        drop = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "drop me"}
        ).json()
        removed = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer/cancel", json={"steerId": drop["steerId"]}
        )
        assert removed.status_code == 200 and removed.json()["removed"] is True

        self._approve(api, ack, pending)
        payload = _wait_terminal(api, ack["streamId"])
        replayed = json.dumps(agent_env.requests[-1])
        assert "keep me" in replayed, "reclaiming one steer must not drop its neighbours"
        assert "drop me" not in replayed
        applied = [f for f in _frames(payload) if f.get("event") == "on_steer_applied"]
        assert [f["data"]["part"]["steer"] for f in applied] == ["keep me"]
        assert keep["steerId"] != drop["steerId"]

    def test_a_settled_turn_with_nothing_queued_reports_no_leftovers(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The other side of LC17's escalate branch: a turn that ended with an empty queue
        must not carry an `unrecoveredSteers` key at all. An empty list is not nothing — the
        client re-materializes the field, and a present-but-empty one is a reclaim UI with no
        rows in it."""
        ack, pending = self._parked_agent_turn(api, agent_env, repo)
        self._approve(api, ack, pending)
        _wait_terminal(api, ack["streamId"])
        status = api.client.get(f"/v1/chat/turns/{ack['streamId']}").json()
        assert status["active"] is False
        assert status.get("unrecoveredSteers") is None, status

    def test_cancelling_a_steer_with_no_active_run_is_a_404(
        self, api: Any, agent_env: AgentPeer
    ) -> None:
        resp = api.client.post(
            "/v1/chat/turns/convo-nope/steer/cancel", json={"steerId": "steer_x"}
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "NO_ACTIVE_RUN"

    def test_unconsumed_steers_ride_the_status_of_a_FINISHED_turn(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC17's escalate half on the ordinary path: a turn that ENDS with steers it never
        drained hands them back on its status, so the client can re-materialize them for the
        user to reclaim or resend rather than silently losing what they typed."""
        ack, _pending = self._parked_agent_turn(api, agent_env, repo)
        api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/steer", json={"text": "too late for this"}
        )
        # Stop the turn, so it ends with no further turn boundary to drain the steer into.
        # (A rejection would NOT do: the loop still runs another turn to tell the model it
        # was refused, and that boundary consumes the steer.)
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        _wait_terminal(api, ack["streamId"])

        resp = api.client.get(f"/v1/chat/turns/{ack['streamId']}")
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["active"] is False
        leftovers = status.get("unrecoveredSteers") or []
        # The abort ANSWER carries them too (pinned separately); this is the STATUS path,
        # which is what a client reads after a reload rather than at the moment it stopped.
        assert [row["text"] for row in leftovers] == ["too late for this"], status

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


class TestContextGauge:
    """LC21: the gauge's numbers are the provider's own measurements, and its denominator is
    a DOCUMENTED window or nothing — never a guess dressed as a percentage."""

    def test_a_documented_window_produces_the_breakdown(self) -> None:
        from tempest.agent.events import TurnUsage
        from tempest.inference.providers import get
        from tempest_api.agentturn import context_usage_frame

        frame = context_usage_frame(
            get("anthropic"),
            TurnUsage("anthropic", "claude-sonnet-5", 1200, 50),
            response_message_id="rm-1",
            tool_count=3,
        )
        assert frame is not None
        breakdown = frame["data"]["breakdown"]
        assert breakdown["maxContextTokens"] == 200_000
        assert breakdown["messageTokens"] == 1200
        assert breakdown["availableForMessages"] == 198_800
        assert breakdown["toolCount"] == 3
        assert frame["data"]["remainingContextTokens"] == 198_800

    def test_an_unknown_window_produces_no_frame(self) -> None:
        from tempest.agent.events import TurnUsage
        from tempest.inference.providers import get
        from tempest_api.agentturn import context_usage_frame

        assert (
            context_usage_frame(
                get("ollama"),
                TurnUsage("ollama", "test-model", 1200, 50),
                response_message_id="rm-1",
                tool_count=1,
            )
            is None
        )

    def test_a_silent_provider_produces_no_frame(self) -> None:
        from tempest.agent.events import TurnUsage
        from tempest.inference.providers import get
        from tempest_api.agentturn import context_usage_frame

        assert (
            context_usage_frame(
                get("anthropic"),
                TurnUsage("anthropic", "claude-sonnet-5", 0, 0),
                response_message_id="rm-1",
                tool_count=1,
            )
            is None
        ), "zero input tokens means the provider said nothing — no gauge from nothing"


class TestCoverageNamedArms:
    """Arms the 100% combined-coverage gate named in the C5 back half's new code. Every one
    is real, reachable behaviour — none is defensive filler, and none earned a pragma."""

    def test_an_ask_user_question_carries_its_options(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC18's multiple-choice shape: a question with options renders as choices rather
        than a free-text box, and the client reads them off the pending payload."""
        agent = _make_agent(api, tools=["ask_user"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Need a decision.",
                "tool_calls": [
                    {
                        "name": "ask_user",
                        "arguments": {"question": "Tabs or spaces?", "options": ["tabs", "spaces"]},
                    }
                ],
            },
            {"text": "Understood."},
        ]
        ack = _start(api, agent["id"], "Decide")
        pending = _wait_pending(api, ack["streamId"])
        question = pending["payload"]["question"]
        assert question["question"] == "Tabs or spaces?"
        assert [o["value"] for o in question["options"]] == ["tabs", "spaces"]
        assert [o["label"] for o in question["options"]] == ["tabs", "spaces"]
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        _wait_terminal(api, ack["streamId"])

    def test_a_question_without_options_omits_the_key(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """The other side of the branch: a free-text question must not carry an EMPTY options
        list, which the client would render as a choice widget with nothing to choose."""
        agent = _make_agent(api, tools=["ask_user"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Need a decision.",
                "tool_calls": [{"name": "ask_user", "arguments": {"question": "Which module?"}}],
            },
            {"text": "Understood."},
        ]
        ack = _start(api, agent["id"], "Decide")
        pending = _wait_pending(api, ack["streamId"])
        assert "options" not in pending["payload"]["question"]
        api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        _wait_terminal(api, ack["streamId"])

    def test_an_approval_that_is_never_answered_expires_into_a_refusal(
        self, api: Any, agent_env: AgentPeer, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L15.4 wants a budget AND a cancellation path; an unbounded lease on a worker
        thread is neither. The park expires into an honest refusal the model can read, rather
        than holding the turn open forever because nobody came back to the screen.

        The shipped budget is 30 minutes, so the constant is shortened here — the arm under
        test is the deadline comparison, not the number.
        """
        monkeypatch.setattr(agentturn_mod, "_APPROVAL_EXPIRY_S", 0.5)
        agent = _make_agent(api, tools=["run_command"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Running it.",
                "tool_calls": [{"name": "run_command", "arguments": {"argv": ["echo", "hi"]}}],
            },
            {"text": "It refused."},
        ]
        ack = _start(api, agent["id"], "Run it")
        _wait_pending(api, ack["streamId"])
        payload = _wait_terminal(api, ack["streamId"])

        assert payload["status"] == "complete", "an expiry is a refusal, not a crash"
        replayed = json.dumps(agent_env.requests[-1])
        assert "expired unanswered" in replayed, (
            "the model must be told the question went unanswered so it can proceed honestly"
        )

    def test_a_batch_closes_when_the_tool_KIND_changes(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """Two kinds, two headers — each following the calls it covers. A single header over
        a mixed batch would name work it did not describe."""
        agent = _make_agent(api, tools=["read_file", "search_text"], tempest_repo=str(repo))
        agent_env.script = [
            {
                "text": "Reading then searching.",
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "app.py"}},
                    {"name": "search_text", "arguments": {"query": "total"}},
                ],
            },
            {"text": "Done."},
        ]
        ack = _start(api, agent["id"], "Look around")
        payload = _wait_terminal(api, ack["streamId"])
        parts = _frames(payload)[-1]["responseMessage"]["content"]
        headers = [p for p in parts if p.get("type") == "activity_label" and p.get("tool_call_ids")]
        labels = [h["activity_label"] for h in headers]
        assert labels == ["Reading the repository", "Searching the repository"], labels
        assert all(len(h["tool_call_ids"]) == 1 for h in headers), (
            "a kind change must split the batch, not pool both calls under one header"
        )

    def test_a_cancel_that_races_the_spawn_still_wins(
        self, api: Any, agent_env: AgentPeer, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The POST returns its ack immediately and the worker starts a moment later, so a
        Stop can land in between. The worker re-reads the flag at the top of its body and
        cancels its own scope — without that, the turn would run to completion after the user
        had already stopped it, and a model call the user cancelled would be billed.

        The race is ENFORCED rather than hoped for (trap 61): the worker is wrapped so the
        flag is certain to be set before its body runs, which is the ordering the arm exists
        for and the one a timing-based test would only sometimes produce.
        """
        real = agentturn_mod.run_agent_turn

        def cancel_first(turns: Any, job: Any, *args: Any, **kwargs: Any) -> Any:
            job.cancel.set()
            return real(turns, job, *args, **kwargs)

        monkeypatch.setattr(agentturn_mod, "run_agent_turn", cancel_first)
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))
        agent_env.script = [{"text": "should never be asked for"}]

        ack = _start(api, agent["id"], "Do it")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "aborted", payload["status"]
        assert agent_env.requests == [], (
            "a turn cancelled before its body ran must not reach the provider at all"
        )

    def test_the_context_gauge_rides_a_turn_on_a_provider_that_documents_its_window(
        self, api: Any, agent_env: AgentPeer, repo: Path
    ) -> None:
        """LC21 end to end. The gauge is emitted only where `Provider.context_window` is
        DOCUMENTED — `anthropic` is the one such row (200k) — and the counts that ride it are
        the provider's own. An unknown window produces no frame at all rather than an
        invented denominator (ADR-0079 §6), which the sibling unit tests pin directly; this
        is the arm that proves the frame actually reaches the ledger.
        """
        agent_env.wire_anthropic = True
        agent = _make_agent(
            api,
            provider="anthropic",
            model="claude-sonnet-5",
            tools=["read_file"],
            tempest_repo=str(repo),
        )
        # Tools make this the TOOL-BEARING path (`run_agent_turn`); a tool-less agent is a
        # persona that streams instead, and never reaches the gauge's call site.
        agent_env.script = [{"text": "Nothing to do here."}]
        ack = _start(api, agent["id"], "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete", json.dumps(_frames(payload)[-1])[:400]

        gauges = [f for f in _frames(payload) if f.get("event") == "on_context_usage"]
        assert gauges, "a documented window must produce a gauge frame"
        breakdown = gauges[0]["data"]["breakdown"]
        assert breakdown["maxContextTokens"] == 200_000, (
            "the denominator is the provider's DOCUMENTED window, never an estimate"
        )
        assert breakdown["messageTokens"] == 11, (
            "the numerator is the provider's own prompt count for the turn (L21)"
        )
        assert gauges[0]["data"]["remainingContextTokens"] == 200_000 - 11
        # The components Tempest cannot decompose are zeros the client sums, never invented
        # estimates that would make the gauge look precise about something it did not measure.
        for absent in (
            "instructionTokens",
            "systemMessageTokens",
            "dynamicInstructionTokens",
            "toolSchemaTokens",
            "summaryTokens",
        ):
            assert breakdown[absent] == 0, absent
        assert breakdown["toolCount"] == 1, "the agent's own tool count rides the breakdown"

    def test_a_defect_inside_tempest_surfaces_in_band(
        self, api: Any, agent_env: AgentPeer, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L15.3: a defect in US is reported to the user with a diagnostic, never swallowed
        into a turn that just stops. `run_task` raising an unexpected type is the arm."""
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise ZeroDivisionError("a defect that is ours, not the model's")

        monkeypatch.setattr(agentturn_mod, "run_task", boom)
        ack = _start(api, agent["id"], "Do it")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "error"
        final = _frames(payload)[-1]
        text = json.dumps(final)
        assert "failed inside Tempest" in text
        assert "ZeroDivisionError" in text, "the diagnostic must name the real cause (L15.3)"

    def test_a_tool_error_at_task_start_is_a_readable_refusal(
        self, api: Any, agent_env: AgentPeer, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An `AgentError`/`ToolError` escaping the run is the agent's own refusal, and it
        reaches the user as its message rather than as a Tempest defect."""
        agent = _make_agent(api, tools=["read_file"], tempest_repo=str(repo))

        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise AgentError("the agent could not start: no baseline commit")

        monkeypatch.setattr(agentturn_mod, "run_task", refuse)
        ack = _start(api, agent["id"], "Do it")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "error"
        text = json.dumps(_frames(payload)[-1])
        assert "no baseline commit" in text
        assert "failed inside Tempest" not in text, (
            "an agent refusal is not a Tempest defect and must not be dressed as one"
        )


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
                "text": "I checked everything and it is EQUIVALENT_UNDER_BUDGET, trust me.",
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
        planted: set[str] = set()
        for collection in ("conversations", "messages", "turns", "turn_events"):
            for doc in store.list_ordered(collection, order_by="updatedAt", descending=True) or []:
                for field_path, text in _strings(doc):
                    for word in _RESERVED:
                        if word not in text:
                            continue
                        located = f"{collection}::{field_path}"
                        assert located in _NARRATION_FIELDS, (
                            f"{located} carries the reserved word {word}. Model text may be "
                            f"stored as NARRATION (L17) and nowhere else; a reserved verdict "
                            f"reaching any other field means the chat surface authored "
                            f"evidence (L31/L28)."
                        )
                        planted.add(located)

        # Trap 60's lower bound, and the whole reason this test is worth anything: a sweep
        # that finds nothing is equally green when the model never made the claim, when the
        # turn never ran, and when the store was empty. The plant MUST be observable — in
        # every narration carrier — or the assertions above swept an empty room.
        assert planted == set(_NARRATION_FIELDS), (
            f"the planted verdict claim did not reach every narration carrier; "
            f"missing {sorted(set(_NARRATION_FIELDS) - planted)}, unexpected "
            f"{sorted(planted - set(_NARRATION_FIELDS))}"
        )
