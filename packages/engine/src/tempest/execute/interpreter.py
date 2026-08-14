"""Worker interpreter discovery — which CPython spawns sandbox workers.

In a normal install the answer is `sys.executable`. Inside a frozen (PyInstaller) sidecar,
`sys.executable` is the sidecar binary itself and cannot run `worker.py`, so a real host
CPython >= 3.12 must be discovered instead. Every candidate is validated by actually running
`<candidate> --version` (Law L4: no assumed interpreters); the result is cached per-process.

Resolution order:
1. `TEMPEST_PYTHON` env override — must exist and report >= 3.12, else the run fails loudly.
2. Not frozen → `sys.executable`.
3. Frozen → `python3.12` on PATH, then `python3` on PATH (only if >= 3.12), then uv-managed
   interpreters under `~/.local/share/uv/python/` (newest first).
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_VERSION = (3, 12)

_cache: str | None = None


class WorkerPythonNotFound(RuntimeError):
    """No CPython >= 3.12 is available to run sandbox workers. The message says how to fix it."""


def _reset_cache() -> None:
    """Test seam: discovery is cached per-process; tests reset between scenarios."""
    global _cache
    _cache = None


def _probe_version(candidate: str) -> tuple[int, int] | None:
    """Run `<candidate> --version` for real; (major, minor) or None if unrunnable/unparsable."""
    try:
        proc = subprocess.run(
            [candidate, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"Python (\d+)\.(\d+)", proc.stdout + proc.stderr)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _uv_managed_candidates(base: Path | None = None) -> list[str]:
    """uv-installed CPython 3.12+ binaries, newest interpreter version first."""
    root = base if base is not None else Path.home() / ".local" / "share" / "uv" / "python"
    found: list[tuple[tuple[int, ...], str]] = []
    for install in root.glob("cpython-3.1[2-9]*"):
        match = re.match(r"cpython-(\d+)\.(\d+)(?:\.(\d+))?", install.name)
        if match is None:
            continue
        version = tuple(int(part) for part in match.groups() if part is not None)
        found.extend((version, str(binary)) for binary in sorted(install.glob("bin/python3*")))
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in found]


def _resolve_override(override: str) -> str:
    """Validate the TEMPEST_PYTHON override or raise with an actionable message."""
    resolved = override if os.sep in override else shutil.which(override) or override
    if not Path(resolved).exists():
        raise WorkerPythonNotFound(
            f"TEMPEST_PYTHON={override!r} does not exist — point it at a real CPython "
            f">= {'.'.join(map(str, MIN_VERSION))} binary, or unset it to use auto-discovery"
        )
    version = _probe_version(resolved)
    if version is None:
        raise WorkerPythonNotFound(
            f"TEMPEST_PYTHON={override!r} is not a runnable Python interpreter "
            "(`--version` failed) — point it at a real CPython "
            f">= {'.'.join(map(str, MIN_VERSION))} binary, or unset it to use auto-discovery"
        )
    if version < MIN_VERSION:
        raise WorkerPythonNotFound(
            f"TEMPEST_PYTHON={override!r} is Python {version[0]}.{version[1]}, but sandbox "
            f"workers need >= {'.'.join(map(str, MIN_VERSION))} — install Python 3.12+ "
            "(e.g. `uv python install 3.12`) and update TEMPEST_PYTHON"
        )
    return resolved


def _discover() -> str:
    override = os.environ.get("TEMPEST_PYTHON")
    if override:
        return _resolve_override(override)
    if not getattr(sys, "frozen", False):
        return sys.executable
    candidates: list[str] = []
    for name in ("python3.12", "python3"):
        which = shutil.which(name)
        if which is not None:
            candidates.append(which)
    candidates.extend(_uv_managed_candidates())
    for candidate in candidates:
        version = _probe_version(candidate)
        if version is not None and version >= MIN_VERSION:
            return candidate
    raise WorkerPythonNotFound(
        "no CPython >= 3.12 found to run sandbox workers (this frozen runtime cannot host "
        "them itself) — install Python 3.12+ (`brew install python@3.12` or "
        "`uv python install 3.12`), or set TEMPEST_PYTHON to an existing interpreter"
    )


def find_worker_python() -> str:
    """The interpreter used to spawn sandbox workers; discovered once, cached per-process."""
    global _cache
    if _cache is None:
        _cache = _discover()
    return _cache
