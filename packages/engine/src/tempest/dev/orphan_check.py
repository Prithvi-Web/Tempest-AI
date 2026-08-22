"""THE ORPHAN GATE: `python -m tempest.dev.orphan_check [--all-children] [--after-sigkill]`.

Launches the REAL installed app binary, waits for its sidecar(s) to appear, then SIGKILLs
the host — the one signal the Rust supervisor can never handle. Within the deadline every
child process must be gone from the process table (Phase 9 gate; L11: the user's machine is
not your CI runner; L34 from C2: EVERY process is supervised and orphans are impossible).
Two independent mechanisms make this true, and this gate proves the belt-and-braces actually
hold on this machine:

  - graceful/TERM paths: the supervisor sweeps each sidecar's whole process group on exit;
  - SIGKILL of the host: each sidecar notices on its own — the engine's parent-watch thread
    sees the reparenting within ~2 s; the platform sidecar's stdin (held open by the host)
    reaches EOF and its ppid-poll sees init — and exits itself.

`--all-children` (PLAN-V3 C2) widens the claim from "the engine sidecar" to **every
descendant the app spawned**: the engine, the Node platform sidecar (spawned for the gate via
`TEMPEST_PLATFORM_SIDECAR=1`), and anything they started. It also runs the C2 port probe:
**no process in the tree may hold a TCP listener** — boundary E is a Unix socket, and a
listening port fails enterprise security review. `--after-sigkill` names the kill the gate
has always used; it is accepted for gate-command fidelity.
"""

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
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


def _descendants(root_pid: int) -> set[int]:
    """Every live descendant of `root_pid`, walked from one `ps` snapshot."""
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, check=False
    )
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            pid, ppid = int(parts[0]), int(parts[1])
            children.setdefault(ppid, []).append(pid)
    out: set[int] = set()
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def _alive(pids: set[int]) -> set[int]:
    live: set[int] = set()
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, 0)
            live.add(pid)
    return live


def _tcp_listeners(pids: set[int]) -> str:
    """lsof output for any TCP listener held by `pids` — empty means the property holds."""
    joined = ",".join(str(pid) for pid in sorted(pids))
    result = subprocess.run(
        ["lsof", "-a", "-p", joined, "-iTCP", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=_DEFAULT_APP)
    parser.add_argument(
        "--all-children",
        action="store_true",
        help="C2/L34: track EVERY descendant (engine + platform sidecar + their children) "
        "and probe for TCP listeners; spawns the platform sidecar via env for the run",
    )
    parser.add_argument(
        "--after-sigkill",
        action="store_true",
        help="names the kill this gate has always used (SIGKILL of the host); accepted "
        "for gate-command fidelity",
    )
    args = parser.parse_args()
    if not args.app.is_file():
        raise SystemExit(f"app binary not found: {args.app} — build and install Tempest.app")

    env = dict(os.environ)
    if args.all_children:
        node = os.environ.get("TEMPEST_PLATFORM_NODE") or shutil.which("node")
        if not node:
            raise SystemExit(
                "--all-children exercises the platform sidecar and needs `node` on PATH "
                "(or TEMPEST_PLATFORM_NODE)"
            )
        env["TEMPEST_PLATFORM_SIDECAR"] = "1"
        env["TEMPEST_PLATFORM_NODE"] = node

    before = _sidecar_pids()
    app = subprocess.Popen(
        [str(args.app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
    )
    print(f"launched {args.app.name} (pid {app.pid}); waiting for its sidecar(s)…")

    deadline = time.monotonic() + _SIDECAR_DEADLINE_S
    engine: set[int] = set()
    platform: set[int] = set()
    while time.monotonic() < deadline:
        if app.poll() is not None:
            raise SystemExit(f"app exited before spawning a sidecar (rc {app.returncode})")
        engine = _sidecar_pids() - before
        if args.all_children:
            probe = subprocess.run(
                ["pgrep", "-f", "boundary.mjs"], capture_output=True, text=True, check=False
            )
            platform = (
                {int(line) for line in probe.stdout.split()} if probe.returncode == 0 else set()
            )
            if engine and platform:
                break
        elif engine:
            break
        time.sleep(0.25)
    if not engine:
        app.kill()
        raise SystemExit("no engine sidecar appeared — nothing to prove")
    if args.all_children and not platform:
        app.kill()
        raise SystemExit(
            "the platform sidecar never appeared — TEMPEST_PLATFORM_SIDECAR=1 was set, so "
            "either the resource is not bundled or the spawn failed; read the app log"
        )

    tracked = engine | platform
    if args.all_children:
        tracked |= _descendants(app.pid)
        print(
            f"tracking {len(tracked)} descendant(s): engine {sorted(engine)}, "
            f"platform {sorted(platform)}, full tree {sorted(tracked)}"
        )
        listeners = _tcp_listeners(tracked | {app.pid})
        if listeners:
            app.kill()
            print("TCP LISTENER FOUND — boundary E must be a Unix socket, never a port:")
            print(listeners)
            sys.exit(1)
        print("port probe: zero TCP listeners across the host and every descendant")
    else:
        print(f"sidecar up: pids {sorted(tracked)}; SIGKILLing the host now")

    os.kill(app.pid, signal.SIGKILL)
    app.wait(timeout=10)

    deadline = time.monotonic() + _CLEANUP_DEADLINE_S
    while time.monotonic() < deadline:
        survivors = _alive(tracked)
        if not survivors:
            elapsed = _CLEANUP_DEADLINE_S - (deadline - time.monotonic())
            socket = Path(tempfile.gettempdir()) / "tempest-platform.sock"
            if args.all_children and socket.exists():
                print(f"ORPHANED SOCKET: {socket} outlived the sidecar — failing")
                sys.exit(1)
            scope = "descendant" if args.all_children else "sidecar"
            print(
                f"orphan check: zero {scope} processes survive SIGKILL of the host "
                f"(cleared in {elapsed:.1f}s, bar {_CLEANUP_DEADLINE_S:.0f}s)"
            )
            sys.exit(0)
        time.sleep(0.5)

    leftovers = sorted(_alive(tracked))
    print(f"ORPHANS SURVIVED: pids {leftovers} still alive — killing them and failing")
    for pid in leftovers:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    sys.exit(1)
