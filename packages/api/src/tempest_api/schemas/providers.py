"""The provider catalog (PLAN-V3 C4, ADR-0076) — the platform client's model world, shaped
exactly as its wire expects.

`endpoints` and `models` are LibreChat's own `/api/endpoints` + `/api/models` response shapes
(TEndpointsConfig / TModelsConfig), built here from the ONE registry (`tempest.inference.
providers`) so the chat surface's selector and the proof engine's router can never disagree
about what exists. `providers` carries the registry rows the Rust host needs to run the key
bridge — which endpoint key maps to which environment variable — and never a key value: keys
live in the OS keychain and only the host touches them (L9, L18).

Field names are camelCase where the vendored client reads camelCase: these two maps are wire
shapes owned by the adopted surface, not Tempest domain types.
"""

from pydantic import BaseModel


class CatalogEndpoint(BaseModel):
    """One `/api/endpoints` row, exactly the fields the vendored client reads."""

    order: int
    #: "custom" for every OpenAI-compatible row; None for the built-in anthropic endpoint
    #: (the client resolves built-ins by their key alone).
    type: str | None = None
    userProvide: bool
    userProvideURL: bool = False
    modelDisplayLabel: str
    #: Root-relative badge (/tempest-assets/providers/<id>.svg) — written by the DESKTOP
    #: HOST as it bridges the catalog, because only its protocol serves that route; the
    #: engine always emits None. Never a remote URL (L32). The client's UnknownIcon
    #: renders it verbatim as an <img src>; built-in rows ignore it.
    iconURL: str | None = None
    #: The `agents` endpoint row only (PLAN-V3 C5): which builder sub-sections the client
    #: may show. Declared per what the re-target actually serves — the honest list grows as
    #: run-control items land, and a capability named here that the runtime refuses would be
    #: the UI writing a check the engine bounces.
    capabilities: list[str] | None = None
    #: The `agents` endpoint row only: False is what mounts the no-code builder nav entry.
    disableBuilder: bool | None = None


class CatalogProvider(BaseModel):
    """One registry row, host-facing: enough for the key bridge, never a secret."""

    id: str
    #: The `/api/endpoints` object key this provider is served under — the client treats
    #: that key as the display name, and the key bridge maps it back to `key_env`.
    endpoint_key: str
    label: str
    wire: str
    #: Environment variable the key arrives in ("" for local runners).
    key_env: str
    local: bool


class PlatformCatalog(BaseModel):
    endpoints: dict[str, CatalogEndpoint]
    models: dict[str, list[str]]
    providers: list[CatalogProvider]
