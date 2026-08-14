"""Bundle-integrity enforcement at ingestion (400, stable code, atomically nothing written)
and the divergence-evidence rule as a real database NOT NULL constraint — BUNDLE_SCHEMA.md
"mirrored as DB constraints in Phase 4"."""

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from tempest.model import DivergenceClass, Severity
from tempest_api.db import Base
from tempest_api.db.models import Divergence

Mutator = Callable[[Any], None]


def _mutated_zip(
    data: bytes,
    *,
    targets_mutator: Mutator | None = None,
    manifest_mutator: Mutator | None = None,
) -> bytes:
    """Hand-corrupt a real writer-produced zip — the writer itself refuses to produce these."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if targets_mutator is not None:
        targets = json.loads(entries["targets.json"])
        targets_mutator(targets)
        entries["targets.json"] = json.dumps(targets).encode()
    if manifest_mutator is not None:
        manifest = json.loads(entries["manifest.json"])
        manifest_mutator(manifest)
        entries["manifest.json"] = json.dumps(manifest).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, blob in entries.items():
            archive.writestr(name, blob)
    return buffer.getvalue()


def _assert_rejected(resp: Any, code: str) -> None:
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == code


class TestCorruptedBundleRejection:
    def test_missing_minimized_input_is_rejected_and_nothing_written(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)

        def strip_minimized(targets: Any) -> None:
            targets[0]["divergences"][0]["minimized_args"] = None
            targets[0]["divergences"][0]["minimized_kwargs"] = None

        resp = api.upload_zip(
            run_id, _mutated_zip(api.zip_bytes(bundle), targets_mutator=strip_minimized)
        )
        _assert_rejected(resp, "BUNDLE_INVALID")

        run = api.get_json(f"/v1/runs/{run_id}")
        assert run["status"] == "PENDING"  # atomically nothing written
        assert run["verdict"] is None
        assert run["targets"] == []
        # …and the untouched original still ingests into this same run afterwards.
        assert api.upload_zip(run_id, api.zip_bytes(bundle)).status_code == 200

    def test_missing_repro_script_reference_is_rejected(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)

        def strip_repro(targets: Any) -> None:
            targets[0]["divergences"][0]["repro_filename"] = None

        resp = api.upload_zip(
            run_id, _mutated_zip(api.zip_bytes(bundle), targets_mutator=strip_repro)
        )
        _assert_rejected(resp, "BUNDLE_INVALID")

    def test_dangling_repro_reference_is_rejected(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)

        def dangle(targets: Any) -> None:
            targets[0]["divergences"][0]["repro_filename"] = "ghost.py"

        resp = api.upload_zip(run_id, _mutated_zip(api.zip_bytes(bundle), targets_mutator=dangle))
        _assert_rejected(resp, "BUNDLE_INVALID")

    def test_bogus_enum_value_is_rejected(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)

        def bogus_verdict(targets: Any) -> None:
            targets[0]["verdict"] = "BOGUS"

        resp = api.upload_zip(
            run_id, _mutated_zip(api.zip_bytes(bundle), targets_mutator=bogus_verdict)
        )
        _assert_rejected(resp, "BUNDLE_INVALID")

    def test_newer_schema_version_is_rejected(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.create_run_for(bundle)

        def bump(manifest: Any) -> None:
            manifest["schema_version"] = 99

        resp = api.upload_zip(run_id, _mutated_zip(api.zip_bytes(bundle), manifest_mutator=bump))
        _assert_rejected(resp, "BUNDLE_SCHEMA_UNSUPPORTED")

    def test_non_zip_upload_is_rejected(self, api) -> None:
        run_id = api.create_run_id(repo="r", base_sha="a" * 40, head_sha="b" * 40)
        _assert_rejected(api.upload_zip(run_id, b"definitely not a zip"), "BUNDLE_INVALID")

    def test_manifest_not_matching_the_run_is_rejected(self, api) -> None:
        bundle = api.make_bundle()  # head_sha = "b" * 40
        run_id = api.create_run_id(repo="pyfix", base_sha="a" * 40, head_sha="c" * 40)
        resp = api.upload_zip(run_id, api.zip_bytes(bundle))
        _assert_rejected(resp, "BUNDLE_MISMATCH")
        assert "head_sha" in resp.json()["error"]["details"]["mismatches"]


class TestUploadStateRules:
    def test_second_upload_conflicts(self, api) -> None:
        bundle = api.make_bundle()
        run_id = api.ingest(bundle)
        resp = api.upload_zip(run_id, api.zip_bytes(bundle))
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "RUN_NOT_PENDING"

    def test_upload_to_missing_run_is_404(self, api) -> None:
        resp = api.upload_zip(999_999, api.zip_bytes(api.make_bundle()))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestDatabaseLevelConstraints:
    def test_divergence_evidence_columns_are_not_null_in_the_ddl(self, tmp_path: Path) -> None:
        """Insert below the application layer: the schema itself must refuse a divergence
        without minimized input or repro script."""
        engine = sa.create_engine(f"sqlite:///{tmp_path}/constraints.db")
        Base.metadata.create_all(engine)
        complete_row: dict[str, Any] = {
            "target_id": 1,
            "position": 0,
            "divergence_class": DivergenceClass.RETURN_VALUE,
            "severity": Severity.NORMAL,
            "detail": "return values differ",
            "args_literal": "(-7,)",
            "kwargs_literal": "{}",
            "minimized_args": "(0,)",
            "minimized_kwargs": "{}",
            "shrink_path": ["args[0]: -7→0"],
            "base_summary": "returned 0",
            "head_summary": "returned 1",
            "repro_filename": "clamp_0.py",
            "repro_script": "print('repro')\n",
        }
        for evidence_column in (
            "minimized_args",
            "minimized_kwargs",
            "repro_filename",
            "repro_script",
        ):
            values = complete_row | {evidence_column: None}
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(sa.insert(Divergence.__table__).values(**values))
        with engine.begin() as conn:  # sanity: the fully-evidenced row is accepted
            conn.execute(sa.insert(Divergence.__table__).values(**complete_row))
        engine.dispose()
