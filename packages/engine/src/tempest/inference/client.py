"""The model client — one code path, two wire protocols, sixteen providers (P1, L18/L21/L23).

Every provider in `providers.PROVIDERS` is reached through this module. There is deliberately no
per-provider branch anywhere: the wire is a field on the row, and this file contains exactly two
request builders and two response readers. That is what makes "adding a provider must not touch
feature code" true rather than aspirational.

**Stdlib only.** `urllib.request` rather than a vendor SDK, because a vendor SDK is a per-provider
dependency and the whole point of P1 is that a provider costs a table row. It also keeps the
frozen sidecar small and keeps the egress surface something we can see in one file (L10).

**Cancellation actually cancels (master prompt §7).** `stream()` and `complete()` take a cancel
token and **close the HTTP response** when it fires, which tears down the upstream connection —
the model stops generating and stops billing. The READ itself is bounded (`_cancel_guard`,
trap 58): a provider that goes silent cannot hold the abort hostage until the socket timeout,
because the watcher closes the response out from under the blocked read. Hiding output while
the request runs to completion would be the dishonest version of this feature, and it is the
version most clients ship.

**Errors are actionable (L15.3).** A missing key names the provider, the environment variable,
and how to set it. An unreachable endpoint says whether we are offline or the endpoint refused
us. An upstream rejection carries the provider's own message verbatim — including "no such
model", because model ids change faster than any registry and guessing on the user's behalf
would be worse than repeating what the provider said.

**Offline is a designed state, not a spinner (L23).** `Offline` is raised with the reason and,
when local runners are configured, the suggestion that they keep working unplugged.
"""

import contextlib
import http.client
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from tempest.inference.providers import (
    BASE_URL_ENV_PREFIX,
    WIRE_ANTHROPIC,
    Provider,
    get,
    local_ids,
)

#: Pinned so a provider upgrade cannot silently change the request shape under us.
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TIMEOUT_S = 60.0
#: How often the cancel watcher looks up. It bounds how long a cancel can go unnoticed while
#: the reading thread is blocked inside a socket read — NOT how often anything polls the wire.
_CANCEL_POLL_S = 0.1


class _Redirected(Exception):
    """Internal: a 3xx arrived. Carries only the target host — never the request headers."""

    def __init__(self, host: str) -> None:
        super().__init__(host)
        self.host = host


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects, because the API key travels in the request headers.

    `urlopen` follows 3xx by default, and CPython's `HTTPRedirectHandler` copies every header
    onto the new request — so `x-api-key` / `authorization` would be re-sent verbatim to
    whatever host the redirect names, past the per-project egress allowlist (THREAT-MODEL T2).
    A provider that legitimately moves its endpoint is a configuration change the user makes
    deliberately, not something a response header gets to do silently.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise _Redirected(urllib.parse.urlsplit(newurl).hostname or "an unnamed host")


class ModelError(Exception):
    """Any failure reaching a model. Every subclass names what the user can do about it."""


class MissingKey(ModelError):
    """No API key for this provider. Names the provider and the variable that carries it."""


class MissingModel(ModelError):
    """No model chosen and the registry has no default worth asserting for this provider."""


class Offline(ModelError):
    """The endpoint could not be reached (L23) — stated specifically, never as a spinner."""


class UpstreamError(ModelError):
    """The provider rejected the request. Carries the provider's own message verbatim."""


class Cancelled(ModelError):
    """The caller cancelled. The upstream connection was closed, not merely ignored."""


@dataclass(frozen=True)
class ToolCall:
    """One structured tool invocation the model asked for.

    `arguments` is a decoded object, never the raw string an OpenAI-shaped wire sends: a caller
    that had to json-decode it would be a second place that can get it wrong, and a model that
    emits malformed JSON is a fact the parser must settle once, here.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One turn. `role` is "user" | "assistant"; `content` is the text.

    A message may instead carry the RESULT of a tool the model asked for, in which case
    `tool_result_for` is the id of that call. The two wires disagree about how a result is
    carried — Anthropic wants a `user` message whose content is a `tool_result` block,
    OpenAI wants a message with role `tool` and a `tool_call_id` — so the difference is
    resolved in `_body`, the one function allowed to know which wire this is.
    """

    role: str  # "user" | "assistant"
    content: str
    #: The `ToolCall.id` this message answers, when it is a tool result.
    tool_result_for: str | None = None
    #: Tool calls an ASSISTANT turn made. Replayed back so the model sees its own request — a
    #: result without the call it answers is rejected by both wires.
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class Usage:
    """Token counts as the provider reported them — the input to the cost meter (L21/P11)."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class TextDelta:
    """One streamed text chunk, as the provider sent it."""

    text: str


@dataclass(frozen=True)
class StreamUsage:
    """Token counts the provider reported INSIDE its own stream (L21: measured, never
    estimated). A server that streams no usage produces no event — absence stays absence,
    not a fabricated zero."""

    input_tokens: int
    output_tokens: int


StreamEvent = TextDelta | StreamUsage


@dataclass(frozen=True)
class ToolCatalog:
    """The committed, model-facing tool definitions for BOTH wires.

    Held as the two shapes rather than one, because the shapes are what
    `make gen-contracts` emits and what review sees (§9c: "what the model is told must be
    visible in review, not computed silently at runtime"). `_body` picks by wire, which keeps
    the promise that the two wires differ in exactly one function.
    """

    anthropic: list[dict[str, Any]]
    openai: list[dict[str, Any]]


@dataclass(frozen=True)
class Completion:
    provider: str
    model: str
    text: str
    usage: Usage
    #: Structured calls the model asked for. Empty when it answered with prose alone.
    tool_calls: tuple[ToolCall, ...] = ()
    #: Why the model stopped, normalised across wires: "tool_use" | "end" | "length" | "".
    stop_reason: str = ""


def resolve_base_url(provider: Provider, env: dict[str, str]) -> str:
    """The row's default, unless the environment overrides it (Azure and local runners)."""
    return env.get(provider.base_url_env(), "").strip() or provider.base_url


def resolve_key(provider: Provider, env: dict[str, str]) -> str:
    if not provider.needs_key:
        return ""
    key = env.get(provider.env_var, "").strip()
    if not key:
        raise MissingKey(
            f"no API key for {provider.label}. Set it in Settings, or export "
            f"{provider.env_var}. Keys are stored in the OS keychain and never written to "
            f"disk in plaintext (L18)."
        )
    return key


def resolve_model(provider: Provider, model: str | None) -> str:
    chosen = (model or provider.default_model or "").strip()
    if not chosen:
        raise MissingModel(
            f"no model chosen for {provider.label}. Set one in Settings — this registry does "
            f"not ship a default for {provider.id} because model ids change faster than a "
            f"pinned table can stay honest."
        )
    return chosen


def _headers(provider: Provider, key: str) -> dict[str, str]:
    if provider.wire == WIRE_ANTHROPIC:
        return {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


def _endpoint(provider: Provider, base_url: str) -> str:
    tail = "/v1/messages" if provider.wire == WIRE_ANTHROPIC else "/chat/completions"
    return base_url.rstrip("/") + tail


def _turns(provider: Provider, messages: list[Message]) -> list[dict[str, Any]]:
    """Render the conversation for one wire, including tool calls and their results.

    This is the only place the two shapes are known, which is what keeps sixteen providers at
    two builders. Both wires require that a tool RESULT be preceded by the CALL it answers, so
    an assistant turn that made calls replays them; dropping them produces a 400 that reads like
    a model error and is actually ours.
    """
    rendered: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_result_for is not None:
            if provider.wire == WIRE_ANTHROPIC:
                rendered.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_result_for,
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:
                rendered.append(
                    {"role": "tool", "tool_call_id": m.tool_result_for, "content": m.content}
                )
            continue
        if m.tool_calls:
            if provider.wire == WIRE_ANTHROPIC:
                blocks: list[dict[str, Any]] = (
                    [{"type": "text", "text": m.content}] if m.content else []
                )
                blocks += [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                    for c in m.tool_calls
                ]
                rendered.append({"role": m.role, "content": blocks})
            else:
                rendered.append(
                    {
                        "role": m.role,
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {
                                    "name": c.name,
                                    "arguments": json.dumps(c.arguments),
                                },
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            continue
        rendered.append({"role": m.role, "content": m.content})
    return rendered


def _body(
    provider: Provider,
    model: str,
    messages: list[Message],
    max_tokens: int,
    stream: bool,
    system: str | None,
    tools: ToolCatalog | None = None,
    want_usage: bool = False,
) -> dict[str, Any]:
    """The one place the two wires differ in shape, and only by where `system` goes.

    Anthropic carries it as a top-level field; OpenAI carries it as a leading message with the
    `system` role. Everything else about the two payloads is identical, which is why sixteen
    providers cost two builders.
    """
    turns = _turns(provider, messages)
    payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if provider.wire == WIRE_ANTHROPIC:
        if system:
            payload["system"] = system
        payload["messages"] = turns
    else:
        payload["messages"] = ([{"role": "system", "content": system}] if system else []) + turns
    if tools is not None:
        # The committed model-facing artifacts, sent verbatim. Anthropic takes `{name,
        # description, input_schema}`; OpenAI takes `{type:"function", function:{...}}`. Both
        # are generated from `agent_tools.rs` by `make gen-contracts`, so what the model is told
        # is drift-gated against the enforcement point rather than assembled here.
        if provider.wire == WIRE_ANTHROPIC:
            payload["tools"] = tools.anthropic
        else:
            payload["tools"] = tools.openai
    if stream:
        payload["stream"] = True
        if want_usage and provider.wire != WIRE_ANTHROPIC:
            # Anthropic streams usage unasked; the OpenAI wire reports it only when asked.
            # Asked only on the usage-aware path, so every existing request stays
            # byte-identical to what its pinned tests recorded.
            payload["stream_options"] = {"include_usage": True}
    return payload


def _open(
    *,
    provider: Provider,
    model: str,
    messages: list[Message],
    env: dict[str, str],
    max_tokens: int,
    stream: bool,
    timeout: float,
    system: str | None,
    tools: ToolCatalog | None = None,
    want_usage: bool = False,
) -> Any:
    key = resolve_key(provider, env)
    base = resolve_base_url(provider, env)
    request = urllib.request.Request(
        _endpoint(provider, base),
        data=json.dumps(
            _body(provider, model, messages, max_tokens, stream, system, tools, want_usage)
        ).encode(),
        headers=_headers(provider, key),
        method="POST",
    )
    opener = urllib.request.build_opener(_RefuseRedirects)
    try:
        return opener.open(request, timeout=timeout)
    except _Redirected as err:
        # `from None`: the chained context would carry the request, and the request carries the
        # key. This message names the host and nothing else.
        raise UpstreamError(
            f"{provider.label} responded with a redirect to {err.host}; refusing to follow it "
            f"because the API key travels in the request headers and that host is not the one "
            f"you configured. If the endpoint really moved, set {provider.base_url_env()} "
            f"deliberately."
        ) from None
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:500]
        raise UpstreamError(
            f"{provider.label} rejected the request (HTTP {err.code}): {detail}"
        ) from err
    except (urllib.error.URLError, TimeoutError) as err:
        hint = ""
        if not provider.local:
            hint = (
                f" If you are offline, the local runners still work unplugged: "
                f"{', '.join(local_ids())}."
            )
        raise Offline(
            f"could not reach {provider.label} at {base} — {err}.{hint} Proof features are "
            f"unaffected; only generative features need a model (L23)."
        ) from err


def _text_and_usage(provider: Provider, document: Any) -> tuple[str, Usage]:
    """Read the two response shapes. Missing counts read as 0 — never invented."""
    if provider.wire == WIRE_ANTHROPIC:
        blocks = document.get("content", []) if isinstance(document, dict) else []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        raw = document.get("usage", {}) if isinstance(document, dict) else {}
        return text, Usage(int(raw.get("input_tokens", 0)), int(raw.get("output_tokens", 0)))
    choices = document.get("choices", []) if isinstance(document, dict) else []
    text = ""
    if choices:
        text = str(choices[0].get("message", {}).get("content") or "")
    raw = document.get("usage", {}) if isinstance(document, dict) else {}
    return text, Usage(int(raw.get("prompt_tokens", 0)), int(raw.get("completion_tokens", 0)))


def _tool_calls(provider: Provider, document: Any) -> tuple[ToolCall, ...]:
    """The structured calls in a response, for whichever wire this is.

    A call whose arguments will not decode is DROPPED, not passed on as an empty object: an
    empty `{}` reads downstream as "the model asked for this tool with no arguments", which is a
    different request from the one it actually made and would be dispatched as if it were valid.
    Dropping it leaves the model with a turn that did nothing, which it can see and retry.
    """
    if not isinstance(document, dict):
        return ()
    found: list[ToolCall] = []
    if provider.wire == WIRE_ANTHROPIC:
        for block in document.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            args = block.get("input")
            if not isinstance(args, dict):
                continue
            found.append(
                ToolCall(
                    id=str(block.get("id", "")), name=str(block.get("name", "")), arguments=args
                )
            )
        return tuple(found)
    choices = document.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return ()
    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        return ()
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function", {})
        if not isinstance(fn, dict):
            continue
        # OpenAI-shaped wires send arguments as a JSON *string*; decode once, here.
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            continue
        if not isinstance(args, dict):
            continue
        found.append(
            ToolCall(id=str(call.get("id", "")), name=str(fn.get("name", "")), arguments=args)
        )
    return tuple(found)


def _stop_reason(provider: Provider, document: Any, calls: tuple[ToolCall, ...]) -> str:
    """Normalised across wires so the turn loop has one condition to read.

    Anthropic says `stop_reason: "tool_use" | "end_turn" | "max_tokens"`; OpenAI says
    `finish_reason: "tool_calls" | "stop" | "length"`. A loop written against either spelling
    would be a per-provider branch, which §7 forbids in feature code.
    """
    if not isinstance(document, dict):
        return ""
    if provider.wire == WIRE_ANTHROPIC:
        raw = str(document.get("stop_reason") or "")
        mapping = {"tool_use": "tool_use", "end_turn": "end", "max_tokens": "length"}
    else:
        choices = document.get("choices", [])
        raw = str(choices[0].get("finish_reason") or "") if choices else ""
        mapping = {"tool_calls": "tool_use", "stop": "end", "length": "length"}
    normalised = mapping.get(raw, "")
    # A peer that returns tool calls without saying so still means "tool_use" — the calls are
    # the fact; the label is the claim about it.
    return "tool_use" if calls and normalised != "length" else normalised


def _shutdown_fd(fd: int) -> None:
    """`shutdown(2)` on a socket fd, borrowing — never owning — the descriptor."""
    sock = socket.socket(fileno=fd)
    try:
        sock.shutdown(socket.SHUT_RDWR)
    finally:
        # The fd still belongs to the response; detaching stops this wrapper's GC from
        # closing it a second time under whoever reuses the number next.
        sock.detach()


def _open_cancellable(cancel: threading.Event | None, /, **kwargs: Any) -> Any:
    """`_open`, with the cancel flag observable while it blocks.

    `_cancel_guard` bounds the READ, and the module docstring's promise — "a provider that
    goes silent cannot hold the abort hostage until the socket timeout" — was true only of
    silence AFTER the response headers. Connect, TLS, the request body write and
    `getresponse()` all happen inside `_open`, with no watcher alive and no flag read. A
    provider that accepts the TCP connection and then says nothing (a cold local model
    loading weights, a wedged proxy) held Stop for the FULL socket timeout: the chat job
    stayed `active` for 300 s, so the user's next message on that conversation was refused
    with a 409, and the turn finally settled as `error ... timed out` rather than the
    `aborted` terminal the client asked for. The wrong exception class, too — `_open`
    translates a timeout to `Offline`, so `except Cancelled` never ran.
    (Trap 45: the existing tests all arm peers that send headers FIRST, so the arm they
    exercised was the one that already worked.)

    The connect runs on a worker so the caller can stop waiting for it. The socket itself
    cannot be interrupted before a response object exists — there is no descriptor to shut
    down yet — so the abandoned attempt is left to expire at its own timeout, and if it
    does open after the caller gave up, the worker closes it rather than leaking it.
    """
    if cancel is None:
        return _open(**kwargs)
    if cancel.is_set():
        raise Cancelled("cancelled by the caller before the request was sent")

    box: dict[str, Any] = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["response"] = _open(**kwargs)
        except BaseException as exc:  # re-raised on the CALLER's thread, never swallowed
            box["error"] = exc
        finally:
            done.set()
            # The caller may already have unwound. An orphaned response would hold the
            # connection (and the provider's generation) open until GC.
            if cancel.is_set() and "response" in box:
                with contextlib.suppress(Exception):
                    box["response"].close()

    threading.Thread(target=run, name="tempest-open", daemon=True).start()
    while not done.wait(_CANCEL_POLL_S):
        if cancel.is_set():
            raise Cancelled("cancelled by the caller while the request was still connecting")
    if "error" in box:
        raise box["error"]
    if cancel.is_set():
        with contextlib.suppress(Exception):
            box["response"].close()
        raise Cancelled("cancelled by the caller as the response arrived")
    return box["response"]


@contextlib.contextmanager
def _cancel_guard(cancel: threading.Event | None, response: Any, label: str) -> Iterator[None]:
    """Bound the READ, not just the loop around it (trap 58).

    A cancel check between chunks is only reachable when chunks arrive; a provider that goes
    SILENT leaves the reading thread blocked inside a socket read that no deadline around the
    loop can interrupt. The guard watches the cancel flag from beside the read and, the moment
    it fires, **shuts the socket down at the fd** — `response.close()` will not do: the
    buffered reader's own lock is held by the blocked read, so a cross-thread close queues
    behind the very block it is trying to break (measured: a 10 s stall served in full).
    `shutdown(2)` touches no Python buffering and makes the OS read return at once.

    The unblocked read then ends as an I/O error (translated to `Cancelled` if and only if the
    caller really cancelled — a genuine upstream fault keeps its own face) or as a clean EOF,
    which is why both call sites re-check the flag after the read: a shut-down stream must
    never impersonate a completed one. The shutdown IS the abort — the connection dies, the
    model stops generating and stops billing.

    The fd is captured while nothing is blocked; the watcher is joined before the guard
    returns, so it can never touch the descriptor after the response is closed and the number
    reused.
    """
    if cancel is None:
        yield
        return
    if cancel.is_set():
        response.close()
        raise Cancelled(f"cancelled by the caller; {label} connection closed")
    fd: int = -1
    with contextlib.suppress(OSError, ValueError):
        fd = response.fileno()
    finished = threading.Event()

    def watch() -> None:
        while not finished.wait(_CANCEL_POLL_S):
            if cancel.is_set():
                if fd >= 0:
                    with contextlib.suppress(OSError):
                        _shutdown_fd(fd)
                return

    watcher = threading.Thread(target=watch, name="tempest-cancel-watch", daemon=True)
    watcher.start()
    try:
        yield
    # AttributeError belongs in this tuple: a response closed out from under a blocked read
    # Nones its `fp` mid-`readinto`, and the read surfaces AS AttributeError — observed on the
    # first cut of this guard, not theorized.
    except (OSError, ValueError, AttributeError, http.client.HTTPException) as err:
        if cancel.is_set():
            raise Cancelled(f"cancelled by the caller; {label} connection closed") from None
        raise err
    finally:
        finished.set()
        watcher.join(timeout=1.0)


def complete(
    provider_id: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_S,
    system: str | None = None,
    tools: ToolCatalog | None = None,
    cancel: threading.Event | None = None,
) -> Completion:
    """One non-streaming completion. `env` is passed in so callers can scope the key exactly.

    `cancel` aborts the in-flight request the way `stream()`'s does: the response is closed —
    the real hang-up, observed by the peer — and `Cancelled` is raised. The read is bounded
    (`_cancel_guard`), so a silent upstream cannot hold the abort hostage."""
    provider = get(provider_id)
    chosen = resolve_model(provider, model)
    with (
        _open_cancellable(
            cancel,
            provider=provider,
            model=chosen,
            messages=messages,
            env=env,
            max_tokens=max_tokens,
            stream=False,
            timeout=timeout,
            system=system,
            tools=tools,
        ) as response,
        _cancel_guard(cancel, response, provider.label),
    ):
        raw = response.read().decode("utf-8", errors="replace")
        if cancel is not None and cancel.is_set():
            # A shut-down socket can end the read as a clean-looking EOF; a partial body
            # must never be parsed as an answer the caller asked to abandon.
            raise Cancelled(f"cancelled by the caller; {provider.label} connection closed")
    try:
        document: Any = json.loads(raw)
    except ValueError as err:
        raise UpstreamError(f"{provider.label} returned a non-JSON body: {raw[:200]}") from err
    text, usage = _text_and_usage(provider, document)
    calls = _tool_calls(provider, document)
    return Completion(
        provider=provider.id,
        model=chosen,
        text=text,
        usage=usage,
        tool_calls=calls,
        stop_reason=_stop_reason(provider, document, calls),
    )


def _sse_delta(provider: Provider, payload: Any) -> str:
    """The text carried by one server-sent event, for whichever wire this is."""
    if not isinstance(payload, dict):
        return ""
    if provider.wire == WIRE_ANTHROPIC:
        if payload.get("type") == "content_block_delta":
            delta = payload.get("delta", {})
            return str(delta.get("text", "")) if isinstance(delta, dict) else ""
        return ""
    choices = payload.get("choices", [])
    if not choices:
        return ""
    delta = choices[0].get("delta", {})
    return str(delta.get("content") or "") if isinstance(delta, dict) else ""


def stream(
    provider_id: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_S,
    cancel: threading.Event | None = None,
    system: str | None = None,
) -> Iterator[str]:
    """Yield text deltas as they arrive.

    Cancellation is real: when `cancel` is set the response is **closed**, which tears down the
    upstream connection so the model stops generating — and stops charging. A client that only
    stops displaying tokens is pretending, and the user pays for the pretence.
    """
    for event in _stream_core(
        provider_id,
        messages,
        env=env,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
        cancel=cancel,
        system=system,
        want_usage=False,
    ):
        if isinstance(event, TextDelta):
            yield event.text


def stream_events(
    provider_id: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_S,
    cancel: threading.Event | None = None,
    system: str | None = None,
) -> Iterator[StreamEvent]:
    """`stream()` with the provider's own usage report riding along.

    Text arrives as `TextDelta`s; when the provider states token counts inside its stream
    (Anthropic always does; the OpenAI wire does when asked, which this path asks for), ONE
    trailing `StreamUsage` follows the last delta. A server that reports nothing produces no
    usage event — the cost meter records absence, never an estimate (L21). Cancellation is
    `stream()`'s, unchanged: the connection is torn down for real, and no usage is claimed
    for a turn the caller killed.
    """
    return _stream_core(
        provider_id,
        messages,
        env=env,
        model=model,
        max_tokens=max_tokens,
        timeout=timeout,
        cancel=cancel,
        system=system,
        want_usage=True,
    )


def _stream_core(
    provider_id: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    model: str | None,
    max_tokens: int,
    timeout: float,
    cancel: threading.Event | None,
    system: str | None,
    want_usage: bool,
) -> Iterator[StreamEvent]:
    provider = get(provider_id)
    chosen = resolve_model(provider, model)
    response = _open_cancellable(
        cancel,
        provider=provider,
        model=chosen,
        messages=messages,
        env=env,
        max_tokens=max_tokens,
        stream=True,
        timeout=timeout,
        system=system,
        want_usage=want_usage,
    )
    input_tokens: int | None = None
    output_tokens: int | None = None
    try:
        with _cancel_guard(cancel, response, provider.label):
            for raw_line in response:
                if cancel is not None and cancel.is_set():
                    response.close()  # the deterministic between-chunks abort
                    raise Cancelled(f"cancelled by the caller; {provider.label} connection closed")
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    payload: Any = json.loads(data)
                except ValueError:
                    continue  # a keep-alive or a partial frame is not an error
                if isinstance(payload, dict):
                    observed_in, observed_out = _sse_usage(provider, payload)
                    input_tokens = observed_in if observed_in is not None else input_tokens
                    output_tokens = observed_out if observed_out is not None else output_tokens
                delta = _sse_delta(provider, payload)
                if delta:
                    yield TextDelta(delta)
            if cancel is not None and cancel.is_set():
                # The watcher's shutdown ends the iteration as EOF, not an exception; a
                # cancelled stream must never impersonate a completed one.
                raise Cancelled(f"cancelled by the caller; {provider.label} connection closed")
    finally:
        response.close()
    if input_tokens is not None and output_tokens is not None:
        # BOTH halves observed, or nothing: a half-known count padded with a zero would be
        # the fabricated number L21 forswears, flowing into the meter as "measured". The
        # Anthropic wire states usage unasked, so `stream()` receives (and filters) the
        # event too — `want_usage` gates only the OpenAI request knob, never the parsing.
        yield StreamUsage(input_tokens, output_tokens)


def _sse_usage(provider: Provider, payload: dict[str, Any]) -> tuple[int | None, int | None]:
    """(input, output) stated by one event — either side None when the event is silent on it.

    Anthropic: `message_start` carries the input count, `message_delta` the cumulative output
    count (the last one wins, which is the total). OpenAI wire: a chunk-level `usage` object
    with prompt/completion counts, sent once at the end when `include_usage` was requested.
    """
    if provider.wire == WIRE_ANTHROPIC:
        if payload.get("type") == "message_start":
            message = payload.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int):
                return usage["input_tokens"], None
            return None, None
        if payload.get("type") == "message_delta":
            usage = payload.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("output_tokens"), int):
                return None, usage["output_tokens"]
            return None, None
        return None, None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        return (
            prompt if isinstance(prompt, int) else None,
            completion if isinstance(completion, int) else None,
        )
    return None, None


def describe_env(provider_id: str) -> dict[str, str]:
    """What a UI needs to explain configuration, without ever touching a key's value."""
    provider = get(provider_id)
    return {
        "id": provider.id,
        "label": provider.label,
        "wire": provider.wire,
        "key_env": provider.env_var,
        "base_url_env": provider.base_url_env(),
        "base_url_default": provider.base_url,
        "local": "yes" if provider.local else "no",
    }


__all__ = [
    "ANTHROPIC_VERSION",
    "BASE_URL_ENV_PREFIX",
    "Cancelled",
    "Completion",
    "Message",
    "MissingKey",
    "MissingModel",
    "ModelError",
    "Offline",
    "UpstreamError",
    "Usage",
    "complete",
    "describe_env",
    "resolve_base_url",
    "resolve_key",
    "resolve_model",
    "stream",
]
