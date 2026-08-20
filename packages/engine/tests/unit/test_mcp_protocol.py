"""The JSON-RPC transport MCP speaks: what it accepts, what it refuses, and what it never does.

`mcp_check` drives the whole server over a real pipe. This pins the transport itself, where the
failures are quiet: a response to a notification, a crash that closes the connection, a line that
is not JSON becoming a traceback instead of an error object.

States enumerated before the tests (trap 43): a well-formed request · a notification · a line that
is not JSON · a JSON value that is not an object · an object with no `jsonrpc` · an object with no
method · params that are not an object · a handler that raises `RpcError` · a handler that raises
something else · an empty line · an empty stream.
"""

from __future__ import annotations

import io
import json
from typing import Any

from tempest.mcp import protocol


def _drive(lines: list[str], handler: Any) -> list[dict[str, Any]]:
    out = io.StringIO()
    protocol.serve(handler, stdin=io.StringIO("".join(f"{line}\n" for line in lines)), stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _request(method: str, rid: object = 1, **params: Any) -> str:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if rid is not None:
        body["id"] = rid
    return json.dumps(body)


class TestWhatItAnswers:
    def test_a_request_gets_exactly_one_response_carrying_its_id(self) -> None:
        got = _drive([_request("ping", rid=7)], lambda _r: {"ok": True})
        assert got == [{"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}]

    def test_a_notification_gets_NO_response(self) -> None:
        """`notifications/initialized` is the one every client sends, and answering it is a
        protocol violation that desynchronises the stream for everything after."""
        assert (
            _drive([_request("notifications/initialized", rid=None)], lambda _r: {"ok": True}) == []
        )

    def test_params_are_always_a_dict_even_when_the_client_sends_something_else(self) -> None:
        seen: list[dict[str, Any]] = []

        def handler(request: protocol.Request) -> dict[str, Any]:
            seen.append(request.params)
            return {}

        _drive(['{"jsonrpc": "2.0", "id": 1, "method": "x", "params": [1, 2]}'], handler)
        assert seen == [{}], "a handler should never have to defend against a list"

    def test_an_empty_line_is_skipped_rather_than_answered(self) -> None:
        assert _drive(["", _request("ping")], lambda _r: {}) == [
            {"jsonrpc": "2.0", "id": 1, "result": {}}
        ]

    def test_an_empty_stream_produces_nothing_and_returns(self) -> None:
        assert _drive([], lambda _r: {}) == []


class TestWhatItRefuses:
    def test_a_line_that_is_not_json_is_an_error_object(self) -> None:
        (got,) = _drive(["{not json"], lambda _r: {})
        assert got["error"]["code"] == protocol.PARSE_ERROR and got["id"] is None

    def test_a_json_value_that_is_not_an_object_is_refused(self) -> None:
        (got,) = _drive(["[1, 2, 3]"], lambda _r: {})
        assert got["error"]["code"] == protocol.INVALID_REQUEST

    def test_a_message_without_the_version_marker_is_refused(self) -> None:
        (got,) = _drive(['{"id": 1, "method": "ping"}'], lambda _r: {})
        assert got["error"]["code"] == protocol.INVALID_REQUEST

    def test_a_message_with_no_method_is_refused(self) -> None:
        (got,) = _drive(['{"jsonrpc": "2.0", "id": 1}'], lambda _r: {})
        assert (
            got["error"]["code"] == protocol.INVALID_REQUEST and "method" in got["error"]["message"]
        )


class TestTheLoopOutlivesItsHandlers:
    def test_an_RpcError_becomes_an_error_object_with_its_code(self) -> None:
        def handler(_request: protocol.Request) -> dict[str, Any]:
            raise protocol.RpcError(protocol.TOOL_REFUSED, "no", data={"why": "stated"})

        (got,) = _drive([_request("x")], handler)
        assert got["error"] == {
            "code": protocol.TOOL_REFUSED,
            "message": "no",
            "data": {"why": "stated"},
        }

    def test_an_UNEXPECTED_exception_becomes_an_error_object_too(self) -> None:
        """A client that loses the connection cannot tell a crash from a refusal, and those are
        very different facts about a proof."""

        def handler(_request: protocol.Request) -> dict[str, Any]:
            raise KeyError("something nobody predicted")

        (got,) = _drive([_request("x")], handler)
        assert got["error"]["code"] == protocol.INTERNAL_ERROR
        assert "KeyError" in got["error"]["message"]

    def test_the_stream_keeps_serving_after_a_failure(self) -> None:
        calls = {"n": 0}

        def handler(_request: protocol.Request) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {"still": "here"}

        first, second = _drive([_request("x", rid=1), _request("x", rid=2)], handler)
        assert "error" in first
        assert second["result"] == {"still": "here"}


class TestWriting:
    def test_every_message_is_one_line_and_is_flushed(self) -> None:
        """A client blocked on a response sitting in a buffer looks exactly like a server that
        hung, and a message split across lines desynchronises the stream."""
        out = io.StringIO()
        protocol.write(out, {"jsonrpc": "2.0", "id": 1, "result": {"a": "b\nc"}})
        assert out.getvalue().count("\n") == 1
        assert json.loads(out.getvalue())["result"]["a"] == "b\nc"

    def test_an_error_without_data_omits_the_field(self) -> None:
        (got,) = _drive(
            [_request("x")],
            lambda _r: (_ for _ in ()).throw(protocol.RpcError(protocol.METHOD_NOT_FOUND, "nope")),
        )
        assert "data" not in got["error"]


class TestRequestShape:
    def test_a_request_with_no_id_is_a_notification(self) -> None:
        assert protocol.Request(id=None, method="x", params={}).is_notification
        assert not protocol.Request(id=0, method="x", params={}).is_notification, (
            "id 0 is an id; only its absence makes a notification"
        )
