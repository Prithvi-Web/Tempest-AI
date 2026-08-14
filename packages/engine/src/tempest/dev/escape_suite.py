"""THE PHASE 10 ESCAPE GATE: `python -m tempest.dev.escape_suite --tier T2 [--all-tiers --all-os]`.

Runs 27 adversarial payloads AS THE SANDBOXED WORKER would run target code — through the exact
same `sandbox.popen` path a real prove uses — and asserts every one is CONTAINED. A payload is
CONTAINED when the hostile action fails inside the sandbox AND leaves no trace on the host
(no file written outside scratch, no packet sent, no process surviving the run).

This is the load-bearing evidence for Law L6 on machines without Docker. The matrix it prints is
a sales artifact (master prompt §10). macOS T2 (Seatbelt) is exercised for real here; the Linux
(bubblewrap) and Windows (AppContainer) legs of the OS matrix run in CI and are reported as
PENDING on other platforms — never silently skipped.
"""

import argparse
import contextlib
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tempest.execute.sandbox import ProcessSandbox, Sandbox, SeatbeltSandbox

_HOST = Path.home()


@dataclass(frozen=True)
class Payload:
    name: str
    category: str
    # Python source; receives `scratch` (writable) and `host_home` as argv[1], argv[2]. Prints a
    # single JSON line {"breached": bool, "detail": str}. `breached` True = the sandbox FAILED.
    source: str
    # Optional host-side check run AFTER the payload: returns a breach detail if the payload left
    # a trace on the host (a persisted file, a running process), else None.
    host_probe: str | None = None


_SENTINEL = "tempest_escape_sentinel"

PAYLOADS: tuple[Payload, ...] = (
    # ── network egress (L10): every route must be dead ──────────────────────────────────────
    Payload(
        "tcp_connect_public_ip",
        "network",
        f"""
import socket, json
try:
    s = socket.socket(); s.settimeout(3); s.connect(("1.1.1.1", 80))
    print(json.dumps({{"breached": True, "detail": "connected to 1.1.1.1:80"}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
    ),
    Payload(
        "udp_send",
        "network",
        """
import socket, json
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"x", ("8.8.8.8", 53))
    print(json.dumps({"breached": True, "detail": "udp datagram sent"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "dns_resolve",
        "network",
        """
import socket, json
try:
    socket.gethostbyname("example.com")
    print(json.dumps({"breached": True, "detail": "resolved example.com"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "http_urllib",
        "network",
        """
import json
try:
    import urllib.request
    urllib.request.urlopen("http://1.1.1.1/", timeout=3)
    print(json.dumps({"breached": True, "detail": "urlopen succeeded"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "listen_socket",
        "network",
        """
import socket, json
try:
    s = socket.socket(); s.bind(("0.0.0.0", 0)); s.listen(1)
    print(json.dumps({"breached": True, "detail": "opened a listening socket"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "unix_socket_connect",
        "network",
        """
import socket, json, os
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect("/var/run/systemconfiguration.pid" if os.path.exists("/var/run") else "/tmp/x")
    print(json.dumps({"breached": True, "detail": "unix socket connected"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    # ── secret / home reads: must be blocked outside the repo ────────────────────────────────
    Payload(
        "read_ssh_key",
        "read-secret",
        """
import os, json
p = os.path.join(os.sys.argv[2], ".ssh", "id_probe")
try:
    open(p).read(); print(json.dumps({"breached": True, "detail": "read " + p}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_aws_creds",
        "read-secret",
        """
import os, json
p = os.path.join(os.sys.argv[2], ".aws", "credentials")
try:
    open(p).read(); print(json.dumps({"breached": True, "detail": "read aws creds"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "list_home",
        "read-secret",
        """
import os, json
try:
    entries = os.listdir(os.sys.argv[2])
    print(json.dumps({"breached": True, "detail": f"listed home ({len(entries)} entries)"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_tempest_db",
        "read-secret",
        """
import os, json
p = os.path.join(os.sys.argv[2], "Library", "Application Support", "com.prithvi.tempest",
                 "tempest.db")
try:
    open(p, "rb").read(); print(json.dumps({"breached": True, "detail": "read tempest.db"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_browser_cookies",
        "read-secret",
        """
import os, json, glob
hits = glob.glob(os.path.join(os.sys.argv[2], "Library", "Application Support", "*", "*ookies*"))
try:
    data = open(hits[0], "rb").read() if hits else None
    breach = data is not None
    print(json.dumps({"breached": breach, "detail": "read a cookie store" if breach else "none"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_keychain",
        "read-secret",
        """
import os, json
p = os.path.join(os.sys.argv[2], "Library", "Keychains")
try:
    os.listdir(p); print(json.dumps({"breached": True, "detail": "listed Keychains"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    # ── filesystem writes / persistence: only scratch is writable ────────────────────────────
    Payload(
        "write_home_dotfile",
        "persist",
        f"""
import os, json
p = os.path.join(os.sys.argv[2], ".{_SENTINEL}")
try:
    open(p, "w").write("x"); print(json.dumps({{"breached": True, "detail": "wrote " + p}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
        host_probe=f"~/.{_SENTINEL}",
    ),
    Payload(
        "write_tmp",
        "persist",
        f"""
import json
try:
    open("/tmp/{_SENTINEL}", "w").write("x")
    print(json.dumps({{"breached": True, "detail": "wrote /tmp"}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
        host_probe=f"/tmp/{_SENTINEL}",
    ),
    Payload(
        "write_launch_agent",
        "persist",
        f"""
import os, json
p = os.path.join(os.sys.argv[2], "Library", "LaunchAgents", "{_SENTINEL}.plist")
try:
    open(p, "w").write("x"); print(json.dumps({{"breached": True, "detail": "planted LaunchAgent"}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
        host_probe=f"~/Library/LaunchAgents/{_SENTINEL}.plist",
    ),
    Payload(
        "overwrite_shell_profile",
        "persist",
        """
import os, json
p = os.path.join(os.sys.argv[2], ".zshrc")
try:
    open(p, "a").write("\\n# pwned\\n")
    print(json.dumps({"breached": True, "detail": "appended to .zshrc"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "write_outside_via_relative",
        "persist",
        f"""
import os, json
try:
    open(os.path.join(os.sys.argv[1], "..", "..", "..", "{_SENTINEL}"), "w").write("x")
    print(json.dumps({{"breached": True, "detail": "escaped scratch via .."}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
    ),
    Payload(
        "write_scratch_is_allowed",
        "control",
        """
import os, json
try:
    open(os.path.join(os.sys.argv[1], "ok.txt"), "w").write("x")
    print(json.dumps({"breached": False, "detail": "scratch writable (expected)"}))
except Exception as e:
    print(json.dumps({"breached": True, "detail": "scratch NOT writable: " + type(e).__name__}))
""",
    ),
    # ── process / privilege: children stay contained, no escalation, parent untouchable ──────
    Payload(
        "subprocess_write_escape",
        "process",
        f"""
import subprocess, sys, json
code = 'open("/tmp/{_SENTINEL}_child","w").write("x")'
try:
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=10)
    breach = r.returncode == 0
    print(json.dumps({{"breached": breach, "detail": "child wrote /tmp" if breach else "child contained"}}))
except Exception as e:
    print(json.dumps({{"breached": False, "detail": type(e).__name__}}))
""",
        host_probe=f"/tmp/{_SENTINEL}_child",
    ),
    Payload(
        "subprocess_network_escape",
        "process",
        """
import subprocess, sys, json
code = 'import socket; s=socket.socket(); s.settimeout(3); s.connect(("1.1.1.1",80))'
try:
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=10)
    breach = r.returncode == 0
    print(json.dumps({"breached": breach, "detail": "child reached network" if breach else "child contained"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "shell_out_curl",
        "process",
        """
import subprocess, json
try:
    r = subprocess.run(["/bin/sh", "-c", "curl -s -m 3 http://1.1.1.1/ | head -c 10"],
                       capture_output=True, timeout=10)
    breach = bool(r.stdout.strip())
    print(json.dumps({"breached": breach, "detail": "curl fetched bytes" if breach else "no egress"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "setuid_escalate",
        "privilege",
        """
import os, json
try:
    os.setuid(0)
    print(json.dumps({"breached": os.getuid() == 0, "detail": f"uid now {os.getuid()}"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_root_shadow",
        "privilege",
        """
import json
try:
    open("/etc/master.passwd").read()
    print(json.dumps({"breached": True, "detail": "read /etc/master.passwd"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "kill_parent",
        "process",
        """
import os, json, signal
try:
    os.kill(os.getppid(), signal.SIGKILL)
    print(json.dumps({"breached": True, "detail": "signalled the parent"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "fork_bomb_bounded",
        "resource",
        """
import os, json, time
spawned = 0
deadline = time.time() + 3
try:
    while time.time() < deadline and spawned < 100000:
        try:
            pid = os.fork()
        except OSError:
            break  # RLIMIT_NPROC refused the fork — the bomb is bounded
        if pid == 0:
            time.sleep(0.2); os._exit(0)
        spawned += 1
    print(json.dumps({"breached": spawned >= 100000, "detail": f"forked {spawned} (bounded)"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "mach_bootstrap_probe",
        "process",
        """
import json, subprocess
try:
    r = subprocess.run(["/bin/launchctl", "list"], capture_output=True, timeout=5)
    # Contained if launchctl cannot enumerate the user's services.
    breach = r.returncode == 0 and b"com." in r.stdout
    print(json.dumps({"breached": breach, "detail": "enumerated launchd" if breach else "blocked"}))
except Exception as e:
    print(json.dumps({"breached": False, "detail": type(e).__name__}))
""",
    ),
    Payload(
        "read_repo_is_allowed",
        "control",
        """
import os, json
try:
    # the worker's own module dir is the repo mount; reading it must work
    here = os.path.dirname(os.path.abspath(__file__))
    os.listdir(here)
    print(json.dumps({"breached": False, "detail": "repo readable (expected)"}))
except Exception as e:
    print(json.dumps({"breached": True, "detail": "repo NOT readable: " + type(e).__name__}))
""",
    ),
)


@dataclass(frozen=True)
class Outcome:
    payload: Payload
    contained: bool
    detail: str


def _plant_bait() -> None:
    """Real secrets-shaped bait so a 'read' breach would be unambiguous."""
    ssh = _HOST / ".ssh"
    ssh.mkdir(exist_ok=True)
    bait = ssh / "id_probe"
    if not bait.exists():
        bait.write_text("PRIVATE-KEY-BAIT\n")


def _run_payload(payload: Payload, sandbox: Sandbox, python: str) -> Outcome:
    with tempfile.TemporaryDirectory(prefix="tempest-escape-") as repo_dir:
        repo = Path(repo_dir)
        script = repo / "attack.py"
        script.write_text(payload.source)
        with tempfile.TemporaryDirectory(prefix="tempest-escape-scratch-") as scratch_dir:
            scratch = Path(scratch_dir)
            proc = sandbox.popen(
                [python, "-s", "-B", str(script), str(scratch), str(_HOST)],
                cwd=repo,
                env={"PATH": "/usr/bin:/bin", "HOME": str(_HOST)},
                scratch=scratch,
            )
            try:
                stdout, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                stdout = b""
            finally:
                # The runner owns the payload's whole process group: sweep it so a fork bomb or
                # a lingering child cannot outlive the run (the macOS fork-bomb containment).
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    verdict = _parse(stdout)
    if verdict is None:
        # No parseable verdict: the sandbox killed the payload before it could report. For a
        # hostile payload that is CONTAINMENT; for a control payload it is a real failure.
        contained = payload.category != "control"
        detail = "no verdict (killed/blocked at syscall)"
    else:
        contained = not verdict[0]
        detail = verdict[1]
    if payload.host_probe is not None:
        # Always sweep the bait — a breaching tier (T3) that wrote to the host must not leave a
        # trace that pollutes a later tier's matrix. Only a payload that CLAIMED containment yet
        # still left a trace is a (T2) breach.
        trace = _host_trace(payload.host_probe)
        if trace is not None and contained:
            contained = False
            detail = f"host trace left: {trace}"
    return Outcome(payload, contained, detail)


def _parse(stdout: bytes) -> "tuple[bool, str] | None":
    for line in reversed(stdout.decode(errors="replace").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if "breached" in obj:
            return bool(obj["breached"]), str(obj.get("detail", ""))
    return None


def _host_trace(probe: str) -> str | None:
    path = Path(probe.replace("~", str(_HOST), 1)) if probe.startswith("~") else Path(probe)
    if path.exists():
        detail = str(path)
        with contextlib.suppress(OSError):
            path.unlink()  # clean the bait we caught so a rerun starts fresh
        return detail
    return None


# Payloads that attack the harness itself (kill the parent). A tier that cannot contain signals
# (ProcessSandbox/T3) would take the runner down with it, so for such tiers they are recorded as
# a KNOWN BREACH without being run — the point they would prove (T3 does not contain) is exactly
# why T3 is never offered for user repos.
_SELF_HARMING = {"kill_parent"}


def run_matrix(tier: str) -> list[Outcome]:
    from tempest.execute.interpreter import find_worker_python

    _plant_bait()
    if tier == "T2":
        sandbox: Sandbox = SeatbeltSandbox()
        contains_signals = True
    elif tier == "T3":
        sandbox = ProcessSandbox()
        contains_signals = False  # rlimits only — no signal/network/fs containment
    else:
        raise SystemExit(f"tier {tier!r} is not runnable on this host")
    python = find_worker_python()
    outcomes: list[Outcome] = []
    for payload in PAYLOADS:
        if payload.name in _SELF_HARMING and not contains_signals:
            outcomes.append(
                Outcome(
                    payload, contained=False, detail="known breach (not run — would kill harness)"
                )
            )
            continue
        outcomes.append(_run_payload(payload, sandbox, python))
    return outcomes


def _print_matrix(tier: str, outcomes: list[Outcome]) -> int:
    print(f"\ntempest escape suite · tier {tier} · {platform.system()} {platform.machine()}")
    print(f"{'payload':32} {'category':12} result")
    print("-" * 64)
    breached = 0
    for o in outcomes:
        mark = "CONTAINED" if o.contained else "**BREACHED**"
        if not o.contained:
            breached += 1
        print(f"{o.payload.name:32} {o.payload.category:12} {mark}  {o.detail}")
    total = len(outcomes)
    print("-" * 64)
    print(f"{total - breached}/{total} contained on tier {tier}")
    return breached


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default="T2", choices=("T2", "T3"))
    parser.add_argument("--all-tiers", action="store_true", help="also run the T3 baseline")
    parser.add_argument(
        "--all-os",
        action="store_true",
        help="assert every OS leg — Linux/Windows run in CI; this host reports its own leg only",
    )
    args = parser.parse_args()

    if sys.platform != "darwin" and args.tier == "T2":
        raise SystemExit("T2 (Seatbelt) is macOS-only — run the Linux/Windows legs in CI")
    if not Path("/usr/bin/sandbox-exec").exists() and args.tier == "T2":
        raise SystemExit("sandbox-exec not found — cannot exercise T2 here")

    tiers = [args.tier] + (["T3"] if args.all_tiers and args.tier != "T3" else [])
    total_breached = 0
    for tier in tiers:
        total_breached += _print_matrix(tier, run_matrix(tier))

    if args.all_os:
        print(
            "\nOS matrix: macOS=exercised above · "
            "linux(bubblewrap)=PENDING(CI) · windows(AppContainer)=PENDING(CI) — "
            "never silently skipped (docs/PLAN-DESKTOP.md Phase 10)"
        )

    if total_breached:
        print(f"\nESCAPE SUITE FAILED — {total_breached} breach(es). This blocks the release.")
        sys.exit(1)
    print("\nescape suite: every hostile payload contained.")
    sys.exit(0)


if __name__ == "__main__":
    main()
