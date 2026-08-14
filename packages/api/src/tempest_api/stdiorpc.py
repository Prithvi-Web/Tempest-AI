"""Boundary A transport (CLAUDE.md §9b): JSON-RPC 2.0 over stdio, length-prefix framed.

The desktop host owns this process and speaks frames over stdin/stdout — no TCP socket ever
listens in local mode. Method names are the OpenAPI `operationId`s; the dispatch table is built
from the live FastAPI routes at startup, so this transport cannot drift from the REST contract
(one source of truth, two transports). Requests are handled sequentially — every handler
fast-returns (long proves run in their own worker thread and are observed via `getRun` /
`listRunEvents` polling), and sequential dispatch keeps response ordering deterministic.

Frame format (LSP-style):  ``Content-Length: <n>\\r\\n\\r\\n<n bytes of UTF-8 JSON>``
"""

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import BinaryIO

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute

_MAX_FRAME_BYTES = 64 * 1024 * 1024  # a bundle-sized payload fits; a runaway peer does not
_MAX_HEADER_BYTES = 8192

# JSON-RPC 2.0 error codes (spec-defined negatives; -32000 carries HTTP-layer failures).
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603
_HTTP_ERROR = -32000


class FrameProtocolError(Exception):
    """The byte stream stopped being a valid frame sequence — unrecoverable, close down."""


def write_frame(stream: BinaryIO, payload: bytes) -> None:
    stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    stream.write(payload)
    stream.flush()


def read_frame(stream: BinaryIO) -> bytes | None:
    """One frame's payload, or None on clean EOF at a frame boundary."""
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        ch = stream.read(1)
        if not ch:
            if not header:
                return None
            raise FrameProtocolError("EOF inside frame header")
        header += ch
        if len(header) > _MAX_HEADER_BYTES:
            raise FrameProtocolError("frame header exceeds 8 KiB")
    length: int | None = None
    for line in bytes(header[:-4]).split(b"\r\n"):
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                length = int(value.strip())
            except ValueError as exc:
                raise FrameProtocolError(f"bad Content-Length: {value!r}") from exc
    if length is None:
        raise FrameProtocolError("frame missing Content-Length header")
    if not 0 <= length <= _MAX_FRAME_BYTES:
        raise FrameProtocolError(f"frame length {length} outside [0, {_MAX_FRAME_BYTES}]")
    payload = bytearray()
    while len(payload) < length:
        chunk = stream.read(length - len(payload))
        if not chunk:
            raise FrameProtocolError("EOF inside frame payload")
        payload += chunk
    return bytes(payload)


@dataclass(frozen=True)
class _Operation:
    http_method: str
    path_template: str


def _api_routes(routes: object) -> "list[APIRoute]":
    """Flatten APIRoutes whether the app lists them flat or nested under included routers."""
    found: list[APIRoute] = []
    if isinstance(routes, list):
        for route in routes:
            if isinstance(route, APIRoute):
                found.append(route)
            else:
                # FastAPI ≥0.141 wraps include_router() targets in _IncludedRouter, which
                # holds the actual APIRouter as `original_router`.
                inner = getattr(route, "original_router", route)
                found.extend(_api_routes(getattr(inner, "routes", None)))
    return found


def operation_table(app: FastAPI) -> dict[str, _Operation]:
    """operationId → (method, path), read from the live routes — never hand-maintained."""
    table: dict[str, _Operation] = {}
    for route in _api_routes(app.routes):
        if route.operation_id:
            methods = sorted((route.methods or set()) - {"HEAD", "OPTIONS"})
            if methods:
                table[route.operation_id] = _Operation(methods[0], route.path)
    return table


def _error(rpc_id: object, code: int, message: str, data: object = None) -> dict[str, object]:
    err: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": err}


def _result(rpc_id: object, result: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


async def _dispatch(
    client: httpx.AsyncClient,
    table: dict[str, _Operation],
    request: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """(response, shutdown_requested). Every request gets exactly one response."""
    rpc_id = request.get("id")
    method = request.get("method")
    if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error(rpc_id, _INVALID_REQUEST, "not a JSON-RPC 2.0 request object"), False
    raw_params = request.get("params")
    if raw_params is None:
        raw_params = {}
    if not isinstance(raw_params, dict):
        return _error(rpc_id, _INVALID_PARAMS, "params must be an object"), False
    params: dict[str, object] = dict(raw_params)

    if method == "rpc.ping":
        return _result(rpc_id, {"pong": True}), False
    if method == "rpc.shutdown":
        return _result(rpc_id, {"ok": True}), True

    op = table.get(method)
    if op is None:
        known = sorted([*table, "rpc.ping", "rpc.shutdown"])
        return _error(rpc_id, _METHOD_NOT_FOUND, f"unknown method {method!r}", {"known": known}), (
            False
        )

    body = params.pop("body", None)
    path = op.path_template
    for segment in [p.split("}")[0] for p in op.path_template.split("{")[1:]]:
        if segment not in params:
            return _error(
                rpc_id, _INVALID_PARAMS, f"missing path parameter {segment!r} for {method}"
            ), False
        path = path.replace("{" + segment + "}", str(params.pop(segment)))
    query: dict[str, str] = {}
    for key, value in params.items():
        if not isinstance(value, str | int | float | bool):
            return _error(
                rpc_id, _INVALID_PARAMS, f"query parameter {key!r} must be a scalar"
            ), False
        query[key] = str(value)

    response = await client.request(
        op.http_method,
        path,
        params=query or None,
        json=body if body is not None else None,
    )
    content_type = response.headers.get("content-type", "")
    payload: object
    if content_type.startswith("application/json"):
        payload = response.json()
    else:
        payload = {"content_type": content_type, "text": response.text}
    if response.status_code >= 400:
        message = f"HTTP {response.status_code}"
        if isinstance(payload, dict):
            envelope = payload.get("error")
            if isinstance(envelope, dict) and isinstance(envelope.get("message"), str):
                message = str(envelope["message"])
        return _error(
            rpc_id, _HTTP_ERROR, message, {"status": response.status_code, "body": payload}
        ), False
    return _result(rpc_id, payload), False


def serve_stdio(app: FastAPI) -> None:
    """Blocking frame loop over this process's stdin/stdout. Returns on EOF or rpc.shutdown."""
    rpc_in: BinaryIO = sys.stdin.buffer
    rpc_out: BinaryIO = sys.stdout.buffer
    # The RPC channel is sacred: anything else that prints must land on stderr from here on.
    sys.stdout = sys.stderr

    loop = asyncio.new_event_loop()
    stack = AsyncExitStack()
    try:
        # Same startup path uvicorn runs (schema create, engine on app.state) — one lifecycle,
        # two transports.
        loop.run_until_complete(stack.enter_async_context(app.router.lifespan_context(app)))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://tempest.sidecar"
        )
        table = operation_table(app)
        while True:
            try:
                frame = read_frame(rpc_in)
            except FrameProtocolError as exc:
                write_frame(
                    rpc_out,
                    json.dumps(_error(None, _PARSE_ERROR, f"framing error: {exc}")).encode(),
                )
                break
            if frame is None:
                break
            try:
                decoded: object = json.loads(frame)
            except ValueError as exc:
                write_frame(
                    rpc_out, json.dumps(_error(None, _PARSE_ERROR, f"bad JSON: {exc}")).encode()
                )
                continue
            if not isinstance(decoded, dict):
                write_frame(
                    rpc_out,
                    json.dumps(
                        _error(None, _INVALID_REQUEST, "batch requests are not supported")
                    ).encode(),
                )
                continue
            try:
                response, shutdown = loop.run_until_complete(_dispatch(client, table, decoded))
            except Exception as exc:  # one bad request must not kill the sidecar
                response, shutdown = _error(decoded.get("id"), _INTERNAL_ERROR, repr(exc)), False
            write_frame(rpc_out, json.dumps(response).encode())
            if shutdown:
                break
        loop.run_until_complete(client.aclose())
    finally:
        loop.run_until_complete(stack.aclose())
        loop.close()
