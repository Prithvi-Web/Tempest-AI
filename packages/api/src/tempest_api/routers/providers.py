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
import urllib.error
import urllib.request

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
    return sorted(ids)


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
    return PlatformCatalog(endpoints=endpoints, models=models, providers=provider_rows)
