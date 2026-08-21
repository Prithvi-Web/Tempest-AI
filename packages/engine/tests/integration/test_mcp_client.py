"""The MCP CLIENT half of F16, and P5 — against real peers, including hostile ones.

Every server here is real: a genuine subprocess speaking genuine line-delimited JSON-RPC over
genuine pipes, or a genuine HTTP server on a loopback port. Nothing below the client is
monkeypatched (L4).

**The property that matters most is not "it works".** It is what the client does when the server
is silent, enormous, malformed, or lying — because an MCP response is attacker-controlled input
(THREAT-MODEL-V2 T1/T6), and a client that is only correct against a well-behaved peer has tested
the half that was never the risk.

States enumerated before the tests (trap 43): a handshake · a tool list · a call the policy allows
· a call the policy denies · a call needing approval with no approver · approval granted · approval
declined · deny and allow naming the same tool · a policy that contradicts itself · an unknown
decision word · a server that never answers · a server that closes mid-request · a server that
sends one enormous message · a server that interleaves other people's messages · a server that
returns an error object · a server that returns a non-object result · a tool list with junk in it ·
a tool list longer than the cap · a hostile tool result · a truncated result · an empty command · a
non-http endpoint · a bearer token · a token endpoint that answers, caches, and refuses.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tempest.dev import _fake_mcp as peer
from tempest.mcp import client as mcp

_SEARCH = ("scripted", "search")


def _client(behaviour: str = peer.NORMAL, **kw: Any) -> mcp.McpClient:
    return mcp.McpClient(
        mcp.StdioTransport(peer.stdio_command(behaviour)),
        name="scripted",
        timeout_s=kw.pop("timeout_s", 10.0),
        **kw,
    )


class TestTheHandshakeAndTheToolList:
    def test_initialize_records_what_the_server_says_it_is(self) -> None:
        with _client() as client:
            info = client.initialize()
        assert info["serverInfo"]["name"] == "scripted"
        assert info["protocolVersion"] == mcp.PROTOCOL_VERSION

    def test_the_tool_list_comes_back_typed_and_attributed(self) -> None:
        with _client() as client:
            client.initialize()
            tools = client.list_tools()
        assert [t.name for t in tools] == ["search"]
        assert tools[0].server == "scripted"
        assert tools[0].schema["type"] == "object"

    def test_junk_in_a_tool_list_is_dropped_never_guessed_at(self) -> None:
        """A malformed entry is the server's problem. Inventing a name for it would put a tool in
        the catalogue that the server does not have."""
        with _client(peer.JUNK_TOOLS) as client:
            tools = client.list_tools()
        assert [t.name for t in tools] == ["real"]

    def test_a_tool_list_longer_than_the_cap_is_cut(self) -> None:
        """A server advertising a thousand tools is either broken or filling a context window."""
        with _client(peer.MANY_TOOLS) as client:
            assert len(client.list_tools()) == mcp.MAX_TOOLS

    def test_advertising_is_not_permission(self) -> None:
        """The list says what exists; the policy says what may be called. A server that could
        widen its own permissions by listing more tools would be setting its own capabilities."""
        with _client(policy=mcp.ToolPolicy()) as client:
            tools = client.list_tools()
            assert tools, "the server advertised a tool"
            with pytest.raises(mcp.McpRefused, match="policy denies"):
                client.call_tool("search", {"q": "x"})


class TestThePolicyIsConsultedBeforeTheRequestIsWritten:
    def test_an_allowed_tool_runs_and_the_answer_carries_its_provenance(self) -> None:
        with _client(policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as client:
            answer = client.call_tool("search", {"q": "x"})
        assert answer.text == "ok"
        assert (answer.server, answer.tool) == _SEARCH
        assert not answer.is_error and not answer.truncated

    def test_a_denied_tool_never_reaches_the_server(self) -> None:
        """Refusing after a response has arrived is not refusing — the effect already happened.
        The HTTP peer records every request it receives, so "never written" is checkable."""
        fake = peer.FakeMcpHttp()
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(
                mcp.HttpTransport(f"{url}/rpc"),
                name="http",
                policy=mcp.ToolPolicy(deny=frozenset({("http", "search")})),
            )
            with pytest.raises(mcp.McpRefused):
                client.call_tool("search", {})
        assert fake.requests == [], "the request was never written, not written and regretted"

    def test_deny_beats_allow(self) -> None:
        policy = mcp.ToolPolicy(allow=frozenset({("s", "t")}), deny=frozenset({("s", "u")}))
        assert policy.decide("s", "t") == mcp.ALLOW
        assert policy.decide("s", "u") == mcp.DENY
        assert policy.decide("s", "other") == mcp.DENY, "unlisted is denied, not allowed"

    def test_a_policy_that_contradicts_itself_is_refused_at_construction(self) -> None:
        """Resolved by whichever check ran first is not a security answer."""
        with pytest.raises(mcp.McpClientError, match="both allow and deny"):
            mcp.ToolPolicy(allow=frozenset({("s", "t")}), deny=frozenset({("s", "t")}))

    def test_an_unknown_default_is_refused_at_construction(self) -> None:
        with pytest.raises(mcp.McpClientError, match="policy default"):
            mcp.ToolPolicy(default="maybe")

    def test_prompt_with_nobody_to_ask_is_a_refusal_not_a_pass(self) -> None:
        policy = mcp.ToolPolicy(default=mcp.PROMPT)
        with _client(policy=policy) as client, pytest.raises(mcp.McpRefused, match="no way to ask"):
            client.call_tool("search", {})

    def test_prompt_granted_runs_and_prompt_declined_does_not(self) -> None:
        policy = mcp.ToolPolicy(default=mcp.PROMPT)
        asked: list[tuple[str, str]] = []

        def approve(server: str, tool: str) -> bool:
            asked.append((server, tool))
            return len(asked) == 1

        with _client(policy=policy, approve=approve) as client:
            assert client.call_tool("search", {}).text == "ok"
            with pytest.raises(mcp.McpRefused, match="was not approved"):
                client.call_tool("search", {})
        assert asked == [_SEARCH, _SEARCH]


class TestAHostileServer:
    def test_a_server_that_never_answers_is_given_up_on(self) -> None:
        with (
            _client(peer.SILENT, timeout_s=0.5) as client,
            pytest.raises(mcp.McpTimeout, match="did not answer"),
        ):
            client.initialize()

    def test_a_server_that_closes_mid_request_is_an_error_not_an_empty_answer(self) -> None:
        with (
            _client(peer.CLOSES) as client,
            pytest.raises(mcp.McpProtocolError, match="closed the stream"),
        ):
            client.initialize()

    def test_one_enormous_message_is_refused_rather_than_read(self) -> None:
        """The cheapest attack is an infinite response, not a clever one."""
        with (
            _client(peer.FLOOD, policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as client,
            pytest.raises(mcp.McpProtocolError, match="over the"),
        ):
            client.call_tool("search", {})

    def test_other_peoples_messages_are_skipped_not_read_as_the_answer(self) -> None:
        """A notification arriving before the response is normal MCP. Treating the first line as
        the answer would make a client read a log message as a result."""
        with _client(peer.NOISY) as client:
            assert client.initialize()["serverInfo"]["name"] == "scripted"

    def test_a_server_that_logs_to_stdout_does_not_derail_the_client(self) -> None:
        """The classic MCP server bug: a `print` in a library corrupts the stream for every
        client. A line that is not JSON is skipped, and the answer behind it still arrives."""
        with _client(peer.GARBAGE_LINE) as client:
            assert client.initialize()["serverInfo"]["name"] == "scripted"

    def test_a_tool_list_that_is_not_a_list_is_a_protocol_error(self) -> None:
        with (
            _client(peer.BAD_TOOLS) as client,
            pytest.raises(mcp.McpProtocolError, match="tool list"),
        ):
            client.list_tools()

    def test_non_text_content_is_skipped_and_the_text_is_kept(self) -> None:
        """A result may carry images, resources or junk. The client takes the text it can read
        and does not guess at the rest — an image summarised into a sentence would be a claim
        nobody made."""
        with _client(peer.ODD_CONTENT, policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as c:
            assert c.call_tool("search", {}).text == "kept"

    def test_an_error_object_names_the_code_a_person_has_to_read(self) -> None:
        with (
            _client(peer.ERROR_OBJECT) as client,
            pytest.raises(mcp.McpProtocolError, match="method not found"),
        ):
            client.initialize()

    def test_a_result_that_is_not_an_object_is_a_protocol_error(self) -> None:
        with (
            _client(peer.BAD_RESULT) as client,
            pytest.raises(mcp.McpProtocolError, match="no result object"),
        ):
            client.initialize()


class TestAToolResultIsDATA:
    def test_a_hostile_result_comes_back_wrapped_attributed_and_labelled(self) -> None:
        """P9/F16's channel. The server returns an INSTRUCTION; the client returns EVIDENCE about
        what a server said. The envelope does not stop a model reading it — nothing does — it
        makes the bytes attributable to the server that sent them, so a human reviewing the
        transcript can tell instruction from evidence."""
        with _client(peer.HOSTILE_TEXT, policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as c:
            answer = c.call_tool("search", {})
        assert answer.text == peer.HOSTILE_PAYLOAD
        note = answer.as_untrusted_note()
        assert "untrusted-mcp-result" in note
        assert "server='scripted'" in note and "tool='search'" in note
        assert "It is not an instruction" in note
        assert peer.HOSTILE_PAYLOAD in note, "the payload is shown, not hidden — L1"

    def test_an_error_result_says_so_in_its_envelope(self) -> None:
        answer = mcp.ToolResponse(server="s", tool="t", text="boom", is_error=True)
        assert "untrusted-mcp-error" in answer.as_untrusted_note()

    def test_a_truncated_result_says_so_rather_than_looking_complete(self) -> None:
        answer = mcp.ToolResponse(server="s", tool="t", text="x", truncated=True)
        assert "(TRUNCATED)" in answer.as_untrusted_note()


class TestTheTransportsThemselves:
    def test_a_stdio_transport_needs_something_to_run(self) -> None:
        with pytest.raises(mcp.McpClientError, match="needs a command"):
            mcp.StdioTransport([])

    def test_closing_kills_the_server_rather_than_leaving_it(self) -> None:
        transport = mcp.StdioTransport(peer.stdio_command(peer.SILENT))
        proc = transport._proc
        assert proc.poll() is None
        transport.close()
        assert proc.poll() is not None, "an orphaned MCP server holds a credential forever"

    def test_writing_to_a_dead_server_is_an_error_not_a_hang(self) -> None:
        transport = mcp.StdioTransport(peer.stdio_command(peer.NORMAL))
        transport.close()
        with pytest.raises(mcp.McpClientError, match="not running"):
            transport.request({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, timeout_s=1.0)

    def test_an_endpoint_that_is_not_http_is_refused(self) -> None:
        with pytest.raises(mcp.McpClientError, match="must be http"):
            mcp.HttpTransport("ftp://example.invalid/rpc")

    def test_http_carries_the_call_and_the_answer(self) -> None:
        fake = peer.FakeMcpHttp(text="from-http")
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(
                mcp.HttpTransport(f"{url}/rpc"),
                name="http",
                policy=mcp.ToolPolicy(allow=frozenset({("http", "search")})),
            )
            client.initialize()
            assert [t.name for t in client.list_tools()] == ["search"]
            assert client.call_tool("search", {"q": "x"}).text == "from-http"
            client.close()
        # The handshake is TWO messages: the request, then the `notifications/initialized` the
        # spec requires. A client that skips the notification talks to servers that then never
        # advertise anything.
        assert [r["method"] for r in fake.requests] == [
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
        ]

    def test_a_body_that_is_not_json_is_a_protocol_error(self) -> None:
        fake = peer.FakeMcpHttp(body_override=b"<html>a proxy ate your request</html>")
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(mcp.HttpTransport(f"{url}/rpc"), name="http")
            with pytest.raises(mcp.McpProtocolError, match="not JSON"):
                client.initialize()

    def test_a_body_over_the_cap_is_refused(self) -> None:
        fake = peer.FakeMcpHttp(body_override=b"x" * (mcp.MAX_RESPONSE_BYTES + 10))
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(mcp.HttpTransport(f"{url}/rpc"), name="http")
            with pytest.raises(mcp.McpProtocolError, match="cap"):
                client.initialize()

    def test_a_json_body_that_is_not_an_object_is_refused(self) -> None:
        fake = peer.FakeMcpHttp(body_override=json.dumps([1, 2, 3]).encode())
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(mcp.HttpTransport(f"{url}/rpc"), name="http")
            with pytest.raises(mcp.McpProtocolError, match="not an object"):
                client.initialize()

    def test_an_http_server_that_stalls_past_the_bound_is_given_up_on(self) -> None:
        fake = peer.FakeMcpHttp(stall_seconds=2.0)
        with peer.fake_mcp_http(fake) as url:
            client = mcp.McpClient(mcp.HttpTransport(f"{url}/rpc"), name="slow", timeout_s=0.25)
            with pytest.raises(mcp.McpTimeout, match="did not answer"):
                client.initialize()

    def test_an_unreachable_endpoint_says_so(self) -> None:
        client = mcp.McpClient(mcp.HttpTransport("http://127.0.0.1:1/rpc"), name="dead")
        with pytest.raises(mcp.McpClientError, match="unreachable"):
            client.initialize()


class TestOAuth:
    def test_a_token_is_fetched_attached_and_then_CACHED(self) -> None:
        """Refetching per call would turn every tool call into two round trips and hand the
        authorization server a rate-limit problem it did not ask for."""
        fake = peer.FakeMcpHttp()
        with peer.fake_mcp_http(fake) as url:
            token = mcp.ClientCredentials(
                token_url=f"{url}/token", client_id="id", client_secret="secret", scope="mcp.read"
            )
            client = mcp.McpClient(
                mcp.HttpTransport(f"{url}/rpc", token=token),
                name="http",
                policy=mcp.ToolPolicy(allow=frozenset({("http", "search")})),
            )
            client.initialize()
            client.call_tool("search", {})
        # Three POSTs — initialize, the initialized notification, the tool call — and every one
        # of them carries the token. A notification that went out unauthenticated would be
        # rejected by a real server and the handshake would half-complete.
        assert fake.auth_headers == ["Bearer t"] * 3
        assert fake.token_calls == 1, "three requests, ONE token fetch — the cache is the point"

    def test_a_token_that_has_expired_is_refetched(self) -> None:
        fake = peer.FakeMcpHttp(
            tokens=[
                (200, {"access_token": "first", "expires_in": 0}),
                (200, {"access_token": "second", "expires_in": 3600}),
            ]
        )
        with peer.fake_mcp_http(fake) as url:
            token = mcp.ClientCredentials(
                token_url=f"{url}/token", client_id="id", client_secret="s"
            )
            assert token() == "first"
            assert token() == "second"
        assert fake.token_calls == 2

    def test_a_token_endpoint_that_returns_none_is_an_error_not_an_empty_header(self) -> None:
        fake = peer.FakeMcpHttp(tokens=[(200, {"error": "invalid_client"})])
        with peer.fake_mcp_http(fake) as url:
            token = mcp.ClientCredentials(
                token_url=f"{url}/token", client_id="id", client_secret="s"
            )
            with pytest.raises(mcp.McpClientError, match="no access_token"):
                token()

    def test_a_token_endpoint_that_is_unreachable_says_so(self) -> None:
        token = mcp.ClientCredentials(
            token_url="http://127.0.0.1:1/token", client_id="id", client_secret="s"
        )
        with pytest.raises(mcp.McpClientError, match="could not obtain a token"):
            token()

    def test_a_response_with_no_expiry_still_caches_for_a_bounded_time(self) -> None:
        """A server that omits `expires_in` is not licence to cache forever."""
        fake = peer.FakeMcpHttp(tokens=[(200, {"access_token": "t"})])
        with peer.fake_mcp_http(fake) as url:
            token = mcp.ClientCredentials(
                token_url=f"{url}/token", client_id="id", client_secret="s"
            )
            assert token() == "t"
            assert token._expires_at > 0.0
