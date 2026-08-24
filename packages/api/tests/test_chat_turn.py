"""Streamed chat turns end to end — REAL streaming, no mocks (Law L4): a loopback OpenAI-wire
SSE peer plays the provider, the real FastAPI app takes the client's own TPayload shapes, and
every assertion reads the public surface (ack, events ledger, conversations, messages).

The provider under test is `ollama` (endpoint key "Ollama (local)"): local, keyless, OpenAI
wire — its base URL env override points at the peer, which is exactly how a real local runner
is reached."""

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

import tempest_api.routers.chat as chat_router
from tempest_api.platformstore import PlatformStore

ENDPOINT = "Ollama (local)"


class ChatPeer:
    """A recording OpenAI-wire SSE peer with STAGED holds (trap 61): park after the frame
    indices in `holds`, release one hold per `release()` — so "the client hung up" is a
    write into a socket that died seconds ago, never a buffer race the suite's load can
    flip."""

    def __init__(self) -> None:
        self.chunks: list[str] = ["Hel", "lo ", "there"]
        #: A reasoning model's THINKING frames, sent BEFORE the answer chunks — the order
        #: a real `llama-server` uses (ADR-0081).
        self.reasoning: list[str] = []
        self.usage: dict[str, int] | None = {"prompt_tokens": 7, "completion_tokens": 3}
        self.status = 200
        self.reject_stream_options = False
        self.requests: list[dict[str, Any]] = []
        self.holds: list[int] = []
        self.released = 0
        self.closed_early = threading.Event()

    @property
    def hold_after_first(self) -> "_HoldSugar":
        return _HoldSugar(self)

    @property
    def resume(self) -> "_ReleaseSugar":
        return _ReleaseSugar(self)

    def release(self, count: int = 1) -> None:
        self.released += count

    def frames(self) -> list[bytes]:
        out = [
            b"data: "
            + json.dumps({"choices": [{"delta": {"reasoning_content": chunk}}]}).encode()
            + b"\n\n"
            for chunk in self.reasoning
        ]
        out += [
            b"data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}).encode() + b"\n\n"
            for chunk in self.chunks
        ]
        if self.usage is not None:
            out.append(
                b"data: " + json.dumps({"choices": [], "usage": self.usage}).encode() + b"\n\n"
            )
        out.append(b"data: [DONE]\n\n")
        return out


class _HoldSugar:
    """`peer.hold_after_first.set()` — the original single-hold spelling, kept readable."""

    def __init__(self, peer: ChatPeer) -> None:
        self._peer = peer

    def set(self) -> None:
        self._peer.holds = [0]


class _ReleaseSugar:
    """`peer.resume.set()` releases every hold the script declared."""

    def __init__(self, peer: ChatPeer) -> None:
        self._peer = peer

    def set(self) -> None:
        self._peer.release(len(self._peer.holds) or 1)


@contextmanager
def serve_peer(peer: ChatPeer) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw)
            peer.requests.append(body)
            if peer.reject_stream_options and "stream_options" in body:
                message = json.dumps(
                    {"error": {"message": "unknown parameter: stream_options"}}
                ).encode()
                self.send_response(400)
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
                return
            if peer.status != 200:
                message = json.dumps({"error": {"message": "planted failure"}}).encode()
                self.send_response(peer.status)
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                self.wfile.write(message)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                holds_passed = 0
                for index, frame in enumerate(peer.frames()):
                    self.wfile.write(frame)
                    self.wfile.flush()
                    if index in peer.holds:
                        holds_passed += 1
                        deadline = time.monotonic() + 10  # a safety net, not an expected wait
                        while peer.released < holds_passed and time.monotonic() < deadline:
                            time.sleep(0.02)
            except OSError:
                # BrokenPipe and ConnectionReset are the textbook spellings, but macOS also
                # surfaces send-after-FIN races as plain OSError(EPROTOTYPE) — one net for all.
                peer.closed_early.set()

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def chat_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatPeer]:
    """Point the data root at a fresh world and the ollama provider at a fresh peer."""
    peer = ChatPeer()
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    chat_router._REGISTRY.clear()
    with serve_peer(peer) as base:
        monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_OLLAMA", base)
        yield peer
    chat_router._REGISTRY.clear()


def _start(api: Any, text: str, **extra: Any) -> dict[str, Any]:
    body = {"text": text, "endpoint": ENDPOINT, "model_parameters": {"model": "test-model"}}
    body.update(extra)
    resp = api.client.post("/v1/chat/turns", json=body)
    assert resp.status_code == 200, resp.text
    ack: dict[str, Any] = resp.json()
    assert ack["streamId"] == ack["conversationId"]
    assert ack["status"] == "started"
    return ack


def _delta_text_of(frame: Any) -> str | None:
    """The text of an `on_message_delta` frame, read the way the CLIENT reads it.

    Deliberately NOT `chatturn._delta_text`: a test that measures the stream with the
    production helper is blind to a bug in that helper, and this file's whole subject is
    whether the frames a consumer sees are correct.
    """
    if not isinstance(frame, dict) or frame.get("event") != "on_message_delta":
        return None
    try:
        content = frame["data"]["delta"]["content"]
    except (KeyError, TypeError):
        return None
    if not isinstance(content, list) or len(content) != 1:
        return None
    part = content[0]
    if not isinstance(part, dict) or part.get("type") != "text":
        return None
    return str(part.get("text", ""))


def _events(api: Any, stream_id: str, after: int = 0) -> dict[str, Any]:
    resp = api.client.get(f"/v1/chat/turns/{stream_id}/events", params={"after": after})
    assert resp.status_code == 200, resp.text
    payload: dict[str, Any] = resp.json()
    return payload


def _wait_terminal(api: Any, stream_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _events(api, stream_id)
        if payload["status"] != "active":
            return payload
        time.sleep(0.02)
    raise AssertionError(f"turn {stream_id} still active after {timeout}s")


def _frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [event["frame"] for event in payload["events"]]


class TestStreamedTurn:
    def test_a_turn_streams_persists_and_reports_usage(self, api: Any, chat_env: ChatPeer) -> None:
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        frames = _frames(payload)

        # The opening pair precedes every delta (the client keys everything off them).
        assert frames[0]["created"] is True
        assert frames[0]["message"]["text"] == "Say hello"
        assert frames[0]["message"]["isCreatedByUser"] is True
        assert frames[1]["event"] == "on_run_step"
        step_id = frames[1]["data"]["id"]

        deltas = [f for f in frames if f.get("event") == "on_message_delta"]
        # The CONTRACT is the concatenation, not the chunking: provider chunk boundaries are
        # a transport artifact, and the read side batches adjacent deltas (LC06).
        assert "".join(d["data"]["delta"]["content"][0]["text"] for d in deltas) == "Hello there"
        assert all(d["data"]["id"] == step_id for d in deltas)

        usage = [f for f in frames if f.get("event") == "on_token_usage"]
        assert len(usage) == 1
        assert usage[0]["data"]["input_tokens"] == 7
        assert usage[0]["data"]["output_tokens"] == 3

        final = frames[-1]
        assert final["final"] is True
        assert final["responseMessage"]["text"] == "Hello there"
        assert final["responseMessage"]["unfinished"] is False
        assert final["responseMessage"]["error"] is False
        assert final["conversation"]["title"] == "Say hello"

        # The final frame is a persistence receipt: both rows are durably served.
        convo_id = ack["conversationId"]
        convos = api.get_json("/v1/chat/conversations")["conversations"]
        assert [c["conversationId"] for c in convos] == [convo_id]
        messages = api.get_json(f"/v1/chat/conversations/{convo_id}/messages")
        assert [m["text"] for m in messages] == ["Say hello", "Hello there"]
        assert messages[1]["parentMessageId"] == messages[0]["messageId"]
        # The stored response carries the final content-part shape the client re-renders.
        assert messages[1]["content"] == [{"type": "text", "text": {"value": "Hello there"}}]

    def test_the_request_reaches_the_wire_with_the_users_settings(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        _wait_terminal(
            api,
            _start(
                api,
                "hi",
                promptPrefix="You are terse.",
                maxOutputTokens=512,
            )["streamId"],
        )
        sent = chat_env.requests[0]
        assert sent["model"] == "test-model"
        assert sent["max_tokens"] == 512
        assert sent["messages"][0] == {"role": "system", "content": "You are terse."}
        assert sent["stream_options"] == {"include_usage": True}

    def test_terminal_status_is_never_ahead_of_its_ledger_or_its_messages(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """The 52e18fd invariant, on this surface: the FIRST read that sees a non-active
        status must already see the final frame, and the response message must already be
        served durably."""
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        frames = _frames(payload)
        assert frames[-1].get("final") is True
        messages = api.get_json(f"/v1/chat/conversations/{ack['conversationId']}/messages")
        assert [m["text"] for m in messages] == ["Say hello", "Hello there"]

    def test_history_reaches_the_model_root_first(self, api: Any, chat_env: ChatPeer) -> None:
        first = _start(api, "First question")
        first_final = _frames(_wait_terminal(api, first["streamId"]))[-1]
        response_id = first_final["responseMessage"]["messageId"]

        second = _start(
            api,
            "Second question",
            conversationId=first["conversationId"],
            parentMessageId=response_id,
        )
        _wait_terminal(api, second["streamId"])
        sent = chat_env.requests[1]["messages"]
        assert [(m["role"], m["content"]) for m in sent] == [
            ("user", "First question"),
            ("assistant", "Hello there"),
            ("user", "Second question"),
        ]


class TestRegenerate:
    def test_regenerate_reuses_the_user_message_and_makes_a_sibling(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        first = _start(api, "Original question")
        first_frames = _frames(_wait_terminal(api, first["streamId"]))
        user_id = first_frames[0]["message"]["messageId"]
        first_response = first_frames[-1]["responseMessage"]["messageId"]

        # The client's regenerate shape: fresh placeholder messageId, the TARGET user
        # message in overrideParentMessageId, isRegenerate on.
        chat_env.chunks = ["A better", " answer"]
        regen = _start(
            api,
            "",
            conversationId=first["conversationId"],
            isRegenerate=True,
            messageId="placeholder-never-stored",
            overrideParentMessageId=user_id,
            parentMessageId="00000000-0000-0000-0000-000000000000",
        )
        frames = _frames(_wait_terminal(api, regen["streamId"]))
        assert frames[0]["message"]["messageId"] == user_id  # the ORIGINAL user message
        final = frames[-1]
        assert final["responseMessage"]["text"] == "A better answer"
        assert final["responseMessage"]["parentMessageId"] == user_id
        assert final["responseMessage"]["messageId"] != first_response

        messages = api.get_json(f"/v1/chat/conversations/{first['conversationId']}/messages")
        texts = {m["text"] for m in messages}
        assert texts == {"Original question", "Hello there", "A better answer"}
        assert not any(m["messageId"] == "placeholder-never-stored" for m in messages)
        # Two responses, both siblings under the one user message.
        siblings = [m for m in messages if m["parentMessageId"] == user_id]
        assert len(siblings) == 2
        # The regenerate context contains ONLY the chain up to the user message — the old
        # response is a branch, not history.
        assert [(m["role"], m["content"]) for m in chat_env.requests[1]["messages"]] == [
            ("user", "Original question")
        ]

    def test_regenerate_of_a_missing_target_is_a_400(self, api: Any, chat_env: ChatPeer) -> None:
        resp = api.client.post(
            "/v1/chat/turns",
            json={
                "text": "",
                "endpoint": ENDPOINT,
                "isRegenerate": True,
                "conversationId": "c-none",
                "overrideParentMessageId": "no-such-message",
            },
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


class TestCancellation:
    def test_cancel_mid_stream_really_hangs_up(self, api: Any, chat_env: ChatPeer) -> None:
        chat_env.chunks = [f"chunk{i} " for i in range(200)]
        # Two staged holds: the cancel lands during the first; releasing it lets the engine
        # observe the cancel at chunk 2 and close; the SECOND hold parks the peer until the
        # turn has settled, so its next write measures a dead socket rather than racing the
        # suite's load into the buffer (trap 61).
        chat_env.holds = [0, 1]
        ack = _start(api, "Long story please")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(
                f.get("event") == "on_message_delta" for f in _frames(_events(api, ack["streamId"]))
            ):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("the first delta never arrived")

        resp = api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        assert resp.status_code == 200
        assert resp.json()["aborted"] == ack["streamId"]

        chat_env.release()
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "aborted"
        final = _frames(payload)[-1]
        assert final["aborted"] is True
        assert final["responseMessage"]["unfinished"] is True
        assert final["responseMessage"]["text"].startswith("chunk0")
        # The turn settled above; the second hold's release writes into the socket the
        # engine closed — the deterministic observation of the hangup.
        chat_env.release()
        assert chat_env.closed_early.wait(timeout=5), "the upstream connection stayed open"

    def test_cancel_lands_while_the_upstream_is_silent(self, api: Any, chat_env: ChatPeer) -> None:
        """Trap 58 closed (C5 run control): the blocked READ is bounded, not just the loop
        around it. The peer is PARKED — not one byte arriving — when the cancel lands, and
        nothing ever releases it before the abort settles. The old loop could only observe
        cancel at the next chunk, so this exact scenario blocked for the full 300 s socket
        timeout; the bound is the difference between an abort and a hostage. 200 chunks,
        matching the test above: the hangup observation needs enough post-park writes to
        outrun the socket buffer (trap 61)."""
        chat_env.chunks = [f"chunk{i} " for i in range(200)]
        chat_env.holds = [0, 1]
        ack = _start(api, "Long story please")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(
                f.get("event") == "on_message_delta" for f in _frames(_events(api, ack["streamId"]))
            ):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("the first delta never arrived")

        started = time.monotonic()
        resp = api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        assert resp.status_code == 200
        assert resp.json()["aborted"] == ack["streamId"]
        payload = _wait_terminal(api, ack["streamId"])
        elapsed = time.monotonic() - started
        assert payload["status"] == "aborted"
        assert elapsed < 5.0, f"the abort waited {elapsed:.1f}s on a silent upstream"
        final = _frames(payload)[-1]
        assert final["aborted"] is True
        assert final["responseMessage"]["unfinished"] is True
        # Only now let the parked peer go; its next write observes the dead socket.
        chat_env.release(2)
        assert chat_env.closed_early.wait(timeout=5), "the upstream connection stayed open"

    def test_a_matching_epoch_aborts_exactly_its_own_turn(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        chat_env.hold_after_first.set()
        ack = _start(api, "Hold and abort me")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if any(
                f.get("event") == "on_message_delta" for f in _frames(_events(api, ack["streamId"]))
            ):
                break
            time.sleep(0.02)
        resp = api.client.post(
            f"/v1/chat/turns/{ack['streamId']}/cancel",
            params={"generation_created_at": ack["generationCreatedAt"]},
        )
        assert resp.status_code == 200
        assert resp.json()["aborted"] == ack["streamId"]
        chat_env.resume.set()
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "aborted"

    def test_a_stale_epoch_cannot_abort_the_successor_turn(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        first = _start(api, "One")
        _wait_terminal(api, first["streamId"])
        chat_env.hold_after_first.set()
        second = _start(api, "Two", conversationId=first["conversationId"])
        stale = first["generationCreatedAt"] - 1
        resp = api.client.post(
            f"/v1/chat/turns/{second['streamId']}/cancel",
            params={"generation_created_at": stale},
        )
        assert resp.status_code == 200
        assert resp.json().get("settled") is True  # refused as stale, nothing aborted
        chat_env.resume.set()
        assert _wait_terminal(api, second["streamId"])["status"] == "complete"


class TestHonestFailure:
    def test_missing_key_is_an_error_final_not_a_500(
        self, api: Any, chat_env: ChatPeer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Hermetic on EVERY machine: a developer's exported key must never turn this into a
        # real, paid api.anthropic.com call (the suite's own trap-23 discipline).
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ack_resp = api.client.post("/v1/chat/turns", json={"text": "hi", "endpoint": "anthropic"})
        assert ack_resp.status_code == 200  # the ack is honest; the turn itself reports
        payload = _wait_terminal(api, ack_resp.json()["streamId"])
        assert payload["status"] == "error"
        final = _frames(payload)[-1]
        parts = final["responseMessage"]["content"]
        assert parts and parts[-1]["type"] == "error"
        assert "ANTHROPIC_API_KEY" in parts[-1]["error"]
        assert final["responseMessage"]["error"] is True

    def test_a_strict_server_rejecting_stream_options_still_chats(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        chat_env.reject_stream_options = True
        ack = _start(api, "hi")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        final = _frames(payload)[-1]
        assert final["responseMessage"]["text"] == "Hello there"
        # First request asked for usage, the retry did not — and no usage frame is claimed.
        assert "stream_options" in chat_env.requests[0]
        assert "stream_options" not in chat_env.requests[1]
        assert not any(f.get("event") == "on_token_usage" for f in _frames(payload))

    def test_unknown_endpoint_is_a_400(self, api: Any, chat_env: ChatPeer) -> None:
        resp = api.client.post("/v1/chat/turns", json={"text": "hi", "endpoint": "Nope"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_an_empty_message_is_a_400(self, api: Any, chat_env: ChatPeer) -> None:
        resp = api.client.post("/v1/chat/turns", json={"text": "   ", "endpoint": ENDPOINT})
        assert resp.status_code == 400

    def test_the_chat_surface_cannot_author_a_proof_claim(self) -> None:
        """The L28 vacancy, pinned as a forge test (gate_audit's chat-surface row): a chat
        turn authors no repository change — no ProvenChange, no run_prove, no shadow — so
        there is nothing the proof gate could even be asked to bless. If either name ever
        appears in the module, this path stops being vacuously safe and must grow a real
        forge test in the same commit."""
        import ast as ast_module
        import inspect

        import tempest_api.chatturn as chatturn_module

        tree = ast_module.parse(inspect.getsource(chatturn_module))
        names = {node.id for node in ast_module.walk(tree) if isinstance(node, ast_module.Name)}
        names |= {
            node.attr for node in ast_module.walk(tree) if isinstance(node, ast_module.Attribute)
        }
        assert "ProvenChange" not in names
        assert "run_prove" not in names
        assert "shadow" not in {n.lower() for n in names}

    def test_a_second_start_while_active_is_a_409(self, api: Any, chat_env: ChatPeer) -> None:
        chat_env.hold_after_first.set()
        ack = _start(api, "One")
        resp = api.client.post(
            "/v1/chat/turns",
            json={"text": "Two", "endpoint": ENDPOINT, "conversationId": ack["conversationId"]},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        chat_env.resume.set()
        _wait_terminal(api, ack["streamId"])


class TestDurabilityAndResume:
    def test_the_ledger_replays_from_the_store_after_a_restart(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "Say hello")
        live = _wait_terminal(api, ack["streamId"])
        chat_router._REGISTRY.clear()  # a fresh process: no jobs in memory
        replayed = _events(api, ack["streamId"])
        assert replayed["status"] == "complete"
        assert _frames(replayed) == _frames(live)
        # Active-jobs and status read honestly from nothing.
        assert api.get_json("/v1/chat/turns")["activeJobIds"] == []
        status = api.get_json(f"/v1/chat/turns/{ack['streamId']}")
        assert status["active"] is False

    def test_a_dead_processes_turn_reconciles_on_first_read(
        self, api: Any, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        """A turns row claiming `active` with no live job is a previous process that died
        mid-turn: the first read settles it — partial text kept, aborted final appended,
        status honest."""
        store = PlatformStore(tmp_path / "appdata" / "platform" / "store.sqlite3")
        store.put_many_multi(
            [
                (
                    "conversations",
                    "dead-c",
                    {"conversationId": "dead-c", "title": "t", "updatedAt": "2026-01-01"},
                ),
                (
                    "messages",
                    "dead-u",
                    {
                        "messageId": "dead-u",
                        "conversationId": "dead-c",
                        "text": "the question",
                        "isCreatedByUser": True,
                        "createdAt": "2026-01-01",
                    },
                ),
                (
                    "turns",
                    "dead-c",
                    {
                        "streamId": "dead-c",
                        "conversationId": "dead-c",
                        "status": "active",
                        "generationCreatedAt": 1,
                        "userMessageId": "dead-u",
                        "responseMessageId": "dead-r",
                        "sender": "Ollama (local)",
                    },
                ),
                (
                    "turn_events",
                    "dead-c:00000001",
                    {
                        "streamId": "dead-c",
                        "seq": 1,
                        "frame": {
                            "event": "on_message_delta",
                            "data": {
                                "id": "step_dead-r_0",
                                "delta": {"content": [{"type": "text", "text": "partial "}]},
                            },
                        },
                    },
                ),
            ]
        )
        status = api.get_json("/v1/chat/turns/dead-c")
        assert status["active"] is False
        payload = _events(api, "dead-c")
        assert payload["status"] == "aborted"
        final = _frames(payload)[-1]
        assert final["final"] is True and final["aborted"] is True
        assert final["responseMessage"]["text"] == "partial "
        assert final["responseMessage"]["sender"] == "Ollama (local)"
        messages = api.get_json("/v1/chat/conversations/dead-c/messages")
        assert [m["messageId"] for m in messages] == ["dead-u", "dead-r"]
        assert messages[1]["unfinished"] is True

    def test_a_new_turn_retires_the_previous_generations_ledger(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        first = _start(api, "First")
        _wait_terminal(api, first["streamId"])
        first_len = len(_frames(_events(api, first["streamId"])))
        assert first_len >= 4

        chat_env.chunks = ["short"]
        follow = _frames(
            _wait_terminal(
                api, _start(api, "Second", conversationId=first["conversationId"])["streamId"]
            )
        )
        chat_router._REGISTRY.clear()  # force the store path: no memory ledger survives
        replayed = _frames(_events(api, first["streamId"]))
        # ONLY the second generation's frames — no interleaving with the first's longer run.
        assert replayed == follow
        assert replayed[0]["created"] is True
        assert replayed[-1]["final"] is True


class _FlakyStore(PlatformStore):
    """A store whose Nth put_many_multi raises — the disk-full rehearsal."""

    def __init__(self, path: Path, *, fail_on_calls: set[int]) -> None:
        super().__init__(path)
        self.calls = 0
        self.fail_on_calls = fail_on_calls

    def put_many_multi(
        self,
        rows: list[tuple[str, str, dict[str, Any]]],
        *,
        delete_equal: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise OSError("planted store failure")
        super().put_many_multi(rows, delete_equal=delete_equal)


def _direct_turns(tmp_path: Path, **kwargs: Any) -> Any:
    """A ChatTurns over its own store, for arms the HTTP surface cannot reach directly."""
    from tempest.inference import cost
    from tempest_api.chatturn import ChatTurns

    store = kwargs.pop("store", None) or PlatformStore(tmp_path / "direct" / "store.sqlite3")
    meter = kwargs.pop("meter", None)
    if meter is None:
        meter = cost.Meter(repo=tmp_path / "direct")
    import os

    return ChatTurns(store, env_provider=lambda: dict(os.environ), meter=meter), store


def _drive(turns: Any, text: str = "hi", **extra: Any) -> dict[str, Any]:
    body = {"text": text, "endpoint": ENDPOINT, "model_parameters": {"model": "m"}}
    body.update(extra)
    ack: dict[str, Any] = turns.start_turn(body)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        payload: dict[str, Any] = turns.events_after(ack["streamId"], 0)
        if payload["status"] != "active":
            payload["ack"] = ack
            return payload
        time.sleep(0.02)
    raise AssertionError("direct turn never settled")


class TestCoverageNamedArms:
    def test_quotes_and_files_ride_the_stored_user_message(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "with baggage", quotes=[{"text": "q"}], files=[{"file_id": "f1"}])
        _wait_terminal(api, ack["streamId"])
        messages = api.get_json(f"/v1/chat/conversations/{ack['conversationId']}/messages")
        assert messages[0]["quotes"] == [{"text": "q"}]
        assert messages[0]["files"] == [{"file_id": "f1"}]

    def test_a_failed_opening_commit_releases_the_reservation(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        store = _FlakyStore(tmp_path / "flaky" / "store.sqlite3", fail_on_calls={1})
        turns, _ = _direct_turns(tmp_path, store=store)
        with pytest.raises(OSError):
            turns.start_turn({"text": "hi", "endpoint": ENDPOINT})
        # The stream id is NOT stuck reserved: the same conversation can start again.
        payload = _drive(turns, "hi again")
        assert payload["status"] == "complete"

    def test_settled_jobs_are_evicted_and_replay_from_the_store(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        turns, _ = _direct_turns(tmp_path)
        first = _drive(turns, "turn zero")
        for index in range(9):
            _drive(turns, f"turn {index + 1}")
        with turns._lock:
            assert len(turns._jobs) <= 9  # 8 settled kept + at most the newest
            assert first["ack"]["streamId"] not in turns._jobs
        replay = turns.events_after(first["ack"]["streamId"], 0)
        assert replay["status"] == "complete"
        assert replay["events"][-1]["frame"]["final"] is True

    def test_an_upstream_500_is_an_error_final(self, api: Any, chat_env: ChatPeer) -> None:
        chat_env.status = 500
        payload = _wait_terminal(api, _start(api, "hi")["streamId"])
        assert payload["status"] == "error"
        parts = _frames(payload)[-1]["responseMessage"]["content"]
        assert parts[-1]["type"] == "error"

    def test_a_defect_inside_tempest_is_surfaced_in_band(
        self, api: Any, chat_env: ChatPeer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempest_api.chatturn as chatturn_module

        def explode(*_: Any, **__: Any) -> Any:
            raise RuntimeError("planted defect")

        monkeypatch.setattr(chatturn_module, "stream_events", explode)
        payload = _wait_terminal(api, _start(api, "hi")["streamId"])
        assert payload["status"] == "error"
        parts = _frames(payload)[-1]["responseMessage"]["content"]
        assert "planted defect" in parts[-1]["error"]

    def test_a_breached_cost_cap_reaches_the_reply_and_survives_reload(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        from decimal import Decimal

        from tempest.inference import cost

        meter = cost.Meter(
            repo=tmp_path / "direct",
            budgets={"task": cost.Budget(max_total_tokens=1)},
        )
        turns, _ = _direct_turns(tmp_path, meter=meter)
        payload = _drive(turns, "expensive question")
        final = payload["events"][-1]["frame"]
        assert "[cost cap:" in final["responseMessage"]["text"]
        # The note is part of the durable message, not a ghost delta (M3).
        stored = turns.messages_for(final["responseMessage"]["conversationId"])
        assert "[cost cap:" in stored[-1]["text"]
        assert Decimal is not None  # keep the import honest

    def test_a_failed_terminal_commit_publishes_an_error_not_a_lie(
        self, chat_env: ChatPeer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tempest_api.chatturn as chatturn_module

        # Call #2 must BE the terminal commit on every machine: a loaded runner can stretch
        # the opening past the time-based flush trigger, landing the planted failure on a
        # recoverable mid-stream flush instead. Frames stay under the count trigger; the
        # clock trigger is parked.
        monkeypatch.setattr(chatturn_module, "_FLUSH_EVERY_SECONDS", 3600.0)
        store = _FlakyStore(tmp_path / "flaky2" / "store.sqlite3", fail_on_calls={2})
        turns, _ = _direct_turns(tmp_path, store=store)
        payload = _drive(turns, "hi")
        assert payload["status"] == "error"
        final = payload["events"][-1]["frame"]
        assert final["responseMessage"]["error"] is True
        assert any(
            part.get("type") == "error" and "could not be saved" in str(part.get("error"))
            for part in final["responseMessage"]["content"]
        )

    def test_a_failed_delta_flush_retries_into_the_terminal_commit(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        chat_env.chunks = [f"c{i} " for i in range(40)]  # enough to force a mid-stream flush
        store = _FlakyStore(tmp_path / "flaky3" / "store.sqlite3", fail_on_calls={2})
        turns, _ = _direct_turns(tmp_path, store=store)
        payload = _drive(turns, "long")
        assert payload["status"] == "complete"
        assert store.calls >= 3
        # Restart: the durable replay carries EVERY delta — no mid-text hole (M4).
        fresh_turns, _ = _direct_turns(tmp_path, store=PlatformStore(store.path))
        replayed = fresh_turns.events_after(payload["ack"]["streamId"], 0)
        deltas = [
            e["frame"] for e in replayed["events"] if e["frame"].get("event") == "on_message_delta"
        ]
        joined = "".join(d["data"]["delta"]["content"][0]["text"] for d in deltas)
        assert joined == "".join(f"c{i} " for i in range(40)), "a mid-text hole survived"

    def test_a_broken_parent_chain_still_reaches_the_model(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "orphan", parentMessageId="ghost-parent")
        _wait_terminal(api, ack["streamId"])
        sent = chat_env.requests[0]["messages"]
        assert [(m["role"], m["content"]) for m in sent] == [("user", "orphan")]

    def test_events_for_a_stream_nobody_started_are_empty_and_honest(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        payload = _events(api, "never-existed")
        assert payload == {"streamId": "never-existed", "status": "unknown", "events": []}

    def test_status_of_a_live_turn_reports_active_with_its_epoch(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        chat_env.hold_after_first.set()
        ack = _start(api, "hold me")
        status = api.get_json(f"/v1/chat/turns/{ack['streamId']}")
        assert status["active"] is True
        assert status["generationCreatedAt"] == ack["generationCreatedAt"]
        assert status["createdAt"] == ack["generationCreatedAt"]
        assert api.get_json("/v1/chat/turns")["activeJobIds"] == [ack["streamId"]]
        chat_env.resume.set()
        _wait_terminal(api, ack["streamId"])

    def test_cancel_of_a_settled_turn_is_a_settled_answer(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "hi")
        _wait_terminal(api, ack["streamId"])
        resp = api.client.post(f"/v1/chat/turns/{ack['streamId']}/cancel")
        assert resp.json().get("settled") is True

    def test_reconcile_stands_down_when_the_job_appears_mid_check(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        """The registry double-check under the lock: a turns row can read `active` while the
        job insert is a hair behind only in a foreign process's snapshot — if the job shows
        up before the reconciler writes, it must stand down."""
        from tempest_api.chatturn import _Job

        turns, store = _direct_turns(tmp_path)
        job = _Job(
            stream_id="race-c",
            conversation_id="race-c",
            generation_created_at=1,
            user_message_id="u",
            response_message_id="r",
        )

        real_get = store.get

        def get_and_sneak(collection: str, doc_id: str) -> Any:
            doc = real_get(collection, doc_id)
            if collection == "turns" and doc_id == "race-c":
                with turns._lock:
                    turns._jobs["race-c"] = job
            return doc

        store.put("turns", "race-c", {"streamId": "race-c", "status": "active"})
        store.get = get_and_sneak  # type: ignore[method-assign]
        found = turns._job_or_reconcile("race-c")
        assert found is job
        # No reconciliation happened: no aborted final was written for the live turn.
        assert store.find_equal("turn_events", "streamId", "race-c", order_by="seq") == []

    def test_the_token_ceiling_clamps_and_model_parameters_is_a_real_source(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        _wait_terminal(api, _start(api, "top-level huge", maxOutputTokens=999_999)["streamId"])
        assert chat_env.requests[-1]["max_tokens"] == 32_768  # the ceiling bites

        body = {
            "text": "nested source",
            "endpoint": ENDPOINT,
            "model_parameters": {"model": "test-model", "maxOutputTokens": 777},
        }
        resp = api.client.post("/v1/chat/turns", json=body)
        assert resp.status_code == 200
        _wait_terminal(api, resp.json()["streamId"])
        assert chat_env.requests[-1]["max_tokens"] == 777

    def test_events_after_a_cursor_serves_only_the_tail_on_both_paths(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "cursor test")
        full = _wait_terminal(api, ack["streamId"])
        # Cursors are SEQ-based, and coalesced frames carry their run's LAST seq (LC06) —
        # so the cursor comes from the previous event's seq, never from a frame count.
        last_seq = full["events"][-1]["seq"]
        prev_seq = full["events"][-2]["seq"]
        tail = _events(api, ack["streamId"], after=prev_seq)
        assert [e["seq"] for e in tail["events"]] == [last_seq]
        assert tail["events"][0]["frame"].get("final") is True
        chat_router._REGISTRY.clear()  # the store path must agree with the memory path
        stored_tail = _events(api, ack["streamId"], after=prev_seq)
        assert [e["seq"] for e in stored_tail["events"]] == [last_seq]
        assert stored_tail["events"][0]["frame"].get("final") is True

    def test_only_a_single_text_delta_frame_is_coalescable(self) -> None:
        """`_delta_text` is the predicate the coalescer merges on, and every arm that answers
        None keeps a frame OUT of a merge. Getting one wrong does not raise — it silently
        merges frames that are not adjacent text, or refuses to merge ones that are, and the
        reader sees the damage rather than an error. So each shape is pinned directly.

        The multi-part and non-text arms matter because a merge concatenates `content[0].text`
        and drops everything else: a frame carrying a second part, or an image part, would
        lose it silently.
        """
        from tempest_api.chatturn import _delta_text

        def frame_with(content: Any) -> dict[str, Any]:
            return {
                "event": "on_message_delta",
                "data": {"id": "s0", "delta": {"content": content}},
            }

        assert _delta_text(frame_with([{"type": "text", "text": "hi"}])) == "hi"

        # Not a delta frame at all.
        assert _delta_text({"event": "on_run_step", "data": {}}) is None
        assert _delta_text("not a frame") is None
        assert _delta_text(None) is None

        # A delta whose content is not exactly ONE text part: merging would drop a part.
        assert _delta_text(frame_with([])) is None
        assert (
            _delta_text(frame_with([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]))
            is None
        )
        assert _delta_text(frame_with([{"type": "image_url", "image_url": {}}])) is None

        # Malformed shapes reach the same answer through the except arm rather than raising:
        # a frame the coalescer cannot read is a frame it must not merge, not a crash.
        assert _delta_text({"event": "on_message_delta", "data": {}}) is None
        assert _delta_text({"event": "on_message_delta", "data": {"delta": {}}}) is None
        assert _delta_text(frame_with("not-a-list")) is None
        assert _delta_text(frame_with([{"type": "text"}])) is None

    def test_a_coalesced_frame_carries_its_runs_LAST_seq_so_a_resume_repeats_nothing(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """LC06/ADR-0079 §7's actual invariant, and the one the suite could not see.

        `_coalesce_deltas` merges adjacent same-step text deltas into ONE frame and sets
        `merged["seq"] = event["seq"]` — the run's LAST seq. The docstring calls that rule
        load-bearing "because a consumer that saw the merged frame has seen everything up to
        that seq", and it is: `useResumableSSE` resumes with `after=<the seq it last saw>`.

        Deleting that one line left all 37 tests in this file green. The sibling cursor test
        above cannot catch it because it reads BOTH its cursor and its expectation out of the
        same (mutated) event list, so it stays self-consistent — an expectation derived from
        the output cannot contradict the output.

        This asserts the user-visible consequence instead: resume from the cursor a client
        would actually hold after rendering the whole stream, and require that the tail
        carries no delta text at all. With the merged frame carrying the FIRST seq, the tail
        re-serves every chunk after the run's first one and the reader sees duplicated text.
        """
        ack = _start(api, "coalescing cursor test")
        full = _wait_terminal(api, ack["streamId"])
        events = full["events"]

        def delta_text(payload_events: list[dict[str, Any]]) -> str:
            return "".join(
                str(t) for e in payload_events if (t := _delta_text_of(e.get("frame"))) is not None
            )

        whole = delta_text(events)
        assert whole, "no delta text streamed — this test would be vacuous (trap 60)"
        deltas = [e for e in events if _delta_text_of(e.get("frame")) is not None]
        assert deltas, "no delta frames at all"

        # A merge must actually have HAPPENED, or the seq rule under test was never
        # exercised and everything below is green about nothing (trap 60). The peer sends
        # three chunks; a working coalescer delivers them as strictly fewer frames carrying
        # the identical text.
        assert len(chat_env.chunks) > 1, "the peer must send more than one chunk"
        assert whole == "".join(chat_env.chunks), (
            "the delivered text must be exactly what the peer streamed"
        )
        assert len(deltas) < len(chat_env.chunks), (
            f"{len(chat_env.chunks)} chunks arrived as {len(deltas)} frame(s) — nothing was "
            f"coalesced, so the LAST-seq rule is not under test here"
        )

        # The cursor a client holds once it has rendered every delta it was sent.
        cursor = deltas[-1]["seq"]
        tail = _events(api, ack["streamId"], after=cursor)
        assert delta_text(tail["events"]) == "", (
            "resuming from the last delta frame's seq re-delivered text the client had "
            "already rendered — the merged frame is not carrying its run's LAST seq"
        )

        # Both paths, because a reload reads the STORE and must agree with the live feed.
        chat_router._REGISTRY.clear()
        stored_full = _events(api, ack["streamId"], after=0)
        assert delta_text(stored_full["events"]) == whole, (
            "the store replay must render exactly what the stream rendered"
        )
        stored_deltas = [
            e for e in stored_full["events"] if _delta_text_of(e.get("frame")) is not None
        ]
        stored_tail = _events(api, ack["streamId"], after=stored_deltas[-1]["seq"])
        assert delta_text(stored_tail["events"]) == ""

    def test_every_cursor_in_the_stream_splits_the_text_without_overlap(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """The general form: for EVERY seq in the stream, what was delivered up to that seq
        plus what a resume from it delivers must equal the whole text exactly once. A rule
        that only held at the end would still duplicate mid-stream, which is precisely when
        a real reconnect happens."""
        ack = _start(api, "every cursor")
        full = _wait_terminal(api, ack["streamId"])
        events = full["events"]

        def delta_text(payload_events: list[dict[str, Any]]) -> str:
            return "".join(
                str(t) for e in payload_events if (t := _delta_text_of(e.get("frame"))) is not None
            )

        whole = delta_text(events)
        assert whole, "vacuous without streamed text"
        checked = 0
        for event in events:
            seq = event["seq"]
            head = delta_text([e for e in events if e["seq"] <= seq])
            tail = delta_text(_events(api, ack["streamId"], after=seq)["events"])
            assert head + tail == whole, (
                f"resuming after seq {seq} does not split the text cleanly: "
                f"{head!r} + {tail!r} != {whole!r}"
            )
            checked += 1
        assert checked == len(events) and checked > 0, "no cursors were actually exercised"

    def test_a_broken_meter_disk_never_kills_the_turn(
        self, chat_env: ChatPeer, tmp_path: Path
    ) -> None:
        """The spend ledger's volume filling up degrades to an unrecorded charge with a
        logged cause — never a dead turn thread that leaves the conversation active forever."""

        class DiskFullMeter:
            def spend(self, **_: Any) -> None:
                raise OSError("no space left on device")

        turns, _ = _direct_turns(tmp_path, meter=DiskFullMeter())
        payload = _drive(turns, "spend fails")
        assert payload["status"] == "complete"
        final = payload["events"][-1]["frame"]
        assert final["responseMessage"]["text"] == "Hello there"
        assert "[cost cap:" not in final["responseMessage"]["text"]

    def test_the_single_conversation_read_serves_the_view_mount(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "mount me")
        _wait_terminal(api, ack["streamId"])
        doc = api.get_json(f"/v1/chat/conversations/{ack['conversationId']}")
        assert doc["conversationId"] == ack["conversationId"]
        assert doc["title"] == "mount me"
        missing = api.client.get("/v1/chat/conversations/no-such-conversation")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "NOT_FOUND"

    def test_a_long_first_message_becomes_a_trimmed_title(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        ack = _start(api, "this opening message is far too long to be a conversation title")
        _wait_terminal(api, ack["streamId"])
        convos = api.get_json("/v1/chat/conversations")["conversations"]
        assert convos[0]["title"].endswith("…")
        assert len(convos[0]["title"]) <= 41


def _reasoning_text_of(frame: Any) -> str | None:
    """The thinking of an `on_reasoning_delta` frame, read the way the CLIENT reads it
    (`useStepHandler.ts` → `ContentTypes.THINK` → `part.think`). Deliberately not the
    production helper, for the reason `_delta_text_of` gives."""
    if not isinstance(frame, dict) or frame.get("event") != "on_reasoning_delta":
        return None
    try:
        content = frame["data"]["delta"]["content"]
    except (KeyError, TypeError):
        return None
    if not isinstance(content, list) or len(content) != 1:
        return None
    part = content[0]
    if not isinstance(part, dict) or part.get("type") != "think":
        return None
    return str(part.get("think", ""))


class TestReasoningReachesTheUser:
    """A reasoning model's thinking is its own channel on the wire too (ADR-0081).

    The failure this pins was measured against a real `llama-server` serving Qwen3 0.6B:
    every frame carried `reasoning_content`, none carried `content`, and the turn finished
    with `finish_reason: length`. The user saw a spinner and then nothing — no text, no
    explanation, no error (L15.3, L23). Both Qwen3 rows and the DeepSeek-R1 distill in the
    shipped catalogue are reasoning models, and the smallest is the first thing a person
    clicks.
    """

    def test_thinking_streams_on_its_own_step_and_persists_beside_the_answer(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        chat_env.reasoning = ["Okay", ", the user"]
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        frames = _frames(payload)

        # The thinking gets its OWN run step, declared as a think step, because the client
        # indexes content parts by step index — two channels on one step would collide.
        steps = [f for f in frames if f.get("event") == "on_run_step"]
        assert len(steps) == 2
        text_step, think_step = steps[0], steps[1]
        assert text_step["data"]["index"] == 0
        assert think_step["data"]["index"] == 1
        assert think_step["data"]["stepDetails"]["message_creation"]["content_type"] == "think"

        thinking = [t for t in (_reasoning_text_of(f) for f in frames) if t is not None]
        assert "".join(thinking) == "Okay, the user"
        assert all(
            f["data"]["id"] == think_step["data"]["id"]
            for f in frames
            if f.get("event") == "on_reasoning_delta"
        )

        # The answer is unchanged and still the message's `text` — thinking is never folded
        # into it, because `text` is what a fork, an export and a title are built from.
        assert (
            "".join(t for t in (_delta_text_of(f) for f in frames) if t is not None)
            == "Hello there"
        )
        final = frames[-1]
        assert final["responseMessage"]["text"] == "Hello there"

        # And the persisted message renders what the stream rendered, in the same order.
        convo_id = ack["conversationId"]
        messages = api.get_json(f"/v1/chat/conversations/{convo_id}/messages")
        assert messages[1]["content"] == [
            {"type": "text", "text": {"value": "Hello there"}},
            {"type": "think", "think": {"value": "Okay, the user"}},
        ]

    def test_a_reply_that_is_all_thinking_says_so_instead_of_nothing(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """The exact measured failure: thinking, no answer. The turn must not complete
        silently — an empty bubble is the state L23 forbids."""
        chat_env.reasoning = ["Okay, let me think about this"]
        chat_env.chunks = []
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        assert payload["status"] == "complete"
        frames = _frames(payload)

        thinking = [t for t in (_reasoning_text_of(f) for f in frames) if t is not None]
        assert "".join(thinking) == "Okay, let me think about this", "the thinking survives"

        answer = "".join(t for t in (_delta_text_of(f) for f in frames) if t is not None)
        assert answer, "the turn must say SOMETHING rather than finish blank"
        assert "thinking" in answer.lower()
        assert "reply length" in answer.lower(), "and name the way out (L15.3)"

        convo_id = ack["conversationId"]
        messages = api.get_json(f"/v1/chat/conversations/{convo_id}/messages")
        assert messages[1]["text"] == answer, "a reload shows the same sentence"

    def test_an_utterly_empty_reply_is_reported_too(self, api: Any, chat_env: ChatPeer) -> None:
        """No thinking either — a server that streamed a well-formed nothing. Still not
        allowed to look like a completed answer."""
        chat_env.reasoning = []
        chat_env.chunks = []
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        frames = _frames(payload)
        answer = "".join(t for t in (_delta_text_of(f) for f in frames) if t is not None)
        assert "empty reply" in answer.lower(), answer

    def test_a_model_that_never_thinks_streams_exactly_what_it_did_before(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """The regression guard: no thinking means no think step, no reasoning frames, and
        no second content part. The overwhelming majority of turns take this path."""
        ack = _start(api, "Say hello")
        payload = _wait_terminal(api, ack["streamId"])
        frames = _frames(payload)
        assert [f for f in frames if f.get("event") == "on_run_step"].__len__() == 1
        assert not [f for f in frames if f.get("event") == "on_reasoning_delta"]
        convo_id = ack["conversationId"]
        messages = api.get_json(f"/v1/chat/conversations/{convo_id}/messages")
        assert messages[1]["content"] == [{"type": "text", "text": {"value": "Hello there"}}]

    def test_a_long_think_coalesces_on_replay_like_the_answer_does(
        self, api: Any, chat_env: ChatPeer
    ) -> None:
        """LC06 applies to both channels or to neither: a reload that re-renders 200 frames
        where the stream rendered 3 is a different experience, and the batching is the read
        side's, applied identically live and from the store."""
        chat_env.reasoning = [f"t{i}" for i in range(12)]
        ack = _start(api, "Say hello")
        _wait_terminal(api, ack["streamId"])
        frames = _frames(_events(api, ack["streamId"]))
        reasoning_frames = [f for f in frames if f.get("event") == "on_reasoning_delta"]
        assert len(reasoning_frames) < 12, "adjacent thinking deltas merged"
        assert "".join(
            t for t in (_reasoning_text_of(f) for f in frames) if t is not None
        ) == "".join(f"t{i}" for i in range(12))
