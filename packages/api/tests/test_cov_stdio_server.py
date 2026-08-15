"""Sidecar entrypoint edges (Law L4 — real processes only):

- the argparse transport-exclusivity error runs `main()` in-process;
- `_watch_parent` is proven by a REAL orphaning: a launcher process starts the server,
  waits until it serves its port, then dies — the reparented server must notice within its
  poll window, SIGTERM itself, and exit through uvicorn's graceful shutdown.
"""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tempest_api import server

REPO_ROOT = Path(__file__).resolve().parents[3]

_LAUNCHER = """
import os
import socket
import subprocess
import sys
import time

port, data_dir = sys.argv[1], sys.argv[2]
proc = subprocess.Popen(
    [sys.executable, "-m", "tempest_api.server", "--port", port, "--data-dir", data_dir]
)
print(proc.pid, flush=True)
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    try:
        socket.create_connection(("127.0.0.1", int(port)), timeout=0.5).close()
        break
    except OSError:
        time.sleep(0.2)
else:
    proc.kill()
    raise SystemExit("server never opened its port")
os._exit(0)  # die without ceremony: the server is now an orphan and must notice
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestArgumentValidation:
    def test_neither_transport_is_an_argparse_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["tempest-server", "--data-dir", str(tmp_path)])
        with pytest.raises(SystemExit) as excinfo:
            server.main()
        assert excinfo.value.code == 2
        assert "exactly one of --stdio or --port" in capsys.readouterr().err

    def test_both_transports_is_an_argparse_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            ["tempest-server", "--stdio", "--port", "8123", "--data-dir", str(tmp_path)],
        )
        with pytest.raises(SystemExit) as excinfo:
            server.main()
        assert excinfo.value.code == 2
        assert "exactly one of --stdio or --port" in capsys.readouterr().err


def test_stdio_main_serves_until_eof_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`main --stdio` wires env, crash capture, the parent watcher, and the frame loop; an
    already-closed stdin makes the loop return cleanly right after the app lifecycle runs."""
    from types import SimpleNamespace

    data_dir = tmp_path / "made" / "by-main"
    monkeypatch.setenv("TEMPEST_DATABASE_URL", "unset-by-test")  # registers restoration
    monkeypatch.setenv("TEMPEST_DATA_DIR", "unset-by-test")
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # crash capture must not leak out
    monkeypatch.setattr(sys, "argv", ["tempest-server", "--stdio", "--data-dir", str(data_dir)])

    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    os.close(stdin_write)  # immediate EOF at a frame boundary: serve loop exits cleanly
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=os.fdopen(stdin_read, "rb")))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=os.fdopen(stdout_write, "wb")))
    try:
        server.main()
    finally:
        with contextlib.suppress(OSError):
            os.close(stdout_read)
    assert (data_dir / "tempest.db").is_file()  # the server created its own store
    assert os.environ["TEMPEST_DATA_DIR"] == str(data_dir.resolve())


def test_orphaned_server_terminates_itself(tmp_path: Path) -> None:
    port = _free_port()
    launcher = subprocess.run(
        [sys.executable, "-c", _LAUNCHER, str(port), str(tmp_path / "data")],
        cwd=REPO_ROOT,  # the grandchild inherits it; its coverage data lands combinable
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert launcher.stdout.strip(), f"launcher never reported a pid: {launcher.stderr}"
    server_pid = int(launcher.stdout.strip())
    try:
        # The watcher polls every 2 s, then SIGTERMs itself into uvicorn's graceful stop;
        # generous headroom for a loaded CI machine (repo trap 11).
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                os.kill(server_pid, 0)
            except ProcessLookupError:
                break  # the orphan noticed and died on its own
            time.sleep(0.25)
        else:
            pytest.fail("orphaned server still alive 60s after its parent died")
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(server_pid, signal.SIGKILL)
