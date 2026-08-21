"""F16's CLIENT half and P5's gate — real servers, including the ones that misbehave.

    python -m tempest.dev.mcp_client_check

`mcp_check` proves Tempest's server half. This proves the other direction: that Tempest can
consume somebody else's MCP server without that server being able to hurt it.

**What a keyless run CAN prove**, and does here: the handshake and the tool list over real pipes;
that the policy is consulted BEFORE a request is written, so a denied call never reaches the
server at all; that a server which never answers is given up on rather than hanging the client
for ever; that a server which closes mid-request, floods, interleaves other people's messages, or
returns junk produces an error a caller can act on instead of a plausible empty answer; that a
bearer token is fetched once and reused; that killing the client kills the server; and that
**Tempest's own MCP server and this client interoperate** — both halves of F16 over one pipe.

**What it does NOT prove, and P5's gate asks for.** *"Connect to 10 real MCP servers including
OAuth ones."* That needs ten vendors' servers, real credentials, and a browser for the
authorization-code half of OAuth — an owner action, not something a hermetic gate can assert. The
client-credentials flow that a headless client CAN complete is exercised end to end against a
loopback authorization server; the authorization-code flow needs the desktop surface and is not
claimed. This gate says so rather than reporting a number that sounds like ten.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from tempest.dev import _fake_mcp as peer
from tempest.mcp import client as mcp

_SEARCH = ("scripted", "search")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _scripted(behaviour: str, **kw: object) -> mcp.McpClient:
    timeout = kw.pop("timeout_s", 10.0)
    assert isinstance(timeout, float)
    return mcp.McpClient(
        mcp.StdioTransport(peer.stdio_command(behaviour)),
        name="scripted",
        timeout_s=timeout,
        policy=kw.pop("policy", None),  # type: ignore[arg-type]
    )


def _check(name: str, fn: object) -> Check:
    """Run one invariant. A gate that dies on the first surprise reports one fact; this reports
    all of them, which is what makes a red run diagnosable in one read."""
    assert callable(fn)
    try:
        detail = fn()
    except Exception as exc:
        return Check(name, False, f"{type(exc).__name__}: {exc}")
    return Check(name, True, str(detail))


def _handshake() -> str:
    with _scripted(peer.NORMAL) as client:
        info = client.initialize()
        tools = client.list_tools()
    return f"{info['serverInfo']['name']}, {len(tools)} tool(s)"


def _denied_never_reaches_the_server() -> str:
    fake = peer.FakeMcpHttp()
    with peer.fake_mcp_http(fake) as url:
        client = mcp.McpClient(
            mcp.HttpTransport(f"{url}/rpc"),
            name="http",
            policy=mcp.ToolPolicy(deny=frozenset({("http", "search")})),
        )
        try:
            client.call_tool("search", {})
        except mcp.McpRefused:
            pass
        else:  # pragma: no cover — reached only if the policy stopped working
            raise AssertionError("a denied tool was called")
    if fake.requests:
        raise AssertionError(f"{len(fake.requests)} request(s) reached a server that was denied")
    return "0 requests written"


def _unlisted_is_denied() -> str:
    policy = mcp.ToolPolicy()
    if policy.decide("anything", "at-all") != mcp.DENY:
        raise AssertionError("an unlisted tool was not denied")
    return "default deny"


def _a_silent_server_is_given_up_on() -> str:
    with _scripted(peer.SILENT, timeout_s=0.5) as client:
        try:
            client.initialize()
        except mcp.McpTimeout:
            return "gave up after 0.5s instead of blocking on a read that never returns"
    raise AssertionError("a server that never answers did not time out")


def _a_closed_stream_is_an_error() -> str:
    with _scripted(peer.CLOSES) as client:
        try:
            client.initialize()
        except mcp.McpProtocolError:
            return "reported the closed stream rather than an empty result"
    raise AssertionError("a closed stream was read as an answer")


def _a_flood_is_refused() -> str:
    with _scripted(peer.FLOOD, policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as client:
        try:
            client.call_tool("search", {})
        except mcp.McpProtocolError:
            return f"stopped the stream at the {mcp.MAX_RESPONSE_BYTES}-byte cap"
    raise AssertionError("an unbounded response was read")


def _interleaved_messages_are_skipped() -> str:
    with _scripted(peer.NOISY) as client:
        return f"answered with {client.initialize()['serverInfo']['name']}"


def _a_hostile_result_is_data() -> str:
    with _scripted(peer.HOSTILE_TEXT, policy=mcp.ToolPolicy(allow=frozenset({_SEARCH}))) as client:
        answer = client.call_tool("search", {})
    note = answer.as_untrusted_note()
    if "untrusted-mcp-result" not in note or "scripted" not in note:
        raise AssertionError("a tool result reached a caller without its provenance")
    if peer.HOSTILE_PAYLOAD not in note:
        raise AssertionError("the payload was hidden rather than shown (L1)")
    return "attributed, labelled, and shown in full"


def _oauth_is_fetched_once() -> str:
    fake = peer.FakeMcpHttp()
    with peer.fake_mcp_http(fake) as url:
        token = mcp.ClientCredentials(
            token_url=f"{url}/token", client_id="id", client_secret="secret"
        )
        client = mcp.McpClient(
            mcp.HttpTransport(f"{url}/rpc", token=token),
            name="http",
            policy=mcp.ToolPolicy(allow=frozenset({("http", "search")})),
        )
        client.initialize()
        client.call_tool("search", {})
        client.close()
    if fake.token_calls != 1:
        raise AssertionError(f"the token was fetched {fake.token_calls} times, not once")
    if not all(h == "Bearer t" for h in fake.auth_headers):
        raise AssertionError(f"a request went out unauthenticated: {fake.auth_headers}")
    return f"{len(fake.auth_headers)} authenticated requests, 1 token fetch"


def _closing_kills_the_server() -> str:
    transport = mcp.StdioTransport(peer.stdio_command(peer.SILENT))
    proc = transport._proc
    transport.close()
    if proc.poll() is None:
        raise AssertionError("the server outlived the client that started it")
    return f"exited with {proc.poll()}"


def _both_halves_of_f16_meet() -> str:
    """Tempest's own server, driven by Tempest's own client, over a real pipe."""
    transport = mcp.StdioTransport([sys.executable, "-m", "tempest.mcp"])
    client = mcp.McpClient(transport, name="tempest", timeout_s=30.0)
    try:
        info = client.initialize()
        tools = client.list_tools()
    finally:
        client.close()
    names = sorted(t.name for t in tools)
    if "prove" not in names:
        raise AssertionError(f"our own server did not advertise prove: {names}")
    return f"{info.get('serverInfo', {}).get('name')} offers {names}"


def run() -> list[Check]:
    return [
        _check("the handshake and the tool list, over real pipes", _handshake),
        _check("a denied tool never reaches the server", _denied_never_reaches_the_server),
        _check("an unlisted tool is denied, not allowed", _unlisted_is_denied),
        _check("a server that never answers is given up on", _a_silent_server_is_given_up_on),
        _check("a closed stream is an error, not an empty answer", _a_closed_stream_is_an_error),
        _check("one unbounded message is refused rather than read", _a_flood_is_refused),
        _check("other people's messages are skipped", _interleaved_messages_are_skipped),
        _check("a hostile tool result comes back as attributed DATA", _a_hostile_result_is_data),
        _check("an OAuth token is fetched once and reused", _oauth_is_fetched_once),
        _check("closing the client kills the server", _closing_kills_the_server),
        _check("our own MCP server and this client interoperate", _both_halves_of_f16_meet),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", action="store_true", default=True)
    parser.parse_args(argv)

    checks = run()
    print(f"{'invariant':<58} status")
    for check in checks:
        print(f"{check.name:<58} {'PASS' if check.ok else 'FAIL'}  {check.detail[:60]}")
    failed = [c for c in checks if not c.ok]
    print("")
    print(f"mcp_client_check: {len(checks) - len(failed)}/{len(checks)} invariants held")
    print("")
    print(
        "NOT proved here: P5's 'connect to 10 real MCP servers including OAuth ones'. That needs\n"
        "ten vendors' servers, real credentials and a browser for the authorization-code flow —\n"
        "an owner action. The client-credentials flow a headless client CAN complete is proved\n"
        "above against a loopback authorization server; authorization-code is not claimed."
    )
    for check in failed:
        print(f"MCP-CLIENT-CHECK {check.name}: {check.detail}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
