"""`settings.json` — the user's own preferences, stored beside the data they apply to.

The file lives in the DATA DIR, so it belongs to one store: the desktop app keeps its own (its
per-app data dir), a bare CLI run uses `~/.tempest`, and pointing either at the other's
`TEMPEST_DATA_DIR` makes them share one — the same rule the bundle store, logs, and telemetry
counters already follow. What is shared unconditionally is the LAW, the one `tempest.toml`
also follows: **environment variable > settings.json > built-in default**. A `TEMPEST_*`
export in a shell, a CI job, or a script therefore stays authoritative, and the app can never
quietly disagree with the environment it runs in.
Because an invisible override would make the Settings screen lie, `effective_settings()`
returns the names of every field the environment is currently forcing, and the UI says so.

Versioned like the local store (ADR-0016): a file written by a newer Tempest is refused, never
silently downgraded. A corrupt, non-object, or unknown-keyed document is refused too — these
are recorded user intentions (privacy choices among them), and silently resetting them would
be a lie. The *engine* read paths (`load_effective_or_defaults`) swallow that error and fall
back to defaults instead (the environment still applies on top), so a damaged file can never
make proving impossible (L8) nor silently switch off an opted-in export; only the Settings
surface reports it, where the user can act on it.

The AI key is deliberately absent: it lives in the OS keychain and nowhere else (L9).
"""

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

__all__ = [
    "ENV_VARS",
    "MAX_BUNDLE_BUDGET_BYTES",
    "SETTINGS_FILENAME",
    "SETTINGS_SCHEMA_VERSION",
    "Settings",
    "SettingsError",
    "effective_settings",
    "load_effective_or_defaults",
    "load_settings",
    "save_settings",
    "settings_path",
]

SETTINGS_FILENAME = "settings.json"
SETTINGS_SCHEMA_VERSION = 1

# The largest budget the tri-boundary types can carry (the generated Rust/TS integer is
# 32-bit — specta forbids BigInt-style types across Boundary B). 2 GiB of evidence is far
# past any real store; the ceiling is stated out loud rather than silently truncating.
MAX_BUNDLE_BUDGET_BYTES = 2_147_483_647

# field name → the environment variable that outranks it. Public so the Settings surface
# can NAME the variable to the user instead of hardcoding a second copy of this map.
ENV_VARS: dict[str, str] = {
    "sync_server_url": "TEMPEST_SYNC_SERVER_URL",
    "sync_share_source": "TEMPEST_SYNC_SHARE_SOURCE",
    "bundle_budget_bytes": "TEMPEST_BUNDLE_BUDGET_BYTES",
    "telemetry_enabled": "TEMPEST_TELEMETRY",
}


class SettingsError(Exception):
    """settings.json exists but is unusable, or a value is invalid. The message states the fix."""


@dataclass(frozen=True)
class Settings:
    """Every user-facing preference, defaulting to the most private posture."""

    sync_server_url: str | None = None
    sync_share_source: bool = False
    bundle_budget_bytes: int = 0  # 0 = unlimited
    telemetry_enabled: bool = False


def _data_dir() -> Path:
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest")))


def settings_path() -> Path:
    return _data_dir() / SETTINGS_FILENAME


def _vocabulary() -> str:
    return ", ".join(sorted(ENV_VARS))


def _normalized_url(value: str | None) -> str | None:
    """Blank means unset; anything stored must be a URL httpx can actually push to."""
    if value is None:
        return None
    trimmed = value.strip().rstrip("/")
    if not trimmed:
        return None
    if not trimmed.startswith(("http://", "https://")):
        raise SettingsError(f"sync server URL must start with http:// or https:// — got {value!r}")
    return trimmed


def _validated(settings: Settings) -> Settings:
    if not 0 <= settings.bundle_budget_bytes <= MAX_BUNDLE_BUDGET_BYTES:
        raise SettingsError(
            f"bundle budget must be between 0 (unlimited) and {MAX_BUNDLE_BUDGET_BYTES} "
            f"bytes (2 GiB) — got {settings.bundle_budget_bytes}"
        )
    return replace(settings, sync_server_url=_normalized_url(settings.sync_server_url))


def load_settings() -> Settings:
    """Read settings.json. Absent file → defaults; anything unusable → SettingsError."""
    path = settings_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except OSError as exc:
        raise SettingsError(f"{path}: could not be read — {exc}") from exc
    try:
        document: Any = json.loads(raw_text)
    except ValueError as exc:
        raise SettingsError(
            f"{path}: not valid JSON — {exc}. Fix it by hand, or delete the file to return "
            f"to defaults."
        ) from exc
    if not isinstance(document, dict):
        raise SettingsError(f"{path}: must contain a JSON object, got {type(document).__name__}")

    version = document.pop("version", SETTINGS_SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise SettingsError(f"{path}: `version` must be an integer, got {version!r}")
    if version > SETTINGS_SCHEMA_VERSION:
        raise SettingsError(
            f"{path}: written by a newer version of Tempest (settings schema v{version}; "
            f"this build understands v{SETTINGS_SCHEMA_VERSION}). Update Tempest, or move "
            f"the file aside to start from defaults."
        )

    unknown = sorted(key for key in document if key not in ENV_VARS)
    if unknown:
        raise SettingsError(
            f"{path}: unknown setting(s): {', '.join(unknown)}. Valid settings: {_vocabulary()}."
        )

    defaults = Settings()
    values: dict[str, Any] = asdict(defaults)
    for key, value in document.items():
        expected = type(values[key]) if values[key] is not None else str
        if key == "sync_server_url":
            if value is not None and not isinstance(value, str):
                raise SettingsError(f"{path}: `sync_server_url` must be a string or null")
        elif isinstance(value, bool) is not (expected is bool) or not isinstance(value, expected):
            raise SettingsError(f"{path}: `{key}` must be {expected.__name__}, got {value!r}")
        values[key] = value
    return _validated(Settings(**values))


def save_settings(settings: Settings) -> None:
    """Validate, then publish atomically — a torn write must never be observable."""
    checked = _validated(settings)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SETTINGS_SCHEMA_VERSION, **asdict(checked)}
    # A per-process temp name: two writers must not publish each other's half-written state.
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _env_override(field: str, current: object) -> object | None:
    """The environment's value for one field, or None when it is not forcing this field."""
    raw = os.environ.get(ENV_VARS[field])
    if raw is None:
        return None
    if field == "sync_server_url":
        return _normalized_url(raw)
    if field == "bundle_budget_bytes":
        try:
            parsed = int(raw)
        except ValueError:
            return None  # junk in the environment must never break a prove
        return parsed if 0 <= parsed <= MAX_BUNDLE_BUDGET_BYTES else None
    return raw == "1"


def _with_env(stored: Settings) -> tuple[Settings, tuple[str, ...]]:
    values: dict[str, Any] = asdict(stored)
    overridden: list[str] = []
    for field in ENV_VARS:
        forced = _env_override(field, values[field])
        if forced is None:
            continue
        values[field] = forced
        overridden.append(field)
    return Settings(**values), tuple(overridden)


def effective_settings() -> tuple[Settings, tuple[str, ...]]:
    """(settings with the environment applied, names of the fields the environment forces).

    Raises SettingsError when the stored file is unusable — the Settings surface WANTS that,
    because reporting the problem is the only way the user can repair it.
    """
    return _with_env(load_settings())


def load_effective_or_defaults() -> Settings:
    """The engine's read path: never raises. A damaged or unreadable file degrades to the
    DEFAULTS, so a prove still runs (L8) — but the environment is still applied on top, so an
    explicit `TEMPEST_*` export keeps working even when settings.json is broken (it would be
    its own kind of lie for a corrupt file to silently disable an opted-in setting)."""
    try:
        stored = load_settings()
    except SettingsError:
        stored = Settings()
    return _with_env(stored)[0]
