"""Desktop-sidecar entrypoint: one process, loopback-only uvicorn over a local SQLite file.

The Tauri shell spawns this as `tempest-server --port <p> --data-dir <dir>` (also the frozen
PyInstaller binary's __main__). Environment the app reads at creation time — the database URL —
is set BEFORE `tempest_api.app` is imported, so the frozen runtime behaves exactly like
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
            os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tempest-server",
        description="Tempest AI desktop sidecar — binds 127.0.0.1 only, stores in --data-dir.",
    )
    parser.add_argument("--port", type=int, required=True, help="loopback port to bind")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="writable directory for tempest.db (created if missing)",
    )
    args = parser.parse_args()
    port: int = args.port
    data_dir: Path = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["TEMPEST_DATABASE_URL"] = f"sqlite+aiosqlite:///{data_dir / 'tempest.db'}"
    # Everything the sidecar persists lives under --data-dir: the DB above, and the
    # local-prove bundles (tempest_api.localprove reads TEMPEST_DATA_DIR).
    os.environ["TEMPEST_DATA_DIR"] = str(data_dir)

    threading.Thread(target=_watch_parent, args=(os.getppid(),), daemon=True).start()

    # Deferred imports: the app snapshot must see the environment configured above.
    import uvicorn

    from tempest_api.app import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
