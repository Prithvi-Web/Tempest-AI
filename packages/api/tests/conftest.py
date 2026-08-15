"""Shared fixtures: the real ASGI app against a real temp aiosqlite database per test.

No mocked layers anywhere (Law L4): every test speaks HTTP to the app, which speaks SQL to a
file-backed database. Bundle builders mirror the engine's own test helpers
(packages/engine/tests/unit/test_bundle.py) so both sides of the producer/renderer contract are
exercised with the same shapes.
"""

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tempest.bundle.bundle import (
    DivergenceRecord,
    RunBundle,
    RunManifest,
    TargetRecord,
    run_verdict,
    write_bundle,
)
from tempest.model import (
    BUNDLE_SCHEMA_VERSION,
    DivergenceClass,
    Lang,
    ReasonCode,
    Severity,
    TargetClassification,
    Verdict,
)
from tempest_api.app import create_app

# The battery/thermal pause (L11) must never stall the suite on an unplugged laptop; pause
# tests force the condition explicitly via TEMPEST_FORCE_POWER_PAUSE, which outranks this.
# Env here is consumed at runtime (fixtures and subprocess spawns), never at import time.
os.environ.setdefault("TEMPEST_NO_POWER_PAUSE", "1")

# Subprocess coverage (100% gate): children like the spawned sidecar server collect too,
# via scripts/covstart/sitecustomize.py on PYTHONPATH + COVERAGE_PROCESS_START.
_REPO = Path(__file__).resolve().parents[3]
os.environ.setdefault("COVERAGE_PROCESS_START", str(_REPO / "pyproject.toml"))
_COVSTART = str(_REPO / "scripts" / "covstart")
if _COVSTART not in os.environ.get("PYTHONPATH", ""):
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (_COVSTART, os.environ.get("PYTHONPATH", "")) if p
    )


def make_divergence(index: int = 0) -> DivergenceRecord:
    return DivergenceRecord(
        divergence_class=DivergenceClass.RETURN_VALUE,
        severity=Severity.NORMAL,
        detail=f"return values differ (#{index})",
        args_literal="(-7,)",
        kwargs_literal="{}",
        minimized_args="(0,)",
        minimized_kwargs="{}",
        shrink_path=("args[0]: -7→0",),
        base_summary="returned 0",
        head_summary="returned 1",
        repro_filename=f"clamp_{index}.py",
    )


def make_target(
    divergences: tuple[DivergenceRecord, ...], *, module: str = "m", qualname: str = "clamp"
) -> TargetRecord:
    return TargetRecord(
        file_path=f"{module}.py",
        module=module,
        qualname=qualname,
        lang=Lang.PYTHON,
        classification=TargetClassification.PURE_CANDIDATE,
        verdict=Verdict.DIVERGENT if divergences else Verdict.EQUIVALENT_UNDER_BUDGET,
        reason_code=None,
        reason_detail=None,
        inputs_run=42,
        equivalent_inputs=40,
        unprovable_inputs=0,
        changed_line_coverage=1.0,
        divergences=divergences,
    )


def make_unproven_target() -> TargetRecord:
    return TargetRecord(
        file_path="n.py",
        module="n",
        qualname="closure.inner",
        lang=Lang.PYTHON,
        classification=TargetClassification.UNREACHABLE,
        verdict=Verdict.UNPROVEN,
        reason_code=ReasonCode.TARGET_UNREACHABLE,
        reason_detail="`inner` is a closure — lift it to module scope to make it provable",
        inputs_run=0,
        equivalent_inputs=0,
        unprovable_inputs=0,
        changed_line_coverage=0.0,
        divergences=(),
    )


def make_bundle(
    targets: tuple[TargetRecord, ...] | None = None,
    repro_scripts: dict[str, str] | None = None,
    *,
    repo: str = "pyfix",
    base_sha: str = "a" * 40,
    head_sha: str = "b" * 40,
) -> RunBundle:
    if targets is None:
        targets = (make_target((make_divergence(0),)), make_unproven_target())
    if repro_scripts is None:
        repro_scripts = {
            d.repro_filename: f"#!/usr/bin/env python3\nprint('repro {d.repro_filename}')\n"
            for t in targets
            for d in t.divergences
            if d.repro_filename is not None
        }
    return RunBundle(
        manifest=RunManifest(
            schema_version=BUNDLE_SCHEMA_VERSION,
            engine_version="0.1.0",
            repo=repo,
            base_sha=base_sha,
            head_sha=head_sha,
            created_at="2026-08-13T00:00:00Z",
            verdict=run_verdict(targets),
            base_deps="no-lockfile",
            head_deps="no-lockfile",
            budget_max_inputs=300,
        ),
        targets=targets,
        repro_scripts=repro_scripts,
    )


def zip_bytes(bundle: RunBundle) -> bytes:
    """Write the bundle with the engine's own writer and return the .tempest.zip bytes."""
    with tempfile.TemporaryDirectory(prefix="tempest-test-bundle-") as tmp:
        return write_bundle(bundle, Path(tmp) / "run").read_bytes()


@dataclass
class ApiHarness:
    client: TestClient
    db_path: Path

    # Builders re-exposed on the harness: test modules cannot import from conftest under
    # --import-mode=importlib, so the fixture is the single access path.
    make_divergence = staticmethod(make_divergence)
    make_target = staticmethod(make_target)
    make_unproven_target = staticmethod(make_unproven_target)
    make_bundle = staticmethod(make_bundle)
    zip_bytes = staticmethod(zip_bytes)

    def create_run(
        self,
        *,
        repo: str,
        base_sha: str,
        head_sha: str,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else {}
        return self.client.post(
            "/v1/runs",
            json={"repo": repo, "base_sha": base_sha, "head_sha": head_sha},
            headers=headers,
        )

    def create_run_id(
        self, *, repo: str, base_sha: str, head_sha: str, idempotency_key: str | None = None
    ) -> int:
        resp = self.create_run(
            repo=repo, base_sha=base_sha, head_sha=head_sha, idempotency_key=idempotency_key
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]
        assert isinstance(run_id, int)
        return run_id

    def create_run_for(self, bundle: RunBundle) -> int:
        m = bundle.manifest
        return self.create_run_id(repo=m.repo, base_sha=m.base_sha, head_sha=m.head_sha)

    def upload_zip(self, run_id: int, data: bytes) -> httpx.Response:
        return self.client.post(
            f"/v1/runs/{run_id}/bundle",
            files={"file": ("run.tempest.zip", data, "application/zip")},
        )

    def ingest(self, bundle: RunBundle) -> int:
        """POST the run, upload its zip, and return the run id — asserting both succeeded."""
        run_id = self.create_run_for(bundle)
        resp = self.upload_zip(run_id, zip_bytes(bundle))
        assert resp.status_code == 200, resp.text
        return run_id

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self.client.get(path, params=params)
        assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text}"
        return resp.json()

    def fetch_bundle(self, run_id: int) -> RunBundle:
        """Reconstruct a RunBundle purely through the public API — the round-trip half of the
        Phase 4 gate. Every field comes from an endpoint response, nothing from the database."""
        run = self.get_json(f"/v1/runs/{run_id}")
        targets: list[TargetRecord] = []
        scripts: dict[str, str] = {}
        for target_summary in run["targets"]:
            target = self.get_json(f"/v1/targets/{target_summary['id']}")
            divergences: list[DivergenceRecord] = []
            for divergence_summary in target["divergences"]:
                d = self.get_json(f"/v1/divergences/{divergence_summary['id']}")
                repro = self.client.get(f"/v1/divergences/{divergence_summary['id']}/repro.py")
                assert repro.status_code == 200
                scripts[d["repro_filename"]] = repro.text
                divergences.append(
                    DivergenceRecord(
                        divergence_class=DivergenceClass(d["divergence_class"]),
                        severity=Severity(d["severity"]),
                        detail=d["detail"],
                        args_literal=d["args_literal"],
                        kwargs_literal=d["kwargs_literal"],
                        minimized_args=d["minimized_args"],
                        minimized_kwargs=d["minimized_kwargs"],
                        shrink_path=tuple(d["shrink_path"]),
                        base_summary=d["base_summary"],
                        head_summary=d["head_summary"],
                        repro_filename=d["repro_filename"],
                    )
                )
            targets.append(
                TargetRecord(
                    file_path=target["file_path"],
                    module=target["module"],
                    qualname=target["qualname"],
                    lang=Lang(target["lang"]),
                    classification=TargetClassification(target["classification"]),
                    verdict=Verdict(target["verdict"]),
                    reason_code=(
                        ReasonCode(target["reason_code"])
                        if target["reason_code"] is not None
                        else None
                    ),
                    reason_detail=target["reason_detail"],
                    inputs_run=target["inputs_run"],
                    equivalent_inputs=target["equivalent_inputs"],
                    unprovable_inputs=target["unprovable_inputs"],
                    changed_line_coverage=target["changed_line_coverage"],
                    divergences=tuple(divergences),
                )
            )
        manifest = RunManifest(
            schema_version=run["schema_version"],
            engine_version=run["engine_version"],
            repo=run["repo"],
            base_sha=run["base_sha"],
            head_sha=run["head_sha"],
            created_at=run["bundle_created_at"],
            verdict=Verdict(run["verdict"]),
            base_deps=run["base_deps"],
            head_deps=run["head_deps"],
            budget_max_inputs=run["budget_max_inputs"],
        )
        return RunBundle(manifest=manifest, targets=tuple(targets), repro_scripts=scripts)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiHarness]:
    db_path = tmp_path / "api-test.db"
    monkeypatch.setenv("TEMPEST_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    with TestClient(create_app()) as client:
        yield ApiHarness(client=client, db_path=db_path)
