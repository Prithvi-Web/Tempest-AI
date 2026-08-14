"""Sync push (Phase 13): delta-only, idempotent, resumable against a REAL second tempest
server process — a dead server queues work without blocking (L8), a restarted server receives
exactly what was missing (no duplication, no loss), and with the default policy no source
text reaches the remote store."""

import dataclasses
import io
import os
import socket
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

PLANTED_SOURCE = "return secret_business_logic(x) * PLANTED_CONSTANT_777"


class RemoteServer:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("TEMPEST_")  # the remote must not inherit the local's env
        }
        env["TEMPEST_NO_POWER_PAUSE"] = "1"
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tempest_api.server",
                "--port",
                str(self.port),
                "--data-dir",
                str(self.data_dir),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base_url}/v1/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise AssertionError("remote server never became healthy")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(timeout=10)
            self.proc = None

    def runs(self) -> list[dict[str, object]]:
        resp = httpx.get(f"{self.base_url}/v1/runs", timeout=5)
        assert resp.status_code == 200
        items: list[dict[str, object]] = resp.json()["items"]
        return items

    def export(self, run_id: int) -> bytes:
        resp = httpx.get(f"{self.base_url}/v1/runs/{run_id}/bundle", timeout=5)
        assert resp.status_code == 200
        return resp.content


@pytest.fixture
def remote(tmp_path: Path) -> Iterator[RemoteServer]:
    server = RemoteServer(tmp_path / "remote-data")
    server.start()
    yield server
    server.stop()


def _ingest_n(api, n: int, *, planted: bool = False) -> None:
    for i in range(n):
        bundle = api.make_bundle(repo=f"sync-repo-{i}", head_sha=f"{i:x}" * 40)
        if planted:
            body = f"#!/usr/bin/env python3\n{PLANTED_SOURCE}\n"
            scripts = dict.fromkeys(bundle.repro_scripts, body)
            bundle = dataclasses.replace(bundle, repro_scripts=scripts)
        api.ingest(bundle)


def _push(api, server_url: str) -> dict[str, int | list[str]]:
    resp = api.client.post("/v1/sync/push", json={"server_url": server_url})
    assert resp.status_code == 200, resp.text
    report: dict[str, int | list[str]] = resp.json()
    return report


def test_push_is_delta_only_and_idempotent(
    api, remote: RemoteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    _ingest_n(api, 2)

    first = _push(api, remote.base_url)
    assert first["pushed"] == 2 and first["failed"] == 0 and first["remaining"] == 0
    assert len(remote.runs()) == 2

    second = _push(api, remote.base_url)
    assert second["pushed"] == 0 and second["skipped"] == 2, "presence makes re-push a no-op"
    assert len(remote.runs()) == 2, "no duplication, ever"


def test_dead_server_queues_without_blocking_and_resumes_cleanly(
    api, remote: RemoteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    _ingest_n(api, 3)

    remote.stop()  # the network dies before anything crossed
    down = _push(api, remote.base_url)
    assert down["pushed"] == 0 and down["remaining"] == 3, "unreachable server = queued, not lost"

    remote.start()  # same data dir: the server comes back with its previous state
    resumed = _push(api, remote.base_url)
    assert resumed["pushed"] == 3 and resumed["remaining"] == 0
    assert len(remote.runs()) == 3, "resume delivers exactly what was missing"

    remote.stop()
    remote.start()  # a bounce after a complete sync must change nothing
    after_bounce = _push(api, remote.base_url)
    assert after_bounce["pushed"] == 0 and after_bounce["skipped"] == 3
    assert len(remote.runs()) == 3


def test_default_policy_strips_source_before_the_wire(
    api, remote: RemoteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    _ingest_n(api, 1, planted=True)

    assert _push(api, remote.base_url)["pushed"] == 1
    (run,) = remote.runs()
    exported = remote.export(int(str(run["id"])))
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="replace")
            assert PLANTED_SOURCE not in text, f"source crossed the boundary in {name}"


def test_opt_in_sharing_is_push_pull_byte_identical(
    api, remote: RemoteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")
    bundle = api.make_bundle(repo="byte-identical", head_sha="d" * 40)
    data = api.zip_bytes(bundle)
    run_id = api.create_run_for(bundle)
    assert api.upload_zip(run_id, data).status_code == 200

    assert _push(api, remote.base_url)["pushed"] == 1
    (run,) = remote.runs()
    assert remote.export(int(str(run["id"]))) == data, "push = pull, byte-identical (L7)"
