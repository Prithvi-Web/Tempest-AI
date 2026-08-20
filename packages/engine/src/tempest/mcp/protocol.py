"""JSON-RPC 2.0 over stdio — the wire MCP speaks, and nothing else (F16, Phase 23).

Stdlib only, and deliberately small: this is a transport, not a framework. It knows how to read a
request, dispatch it, and write exactly one response — and it knows that **anything printed to
stdout that is not a response corrupts the stream**, which is the same lesson the differential
worker learned the hard way (`_isolate_protocol_fd`). A library that printed a warning would
break every client, so the loop owns stdout and nothing else may have it.

**Errors are values.** A tool that raises becomes a JSON-RPC error object with a code and a
message; the loop does not die, because a client that loses the connection cannot tell a crash
from a refusal, and those are very different facts about a proof.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, TextIO

#: JSON-RPC's reserved codes, plus the one application code this server uses.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
#: A tool ran and refused. Not an error in the protocol sense — the call was well-formed and the
#: answer is "no" — but a caller needs to tell it apart from a malformed request.
TOOL_REFUSED = -32000


@dataclass(frozen=True)
class Request:
    id: object
    method: str
    params: dict[str, Any]

    @property
    def is_notification(self) -> bool:
        """A request with no id expects no response. Answering one corrupts the stream."""
        return self.id is None


class RpcError(Exception):
    """A failure that becomes a JSON-RPC error object rather than a traceback."""

    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def read_requests(stream: TextIO) -> Iterator[Request | RpcError]:
    """One line, one request. Yields an `RpcError` for anything unparseable, never raises.

    Line-delimited JSON rather than the LSP-style `Content-Length` framing: MCP's stdio transport
    is newline-delimited, and a second framing would be a second thing to get wrong.
    """
    for line in stream:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError as exc:
            yield RpcError(PARSE_ERROR, f"not JSON: {exc}")
            continue
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            yield RpcError(INVALID_REQUEST, "every message must be a JSON-RPC 2.0 object")
            continue
        method = payload.get("method")
        if not isinstance(method, str):
            yield RpcError(INVALID_REQUEST, "a request must name a method")
            continue
        params = payload.get("params")
        yield Request(
            id=payload.get("id"),
            method=method,
            params=params if isinstance(params, dict) else {},
        )


def write(stream: TextIO, message: dict[str, Any]) -> None:
    """One message, one line, flushed. The flush is not optional: a client blocked on a response
    that is sitting in a buffer looks exactly like a server that hung."""
    stream.write(json.dumps(message, sort_keys=True) + "\n")
    stream.flush()


def serve(
    handler: Callable[[Request], dict[str, Any]],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """Read, dispatch, respond, until the input ends.

    The handler returns a RESULT object or raises `RpcError`. It never writes to the stream, and
    it never sees an id — keeping the protocol out of the tools is what lets the tools be tested
    without a socket.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    for item in read_requests(source):
        if isinstance(item, RpcError):
            write(sink, {"jsonrpc": "2.0", "id": None, "error": _error(item)})
            continue
        if item.is_notification:
            # Notifications are fire-and-forget. `notifications/initialized` is the one every
            # client sends, and a response to it is a protocol violation.
            continue
        try:
            result = handler(item)
        except RpcError as exc:
            write(sink, {"jsonrpc": "2.0", "id": item.id, "error": _error(exc)})
            continue
        except Exception as exc:
            # The loop must outlive any single tool: a client that loses the connection
            # cannot tell a crash from a refusal, and those are very different facts.
            write(
                sink,
                {
                    "jsonrpc": "2.0",
                    "id": item.id,
                    "error": _error(RpcError(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")),
                },
            )
            continue
        write(sink, {"jsonrpc": "2.0", "id": item.id, "result": result})


def _error(exc: RpcError) -> dict[str, Any]:
    body: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.data is not None:
        body["data"] = exc.data
    return body
