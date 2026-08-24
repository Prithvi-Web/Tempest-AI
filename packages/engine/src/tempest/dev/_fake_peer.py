"""Loopback model peers for both wires — the ONE implementation, shared by tests and gates.

It lives under `tempest/dev/` because the Phase 21 benchmark gates are shipped dev tooling and a
shipped module may not import from the test tree. `tests/helpers_fake_anthropic.py` re-exports
from here so there is one peer rather than two that drift.

These fake the MODEL and nothing else (L4). Every repository, worktree, proof and verdict driven
against them is real.
"""

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeAnthropic:
    def __init__(self) -> None:
        self.reply_text: str = ""
        # Content-routed replies: the first key found in the request body picks the reply —
        # lets one server hand each synthesis target its own adapter.
        self.replies: dict[str, str] = {}
        self.status: int = 200
        self.requests: list[dict[str, object]] = []
        # Phase 21: structured tool calls. When non-empty the reply carries `tool_use` blocks
        # and `stop_reason: "tool_use"`, which is what a real Messages response looks like when
        # the model wants a tool. Additive — every existing caller leaves it empty and gets the
        # text-only shape unchanged.
        self.tool_uses: list[dict[str, object]] = []
        # P2 (`resume_test --sleep-mid-stream`): a peer that accepts the connection and then goes
        # quiet. That is a different failure from a refusal — nothing is wrong with the request,
        # the answer simply never comes — and it is the one the client's wall-clock bound exists
        # for. `stall_on_request` is 1-based over `requests`; 0 means never stall.
        self.stall_seconds: float = 0.0
        self.stall_on_request: int = 0
        # C5 run control: park MID-BODY — headers and half the reply delivered, then silence
        # until `resume`. `stall_*` above stalls BEFORE the response line, which the socket
        # timeout bounds; this stalls the phase only a bounded READ can interrupt (trap 58).
        self.hold_mid_reply = threading.Event()
        self.resume = threading.Event()

    def reply_for(self, body_text: str) -> str:
        for needle, reply in self.replies.items():
            if needle in body_text:
                return reply
        return self.reply_text


@contextmanager
def fake_anthropic_server(fake: FakeAnthropic) -> Iterator[str]:
    """Serve the Messages API shape on a loopback port; yields the base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            fake.requests.append(json.loads(body))
            if fake.stall_seconds and len(fake.requests) == fake.stall_on_request:
                time.sleep(fake.stall_seconds)
            reply_text = fake.reply_for(body.decode("utf-8", errors="replace"))
            if fake.status != 200:
                payload = json.dumps(
                    {"type": "error", "error": {"type": "api_error", "message": "planted failure"}}
                ).encode()
                self.send_response(fake.status)
            else:
                payload = json.dumps(
                    {
                        "id": "msg_fake",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-sonnet-5",
                        "content": (
                            [{"type": "text", "text": reply_text}]
                            + [
                                {
                                    "type": "tool_use",
                                    "id": str(u.get("id", f"toolu_{i}")),
                                    "name": u["name"],
                                    "input": u.get("input", {}),
                                }
                                for i, u in enumerate(fake.tool_uses)
                            ]
                        ),
                        "stop_reason": "tool_use" if fake.tool_uses else "end_turn",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    }
                ).encode()
                self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            if fake.hold_mid_reply.is_set():
                # Half the promised bytes, then not one more until `resume` — the client is
                # now blocked inside its body read with the connection alive.
                half = len(payload) // 2
                self.wfile.write(payload[:half])
                self.wfile.flush()
                fake.resume.wait(timeout=15)
                try:
                    self.wfile.write(payload[half:])
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # the client hung up mid-body, which is the point
                return
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass  # keep test output clean

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class FakeOpenAI:
    """The OpenAI Chat Completions shape — the second of Tempest's two wires.

    Exists so tool calling is tested on BOTH wires with real HTTP against a real peer (L4). The
    two shapes disagree in exactly the ways that matter here: OpenAI nests the call under
    `function` and sends its arguments as a JSON **string**, and it says `finish_reason` rather
    than `stop_reason`. A parser tested on one wire only is a parser tested on half the fleet —
    fifteen of the sixteen providers speak this one.
    """

    def __init__(self) -> None:
        self.reply_text: str = ""
        self.status: int = 200
        self.requests: list[dict[str, object]] = []
        self.tool_calls: list[dict[str, object]] = []
        #: Set to a raw string to serve malformed arguments deliberately.
        self.raw_arguments: str | None = None


@contextmanager
def fake_openai_server(fake: FakeOpenAI) -> Iterator[str]:
    """Serve the Chat Completions shape on a loopback port; yields the base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            fake.requests.append(json.loads(body))
            if fake.status != 200:
                payload = json.dumps({"error": {"message": "planted failure"}}).encode()
                self.send_response(fake.status)
            else:
                calls = [
                    {
                        "id": str(c.get("id", f"call_{i}")),
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": (
                                fake.raw_arguments
                                if fake.raw_arguments is not None
                                else json.dumps(c.get("arguments", {}))
                            ),
                        },
                    }
                    for i, c in enumerate(fake.tool_calls)
                ]
                message: dict[str, object] = {"role": "assistant", "content": fake.reply_text}
                if calls:
                    message["tool_calls"] = calls
                payload = json.dumps(
                    {
                        "id": "chatcmpl_fake",
                        "object": "chat.completion",
                        "model": "gpt-fake",
                        "choices": [
                            {
                                "index": 0,
                                "message": message,
                                "finish_reason": "tool_calls" if calls else "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode()
                self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass  # keep test output clean

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@dataclass
class FakeHuggingFace:
    """A stand-in for the model host, with the two behaviours that matter (ADR-0080).

    **Range**, because resume is the whole reason a 2.5 GB download is tolerable, and a peer
    that ignores `Range:` cannot tell a correct resume from a client that silently restarts.

    **A redirect**, because the real host answers `302` to a CDN and that single hop is the
    reason this downloader needed a redirect policy of its own. A fake that served bytes
    directly would leave the interesting half untested.
    """

    #: The file the peer serves.
    payload: bytes = b""
    #: Serve from this path; anything else is a 404.
    path: str = "/repo/resolve/main/model.gguf"
    #: When set, `path` answers 302 to this location instead of bytes.
    redirect_to: str | None = None
    #: Honour `Range:` (the real host does). Off makes the peer answer 200 from zero, which is
    #: how a resume gets spliced into the middle of a file if the client trusts its request
    #: rather than the response STATUS.
    honour_range: bool = True
    #: Requests seen, as (path, range-header-or-None).
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    #: Serve at most this many bytes per response, then close — a truncated body.
    truncate_at: int | None = None
    #: Write the body in pieces of this size, pausing `chunk_delay_s` between them. Loopback
    #: is fast enough that a small payload arrives before a test can react to it, so a test
    #: about CANCELLING mid-download needs the producer to be the slow one — otherwise the
    #: cancel is a race against the network stack and the test is a coin flip (trap 61).
    chunk_size: int | None = None
    chunk_delay_s: float = 0.0
    #: Send this many bytes BEYOND the payload — a server whose body is longer than the row
    #: the user agreed to. The real hazard is not malice but a broken CDN edge or a proxy
    #: splicing an error page onto the end; either way the client, not the server, has to be
    #: the one that decides how many bytes reach the disk (L15.4).
    overrun_bytes: int = 0
    #: Slice the body from HERE while still answering 206 and reporting the range the client
    #: ASKED for. A server that honours `Range:` in its status line but not in its body is the
    #: one case the status alone cannot detect: the bytes are wrong and every header agrees
    #: with the request. Real enough to matter — a caching proxy that serves a whole object
    #: for a ranged request does exactly this.
    serve_from: int | None = None
    #: Answer 206 with NO `Content-Range` header. Mandatory for that status, so a peer
    #: omitting it has told the client nothing about which bytes it is sending.
    omit_content_range: bool = False


@contextmanager
def fake_huggingface_server(fake: FakeHuggingFace) -> Iterator[str]:
    """Serve `fake` on a loopback port; yields the base URL."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # the http.server contract dictates this name
            rng = self.headers.get("Range")
            fake.requests.append((self.path, rng))

            if fake.redirect_to is not None and self.path == fake.path:
                self.send_response(302)
                self.send_header("Location", fake.redirect_to)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path not in (fake.path, "/cdn/model.gguf"):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            start = 0
            if rng and fake.honour_range and rng.startswith("bytes="):
                start = int(rng.removeprefix("bytes=").split("-")[0])
            if start >= len(fake.payload):
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            # Where the bytes actually come from — normally the requested offset, but a peer
            # can be told to serve from elsewhere while every header still agrees with the
            # request. That is the one dishonesty a client cannot see in the status line.
            sliced_from = fake.serve_from if fake.serve_from is not None else start
            body = fake.payload[sliced_from:]
            if fake.truncate_at is not None:
                body = body[: fake.truncate_at]
            if fake.overrun_bytes:
                # Deterministic filler, so a test can say exactly how many bytes a client
                # that trusts the server would commit to disk.
                body = body + b"\xff" * fake.overrun_bytes
            self.send_response(206 if start else 200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            if start and not fake.omit_content_range:
                # The header describes the bytes actually being sent, which is what makes a
                # `serve_from` peer DETECTABLE: status 206 says "partial content", the range
                # header says which part, and a client that reads only the status splices the
                # wrong one. (A peer that lies in the header too is caught by the sha256 and
                # by nothing earlier — that is the backstop, not the guard.)
                end = sliced_from + len(body) - 1
                self.send_header("Content-Range", f"bytes {sliced_from}-{end}/{len(fake.payload)}")
            self.end_headers()
            if fake.chunk_size:
                for offset in range(0, len(body), fake.chunk_size):
                    try:
                        self.wfile.write(body[offset : offset + fake.chunk_size])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        return  # the client hung up mid-body: exactly what a cancel looks like
                    time.sleep(fake.chunk_delay_s)
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
        thread.join(timeout=5)
