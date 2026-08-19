"""The model client — one code path, two wire protocols, sixteen providers (P1, L18/L21/L23).

Every provider in `providers.PROVIDERS` is reached through this module. There is deliberately no
per-provider branch anywhere: the wire is a field on the row, and this file contains exactly two
request builders and two response readers. That is what makes "adding a provider must not touch
feature code" true rather than aspirational.

**Stdlib only.** `urllib.request` rather than a vendor SDK, because a vendor SDK is a per-provider
dependency and the whole point of P1 is that a provider costs a table row. It also keeps the
frozen sidecar small and keeps the egress surface something we can see in one file (L10).

**Cancellation actually cancels (master prompt §7).** `stream()` checks the cancel token between
chunks and **closes the HTTP response**, which tears down the upstream connection — the model
stops generating and stops billing. Hiding output while the request runs to completion would be
the dishonest version of this feature, and it is the version most clients ship.

**Errors are actionable (L15.3).** A missing key names the provider, the environment variable,
and how to set it. An unreachable endpoint says whether we are offline or the endpoint refused
us. An upstream rejection carries the provider's own message verbatim — including "no such
model", because model ids change faster than any registry and guessing on the user's behalf
would be worse than repeating what the provider said.

**Offline is a designed state, not a spinner (L23).** `Offline` is raised with the reason and,
when local runners are configured, the suggestion that they keep working unplugged.
"""

import json
import threading
import urllib.error
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
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Usage:
    """Token counts as the provider reported them — the input to the cost meter (L21/P11)."""

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    provider: str
    model: str
    text: str
    usage: Usage


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


def _body(
    provider: Provider,
    model: str,
    messages: list[Message],
    max_tokens: int,
    stream: bool,
    system: str | None,
) -> dict[str, Any]:
    """The one place the two wires differ in shape, and only by where `system` goes.

    Anthropic carries it as a top-level field; OpenAI carries it as a leading message with the
    `system` role. Everything else about the two payloads is identical, which is why sixteen
    providers cost two builders.
    """
    turns = [{"role": m.role, "content": m.content} for m in messages]
    payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if provider.wire == WIRE_ANTHROPIC:
        if system:
            payload["system"] = system
        payload["messages"] = turns
    else:
        payload["messages"] = ([{"role": "system", "content": system}] if system else []) + turns
    if stream:
        payload["stream"] = True
    return payload


def _open(
    provider: Provider,
    model: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    max_tokens: int,
    stream: bool,
    timeout: float,
    system: str | None,
) -> Any:
    key = resolve_key(provider, env)
    base = resolve_base_url(provider, env)
    request = urllib.request.Request(
        _endpoint(provider, base),
        data=json.dumps(_body(provider, model, messages, max_tokens, stream, system)).encode(),
        headers=_headers(provider, key),
        method="POST",
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
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


def complete(
    provider_id: str,
    messages: list[Message],
    *,
    env: dict[str, str],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_S,
    system: str | None = None,
) -> Completion:
    """One non-streaming completion. `env` is passed in so callers can scope the key exactly."""
    provider = get(provider_id)
    chosen = resolve_model(provider, model)
    with _open(
        provider,
        chosen,
        messages,
        env=env,
        max_tokens=max_tokens,
        stream=False,
        timeout=timeout,
        system=system,
    ) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        document: Any = json.loads(raw)
    except ValueError as err:
        raise UpstreamError(f"{provider.label} returned a non-JSON body: {raw[:200]}") from err
    text, usage = _text_and_usage(provider, document)
    return Completion(provider=provider.id, model=chosen, text=text, usage=usage)


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
    provider = get(provider_id)
    chosen = resolve_model(provider, model)
    response = _open(
        provider,
        chosen,
        messages,
        env=env,
        max_tokens=max_tokens,
        stream=True,
        timeout=timeout,
        system=system,
    )
    try:
        for raw_line in response:
            if cancel is not None and cancel.is_set():
                response.close()  # the actual abort, not a cosmetic one
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
            delta = _sse_delta(provider, payload)
            if delta:
                yield delta
    finally:
        response.close()


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
