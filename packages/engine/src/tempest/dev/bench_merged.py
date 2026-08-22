"""Measure the merged app's cold launch — process exec → the authed shell's first request.

`tempest.dev.bench` measures the ENGINE sidecar (spawn → healthy stdio) and its payload has
carried ``pending: app-level cold launch`` since the row existed. This module closes that gap
for the merged app (PLAN-V3 C3; §10 row "Cold launch → chat interactive"): launch the
INSTALLED bundle N times and read the host's own instrument line —

    [tempest-perf] merged_cold_launch_ms=NNN

printed once, at the first ``/api/config`` serve, which is the authed shell up and asking for
its world; the landing paint follows from that same data. The samples land in
``bench/merged-metrics.json`` for ``tempest.dev.bench`` to merge exactly the way the editor
leg's file merges: absent file → the budget stays NOT-YET-MEASURED. Silence is the honest
answer to "nobody measured it" (L22); this module is how somebody measures it.

Scope note: this measures the INSTALLED bundle at its default path (or ``--app``). It does
not build one — a stale install measures stale code, which is why the file carries the HEAD
commit and ``bench`` rejects a mismatch rather than merging it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from tempest.dev.bench import _head_commit

DEFAULT_APP = Path("/Applications/Tempest AI.app/Contents/MacOS/tempest-desktop")
_INSTRUMENT = re.compile(r"^\[tempest-perf\] merged_cold_launch_ms=(\d+)\s*$")


def parse_instrument(line: str) -> float | None:
    """The instrument line's value in milliseconds, or None for any other line."""
    match = _INSTRUMENT.match(line)
    if match is None:
        return None
    return float(match.group(1))


def _measure_once(app: Path, timeout_s: float) -> float | None:
    """One launch → one sample. The app is terminated the moment the line arrives; its
    children exit on parent-death (stdio EOF for the engine, piped stdin for the Node
    sidecar) — the property `orphan_check --after-sigkill` gates."""
    proc = subprocess.Popen(
        [str(app)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    sample: float | None = None
    deadline = time.monotonic() + timeout_s
    try:
        assert proc.stderr is not None  # text+PIPE above; narrows the type
        while time.monotonic() < deadline:
            line = proc.stderr.readline()
            if line == "" and proc.poll() is not None:
                break
            sample = parse_instrument(line)
            if sample is not None:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    return sample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=DEFAULT_APP)
    parser.add_argument("--launches", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", type=Path, default=Path("bench") / "merged-metrics.json")
    args = parser.parse_args(argv)

    if not args.app.is_file():
        print(
            f"bench_merged: {args.app} not found — install the bundle first "
            f"(pnpm tauri build + ditto). A measurement of nothing is not a measurement.",
            file=sys.stderr,
        )
        return 2

    samples: list[float] = []
    for launch_index in range(args.launches):
        print(
            f"bench_merged: launch {launch_index + 1}/{args.launches}…",
            file=sys.stderr,
        )
        sample = _measure_once(args.app, args.timeout)
        if sample is None:
            print(
                f"bench_merged: launch {launch_index + 1} produced no instrument line within "
                f"{args.timeout:.0f}s — no file written. Every sample is real or the "
                f"measurement does not exist.",
                file=sys.stderr,
            )
            return 1
        samples.append(sample)
        # Let the previous instance's children finish exiting before the next spawn, so
        # launch N+1 never pays for launch N's teardown.
        time.sleep(2.0)

    payload = {
        "commit": _head_commit(),
        "measured_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "app": str(args.app),
        "samples": {"merged_cold_launch_ms": samples},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    best_s = min(samples) / 1000.0
    print(
        f"bench_merged: {len(samples)} launches, best {best_s:.3f}s → {args.out} "
        f"(merged by the next `make bench`)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
