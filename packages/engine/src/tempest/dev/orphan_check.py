"""THE ORPHAN GATE: `python -m tempest.dev.orphan_check [--app <binary>]`.

Launches the REAL installed app binary, waits for its engine sidecar to appear, then SIGKILLs
the host — the one signal the Rust supervisor can never handle. Within the deadline every
sidecar process must be gone from the process table (Phase 9 gate; L11: the user's machine is
not your CI runner). Two independent mechanisms make this true, and this gate proves the
belt-and-braces actually hold on this machine:

  - graceful/TERM paths: the supervisor sweeps the sidecar's whole process group on exit;
  - SIGKILL of the host: the sidecar's parent-watch thread notices the reparenting within ~2 s
    and exits itself (SIGTERM, then hard exit five seconds later).
"""

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_DEFAULT_APP = Path("/Applications/Tempest.app/Contents/MacOS/tempest-desktop")
_SIDECAR_DEADLINE_S = 40.0
_CLEANUP_DEADLINE_S = 15.0


def _sidecar_pids() -> set[int]:
    result = subprocess.run(
        ["pgrep", "-f", "tempest-server"], capture_output=True, text=True, check=False
    )
    return {int(line) for line in result.stdout.split()} if result.returncode == 0 else set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=_DEFAULT_APP)
    args = parser.parse_args()
    if not args.app.is_file():
        raise SystemExit(f"app binary not found: {args.app} — build and install Tempest.app")

    before = _sidecar_pids()
    app = subprocess.Popen([str(args.app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"launched {args.app.name} (pid {app.pid}); waiting for its sidecar…")

    deadline = time.monotonic() + _SIDECAR_DEADLINE_S
    spawned: set[int] = set()
    while time.monotonic() < deadline:
        if app.poll() is not None:
            raise SystemExit(f"app exited before spawning a sidecar (rc {app.returncode})")
        spawned = _sidecar_pids() - before
        if spawned:
            break
        time.sleep(0.25)
    if not spawned:
        app.kill()
        raise SystemExit("no sidecar process appeared — nothing to prove")
    print(f"sidecar up: pids {sorted(spawned)}; SIGKILLing the host now")

    os.kill(app.pid, signal.SIGKILL)
    app.wait(timeout=10)

    deadline = time.monotonic() + _CLEANUP_DEADLINE_S
    while time.monotonic() < deadline:
        survivors = _sidecar_pids() & spawned
        if not survivors:
            elapsed = _CLEANUP_DEADLINE_S - (deadline - time.monotonic())
            print(
                f"orphan check: zero sidecar processes survive SIGKILL of the host "
                f"(cleared in {elapsed:.1f}s, bar {_CLEANUP_DEADLINE_S:.0f}s)"
            )
            sys.exit(0)
        time.sleep(0.5)

    leftovers = sorted(_sidecar_pids() & spawned)
    print(f"ORPHANS SURVIVED: pids {leftovers} still alive — killing them and failing")
    for pid in leftovers:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    sys.exit(1)


if __name__ == "__main__":
    main()
