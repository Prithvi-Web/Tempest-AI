"""Desktop-sidecar entrypoint over a local SQLite file — two transports, one app:

- `tempest-server --stdio --data-dir <dir>`: JSON-RPC 2.0 over stdin/stdout (Boundary A,
  CLAUDE.md §9b) — the desktop path; no TCP socket ever listens.
- `tempest-server --port <p> --data-dir <dir>`: loopback-only uvicorn — dev/browser fallback.

Environment the app reads at creation time — the database URL — is set BEFORE
`tempest_api.app` is imported, so the frozen PyInstaller runtime behaves exactly like
`uv run tempest-server`. CORS defaults (Tauri webview + dev origins) live in app.py itself.
"""

import argparse
import os
import signal
import threading
import time
from pathlib import Path


def _watch_parent(initial_ppid: int) -> None:
    """Exit when the parent process dies (PyInstaller-onefile children get reparented when the
    Tauri shell kills the bootstrap parent, and would otherwise run forever). Graceful SIGTERM
    first; hard exit if uvicorn hasn't finished shutting down five seconds later."""
    while True:
        time.sleep(2.0)
        if os.getppid() != initial_ppid:
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5.0)
            os._exit(0)  # pragma: no cover — os._exit skips atexit, so no tracer can flush it


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tempest-server",
        description="Tempest AI desktop sidecar — stdio JSON-RPC (desktop) or 127.0.0.1 HTTP.",
    )
    parser.add_argument("--port", type=int, default=None, help="loopback port to bind (HTTP mode)")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="serve JSON-RPC 2.0 over stdin/stdout instead of HTTP (no listening socket)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="writable directory for tempest.db (created if missing)",
    )
    args = parser.parse_args()
    port: int | None = args.port
    stdio: bool = args.stdio
    if stdio == (port is not None):
        parser.error("exactly one of --stdio or --port is required")
    data_dir: Path = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["TEMPEST_DATABASE_URL"] = f"sqlite+aiosqlite:///{data_dir / 'tempest.db'}"
    # Everything the sidecar persists lives under --data-dir: the DB above, and the
    # local-prove bundles (tempest_api.localprove reads TEMPEST_DATA_DIR).
    os.environ["TEMPEST_DATA_DIR"] = str(data_dir)

    threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()

    # Deferred imports: the app snapshot must see the environment configured above.
    from tempest.crashlog import install_crash_capture
    from tempest_api.app import create_app

    install_crash_capture()  # Phase 17: sidecar crashes leave a scrubbed local record

    if stdio:
        from tempest_api.stdiorpc import serve_stdio

        serve_stdio(create_app())
        return

    import uvicorn

    assert port is not None  # argparse validation above guarantees it in HTTP mode
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
