"""Boundary A transport edges, exercised for real (Law L4):

- frame reader/writer corner cases at the byte level;
- `_dispatch` against a REAL adversarial FastAPI app over a real ASGI transport — the
  response shapes a well-behaved API never produces but the transport must survive;
- `serve_stdio` driven IN-PROCESS over real OS pipes by a real client thread protocol —
  the same loop the desktop supervises, without losing subprocess coverage to SIGKILL.
"""

import asyncio
import contextlib
import io
import json
import os
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

from tempest_api.app import create_app
from tempest_api.stdiorpc import (
    FrameProtocolError,
    _dispatch,
    operation_table,
    read_frame,
    serve_stdio,
    write_frame,
)


class TestFrameEdges:
    def test_header_larger_than_8k_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError, match="8 KiB"):
            read_frame(io.BytesIO(b"A" * 9000))

    def test_unparsable_content_length_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError, match="bad Content-Length"):
            read_frame(io.BytesIO(b"Content-Length: twelve\r\n\r\nxx"))


class TestOperationTable:
    def test_routes_without_ids_or_without_body_methods_are_not_dispatchable(self) -> None:
        app = FastAPI()

        @app.get("/anonymous")
        def anonymous() -> dict[str, bool]:  # no operation_id: invisible to the RPC surface
            return {"ok": True}

        app.add_api_route("/head-only", anonymous, methods=["HEAD"], operation_id="headOnly")
        table = operation_table(app)
        assert "headOnly" not in table  # HEAD/OPTIONS strip to nothing
        assert all(op.path_template not in ("/anonymous",) for op in table.values())


def _adversarial_app() -> FastAPI:
    """Real endpoints answering with the shapes the envelope contract forbids."""
    app = FastAPI()

    @app.get("/plain", operation_id="getPlain")
    def plain() -> PlainTextResponse:
        return PlainTextResponse("just text")

    @app.get("/broken-list", operation_id="getBrokenList")
    def broken_list() -> JSONResponse:
        return JSONResponse(status_code=500, content=[1, 2, 3])

    @app.get("/broken-shape", operation_id="getBrokenShape")
    def broken_shape() -> JSONResponse:
        return JSONResponse(status_code=500, content={"not-an-envelope": True})

    @app.get("/echo", operation_id="getEcho")
    def echo(n: int, flag: bool = False) -> dict[str, object]:
        return {"n": n, "flag": flag}

    return app


def _rpc(method: object, params: object = "omit", **extra: object) -> dict[str, object]:
    request: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "method": method, **extra}
    if params != "omit":
        request["params"] = params
    return request


class TestDispatchAgainstARealApp:
    @pytest.fixture
    def dispatch(self) -> Iterator[Callable[[dict[str, object]], dict[str, object]]]:
        app = _adversarial_app()
        table = operation_table(app)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://adversary"
        )

        def call(request: dict[str, object]) -> dict[str, object]:
            response, shutdown = asyncio.run(_dispatch(client, table, request))
            assert shutdown is False
            return response

        yield call
        asyncio.run(client.aclose())

    def test_wrong_jsonrpc_version_is_invalid_request(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        error = dispatch(_rpc("rpc.ping", **{"jsonrpc": "1.0"}))["error"]
        assert isinstance(error, dict) and error["code"] == -32600

    def test_missing_params_defaults_to_empty_object(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        assert dispatch(_rpc("rpc.ping"))["result"] == {"pong": True}

    def test_non_object_params_are_invalid(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        error = dispatch(_rpc("rpc.ping", params=[1, 2]))["error"]
        assert isinstance(error, dict) and error["code"] == -32602

    def test_scalar_query_params_reach_the_endpoint(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        response = dispatch(_rpc("getEcho", params={"n": 7, "flag": True}))
        assert response["result"] == {"n": 7, "flag": True}

    def test_non_scalar_query_params_are_refused_before_http(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        error = dispatch(_rpc("getEcho", params={"n": {"nested": 1}}))["error"]
        assert isinstance(error, dict) and error["code"] == -32602
        assert "scalar" in str(error["message"])

    def test_non_json_success_is_wrapped_with_its_content_type(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        result = dispatch(_rpc("getPlain"))["result"]
        assert isinstance(result, dict)
        assert result["text"] == "just text"
        assert str(result["content_type"]).startswith("text/plain")

    def test_non_dict_error_body_still_maps_to_http_error(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        error = dispatch(_rpc("getBrokenList"))["error"]
        assert isinstance(error, dict) and error["code"] == -32000
        assert error["message"] == "HTTP 500"
        assert error["data"] == {"status": 500, "body": [1, 2, 3]}

    def test_dict_error_body_without_envelope_keeps_the_status_message(
        self, dispatch: Callable[[dict[str, object]], dict[str, object]]
    ) -> None:
        error = dispatch(_rpc("getBrokenShape"))["error"]
        assert isinstance(error, dict) and error["code"] == -32000
        assert error["message"] == "HTTP 500"


class _ServeSession:
    """serve_stdio in a thread over real OS pipes; this class is the desktop-shell stand-in
    speaking real frames from the test thread."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
        monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
        stdin_read, stdin_write = os.pipe()
        stdout_read, stdout_write = os.pipe()
        self.to_server: BinaryIO = os.fdopen(stdin_write, "wb")
        self.from_server: BinaryIO = os.fdopen(stdout_read, "rb")
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=os.fdopen(stdin_read, "rb")))
        monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=os.fdopen(stdout_write, "wb")))
        self.thread = threading.Thread(target=serve_stdio, args=(create_app(),))
        self.thread.start()
        self._next_id = 0

    def send_raw(self, payload: bytes) -> None:
        write_frame(self.to_server, payload)

    def read(self) -> dict[str, Any]:
        payload = read_frame(self.from_server)
        assert payload is not None, "server closed the channel unexpectedly"
        decoded: dict[str, Any] = json.loads(payload)
        return decoded

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        self.send_raw(json.dumps(request).encode())
        response = self.read()
        assert response["id"] == self._next_id
        return response

    def finish(self) -> None:
        self.thread.join(timeout=60)
        assert not self.thread.is_alive(), "serve_stdio did not return"
        for stream in (self.to_server, self.from_server):
            with contextlib.suppress(OSError):
                stream.close()


class TestServeStdioInProcess:
    def test_session_survives_bad_frames_and_stops_on_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _ServeSession(monkeypatch, tmp_path / "serve.db")
        try:
            assert session.call("rpc.ping")["result"] == {"pong": True}
            health = session.call("getHealth")
            assert health["result"]["status"] == "ok"

            # HTTP-layer error rides the envelope through to error.data.
            missing = session.call("getRun", {"run_id": 999_999})
            assert missing["error"]["code"] == -32000
            assert missing["error"]["data"]["status"] == 404

            # A payload that is not JSON at all: PARSE_ERROR, channel stays alive.
            session.send_raw(b"{this is not json")
            bad_json = session.read()
            assert bad_json["error"]["code"] == -32700
            assert bad_json["id"] is None

            # A JSON batch (non-object): INVALID_REQUEST, channel stays alive.
            session.send_raw(b"[1, 2, 3]")
            batch = session.read()
            assert batch["error"]["code"] == -32600

            # A request whose dispatch explodes inside httpx (NUL byte in the path): the
            # sidecar answers INTERNAL_ERROR instead of dying.
            internal = session.call("getRun", {"run_id": "\x00"})
            assert internal["error"]["code"] == -32603

            assert session.call("rpc.shutdown")["result"] == {"ok": True}
        finally:
            session.finish()

    def test_clean_eof_ends_the_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _ServeSession(monkeypatch, tmp_path / "eof.db")
        try:
            assert session.call("rpc.ping")["result"] == {"pong": True}
        finally:
            session.to_server.close()  # EOF at a frame boundary: the loop must just return
            session.finish()

    def test_framing_error_reports_then_closes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _ServeSession(monkeypatch, tmp_path / "framing.db")
        try:
            assert session.call("rpc.ping")["result"] == {"pong": True}
            session.to_server.write(b"B" * 9000)  # no header terminator: stream is garbage
            session.to_server.flush()
            error = session.read()
            assert error["error"]["code"] == -32700
            assert "framing error" in error["error"]["message"]
        finally:
            session.finish()
