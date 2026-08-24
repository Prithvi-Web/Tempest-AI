"""Phase 19.5 pins: the multi-provider model layer (P1, L18/L21/L23).

Every network test runs against a **real local HTTP server** speaking the actual wire protocol —
the same discipline as `helpers_fake_anthropic` (L4: nothing is monkeypatched, the genuine
request-building and response-parsing path executes). Zero external egress, so these gates are
free and deterministic in CI, which is the standing answer to QV2/QV10.
"""

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from tempest import netcancel
from tempest.inference import client as mc
from tempest.inference import providers as mp

#: How long the close-delimited peer waits after its headers before writing the body prefix.
#: The client reaches its blocked read in microseconds; this gap only has to be longer than
#: that, and it is a hundred times shorter than the 30 s socket timeout the test runs against.
_PREFIX_DELAY_S = 0.3


class Peer:
    """A recording stand-in for a provider endpoint, in either wire shape."""

    def __init__(self, wire: str) -> None:
        self.wire = wire
        self.status = 200
        self.text = "hello from the peer"
        self.sse: list[str] | None = None
        #: Verbatim frames, for exercising the event shapes real providers actually send.
        self.raw: list[bytes] | None = None
        #: A verbatim NON-stream document, for the same reason `raw` exists on the stream
        #: side: the default body is one tidy text block, and several response shapes worth
        #: pinning (a reasoning model's split content, an empty answer) cannot be spelled
        #: with it.
        self.raw_body: dict[str, Any] | None = None
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
        #: Arm to make the peer go SILENT: SSE headers and then not one byte until `resume`.
        #: This is the trap-58 condition — a blocked read that no deadline around the loop can
        #: interrupt, because the loop body never returns to check anything.
        self.silent_stream = threading.Event()
        #: Arm to stall a NON-stream response mid-body: full Content-Length promised, half the
        #: bytes delivered, then silence until `resume`. `complete()`'s read blocks exactly here.
        self.stall_body = threading.Event()
        #: Arm to BREAK a non-stream response mid-body: half the promised bytes, then the
        #: connection closes. A real upstream fault, for pinning that the cancel guard passes
        #: genuine errors through untranslated when nobody cancelled.
        self.truncate_body = threading.Event()
        #: Arm a CLOSE-DELIMITED stall: no Content-Length at all, a partial body, then
        #: silence. This is the one shape that makes the cancelled read end as a CLEAN EOF
        #: rather than an error — with a promised length, http.client raises on a short read,
        #: which takes the exception path instead. It is the exact case `_cancel_guard`'s
        #: docstring names ("a shut-down stream must never impersonate a completed one").
        self.close_delimited_stall = threading.Event()
        #: Arm SILENCE BEFORE THE HEADERS: the connection is accepted, the request is read,
        #: and then nothing is sent at all. This is the arm no other peer here produces —
        #: every one of them sends headers first — and it is exactly the window `_open`
        #: blocks in, with no watcher alive and no cancel flag read.
        self.stall_before_headers = threading.Event()
        #: Set by the peer once the partial body is on the wire, so the test can cancel at a
        #: moment the client is guaranteed to be blocked — a barrier, not a hopeful sleep
        #: (trap 61).
        self.wrote_prefix = threading.Event()

    def body(self) -> bytes:
        if self.raw_body is not None:
            return json.dumps(self.raw_body).encode()
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
            if peer.stall_before_headers.is_set():
                # Not a byte — not even a status line — until the test releases the hold.
                peer.resume.wait(timeout=10)
                return
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
                if peer.silent_stream.is_set():
                    # Not one byte until the test releases the hold. The client's only honest
                    # exits are its socket timeout or a bounded read observing its cancel flag.
                    peer.resume.wait(timeout=10)
                    try:
                        # Several writes, not one: the first send after the peer's FIN merely
                        # collects the RST — EPIPE surfaces on a SUBSEQUENT write.
                        for _ in range(20):
                            self.wfile.write(b"data: {}\n\n")
                            self.wfile.flush()
                            time.sleep(0.02)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        peer.closed_early.set()  # the client really hung up while we were silent
                    return
                try:
                    for index, frame in enumerate(peer.sse_frames()):
                        self.wfile.write(frame)
                        self.wfile.flush()
                        if index == 0 and peer.hold_after_first.is_set():
                            # Hold the stream open until the test says the client has gone. The
                            # timeout is a safety net, not a wait anybody expects to expire.
                            peer.resume.wait(timeout=10)
                            # Then keep writing UNTIL THE HANGUP IS OBSERVED, rather than a
                            # fixed number of frames and a hope. A run of small frames fits
                            # entirely inside the loopback send buffer, so whether any write
                            # raises depends on which side is scheduled first — under load the
                            # peer finishes first, nothing fails, and a test about
                            # CANCELLATION goes red for a reason about buffer sizes (trap 61).
                            # Writing to a deadline turns "the peer outlasted the client" from
                            # a coin flip into a bounded fact.
                            deadline = time.monotonic() + 3.0
                            while time.monotonic() < deadline:
                                self.wfile.write(b"data: {}\n\n")
                                self.wfile.flush()
                                time.sleep(0.02)
                            return
                except (BrokenPipeError, ConnectionResetError, OSError):
                    peer.closed_early.set()  # the client really hung up
                return
            body = peer.body()
            if peer.close_delimited_stall.is_set():
                # No Content-Length and no chunked encoding: the body is delimited by the
                # connection closing, so `response.read()` reads until EOF. A prefix, then
                # silence — the read blocks with nothing to end it but a shutdown.
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                # Headers land FIRST and the prefix only afterwards, and that ordering is the
                # barrier. `_open()` returns as soon as the headers are read, so the client is
                # inside `_cancel_guard` and blocked in its body read within microseconds —
                # while the test cannot set the cancel flag until `wrote_prefix`, which is a
                # whole poll interval later. Without the gap the flag was already set when the
                # guard was entered and its EARLY arm raised, so the read never blocked and the
                # post-read re-check under test never ran (measured: coverage showed 593-604
                # untouched while the test passed).
                time.sleep(_PREFIX_DELAY_S)
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                peer.wrote_prefix.set()
                peer.resume.wait(timeout=10)
                try:
                    for chunk in [body[len(body) // 2 :]] + [b" "] * 20:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        time.sleep(0.02)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    peer.closed_early.set()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if peer.truncate_body.is_set():
                # Half the promised bytes, then the connection dies: an upstream FAULT, not a
                # cancellation, and it must surface as one.
                self.wfile.write(body[: len(body) // 2])
                self.wfile.flush()
                self.connection.close()
                return
            if peer.stall_body.is_set():
                # Half the promised bytes, then silence: `complete()` is now blocked inside its
                # body read with the connection alive and nothing arriving.
                half = len(body) // 2
                self.wfile.write(body[:half])
                self.wfile.flush()
                peer.resume.wait(timeout=10)
                try:
                    # Several writes, not one — see the silent_stream arm.
                    for chunk in [body[half:]] + [b" "] * 20:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        time.sleep(0.02)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    peer.closed_early.set()  # the client hung up mid-body
                return
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


class TestBoundedReads:
    """C5 run control: cancellation interrupts a SILENT upstream, not just a chatty one.

    Trap 58 — a deadline around a blocking read is not a deadline. The old stream loop checked
    its cancel event only after `readline()` returned, so a provider that stopped sending bytes
    held the turn hostage for the full socket timeout, and `complete()` had no cancel at all.
    These tests hold the upstream SILENT and require cancellation to land within a couple of
    seconds while the socket timeout is thirty — the difference is the bounded read existing.
    """

    def test_cancel_interrupts_a_silent_stream_before_the_socket_timeout(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.silent_stream.set()
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        with serve(peer) as base:
            timer.start()
            started = time.monotonic()
            with pytest.raises(mc.Cancelled):
                for _ in mc.stream(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                ):
                    pass  # pragma: no cover — the peer never sends a frame
            elapsed = time.monotonic() - started
            # Only now release the peer; its next write observes the closed socket.
            peer.resume.set()
            assert peer.closed_early.wait(timeout=5), "the silent connection stayed open"
        assert elapsed < 5.0, f"cancel took {elapsed:.1f}s against a silent upstream"

    def test_stream_events_honors_the_same_bound(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.silent_stream.set()
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        with serve(peer) as base:
            timer.start()
            started = time.monotonic()
            with pytest.raises(mc.Cancelled):
                for _ in mc.stream_events(
                    "anthropic",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                ):
                    pass  # pragma: no cover — the peer never sends a frame
            elapsed = time.monotonic() - started
            peer.resume.set()
            assert peer.closed_early.wait(timeout=5), "the silent connection stayed open"
        assert elapsed < 5.0, f"cancel took {elapsed:.1f}s against a silent upstream"

    def test_complete_aborts_a_stalled_body_on_cancel(self) -> None:
        """`complete()` is the agent loop's one model call; C5 threads cancellation into it."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.stall_body.set()
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        with serve(peer) as base:
            timer.start()
            started = time.monotonic()
            with pytest.raises(mc.Cancelled):
                mc.complete(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                )
            elapsed = time.monotonic() - started
            peer.resume.set()
            assert peer.closed_early.wait(timeout=5), "the stalled connection stayed open"
        assert elapsed < 5.0, f"cancel took {elapsed:.1f}s against a stalled body"

    def test_complete_with_an_unset_cancel_answers_normally(self) -> None:
        """The cancel parameter must cost nothing when nobody cancels."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        with serve(peer) as base:
            answer = mc.complete(
                "openai",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                cancel=threading.Event(),
            )
        assert answer.text == "hello from the peer"
        assert answer.usage.input_tokens == 11

    def test_an_upstream_fault_is_not_dressed_up_as_a_cancellation(self) -> None:
        """The guard translates a read failure into `Cancelled` ONLY when the caller cancelled;
        a genuinely broken upstream keeps its own face."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.truncate_body.set()
        with serve(peer) as base, pytest.raises(Exception) as caught:
            mc.complete(
                "openai",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                cancel=threading.Event(),  # armed, never set
            )
        assert not isinstance(caught.value, mc.Cancelled), (
            "an upstream fault was mislabelled as a cancellation"
        )

    def test_complete_refuses_immediately_when_already_cancelled(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        done = threading.Event()
        done.set()
        with serve(peer) as base, pytest.raises(mc.Cancelled):
            mc.complete(
                "openai",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                cancel=done,
            )


class TestCancelDuringTheConnect:
    """Stop must be observed while the request is still CONNECTING, not only once the
    response headers have arrived.

    `_cancel_guard` bounds the read; `_open` — connect, TLS, request body, `getresponse()` —
    ran outside it with no watcher alive and no flag read. Every peer arm in this suite sends
    headers first, so the tested arm was the one that already worked: a provider that accepts
    the TCP connection and then says nothing held the abort for the full socket timeout
    (300 s on the chat path). The job stayed `active` that whole time, so the user's next
    message on the conversation was refused with a 409, and the turn finally settled as
    `error ... timed out` instead of the `aborted` terminal the client asked for — and as the
    wrong exception class too, since `_open` translates a timeout to `Offline`, so
    `except Cancelled` never ran.
    """

    def _assert_prompt_cancel(self, call: Callable[[threading.Event], None]) -> None:
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        started = time.monotonic()
        timer.start()
        try:
            with pytest.raises(mc.Cancelled) as caught:
                call(cancel)
        finally:
            timer.cancel()
        elapsed = time.monotonic() - started
        # The socket timeout is 30 s. Anything near it means the cancel was not observed and
        # the call simply timed out — which is the defect, and it raises `Offline`, not
        # `Cancelled`, so the class assertion above already separates them.
        assert elapsed < 10.0, f"cancel took {elapsed:.1f}s against a 30s socket timeout"
        assert not isinstance(caught.value, mc.Offline)
        assert "cancel" in str(caught.value).lower()

    def test_complete_observes_a_cancel_while_the_provider_is_still_silent(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.stall_before_headers.set()
        with serve(peer) as base:
            self._assert_prompt_cancel(
                lambda cancel: mc.complete(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                )
            )
            peer.resume.set()

    def test_stream_observes_a_cancel_while_the_provider_is_still_silent(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.stall_before_headers.set()

        def drain(cancel: threading.Event) -> None:
            for _ in mc.stream(
                "openai",
                [mc.Message("user", "hi")],
                env=_env(provider, base),
                model="m-1",
                timeout=30.0,
                cancel=cancel,
            ):
                pass  # pragma: no cover — the peer never sends a frame

        with serve(peer) as base:
            self._assert_prompt_cancel(drain)
            peer.resume.set()

    def test_a_cancel_set_before_the_call_never_opens_a_connection_at_all(self) -> None:
        """The cheapest arm, and the one that matters for a queued turn the user stopped
        before it started: no request is sent, so no provider is billed and no key leaves."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        cancel = threading.Event()
        cancel.set()
        with serve(peer) as base:
            with pytest.raises(mc.Cancelled):
                mc.complete(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                )
            assert peer.requests == [], "a cancelled call must not reach the provider at all"


class TestTheCleanEofCannotImpersonateAnAnswer:
    """`_cancel_guard`'s docstring singles this out as the lesson of trap 58: the unblocked
    read "can end as a clean EOF, which is why both call sites re-check the flag after the
    read: a shut-down stream must never impersonate a completed one."

    `complete()`'s re-check had never executed. Every other peer arm in this suite promises a
    Content-Length, and http.client raises on a short read of a promised body — so the cancel
    always arrived as an EXCEPTION and the clean-EOF arm the line exists for was never
    produced. The suite proved the guard's argument, not the guard.
    """

    def test_a_cancelled_close_delimited_read_is_a_cancellation_not_a_truncated_answer(
        self,
    ) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.close_delimited_stall.set()
        cancel = threading.Event()

        def cancel_once_the_read_is_blocked() -> None:
            # A BARRIER, not a sleep (trap 61): the peer announces the prefix is on the wire,
            # and with no Content-Length there is nothing that can end the client's read but a
            # shutdown — so from here the client is blocked, deterministically.
            assert peer.wrote_prefix.wait(timeout=10), "the peer never wrote its prefix"
            cancel.set()

        with serve(peer) as base:
            waker = threading.Thread(target=cancel_once_the_read_is_blocked, daemon=True)
            waker.start()
            started = time.monotonic()
            with pytest.raises(mc.Cancelled) as caught:
                mc.complete(
                    "openai",
                    [mc.Message("user", "hi")],
                    env=_env(provider, base),
                    model="m-1",
                    timeout=30.0,
                    cancel=cancel,
                )
            elapsed = time.monotonic() - started
            waker.join(timeout=5)
            peer.resume.set()

        # The distinction the re-check exists to make. Without it the half-body flows on into
        # `json.loads` and the caller is told the PROVIDER sent something malformed — blaming
        # the upstream for the caller's own cancellation, and, had the prefix happened to be
        # valid JSON, returning a truncated answer as a real one.
        assert "cancelled by the caller" in str(caught.value)
        assert not isinstance(caught.value, mc.UpstreamError)
        assert elapsed < 10.0, f"cancel took {elapsed:.1f}s against a 30s socket timeout"


class TestTheCancellableOpen:
    """`_open_cancellable`'s own arms, driven directly.

    Its job is to make the CONNECT observable to a cancel flag, and the states worth pinning
    are the ones a live provider cannot be made to produce on demand: an error raised on the
    worker and re-raised on the caller's thread, and a cancel that lands in the same instant
    the response arrives. Both are exercised with a stub `_open` rather than a socket, because
    a test that needs to win a race against a real connect is a coin flip with a good
    reputation (trap 61).
    """

    def _stub_open(self, monkeypatch: pytest.MonkeyPatch, behaviour: Callable[[], Any]) -> None:
        monkeypatch.setattr(mc, "_open", lambda **_kwargs: behaviour())

    def test_no_cancel_flag_means_the_plain_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With nothing to observe, the worker is pure overhead — the call goes straight
        through, which is what every non-cancellable caller relies on."""
        sentinel = object()
        self._stub_open(monkeypatch, lambda: sentinel)
        assert mc._open_cancellable(None) is sentinel

    def test_an_open_failure_is_re_raised_on_the_callers_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fault must keep its own face. Swallowing it on the worker and answering None
        would turn "the provider refused the key" into a mystery, and moving the connect off
        the caller's thread must not change which exception the caller sees."""

        def boom() -> Any:
            raise mc.Offline("could not reach the provider")

        self._stub_open(monkeypatch, boom)
        with pytest.raises(mc.Offline, match="could not reach the provider"):
            mc._open_cancellable(threading.Event())

    def test_a_cancel_landing_as_the_response_arrives_closes_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The narrow window the loop cannot catch: the connect completed, and the flag went
        up before the caller could use it. The response must be CLOSED rather than returned —
        an orphan holds the connection, and the provider's generation, open until GC.
        """
        cancel = threading.Event()
        closed: list[str] = []

        class Response:
            def close(self) -> None:
                closed.append("closed")

        def opened() -> Any:
            cancel.set()  # the flag goes up inside the connect, deterministically
            return Response()

        self._stub_open(monkeypatch, opened)
        with pytest.raises(mc.Cancelled, match="as the response arrived"):
            mc._open_cancellable(cancel)
        assert closed == ["closed"], "the abandoned response must not be left open"

    def test_a_response_that_arrives_after_the_caller_gave_up_is_closed_by_the_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of the same leak. The caller stops waiting and raises; the connect
        completes moments later on a thread nobody is reading. Whoever finishes last is
        responsible for the socket, so the worker closes it on its way out.
        """
        cancel = threading.Event()
        release = threading.Event()
        closed = threading.Event()

        class Response:
            def close(self) -> None:
                closed.set()

        def slow() -> Any:
            assert release.wait(timeout=5), "the test never released the connect"
            return Response()

        self._stub_open(monkeypatch, slow)
        cancel_at = threading.Timer(0.05, cancel.set)
        cancel_at.start()
        try:
            with pytest.raises(mc.Cancelled, match="still connecting"):
                mc._open_cancellable(cancel)
        finally:
            cancel_at.cancel()
        # Only NOW does the connect finish — with nobody waiting for it.
        release.set()
        assert closed.wait(timeout=5), (
            "a response that arrived after the caller unwound was left open"
        )


class TestTheCancelWatchWithoutAnFd:
    def test_entering_the_guard_with_the_flag_already_up_closes_and_refuses(self) -> None:
        """`_cancel_guard`'s early arm, asserted directly because it is now hard to reach
        through a real call: `_open_cancellable` re-checks the flag immediately before
        returning, so a cancel that was already up raises there instead. The window between
        those two checks is real but vanishingly narrow, and defence at a function boundary
        should hold whether or not its caller happens to make it redundant today.
        """
        closed: list[str] = []

        class Response:
            def close(self) -> None:
                closed.append("closed")

        cancel = threading.Event()
        cancel.set()
        with (
            pytest.raises(mc.Cancelled, match="connection closed"),
            mc._cancel_guard(cancel, Response(), "test-provider"),
        ):
            raise AssertionError("the guard must refuse before the body runs")
        assert closed == ["closed"], "the response must be closed, not merely abandoned"

    def test_a_response_with_no_usable_fd_leaves_the_guard_harmless(self) -> None:
        """`_cancel_guard` captures the descriptor with `suppress(OSError, ValueError)`, so a
        response that cannot produce one leaves `fd = -1` and the watcher must simply stand
        down. It must not raise, and it must not shut down descriptor -1 — which on a
        different day is somebody else's socket.

        This is the guard's own defensive arm, and the only one the real peers cannot
        produce: a live HTTP response always has a file number.
        """
        shutdowns: list[int] = []
        original = netcancel.shutdown_fd
        netcancel.shutdown_fd = lambda fd: shutdowns.append(fd)  # type: ignore[assignment]

        class NoFileno:
            closed = False

            def fileno(self) -> int:
                raise OSError("this response has no descriptor")

            def close(self) -> None:
                self.closed = True

        cancel = threading.Event()
        response = NoFileno()
        try:
            with (
                pytest.raises(mc.Cancelled),
                mc._cancel_guard(cancel, response, "test-provider"),
            ):
                cancel.set()
                # Long enough for the watcher to wake at least twice and observe the flag.
                time.sleep(netcancel.CANCEL_POLL_S * 4)
                raise mc.Cancelled("cancelled by the caller; test-provider connection closed")
        finally:
            netcancel.shutdown_fd = original  # type: ignore[assignment]

        assert shutdowns == [], (
            f"the watcher shut down descriptor(s) {shutdowns} despite having none of its own"
        )


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

    def test_plain_stream_filters_the_usage_event_to_text(self) -> None:
        """Anthropic states usage unasked; `stream()`'s contract stays text-only — the
        event arrives and the adapter drops it rather than leaking a foreign type."""
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "message_start", "message": {"usage": {"input_tokens": 2}}}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "only text"}}\n\n',
            b'data: {"type": "message_delta", "usage": {"output_tokens": 4}}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert got == ["only text"]

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

    def test_a_half_observed_usage_stays_absent(self) -> None:
        """message_start arrived, the output count never did (early close): padding the
        missing half with zero would be a fabricated measurement (L21) — absence wins."""
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "message_start", "message": {"usage": {"input_tokens": 5}}}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "cut short"}}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert events == [mc.TextDelta("cut short")]

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


class TestReasoningIsItsOwnChannel:
    """A reasoning model's thinking and its answer are two channels, and reading only one of
    them is how a user gets silence (ADR-0081).

    Measured against a real `llama-server` running Qwen3 0.6B on 2026-08-24: with a 120-token
    budget the reply came back `finish_reason: length`, `content: ''`, and 29 SSE frames of
    `reasoning_content`. A client that reads `content` alone shows the user nothing at all —
    no text, no explanation, no error. That is the L15.3/L23 failure this class pins, and it
    lands on the models people are most likely to pick: both Qwen3 rows and the DeepSeek-R1
    distill in the catalogue are reasoning models, and the smallest is the first click.

    The frames below are the shapes those servers really send, transcribed from that session.
    """

    def test_thinking_and_answer_arrive_as_separate_events_in_order(self) -> None:
        provider = mp.get("llamacpp")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"role": "assistant", "content": null}}]}\n\n',
            b'data: {"choices": [{"delta": {"reasoning_content": "Okay"}}]}\n\n',
            b'data: {"choices": [{"delta": {"reasoning_content": ", the user"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "A local model"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": " runs here."}}]}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "llamacpp", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert [(type(e).__name__, e.text) for e in events] == [
            ("ReasoningDelta", "Okay"),
            ("ReasoningDelta", ", the user"),
            ("TextDelta", "A local model"),
            ("TextDelta", " runs here."),
        ]

    def test_a_turn_that_is_all_thinking_is_not_silence(self) -> None:
        """The exact failure, reproduced: every frame is `reasoning_content` and none is
        `content`. Reading `content` alone yields an empty string — which reaches the user as
        a turn that finished and said nothing."""
        provider = mp.get("llamacpp")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"reasoning_content": "Okay, the user"}}]}\n\n',
            b'data: {"choices": [{"delta": {"reasoning_content": " wants a sentence"}}]}\n\n',
            b'data: {"choices": [{"finish_reason": "length", "delta": {}}]}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "llamacpp", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert not [e for e in events if isinstance(e, mc.TextDelta)], "there is no answer text"
        assert (
            "".join(e.text for e in events if isinstance(e, mc.ReasoningDelta))
            == "Okay, the user wants a sentence"
        ), "and the thinking is not lost with it"

    def test_the_other_openai_wire_spelling_is_read_too(self) -> None:
        """OpenRouter and several relays spell the same channel `reasoning`; llama.cpp and
        DeepSeek spell it `reasoning_content`. Both are read, because a channel that depends
        on which relay is in front of the model is not a channel."""
        provider = mp.get("openrouter")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"reasoning": "hmm"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "yes"}}]}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "openrouter", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert [(type(e).__name__, e.text) for e in events] == [
            ("ReasoningDelta", "hmm"),
            ("TextDelta", "yes"),
        ]

    def test_anthropic_thinking_deltas_are_reasoning_and_never_text(self) -> None:
        """The Anthropic wire carries the same split as a `thinking_delta` inside its
        `content_block_delta`. Folding it into the answer would put the model's private
        reasoning into the text a harness compiles."""
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "content_block_delta", '
            b'"delta": {"type": "thinking_delta", "thinking": "let me see"}}\n\n',
            b'data: {"type": "content_block_delta", '
            b'"delta": {"type": "text_delta", "text": "the answer"}}\n\n',
        ]
        with serve(peer) as base:
            events = list(
                mc.stream_events(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert [(type(e).__name__, e.text) for e in events] == [
            ("ReasoningDelta", "let me see"),
            ("TextDelta", "the answer"),
        ]

    def test_plain_stream_stays_text_only_when_the_model_thinks(self) -> None:
        """`stream()` feeds harness synthesis, which compiles what it is given. Its contract
        is the ANSWER, and thinking is not part of it — a `ReasoningDelta` is dropped there
        exactly as `StreamUsage` already is, rather than leaking a foreign type or, worse,
        prose into generated code."""
        provider = mp.get("llamacpp")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": {"reasoning_content": "thinking out loud"}}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "def f(): pass"}}]}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "llamacpp", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert got == ["def f(): pass"]

    def test_a_completion_carries_reasoning_beside_its_text(self) -> None:
        """The non-stream path has the same split, and the same silence without it."""
        provider = mp.get("llamacpp")
        peer = Peer(provider.wire)
        peer.raw_body = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "Okay, the user is asking for a short sentence",
                    },
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 120},
        }
        with serve(peer) as base:
            done = mc.complete(
                "llamacpp", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
            )
        assert done.text == ""
        assert done.reasoning == "Okay, the user is asking for a short sentence"
        assert done.stop_reason == "length"

    def test_an_anthropic_completion_reads_its_thinking_blocks(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw_body = {
            "content": [
                {"type": "thinking", "thinking": "weighing it up"},
                {"type": "text", "text": "the answer"},
            ],
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }
        with serve(peer) as base:
            done = mc.complete(
                "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
            )
        assert done.text == "the answer"
        assert done.reasoning == "weighing it up"


class TestMalformedDeltasAreSurvived:
    """A `delta` that is not an object at all.

    The wire contract says these are objects; a relay, a proxy, or a half-written frame can
    still put a string or a null there. Splitting the reader into two channels turned what
    used to be one inline `isinstance` guard into three, and a guard nothing exercises is a
    guard nobody has checked — so each one gets a frame that reaches it (ADR-0081).
    """

    def test_an_openai_delta_that_is_not_an_object_is_skipped(self) -> None:
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"choices": [{"delta": "not an object"}]}\n\n',
            b'data: {"choices": [{"delta": {"content": "real"}}]}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream("openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m")
            )
        assert got == ["real"]

    def test_an_anthropic_delta_that_is_not_an_object_is_skipped(self) -> None:
        provider = mp.get("anthropic")
        peer = Peer(provider.wire)
        peer.raw = [
            b'data: {"type": "content_block_delta", "delta": null}\n\n',
            b'data: {"type": "content_block_delta", "delta": {"text": "real"}}\n\n',
        ]
        with serve(peer) as base:
            got = list(
                mc.stream(
                    "anthropic", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
                )
            )
        assert got == ["real"]

    def test_a_completion_whose_message_is_not_an_object_answers_empty(self) -> None:
        """Not a crash, and not an invented answer: an unreadable message is no message."""
        provider = mp.get("openai")
        peer = Peer(provider.wire)
        peer.raw_body = {"choices": [{"message": "not an object"}], "usage": {}}
        with serve(peer) as base:
            done = mc.complete(
                "openai", [mc.Message("user", "hi")], env=_env(provider, base), model="m"
            )
        assert done.text == ""
        assert done.reasoning == ""
        assert done.usage == mc.Usage(0, 0)
