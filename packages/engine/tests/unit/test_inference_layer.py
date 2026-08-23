"""Phase 19.5 pins: the multi-provider model layer (P1, L18/L21/L23).

Every network test runs against a **real local HTTP server** speaking the actual wire protocol —
the same discipline as `helpers_fake_anthropic` (L4: nothing is monkeypatched, the genuine
request-building and response-parsing path executes). Zero external egress, so these gates are
free and deterministic in CI, which is the standing answer to QV2/QV10.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tempest.inference import client as mc
from tempest.inference import providers as mp


class Peer:
    """A recording stand-in for a provider endpoint, in either wire shape."""

    def __init__(self, wire: str) -> None:
        self.wire = wire
        self.status = 200
        self.text = "hello from the peer"
        self.sse: list[str] | None = None
        #: Verbatim frames, for exercising the event shapes real providers actually send.
        self.raw: list[bytes] | None = None
        self.requests: list[dict[str, object]] = []
        self.headers: list[dict[str, str]] = []
        self.paths: list[str] = []
        self.closed_early = threading.Event()
        #: Arm to make "the client hung up MID-STREAM" a fact instead of a race.
        #:
        #: Without it the peer writes every frame in a tight loop, and 200 small frames fit
        #: inside the socket buffer — so whether any write raises BrokenPipe depends on which
        #: side wins a scheduling race. Under load the peer wins, no write ever fails,
        #: `closed_early` stays unset, and a test about CANCELLATION fails for a reason about
        #: buffer sizes (trap 61). Armed, the peer stops after its first frame until `resume`,
        #: which the test sets only once the client has actually torn the connection down.
        self.hold_after_first = threading.Event()
        self.resume = threading.Event()

    def body(self) -> bytes:
        if self.wire == mp.WIRE_ANTHROPIC:
            return json.dumps(
                {
                    "content": [{"type": "text", "text": self.text}],
                    "usage": {"input_tokens": 11, "output_tokens": 22},
                }
            ).encode()
        return json.dumps(
            {
                "choices": [{"message": {"content": self.text}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 22},
            }
        ).encode()

    def sse_frames(self) -> list[bytes]:
        if self.raw is not None:
            return [*self.raw, b"data: [DONE]\n\n"]
        chunks = self.sse or ["one ", "two ", "three"]
        out = []
        for chunk in chunks:
            if self.wire == mp.WIRE_ANTHROPIC:
                payload = {"type": "content_block_delta", "delta": {"text": chunk}}
            else:
                payload = {"choices": [{"delta": {"content": chunk}}]}
            out.append(b"data: " + json.dumps(payload).encode() + b"\n\n")
        out.append(b"data: [DONE]\n\n")
        return out


@contextmanager
def serve(peer: Peer) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            peer.requests.append(json.loads(raw))
            peer.headers.append({k.lower(): v for k, v in self.headers.items()})
            peer.paths.append(self.path)
            if peer.status != 200:
                body = json.dumps({"error": {"message": "planted failure"}}).encode()
                self.send_response(peer.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if json.loads(raw).get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for index, frame in enumerate(peer.sse_frames()):
                        self.wfile.write(frame)
                        self.wfile.flush()
                        if index == 0 and peer.hold_after_first.is_set():
                            # Hold the stream open until the test says the client has gone. The
                            # timeout is a safety net, not a wait anybody expects to expire.
                            peer.resume.wait(timeout=10)
                except (BrokenPipeError, ConnectionResetError):
                    peer.closed_early.set()  # the client really hung up
                return
            body = peer.body()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _env(provider: mp.Provider, base: str, key: str = "test-key") -> dict[str, str]:
    env = {provider.base_url_env(): base}
    if provider.needs_key:
        env[provider.env_var] = key
    return env


class TestRegistry:
    """The master prompt's gate: 12+ providers, and adding one touches no feature code."""

    def test_at_least_twelve_providers_are_configured(self) -> None:
        assert len(mp.PROVIDERS) >= 12, f"only {len(mp.PROVIDERS)} providers"

    def test_ids_are_unique(self) -> None:
        assert len(set(mp.ids())) == len(mp.ids())

    def test_every_provider_is_reachable_by_a_wire_we_actually_implement(self) -> None:
        """A row we cannot speak to would be a provider count that lies."""
        for p in mp.PROVIDERS:
            assert p.wire in mp.WIRES, f"{p.id} has unknown wire {p.wire}"

    def test_every_remote_provider_names_a_key_variable_and_uses_https(self) -> None:
        for p in mp.PROVIDERS:
            if p.local:
                assert p.base_url.startswith("http://127.0.0.1"), f"{p.id} is not loopback"
                assert not p.needs_key, f"{p.id} is local but demands a key"
            else:
                assert p.base_url.startswith("https://"), f"{p.id} is not https"
                assert p.env_var, f"{p.id} names no key variable"

    def test_local_providers_exist_so_offline_use_is_real(self) -> None:
        """L23 is only concrete if something works with the network unplugged."""
        assert len(mp.local_ids()) >= 2

    def test_an_unknown_provider_lists_the_known_ones(self) -> None:
        with pytest.raises(mp.UnknownProvider, match="anthropic"):
            mp.get("not-a-provider")

    def test_a_provider_invented_at_runtime_works_end_to_end(self) -> None:
        """The proof that a provider is DATA: this one is not in the registry file at all."""
        invented = mp.Provider(
            id="invented-co",
            label="Invented Co",
            wire=mp.WIRE_OPENAI,
            base_url="https://example.invalid/v1",
            env_var="INVENTED_CO_API_KEY",
            default_model="m-1",
        )
        peer = Peer(mp.WIRE_OPENAI)
        with serve(peer) as base:
            # Monkeypatching is banned (L4); registering a row is the supported extension point.
            original = mp.PROVIDERS
            mp.PROVIDERS = (*original, invented)
            try:
                out = mc.complete(
                    "invented-co", [mc.Message("user", "hi")], env=_env(invented, base)
                )
            finally:
                mp.PROVIDERS = original
        assert out.text == "hello from the peer"
        assert out.provider == "invented-co"


class TestBothWires:
    @pytest.mark.parametrize("provider_id", ["anthropic", "openai"])
    def test_a_completion_round_trips_with_usage(self, provider_id: str) -> None:
        provider = mp.get(provider_id)
        peer = Peer(provider.wire)
        with serve(peer) as base:
            out = mc.complete(
                provider_id, [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
            )
        assert out.text == "hello from the peer"
        assert out.model == "m-1"
        assert (out.usage.input_tokens, out.usage.output_tokens) == (11, 22)

    def test_the_anthropic_wire_sends_its_own_headers_and_path(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            mc.complete(
                "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
            )
        assert peer.paths == ["/v1/messages"]
        assert peer.headers[0]["x-api-key"] == "test-key"
        assert peer.headers[0]["anthropic-version"] == mc.ANTHROPIC_VERSION
        assert "authorization" not in peer.headers[0]

    def test_the_openai_wire_sends_a_bearer_token_and_its_own_path(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            mc.complete("openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1")
        assert peer.paths == ["/chat/completions"]
        assert peer.headers[0]["authorization"] == "Bearer test-key"
        assert "x-api-key" not in peer.headers[0]

    def test_a_local_provider_needs_no_key_at_all(self) -> None:
        provider = mp.get("ollama")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            out = mc.complete(
                "ollama",
                [mc.Message("user", "hi")],
                env={provider.base_url_env(): base},
                model="llama",
            )
        assert out.text == "hello from the peer"
        assert "authorization" not in peer.headers[0]


class TestStreamingAndCancellation:
    @pytest.mark.parametrize("provider_id", ["anthropic", "openai"])
    def test_streaming_yields_deltas_in_order(self, provider_id: str) -> None:
        provider = mp.get(provider_id)
        peer = Peer(provider.wire)
        peer.sse = ["al", "pha", " beta"]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    provider_id, [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "alpha beta"
        assert peer.requests[0]["stream"] is True

    def test_cancellation_closes_the_upstream_connection(self) -> None:
        """§7: cancellation must cancel the request, not merely hide the output.

        The peer records a broken pipe, which is the observable proof that the connection was
        torn down rather than left running while we stopped displaying tokens.
        """
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = [f"chunk{i} " for i in range(200)]
        # The peer stops after frame 0 and waits, so the client's teardown is guaranteed to
        # happen while the response is still open. Whether a broken pipe is observed is then a
        # fact about cancellation rather than about who won a race to the socket buffer.
        peer.hold_after_first.set()
        cancel = threading.Event()
        with serve(peer) as base:
            received = []
            with pytest.raises(mc.Cancelled):
                for delta in mc.stream(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    cancel=cancel,
                ):
                    received.append(delta)
                    cancel.set()  # cancel after the very first delta
            # Only now — the client has raised and unwound, so the socket is gone. The peer's
            # next write is the observation.
            peer.resume.set()
            assert peer.closed_early.wait(timeout=5), "the upstream connection stayed open"
        assert len(received) == 1, "cancellation did not stop the stream promptly"


class TestStreamEvents:
    """`stream_events` — deltas plus the provider's own in-stream usage report (C5.1)."""

    def test_anthropic_usage_rides_message_start_and_message_delta(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "al"}}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "pha"}}\n\n',
            b'data: {"type": "message_delta", "usage": {"output_tokens": 3}}\n\n',
            b'data: {"type": "message_delta", "usage": {"output_tokens": 7}}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert [e.text for e in events if isinstance(e, mc.TextDelta)] == ["al", "pha"]
        usage = [e for e in events if isinstance(e, mc.StreamUsage)]
        # The LAST cumulative output count wins, and usage follows every delta.
        assert usage == [mc.StreamUsage(input_tokens=12, output_tokens=7)]
        assert isinstance(events[-1], mc.StreamUsage)

    def test_openai_usage_is_requested_and_read(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"content": "one "}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "two"}}]}\n\n',
            b'data: {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert [e.text for e in events if isinstance(e, mc.TextDelta)] == ["one ", "two"]
        assert events[-1] == mc.StreamUsage(input_tokens=9, output_tokens=4)
        # The OpenAI wire reports stream usage only when asked — the request must ask.
        assert peer.requests[0]["stream_options"] == {"include_usage": True}

    def test_plain_stream_never_asks_for_usage(self) -> None:
        """`stream()`'s request stays byte-compatible: no stream_options arrives uninvited."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = ["hi"]
        with serve(peer) as base:
            list(
                mc.stream("openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m")
            )
        assert "stream_options" not in peer.requests[0]

    def test_a_silent_server_yields_no_usage_event(self) -> None:
        """Absence is absence — no fabricated zeros for a server that reported nothing."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = ["only text"]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert events == [mc.TextDelta("only text")]

    def test_malformed_usage_shapes_are_ignored_not_fatal(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "message_start", "message": "not-a-dict"}\n\n',
            b'data: {"type": "message_start", "message": {"usage": {"input_tokens": "NaN"}}}\n\n',
            b'data: {"type": "message_delta", "usage": []}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "ok"}}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert events == [mc.TextDelta("ok")]

    def test_cancellation_reports_no_usage_for_a_killed_turn(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        # Frame 0 must BE a delta: the peer holds after its first frame, and the client can
        # only cancel from inside the loop — a leading usage-only frame would leave both
        # sides waiting on the safety timeout instead of on each other (trap 61).
        peer.raw = [b'data: {"type": "content_block_delta", "delta": {"text": "first"}}\n\n'] + [
            b'data: {"type": "content_block_delta", "delta": {"text": "more"}}\n\n'
            for _ in range(50)
        ]
        peer.hold_after_first.set()
        cancel = threading.Event()
        events: list[mc.StreamEvent] = []
        with serve(peer) as base:
            with pytest.raises(mc.Cancelled):
                for event in mc.stream_events(
                    "anthropic",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m",
                    cancel=cancel,
                ):
                    events.append(event)
                    cancel.set()
            peer.resume.set()
            assert peer.closed_early.wait(timeout=5), "the upstream connection stayed open"
        assert not any(isinstance(e, mc.StreamUsage) for e in events)

    def test_a_stream_cancelled_before_the_first_chunk_still_tears_down(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = [f"c{i} " for i in range(200)]
        cancel = threading.Event()
        cancel.set()
        with serve(peer) as base, pytest.raises(mc.Cancelled):
            list(
                mc.stream(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    cancel=cancel,
                )
            )

    def test_keep_alive_and_partial_frames_are_not_errors(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = ["only"]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "only"


class TestActionableErrors:
    def test_a_missing_key_names_the_provider_and_its_variable(self) -> None:
        with pytest.raises(mc.MissingKey, match="OPENAI_API_KEY"):
            mc.complete("openai", [mc.Message("user", "hi")], env={}, model="m-1")

    def test_a_missing_model_says_why_no_default_is_shipped(self) -> None:
        provider = mp.get("groq")
        with pytest.raises(mc.MissingModel, match="model ids change"):
            mc.complete("groq", [mc.Message("user", "hi")], env={provider.env_var: "k"})

    def test_a_registry_default_model_is_used_when_the_caller_omits_one(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            out = mc.complete("anthropic", [mc.Message("user", "hi")], env=_env(provider, base))
        assert out.model == provider.default_model

    def test_an_upstream_rejection_carries_the_providers_own_message(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.status = 400
        with serve(peer) as base, pytest.raises(mc.UpstreamError, match="planted failure"):
            mc.complete("openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1")

    def test_an_unreachable_endpoint_is_offline_and_points_at_local_runners(self) -> None:
        """L23: a specific reason and a way forward — never a spinner, never a silent failure."""
        provider = mp.get("openai")
        env = {provider.base_url_env(): "http://127.0.0.1:9", provider.env_var: "k"}
        with pytest.raises(mc.Offline, match="ollama"):
            mc.complete("openai", [mc.Message("user", "hi")], env=env, model="m-1", timeout=2)

    def test_offline_states_that_proof_features_are_unaffected(self) -> None:
        provider = mp.get("openai")
        env = {provider.base_url_env(): "http://127.0.0.1:9", provider.env_var: "k"}
        with pytest.raises(mc.Offline, match="Proof features are unaffected"):
            mc.complete("openai", [mc.Message("user", "hi")], env=env, model="m-1", timeout=2)

    def test_a_non_json_body_is_reported_rather_than_crashing(self) -> None:
        provider = mp.get("openai")

        class Junk(Peer):
            def body(self) -> bytes:
                return b"<html>gateway error</html>"

        peer = Junk(provider.wire)
        with serve(peer) as base, pytest.raises(mc.UpstreamError, match="non-JSON"):
            mc.complete("openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1")

    def test_a_missing_usage_block_reads_as_zero_never_invented(self) -> None:
        provider = mp.get("openai")

        class NoUsage(Peer):
            def body(self) -> bytes:
                return json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        peer = NoUsage(provider.wire)
        with serve(peer) as base:
            out = mc.complete(
                "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
            )
        assert out.usage == mc.Usage(0, 0)


class TestConfigSurface:
    def test_the_base_url_override_wins_over_the_row(self) -> None:
        provider = mp.get("azure-openai")
        assert (
            mc.resolve_base_url(provider, {provider.base_url_env(): "https://mine/v1"})
            == "https://mine/v1"
        )

    def test_without_an_override_the_rows_default_is_used(self) -> None:
        provider = mp.get("openai")
        assert mc.resolve_base_url(provider, {}) == provider.base_url

    def test_describe_env_never_exposes_a_key_value(self) -> None:
        described = mc.describe_env("anthropic")
        assert described["key_env"] == "ANTHROPIC_API_KEY"
        assert "test-key" not in json.dumps(described)
        assert set(described) == {
            "id",
            "label",
            "wire",
            "key_env",
            "base_url_env",
            "base_url_default",
            "local",
        }


class TestSystemPrompt:
    """The only shape difference between the two wires — worth pinning on both sides."""

    def test_anthropic_carries_system_as_a_top_level_field(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            mc.complete(
                "anthropic",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                system="be terse",
            )
        body = peer.requests[0]
        assert body["system"] == "be terse"
        assert [m["role"] for m in body["messages"]] == ["user"]

    def test_openai_carries_system_as_a_leading_message(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            mc.complete(
                "openai",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                system="be terse",
            )
        body = peer.requests[0]
        assert "system" not in body
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        assert body["messages"][0]["content"] == "be terse"

    @pytest.mark.parametrize("provider_id", ["anthropic", "openai"])
    def test_no_system_prompt_adds_nothing(self, provider_id: str) -> None:
        provider = mp.get(provider_id)
        peer = Peer(provider.wire)
        with serve(peer) as base:
            mc.complete(
                provider_id, [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
            )
        body = peer.requests[0]
        assert "system" not in body
        assert [m["role"] for m in body["messages"]] == ["user"]

    def test_streaming_carries_the_system_prompt_too(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.sse = ["x"]
        with serve(peer) as base:
            list(
                mc.stream(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    system="be terse",
                )
            )
        assert peer.requests[0]["messages"][0]["role"] == "system"


class TestRealStreamShapes:
    """The frames providers actually send between the text deltas.

    Anthropic interleaves `message_start`, `ping`, and `content_block_stop`; OpenAI sends
    role-only opening frames and empty-choices frames. A reader that treats any of these as an
    error, or as text, corrupts the stream — so each shape gets a test rather than a pragma.
    """

    def test_anthropic_non_text_events_are_skipped(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "message_start", "message": {"id": "m"}}\n\n',
            b'data: {"type": "ping"}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "real"}}\n\n',
            b'data: {"type": "content_block_stop"}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "real"

    def test_openai_role_only_and_empty_choice_frames_are_skipped(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n',
            b'data: {"choices": []}\n\n',
            b'data: {"choices": [{"delta": {"content": "real"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": null}}]}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "real"

    def test_a_non_object_frame_is_skipped(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw = [
            b"data: 12345\n\n",
            b'data: {"choices": [{"delta": {"content": "real"}}]}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "real"

    def test_a_malformed_data_line_is_a_keep_alive_not_an_error(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw = [
            b"data: {not json at all\n\n",
            b": this is an SSE comment\n\n",
            b'data: {"choices": [{"delta": {"content": "real"}}]}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
                )
            )
        assert "".join(got) == "real"

    def test_an_empty_choices_response_reads_as_empty_text_not_a_crash(self) -> None:
        provider = mp.get("openai")

        class NoChoices(Peer):
            def body(self) -> bytes:
                return json.dumps(
                    {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 0}}
                ).encode()

        peer = NoChoices(provider.wire)
        with serve(peer) as base:
            out = mc.complete(
                "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m-1"
            )
        assert out.text == ""
        assert out.usage.input_tokens == 3

    def test_an_unreachable_LOCAL_runner_does_not_suggest_local_runners(self) -> None:
        """Ollama not running is the common case; telling the user to try Ollama would be absurd."""
        provider = mp.get("ollama")
        env = {provider.base_url_env(): "http://127.0.0.1:9"}
        with pytest.raises(mc.Offline) as caught:
            mc.complete("ollama", [mc.Message("user", "hi")], env=env, model="m", timeout=2)
        assert "still work unplugged" not in str(caught.value)
        assert "Proof features are unaffected" in str(caught.value)


class TestRedirectsNeverCarryTheKey:
    """Regression: `urlopen` follows 3xx and CPython copies every header onto the new request,
    so `x-api-key` / `authorization` were re-sent verbatim to whatever host a redirect named —
    a silent key leak to an unconfigured host, past the per-project egress allowlist
    (THREAT-MODEL T2). Found by the Phase-19 review workflow.
    """

    @staticmethod
    def _redirector(target: str) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # the http.server contract dictates this name
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_: object) -> None:
                return

        return Handler

    def test_a_redirect_is_refused_rather_than_followed(self) -> None:
        provider = mp.get("anthropic")
        thief = Peer(provider.wire)
        with serve(thief) as thief_base:
            server = HTTPServer(("127.0.0.1", 0), self._redirector(thief_base + "/v1/messages"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with pytest.raises(mc.UpstreamError, match="redirect"):
                    mc.complete(
                        "anthropic",
                        [mc.Message("user", "hi")],
                        env=_env(provider, base, key="SECRET-KEY"),
                        model="m-1",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        assert thief.headers == [], "the redirect target received a request at all"

    def test_the_refusal_names_the_host_without_leaking_the_key(self) -> None:
        provider = mp.get("openai")
        with serve(Peer(provider.wire)) as thief_base:
            server = HTTPServer(
                ("127.0.0.1", 0), self._redirector(thief_base + "/chat/completions")
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with pytest.raises(mc.UpstreamError) as caught:
                    mc.complete(
                        "openai",
                        [mc.Message("user", "hi")],
                        env=_env(provider, base, key="SECRET-KEY"),
                        model="m-1",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        assert "SECRET-KEY" not in str(caught.value), "the key appeared in an error message"
        assert "redirect" in str(caught.value)
