"""User settings (`settings.json` in the data dir) — the desktop Settings surface's store.

The file lives in the data dir, so it belongs to one store (the app has its own; a bare CLI
run uses `~/.tempest`; a shared TEMPEST_DATA_DIR makes them one). The LAW is what is shared: an
environment variable always OUTRANKS the file (CI, scripts, and `TEMPEST_*` exports must stay
authoritative — precedence mirrors tempest.toml's "flag > file > default"). Because an
invisible override would make the app lie about its own state, every overridden field is
NAMED in the loaded result so the UI can say so out loud.

Versioned like the local store (ADR-0016): a file written by a newer Tempest is refused, never
silently downgraded. A corrupt or unknown-keyed file is an explicit error too — settings are
recorded user intent (privacy choices among them), so silently resetting them would be a lie.
"""

import json
import os
from pathlib import Path

import pytest

from tempest.settings import (
    MAX_BUNDLE_BUDGET_BYTES,
    SETTINGS_SCHEMA_VERSION,
    Settings,
    SettingsError,
    effective_settings,
    load_settings,
    save_settings,
    settings_path,
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never the developer's real ~/.tempest — settings are read per call from this dir."""
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
    for var in (
        "TEMPEST_SYNC_SHARE_SOURCE",
        "TEMPEST_BUNDLE_BUDGET_BYTES",
        "TEMPEST_TELEMETRY",
        "TEMPEST_SYNC_SERVER_URL",
    ):
        monkeypatch.delenv(var, raising=False)


class TestDefaults:
    def test_absent_file_is_all_defaults_and_privacy_off(self, tmp_path: Path) -> None:
        assert not settings_path().exists()
        loaded = load_settings()
        assert loaded == Settings()
        # The defaults ARE the privacy posture: nothing shared, nothing counted, no server.
        assert loaded.sync_share_source is False
        assert loaded.telemetry_enabled is False
        assert loaded.sync_server_url is None
        assert loaded.bundle_budget_bytes == 0  # 0 = unlimited

    def test_settings_path_follows_the_data_dir(self, tmp_path: Path) -> None:
        assert settings_path() == tmp_path / "settings.json"


class TestRoundTrip:
    def test_saved_settings_load_back_identically(self) -> None:
        wanted = Settings(
            sync_server_url="https://tempest.example.com",
            sync_share_source=True,
            bundle_budget_bytes=5_000_000,
            telemetry_enabled=True,
        )
        save_settings(wanted)
        assert load_settings() == wanted

    def test_the_file_records_its_schema_version(self) -> None:
        save_settings(Settings())
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
        assert payload["version"] == SETTINGS_SCHEMA_VERSION

    def test_the_write_is_atomic_and_leaves_no_temp_files(self, tmp_path: Path) -> None:
        save_settings(Settings(telemetry_enabled=True))
        assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]

    def test_saving_creates_a_missing_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nested = tmp_path / "does" / "not" / "exist"
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(nested))
        save_settings(Settings())
        assert load_settings() == Settings()


class TestRefusal:
    def test_a_newer_schema_version_is_refused_with_the_fix(self) -> None:
        settings_path().write_text(
            json.dumps({"version": SETTINGS_SCHEMA_VERSION + 1}), encoding="utf-8"
        )
        with pytest.raises(SettingsError) as err:
            load_settings()
        message = str(err.value)
        assert "newer version of Tempest" in message
        assert str(SETTINGS_SCHEMA_VERSION) in message

    def test_corrupt_json_is_an_error_not_a_silent_reset(self) -> None:
        settings_path().write_text("{not json", encoding="utf-8")
        with pytest.raises(SettingsError) as err:
            load_settings()
        assert str(settings_path()) in str(err.value)

    def test_a_non_object_document_is_refused(self) -> None:
        settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(SettingsError):
            load_settings()

    def test_unknown_keys_name_every_offender_and_the_vocabulary(self) -> None:
        settings_path().write_text(
            json.dumps({"version": 1, "telemetry": True, "sync_url": "x"}), encoding="utf-8"
        )
        with pytest.raises(SettingsError) as err:
            load_settings()
        message = str(err.value)
        assert "telemetry" in message and "sync_url" in message
        assert "telemetry_enabled" in message  # the valid vocabulary is spelled out

    def test_a_non_integer_version_names_the_field(self) -> None:
        settings_path().write_text(
            json.dumps({"version": "one", "telemetry_enabled": True}), encoding="utf-8"
        )
        with pytest.raises(SettingsError) as err:
            load_settings()
        assert "`version` must be an integer" in str(err.value)

    def test_a_non_string_sync_url_names_the_field(self) -> None:
        settings_path().write_text(
            json.dumps({"version": 1, "sync_server_url": 7}), encoding="utf-8"
        )
        with pytest.raises(SettingsError) as err:
            load_settings()
        assert "`sync_server_url` must be a string or null" in str(err.value)

    def test_an_explicit_null_sync_url_is_accepted(self) -> None:
        settings_path().write_text(
            json.dumps({"version": 1, "sync_server_url": None}), encoding="utf-8"
        )
        assert load_settings().sync_server_url is None

    def test_a_wrongly_typed_field_names_the_field(self) -> None:
        settings_path().write_text(
            json.dumps({"version": 1, "telemetry_enabled": "yes"}), encoding="utf-8"
        )
        with pytest.raises(SettingsError) as err:
            load_settings()
        assert "telemetry_enabled" in str(err.value)

    def test_an_unreadable_file_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_settings(Settings())
        path = settings_path()
        path.chmod(0o000)
        try:
            with pytest.raises(SettingsError):
                load_settings()
        finally:
            path.chmod(0o600)


class TestValidation:
    def test_a_negative_budget_is_refused(self) -> None:
        with pytest.raises(SettingsError):
            save_settings(Settings(bundle_budget_bytes=-1))

    def test_a_budget_past_the_boundary_ceiling_is_refused_out_loud(self) -> None:
        with pytest.raises(SettingsError) as err:
            save_settings(Settings(bundle_budget_bytes=MAX_BUNDLE_BUDGET_BYTES + 1))
        assert "2 GiB" in str(err.value)

    def test_the_ceiling_itself_is_allowed(self) -> None:
        save_settings(Settings(bundle_budget_bytes=MAX_BUNDLE_BUDGET_BYTES))
        assert load_settings().bundle_budget_bytes == MAX_BUNDLE_BUDGET_BYTES

    def test_a_non_http_sync_url_is_refused(self) -> None:
        with pytest.raises(SettingsError) as err:
            save_settings(Settings(sync_server_url="ftp://example.com"))
        assert "http://" in str(err.value)

    def test_an_empty_sync_url_means_unset(self) -> None:
        save_settings(Settings(sync_server_url="   "))
        assert load_settings().sync_server_url is None

    def test_a_stored_url_keeps_no_trailing_slash(self) -> None:
        save_settings(Settings(sync_server_url="https://example.com/"))
        assert load_settings().sync_server_url == "https://example.com"


class TestEnvironmentOutranksTheFile:
    def test_env_wins_and_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_settings(Settings(telemetry_enabled=False, sync_share_source=False))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        resolved, overridden = effective_settings()
        assert resolved.telemetry_enabled is True
        assert overridden == ("telemetry_enabled",)

    def test_every_field_is_overridable_and_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")
        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "123")
        monkeypatch.setenv("TEMPEST_SYNC_SERVER_URL", "https://env.example.com")
        resolved, overridden = effective_settings()
        assert resolved == Settings(
            sync_server_url="https://env.example.com",
            sync_share_source=True,
            bundle_budget_bytes=123,
            telemetry_enabled=True,
        )
        assert set(overridden) == {
            "sync_server_url",
            "sync_share_source",
            "bundle_budget_bytes",
            "telemetry_enabled",
        }

    def test_an_env_var_set_to_zero_still_outranks_a_true_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_settings(Settings(telemetry_enabled=True))
        monkeypatch.setenv("TEMPEST_TELEMETRY", "0")
        resolved, overridden = effective_settings()
        assert resolved.telemetry_enabled is False
        assert overridden == ("telemetry_enabled",)

    def test_a_junk_budget_override_is_ignored_rather_than_crashing_a_prove(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_settings(Settings(bundle_budget_bytes=7))
        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "not-a-number")
        resolved, overridden = effective_settings()
        assert resolved.bundle_budget_bytes == 7
        assert overridden == ()

    def test_an_out_of_range_budget_override_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_settings(Settings(bundle_budget_bytes=7))
        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", str(MAX_BUNDLE_BUDGET_BYTES + 1))
        resolved, overridden = effective_settings()
        assert resolved.bundle_budget_bytes == 7
        assert overridden == ()

    def test_no_env_means_no_overrides(self) -> None:
        save_settings(Settings(telemetry_enabled=True))
        resolved, overridden = effective_settings()
        assert resolved.telemetry_enabled is True
        assert overridden == ()


class TestConsumersReadTheFile:
    """The point of the file: the existing surfaces obey it with no env var in sight."""

    def test_telemetry_opt_in_comes_from_settings(self) -> None:
        from tempest.telemetry import telemetry_enabled

        assert telemetry_enabled() is False
        save_settings(Settings(telemetry_enabled=True))
        assert telemetry_enabled() is True

    def test_source_sharing_comes_from_settings(self) -> None:
        from tempest_api.syncstrip import source_sharing_enabled

        assert source_sharing_enabled() is False
        save_settings(Settings(sync_share_source=True))
        assert source_sharing_enabled() is True

    def test_bundle_budget_comes_from_settings(self) -> None:
        from tempest_api.bundlestore import bundle_store

        assert bundle_store().budget_bytes is None
        save_settings(Settings(bundle_budget_bytes=4096))
        assert bundle_store().budget_bytes == 4096

    def test_an_environment_opt_in_survives_a_broken_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt file must not silently switch OFF something the environment turned on."""
        from tempest.telemetry import telemetry_enabled

        settings_path().write_text("{corrupt", encoding="utf-8")
        monkeypatch.setenv("TEMPEST_TELEMETRY", "1")
        assert telemetry_enabled() is True

    def test_a_broken_settings_file_never_breaks_a_prove(self) -> None:
        """Engine read paths degrade to defaults; only the Settings SURFACE reports the error
        (a corrupt file must not make proving impossible — L8)."""
        from tempest.telemetry import telemetry_enabled

        settings_path().write_text("{corrupt", encoding="utf-8")
        assert telemetry_enabled() is False
        assert os.environ.get("TEMPEST_TELEMETRY") is None
