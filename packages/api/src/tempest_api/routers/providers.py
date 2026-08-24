"""GET /v1/platform/catalog (PLAN-V3 C4, ADR-0076) — one registry, every surface.

The vendored chat client boots by asking `/api/endpoints` and `/api/models`; the desktop host
intercepts both at the `tempest://` protocol and answers with this route's output, so the
selector the user sees IS the router the engine spends through — one provider table, zero
drift.

Model lists come from three honest sources and nothing else:

- **Adopted metadata** — the registry's static lists, taken from upstream LibreChat's own
  `defaultModels` tables at the vendored commit (L27: refreshed at upstream merges, never
  invented here).
- **Local discovery** — local runners (Ollama, LM Studio, llama.cpp) are probed live at
  `{base_url}/models`, loopback and keyless, so the user sees the models actually installed
  on their machine. Offline, the probe fails silently in milliseconds and the runner simply
  lists no models — degradation, not error (L23).
- **Keyed discovery** — a remote provider with no static metadata is probed only when its key
  is present in the engine environment: the same user-sanctioned BYOK egress surface
  `verify_key` uses (L10, ADR-0024). No key → no request → the row renders and waits for one.

The catalog never fails because a provider is unreachable: discovery narrows to what is known,
and what is known is stated.
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import PurePosixPath

from fastapi import APIRouter

from tempest.inference import providers as registry
from tempest.inference.client import resolve_base_url
from tempest_api.schemas.providers import CatalogEndpoint, CatalogProvider, PlatformCatalog

router = APIRouter(tags=["providers"])

#: Loopback answers in single-digit milliseconds when the runner is up, and connection-refused
#: is instant when it is not; the ceiling only bites when a runner is wedged mid-start.
_LOCAL_PROBE_TIMEOUT_S = 0.8
#: A keyed remote probe is a real network round trip the user sanctioned by configuring the
#: key; still bounded so a slow provider cannot stall the catalog.
_REMOTE_PROBE_TIMEOUT_S = 4.0

#: `C:\models\x.gguf` and `C:/models/x.gguf` — a local runner on Windows names paths this way.
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _discover_models(provider: registry.Provider, env: dict[str, str]) -> list[str]:
    """`GET {base_url}/models`, OpenAI shape (`{"data": [{"id": ...}]}`) → ids, or [].

    Every failure arm — unreachable, non-JSON, unexpected shape — returns [] rather than
    raising: absence of discovery is a fact the catalog states by listing nothing, never a
    reason the whole model world fails to load.
    """
    base = resolve_base_url(provider, env).rstrip("/")
    request = urllib.request.Request(base + "/models", method="GET")
    key = env.get(provider.env_var, "") if provider.env_var else ""
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    timeout = _LOCAL_PROBE_TIMEOUT_S if provider.local else _REMOTE_PROBE_TIMEOUT_S
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    ids = [row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]
    return sorted(_named(ids) if provider.local else ids)


def _named(ids: list[str]) -> list[str]:
    """A local runner's model ids, with absolute FILE PATHS shown by their name.

    llama.cpp names a model by the path it was started with — measured against a real
    `llama-server` (b10612) serving Qwen3 0.6B: `data[0].id` was the full
    `/Users/<person>/Library/Application Support/…/Qwen3-0.6B-Q8_0.gguf`, and its only alias
    was that same path. Ollama (`qwen3:0.6b`) and LM Studio (`qwen/qwen3-0.6b`) return real
    names, so this is llama.cpp's shape alone — but llama.cpp is the runner Tempest itself
    starts, which makes it the one every user of the local-models feature meets.

    Left alone, the user's HOME DIRECTORY is the label in the model dropdown. It is also what
    lands in every conversation's stored `model` field, every export and every shared link. A
    path is user data (L9); a dropdown is not where it belongs.

    **Why rewriting the id is safe here, measured rather than assumed.** The id is what goes
    back on the next request, so a rename that the server refuses would break chat outright.
    Against the same real `llama-server`, `Qwen3-0.6B-Q8_0`, the full path, and an invented
    name were all accepted — it ignores the field while serving one model, which is exactly
    how Tempest starts it (`server_command` passes a single `--model`).

    Two rules keep it honest. Only an ABSOLUTE path is touched, so `qwen/qwen3-0.6b` and a
    relative `./x.gguf` survive intact — a rule reaching for slashes would rename half the
    models on the internet. And a name two rows would share is not used at all: two models
    under one label is a worse failure than an ugly one, because the picker would be offering
    a choice that cannot be made.
    """
    stems: dict[str, list[str]] = {}
    for model_id in ids:
        if not _is_absolute_path(model_id):
            continue
        stem = _stem(model_id)
        stems.setdefault(stem, []).append(model_id)
    unique = {paths[0]: stem for stem, paths in stems.items() if len(paths) == 1 and stem}
    return [unique.get(model_id, model_id) for model_id in ids]


def _is_absolute_path(model_id: str) -> bool:
    """POSIX absolute, or a Windows drive path — the two shapes a runner can hand back."""
    return model_id.startswith("/") or bool(_WINDOWS_PATH.match(model_id))


def _stem(model_id: str) -> str:
    """The file name without its extension, for a path in EITHER separator style.

    `PurePosixPath` alone was wrong here and the Windows test caught it: it does not treat
    `\\` as a separator, so `C:\\models\\Phi-4-mini.gguf` kept its whole directory in the
    "stem". Splitting on both is what a runner on either platform actually needs, and
    `PurePosixPath` is still what drops the extension.
    """
    tail = re.split(r"[\\/]", model_id)[-1]
    return PurePosixPath(tail).stem


def _models_for(provider: registry.Provider, env: dict[str, str]) -> list[str]:
    static = list(provider.models)
    if provider.local:
        # Locals carry no static metadata today; the concatenation keeps a future row that
        # does from silently masking its discovery.
        return static + _discover_models(provider, env)
    if not static and provider.env_var and env.get(provider.env_var):
        return _discover_models(provider, env)
    return static


@router.get("/v1/platform/catalog", operation_id="getPlatformCatalog")
async def get_platform_catalog() -> PlatformCatalog:
    env = dict(os.environ)
    endpoints: dict[str, CatalogEndpoint] = {}
    models: dict[str, list[str]] = {}
    provider_rows: list[CatalogProvider] = []
    for order, provider in enumerate(registry.PROVIDERS):
        builtin = provider.id == "anthropic"
        # The client renders the OBJECT KEY as the endpoint's display name for custom rows,
        # and resolves built-ins (anthropic) by their canonical key.
        endpoint_key = "anthropic" if builtin else provider.label
        endpoints[endpoint_key] = CatalogEndpoint(
            order=order,
            type=None if builtin else "custom",
            userProvide=provider.needs_key,
            modelDisplayLabel=provider.label,
            # iconURL stays None HERE: the badge route (/tempest-assets/) exists only on
            # the desktop host's protocol, and the host decorates each row as it bridges
            # the catalog. An engine-side URL would hand every other consumer a broken
            # <img> where the client's no-iconURL fallback used to render.
        )
        models[endpoint_key] = _models_for(provider, env)
        provider_rows.append(
            CatalogProvider(
                id=provider.id,
                endpoint_key=endpoint_key,
                label=provider.label,
                wire=provider.wire,
                key_env=provider.env_var,
                local=provider.local,
            )
        )
    # The AGENTS endpoint (PLAN-V3 C5, ADR-0075): the vendored builder, marketplace nav and
    # agent picker all mount on this key existing — `useListAgentsQuery` and
    # `useAvailableAgentToolsQuery` compute `enabled` from it, so without the row the whole
    # surface is invisible, not merely hidden. Capabilities name what the re-target serves
    # TODAY (the tool picker over the one boundary-D registry); run-control capabilities join
    # the list with the C5 items that make them true.
    endpoints["agents"] = CatalogEndpoint(
        order=len(registry.PROVIDERS),
        type=None,
        userProvide=False,
        modelDisplayLabel="Agents",
        capabilities=["tools"],
        disableBuilder=False,
    )
    models["agents"] = []
    return PlatformCatalog(endpoints=endpoints, models=models, providers=provider_rows)
