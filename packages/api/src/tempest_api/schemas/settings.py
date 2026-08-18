"""Settings shapes (HANDOFF-WORLD-CLASS §3.2) — the desktop Settings screen's contract.

`SettingsOut` is deliberately more than the stored document: it also carries the facts the
screen must state to be honest — which fields the ENVIRONMENT is currently forcing (so a
toggle can never silently disagree with reality), where the data lives, how much the bundle
store is actually using, and — when `settings.json` is damaged — the exact problem, with the
shown values being the defaults then in force.

The AI key is absent by construction: it lives in the OS keychain, and only the Rust host
ever touches it (L9).
"""

from pydantic import BaseModel, Field


class EnvOverride(BaseModel):
    """One setting the process environment is currently forcing. Named, never hidden: the
    screen disables that control and says which variable to unset."""

    field: str
    variable: str


class SettingsIn(BaseModel):
    """A full replacement of the stored document — the screen always sends every field, so
    "unset" is expressible and partial-update ambiguity cannot exist."""

    sync_server_url: str | None = Field(default=None, max_length=2000)
    sync_share_source: bool = False
    # Deliberately unconstrained here: `tempest.settings` is the ONE validator (it also
    # guards the CLI and the file), and its message is the one the user reads. The
    # bound is the 2 GiB cap the boundary types can carry — see MAX_BUNDLE_BUDGET_BYTES.
    bundle_budget_bytes: int = 0
    telemetry_enabled: bool = False


class SettingsOut(SettingsIn):
    version: int
    env_overrides: list[EnvOverride]
    data_dir: str
    store_bytes: int
    problem: str | None = None


class AiKeyTestResult(BaseModel):
    """One live ping's honest outcome (never stored, never cached)."""

    ok: bool
    detail: str
    model: str | None = None


class DiagnosticBundle(BaseModel):
    """A written, redacted diagnostic archive. `filename` is a bare name inside the data
    dir's `diagnostics/` folder — the host reveals it by joining, never by trusting a path."""

    filename: str
    bytes: int
    manifest: str
