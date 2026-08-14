"""Phase 7: bundle schema versioning discipline — readers refuse newer schemas actionably,
and the current version round-trips (the v1→v2 migration path slots in here when v2 exists)."""

import json
from pathlib import Path

import pytest

from tempest.bundle.bundle import BundleIntegrityError, read_bundle, write_bundle
from tempest.model import BUNDLE_SCHEMA_VERSION

from .test_bundle import _bundle


class TestSchemaMigration:
    def test_current_version_round_trips(self, tmp_path: Path) -> None:
        write_bundle(_bundle(), tmp_path / "run")
        assert read_bundle(tmp_path / "run").manifest.schema_version == BUNDLE_SCHEMA_VERSION

    def test_newer_schema_is_refused_with_upgrade_guidance(self, tmp_path: Path) -> None:
        write_bundle(_bundle(), tmp_path / "run")
        manifest_path = tmp_path / "run" / "manifest.json"
        raw = json.loads(manifest_path.read_text())
        raw["schema_version"] = BUNDLE_SCHEMA_VERSION + 1
        manifest_path.write_text(json.dumps(raw))
        with pytest.raises(BundleIntegrityError) as exc:
            read_bundle(tmp_path / "run")
        assert "upgrade tempest" in str(exc.value)

    def test_schema_version_is_an_integer_from_day_one(self, tmp_path: Path) -> None:
        write_bundle(_bundle(), tmp_path / "run")
        raw = json.loads((tmp_path / "run" / "manifest.json").read_text())
        assert isinstance(raw["schema_version"], int)
