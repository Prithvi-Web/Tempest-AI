"""Settings endpoints (HANDOFF-WORLD-CLASS §3.2): the stored preference document, plus the
one live "Test key" ping.

A damaged `settings.json` answers 200 with `problem` set and the DEFAULTS shown — the screen
is where the user repairs it, so it must still render (L8). Writing repairs the file: a PUT
always publishes a valid document.
"""

import asyncio

from fastapi import APIRouter

from tempest.cli.diagnose import default_bundle_name, write_diagnostic_bundle
from tempest.harness.llm import verify_key
from tempest.settings import (
    ENV_VARS,
    SETTINGS_SCHEMA_VERSION,
    Settings,
    SettingsError,
    effective_settings,
    save_settings,
    settings_path,
)
from tempest_api.bundlestore import bundle_store
from tempest_api.errors import ApiError
from tempest_api.localprove import data_dir
from tempest_api.schemas.enums import ErrorCode
from tempest_api.schemas.settings import (
    AiKeyTestResult,
    DiagnosticBundle,
    EnvOverride,
    SettingsIn,
    SettingsOut,
)

router = APIRouter(tags=["settings"])


def _rendered(settings: Settings, overrides: tuple[str, ...], problem: str | None) -> SettingsOut:
    return SettingsOut(
        version=SETTINGS_SCHEMA_VERSION,
        sync_server_url=settings.sync_server_url,
        sync_share_source=settings.sync_share_source,
        bundle_budget_bytes=settings.bundle_budget_bytes,
        telemetry_enabled=settings.telemetry_enabled,
        env_overrides=[EnvOverride(field=name, variable=ENV_VARS[name]) for name in overrides],
        data_dir=str(data_dir()),
        store_bytes=bundle_store().total_bytes(),
        problem=problem,
    )


@router.get("/v1/settings", operation_id="getSettings")
async def get_settings() -> SettingsOut:
    try:
        settings, overrides = effective_settings()
    except SettingsError as exc:
        return _rendered(Settings(), (), f"{exc} (showing defaults until this is fixed)")
    return _rendered(settings, overrides, None)


@router.put("/v1/settings", operation_id="updateSettings")
async def update_settings(body: SettingsIn) -> SettingsOut:
    """Replace the stored document. Environment overrides still outrank what is saved — the
    response says which fields they are, so the screen never claims a change it cannot make."""
    try:
        save_settings(
            Settings(
                sync_server_url=body.sync_server_url,
                sync_share_source=body.sync_share_source,
                bundle_budget_bytes=body.bundle_budget_bytes,
                telemetry_enabled=body.telemetry_enabled,
            )
        )
    except SettingsError as exc:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    except OSError as exc:
        raise ApiError(
            500,
            ErrorCode.INTERNAL,
            f"settings could not be written to {settings_path()} — {exc}",
        ) from exc
    settings, overrides = effective_settings()
    return _rendered(settings, overrides, None)


@router.post("/v1/settings/ai-key/test", operation_id="testAiKey")
async def test_ai_key() -> AiKeyTestResult:
    """One live request to the configured model with the key the host injected at spawn.
    Blocking SDK call, so it runs off the event loop; nothing about it is persisted."""
    result = await asyncio.to_thread(verify_key)
    return AiKeyTestResult(ok=result.ok, detail=result.detail, model=result.model)


@router.post("/v1/diagnostics", operation_id="exportDiagnostics")
async def export_diagnostics() -> DiagnosticBundle:
    """Write a redacted diagnostic archive into `<data dir>/diagnostics/` and describe it.

    Nothing is transmitted: the file is local, its manifest is returned so the screen can
    show exactly what it contains, and sharing stays the user's deliberate act (L9).
    """
    target = data_dir() / "diagnostics" / default_bundle_name()
    try:
        manifest = await asyncio.to_thread(write_diagnostic_bundle, target)
    except OSError as exc:
        raise ApiError(
            500, ErrorCode.INTERNAL, f"the diagnostic bundle could not be written — {exc}"
        ) from exc
    return DiagnosticBundle(filename=target.name, bytes=target.stat().st_size, manifest=manifest)
