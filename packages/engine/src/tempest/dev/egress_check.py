"""L10 EGRESS GATE: `python -m tempest.dev.egress_check --expect-zero`.

Law L10 — egress is tested, not promised. Every network-reaching payload in the escape corpus
is run inside the T2 sandbox and must be blocked; the sandbox's `(deny network*)` rule stops the
connection at the socket syscall, so no packet is ever emitted. The count of successful outbound
connections must be exactly zero, or the build fails. The output is a sales artifact (§10).

Scope, stated honestly: on macOS T2 the guarantee is enforced and verified at the syscall layer
(a denied socket never produces a packet). Full packet-capture inside a deny-all network
namespace is the Linux-netns CI leg (a namespace is a Linux construct); this host runs the
syscall-level proof and marks the netns leg PENDING(CI) rather than skipping it silently.
"""

import argparse
import sys
from pathlib import Path

from tempest.dev.escape_suite import PAYLOADS, run_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-zero", action="store_true", required=True)
    parser.add_argument("--tier", default="T2", choices=("T2", "T3"))
    args = parser.parse_args()

    if sys.platform != "darwin" and args.tier == "T2":
        raise SystemExit("T2 (Seatbelt) is macOS-only — run the Linux netns egress leg in CI")
    if args.tier == "T2" and not Path("/usr/bin/sandbox-exec").exists():
        raise SystemExit("sandbox-exec not found — cannot verify egress on T2 here")

    network_payloads = {p.name for p in PAYLOADS if p.category == "network"}
    outcomes = [o for o in run_matrix(args.tier) if o.payload.name in network_payloads]

    print(f"\ntempest egress check · tier {args.tier} · {len(outcomes)} network vectors")
    print("-" * 56)
    escaped = 0
    for o in outcomes:
        blocked = o.contained
        if not blocked:
            escaped += 1
        print(f"  {o.payload.name:26} {'BLOCKED' if blocked else '**EGRESS**'}  {o.detail}")
    print("-" * 56)
    print(f"outbound connections that succeeded: {escaped} (required: 0)")
    print("netns packet-capture leg: PENDING(CI, Linux) — docs/PLAN-DESKTOP.md Phase 10")

    if escaped:
        print("\nL10 VIOLATED — traffic escaped the sandbox. This blocks the release.")
        sys.exit(1)
    print("\negress check: zero outbound connections from sandboxed runner code (L10).")
    sys.exit(0)


if __name__ == "__main__":
    main()
