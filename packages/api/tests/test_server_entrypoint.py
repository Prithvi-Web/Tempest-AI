"""The desktop-sidecar entrypoint, exercised as a REAL `uv run tempest-server` subprocess
(Law L4): boots, serves /v1/health on loopback, creates its SQLite file inside --data-dir,
and shuts down when told to."""

import os
import shutil
import signal
import socket
import subprocess
import sys
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


def _uv() -> str:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    assert Path(uv).exists(), "uv is required to launch the entrypoint under test"
    return uv


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{Path.home() / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    return subprocess.run(
        [_uv(), "run", "--no-sync", "tempest-server", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=STARTUP_DEADLINE_S,
    )


def test_print_tool_manifest_answers_without_a_data_dir() -> None:
    """The self-check a BUILD runs against a frozen binary, exercised as a real subprocess.

    It exists because the shipped app once could NOT read its own tool manifest — an empty
    Tool Library in the builder and a failure at the top of every tool-bearing turn — while
    the repo, the e2e harness and both coverage gates stayed green, because all three run from
    the source tree. `build-server.sh` now runs this on every build.

    Needing no `--data-dir` is part of the contract: a build asking "can you still read your
    contract" should not have to invent a writable directory to get an answer.
    """
    done = _run("--print-tool-manifest")
    assert done.returncode == 0, done.stderr
    names = done.stdout.split()
    assert "ask_user" in names and "run_command" in names
    assert names == sorted(names), "sorted output keeps a build's diff readable"
    assert len(names) >= 7, f"the manifest looks truncated: {names}"


def test_the_data_dir_is_required_for_a_real_run() -> None:
    """…and only for a real run. The flag above made `--data-dir` optional, so the check that
    it is present had to move into the body — this is the arm that proves it still bites."""
    done = _run("--stdio")
    assert done.returncode != 0
    assert "--data-dir is required" in done.stderr


def test_exactly_one_transport_is_required() -> None:
    both = _run("--stdio", "--port", "1", "--data-dir", "/tmp/whatever")
    assert both.returncode != 0
    assert "exactly one of --stdio or --port" in both.stderr


def test_an_EMPTY_manifest_is_a_failure_not_a_quiet_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file that exists and declares no tools is a different bug from a file that is missing,
    and it has to fail too.

    Without this arm the flag would print nothing, exit 0, and `build-server.sh` would pass —
    on a binary whose Tool Library is empty, which is precisely the failure the flag was added
    to catch. In-process rather than a subprocess because the real manifest is never empty:
    the point is the DECISION, not the file.
    """
    from tempest_api import server as server_mod

    monkeypatch.setattr("tempest.agent.tools.load_manifest", lambda *a, **k: {})
    monkeypatch.setattr(sys, "argv", ["tempest-server", "--print-tool-manifest"])
    with pytest.raises(SystemExit) as caught:
        server_mod.main()
    assert caught.value.code == 1, "an empty manifest must be a nonzero exit, or the gate lies"
