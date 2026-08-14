"""The desktop-sidecar entrypoint, exercised as a REAL `uv run tempest-server` subprocess
(Law L4): boots, serves /v1/health on loopback, creates its SQLite file inside --data-dir,
and shuts down when told to."""

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
STARTUP_DEADLINE_S = 90.0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_tempest_server_boots_serves_health_and_terminates(tmp_path: Path) -> None:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    assert Path(uv).exists(), "uv is required to launch the entrypoint under test"
    port = _free_port()
    data_dir = tmp_path / "made" / "by-the-server"  # exercises created-if-missing
    env = {
        **os.environ,
        "PATH": f"{Path.home() / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    proc = subprocess.Popen(
        [
            uv,
            "run",
            "--no-sync",
            "tempest-server",
            "--port",
            str(port),
            "--data-dir",
            str(data_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}/v1/health"
    try:
        deadline = time.monotonic() + STARTUP_DEADLINE_S
        last_refusal: Exception | None = None
        while True:
            if proc.poll() is not None:
                output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                pytest.fail(f"server exited before becoming healthy ({proc.returncode}): {output}")
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200 and response.json()["status"] == "ok":
                    break
            except httpx.HTTPError as exc:
                last_refusal = exc
            if time.monotonic() > deadline:
                pytest.fail(f"server never served /v1/health: {last_refusal!r}")
            time.sleep(0.2)

        # the database landed inside --data-dir, which the server created itself
        assert (data_dir / "tempest.db").is_file()
    finally:
        with_group = proc.poll() is None
        if with_group:
            os.killpg(proc.pid, signal.SIGTERM)
        exit_code = proc.wait(timeout=30)

    # A controlled stop surfaces as one of exactly three encodings of the signal we sent:
    # 0 (uvicorn's graceful shutdown won the race), -SIGTERM (the launcher died by the
    # signal), or 128+SIGTERM (uv run reporting its child's signal death, observed as 143).
    assert exit_code in (0, -signal.SIGTERM, 128 + signal.SIGTERM)
    # and the port is actually released — nothing is still serving behind our back
    with pytest.raises(httpx.HTTPError):
        httpx.get(url, timeout=2.0)
