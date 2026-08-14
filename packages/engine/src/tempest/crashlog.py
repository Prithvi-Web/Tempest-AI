"""Crash capture (Phase 17): scrubbed at write time, local-only, never a second crash.

Records land in `<data_dir>/crashes/` already redacted — the raw traceback (with its source
echoes, symbol names, paths, env values) never touches disk, so nothing downstream can leak
what was never stored (L9, failure-mode #4). Sharing is a separate, deliberate act: the
records travel only inside the user-inspectable diagnostic bundle.
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import TracebackType

import tempest
from tempest.redact import RedactionContext, scrub_traceback, secret_env_values


def crash_dir() -> Path:
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest"))) / "crashes"


def capture_crash(exc: BaseException) -> Path | None:
    """Write one scrubbed crash record; returns its path, or None if even that failed —
    a broken disk must never turn one crash into two."""
    try:
        context = RedactionContext(
            env_secret_values=secret_env_values(), home_dir=str(Path.home())
        )
        raw_tb = "".join(traceback.format_exception(exc))
        record = {
            "tempest_version": tempest.__version__,
            "exception_type": type(exc).__name__,
            "traceback": scrub_traceback(raw_tb, context),
        }
        directory = crash_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"crash-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}.json"
        path.write_text(json.dumps(record, indent=2) + "\n")
        return path
    except OSError:
        return None


def install_crash_capture() -> None:
    """Route unhandled exceptions through capture_crash, then the previous hook — installed by
    the CLI and the sidecar entrypoints so every surface crash leaves a scrubbed record."""
    previous = sys.excepthook

    def _hook(
        exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        capture_crash(exc)
        previous(exc_type, exc, tb)

    sys.excepthook = _hook
