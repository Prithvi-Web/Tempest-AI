"""A REAL local Messages-API peer for synthesis tests (Law L4 — nothing is monkeypatched).

The engine's synthesis client is pointed here via TEMPEST_SYNTHESIS_BASE_URL, so tests
exercise the genuine SDK → HTTP → response-parsing path with zero external egress. The
server answers `POST /v1/messages` with a canned assistant message (the adapter code a
test stages), or an error status to exercise the client's failure mapping.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeAnthropic:
    def __init__(self) -> None:
        self.reply_text: str = ""
        # Content-routed replies: the first key found in the request body picks the reply —
        # lets one server hand each synthesis target its own adapter.
        self.replies: dict[str, str] = {}
        self.status: int = 200
        self.requests: list[dict[str, object]] = []

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
                        "content": [{"type": "text", "text": reply_text}],
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
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
        server.server_close()
