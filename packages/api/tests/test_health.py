import json
from pathlib import Path

from fastapi.testclient import TestClient

import tempest
from tempest.model import BUNDLE_SCHEMA_VERSION
from tempest_api.app import create_app


def test_health_reports_versions() -> None:
    client = TestClient(create_app())
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "engine_version": tempest.__version__,
        "schema_version": BUNDLE_SCHEMA_VERSION,
    }


def test_openapi_dump_is_deterministic(tmp_path: Path) -> None:
    from tempest_api.dev.dump_openapi import dump

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    dump(a)
    dump(b)
    assert a.read_bytes() == b.read_bytes()
    assert "/v1/health" in json.loads(a.read_text())["paths"]
