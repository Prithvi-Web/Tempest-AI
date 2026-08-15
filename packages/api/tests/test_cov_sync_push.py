"""Sync push engine (`tempest_api.sync.push_all`) pinned by DIRECT calls (Phase 13).

test_sync_push proves the wire behavior over HTTP; these tests call `push_all` itself with a
real session and pin every counted outcome the report can carry: the zero-candidate fast path,
digest dedup across runs, a locally missing blob skipped (with the rest still delivered), a
REAL second tempest server rejecting a non-bundle blob (counted `failed`, never blocking), the
presence check against a dead server (everything stays queued), and a peer that drops the
connection mid-push (the loop stops instead of hammering; the store remains the queue). The
mid-push peer is a real TCP server speaking real HTTP that dies after the presence exchange —
the one failure shape a healthy full server cannot produce deterministically."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tempest_api.bundlestore import bundle_store
from tempest_api.db.models import Repo, Run
from tempest_api.db.session import create_engine_and_factory
from tempest_api.schemas import RunStatus
from tempest_api.schemas.sync import SyncReport
from tempest_api.sync import push_all


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine, factory = create_engine_and_factory()
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _push(server_url: str) -> SyncReport:
    async def scenario() -> SyncReport:
        async with _session() as session:
            return await push_all(session, server_url, timeout_s=10.0)

    return asyncio.run(scenario())


class RemoteServer:
    """A REAL second tempest API process with its own store (mirrors test_sync_push)."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TEMPEST_")}
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
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
            self.proc = None

    def run_count(self) -> int:
        resp = httpx.get(f"{self.base_url}/v1/runs", timeout=5)
        assert resp.status_code == 200
        return len(resp.json()["items"])


@pytest.fixture
def remote(tmp_path: Path) -> Iterator[RemoteServer]:
    server = RemoteServer(tmp_path / "remote-data")
    server.start()
    yield server
    server.stop()


def test_zero_candidates_touches_no_network(api: Any, tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    report = _push("http://127.0.0.1:9")  # dead address: reachable only if a request is made
    assert report == SyncReport(candidates=0, pushed=0, skipped=0, failed=0, remaining=0, errors=[])


def _plant_run_with_digest(db_path: Path, *, repo: str, head_sha: str, digest: str) -> None:
    """A completed run whose bundle_digest points at whatever the store holds for it."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as s:
            planted = Repo(name=repo)
            s.add(planted)
            s.flush()
            s.add(
                Run(
                    repo_id=planted.id,
                    base_sha="a" * 40,
                    head_sha=head_sha,
                    status=RunStatus.COMPLETE,
                    bundle_digest=digest,
                )
            )
            s.commit()
    finally:
        engine.dispose()


def test_dedup_missing_blob_rejection_and_resume(
    api: Any, remote: RemoteServer, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    # Opt-in sharing: bytes cross unchanged, so the planted non-bundle zip reaches the server
    # as-is and its rejection is the server's own real 400 (never a simulated status).
    monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")

    good = api.make_bundle(repo="sync-good", head_sha="1" * 40)
    api.ingest(good)
    # The same zip ingested into a second run: two rows, one digest — pushed exactly once.
    data = api.zip_bytes(good)
    dup_run = api.create_run_for(good)
    assert api.upload_zip(dup_run, data).status_code == 200

    doomed = api.make_bundle(repo="sync-doomed", head_sha="2" * 40)
    api.ingest(doomed)

    store = bundle_store()
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("readme.txt", "a zip, but not a bundle")
    reject_digest = store.put(buf.getvalue())
    _plant_run_with_digest(api.db_path, repo="sync-reject", head_sha="3" * 40, digest=reject_digest)

    # The doomed run's blob vanishes from disk (external deletion) — skipped, with an error,
    # while everything after it still crosses.
    doomed_digest = None
    with sa.create_engine(f"sqlite:///{api.db_path}").connect() as conn:
        doomed_digest = conn.execute(
            sa.text(
                "SELECT bundle_digest FROM runs WHERE repo_id = "
                "(SELECT id FROM repos WHERE name = 'sync-doomed')"
            )
        ).scalar()
    assert isinstance(doomed_digest, str)
    (store.root / doomed_digest[:2] / f"{doomed_digest}.tempest.zip").unlink()

    first = _push(remote.base_url)
    assert first.candidates == 3, "every unique digest is accounted (missing blob = failed)"
    assert first.pushed == 1 and first.failed == 2 and first.skipped == 0
    assert first.remaining == 0
    assert any("missing from the store; skipped" in e for e in first.errors)
    assert any(f"server rejected {reject_digest[:12]}" in e and "400" in e for e in first.errors)
    assert remote.run_count() == 1, "the rejected blob must never appear as a remote run"

    second = _push(remote.base_url)
    assert second.pushed == 0 and second.skipped == 1, "presence makes the re-push delta-only"
    assert second.failed == 2, "rejected + missing-blob are re-offered, not silently dropped"
    assert remote.run_count() == 1


def test_unreachable_presence_check_queues_everything(
    api: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    api.ingest(api.make_bundle(repo="queued", head_sha="4" * 40))

    with socket.socket() as probe:  # a port that was free a moment ago: nothing listens
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    report = _push(f"http://127.0.0.1:{dead_port}")
    assert report.candidates == 1 and report.pushed == 0 and report.remaining == 1
    assert any("push interrupted at bundle" in e for e in report.errors)


class _DiesAfterPresence(BaseHTTPRequestHandler):
    """Real HTTP for the presence exchange, then the process 'dies': the import connection is
    severed with no response — exactly what a peer crashing mid-sync looks like on the wire."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/v1/bundles/presence":
            body = json.dumps({"present": [], "missing": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.connection.close()

    def log_message(self, *_args: Any) -> None:
        """Quiet: request logging is not part of the behavior under test."""


def test_mid_push_death_stops_the_loop_and_keeps_the_queue(
    api: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "local-data"))
    api.ingest(api.make_bundle(repo="interrupted-a", head_sha="5" * 40))
    api.ingest(api.make_bundle(repo="interrupted-b", head_sha="6" * 40))

    server = ThreadingHTTPServer(("127.0.0.1", 0), _DiesAfterPresence)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        report = _push(f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()

    assert report.candidates == 2
    assert report.pushed == 0 and report.failed == 0 and report.skipped == 0
    assert report.remaining == 2, "everything not yet pushed stays queued in the store"
    assert any(e.startswith("push interrupted at bundle 1/2") for e in report.errors)
