"""Phase 11 perf bench: `make bench` → `bench/bench.json`, judged by `tempest.dev.bench_guard`.

Measures the engine/API half of the Phase 11 targets against a REAL seeded store served by the
REAL stdio sidecar entrypoint (`tempest_api.server --stdio` — the same process the desktop
supervises, minus PyInstaller freezing):

- `cold_launch_s`      — spawn → first getHealth response over stdio (best of 3 cold spawns)
- `list10k_ms`         — listRuns first page against a 10,000-run store (median of 5)
- `observation_5mb_ms` — getDivergence carrying a ~5 MB observation payload (median of 3)
- `idle_rss_mb`        — resident set after the workload, idle
- `idle_cpu_pct`       — CPU over a 5 s idle window

Webview paint metrics (first paint @60fps, app-level cold launch incl. WebKit) belong to the
desktop E2E leg — PENDING(desktop-e2e), stated here so the narrowing is loud, not silent.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Any


def _write_frame(stream: IO[bytes], payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode()
    stream.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
    stream.flush()


def _read_frame(stream: IO[bytes]) -> dict[str, Any]:
    header = bytearray()
    while not header.endswith(b"\r\n\r\n"):
        ch = stream.read(1)
        if not ch:
            raise RuntimeError("sidecar closed its stdout mid-frame")
        header += ch
    length = int(bytes(header).split(b":")[1].strip())
    body = stream.read(length)
    result: dict[str, Any] = json.loads(body)
    return result


class Sidecar:
    """One spawned `tempest_api.server --stdio` process speaking JSON-RPC frames."""

    def __init__(self, data_dir: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "tempest_api.server", "--stdio", "--data-dir", str(data_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._id = 0

    def call(self, method: str, params: dict[str, Any]) -> Any:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self._id += 1
        _write_frame(
            self.proc.stdin,
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
        )
        response = _read_frame(self.proc.stdout)
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response["result"]

    def stop(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)


def _ps(pid: int, fields: str) -> str:
    return subprocess.run(
        ["ps", "-o", fields, "-p", str(pid)], capture_output=True, text=True, check=True
    ).stdout.strip()


def _cputime_seconds(pid: int) -> float:
    raw = _ps(pid, "cputime=")  # "MM:SS.cc" or "HH:MM:SS"
    parts = raw.split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def _rss_mb(pid: int) -> float:
    return float(_ps(pid, "rss=")) / 1024.0


def _measure(data_dir: Path, seed: dict[str, Any]) -> dict[str, float]:
    cold_samples = []
    sidecar: Sidecar | None = None
    for attempt in range(3):
        if sidecar is not None:
            sidecar.stop()
        started = time.perf_counter()
        sidecar = Sidecar(data_dir)
        sidecar.call("getHealth", {})
        cold_samples.append(time.perf_counter() - started)
        print(f"  cold launch #{attempt + 1}: {cold_samples[-1]:.3f}s", file=sys.stderr)
    assert sidecar is not None

    list_samples = []
    for _ in range(5):
        started = time.perf_counter()
        page = sidecar.call("listRuns", {})
        list_samples.append((time.perf_counter() - started) * 1000)
        assert page["items"], "listRuns returned an empty first page on a seeded store"

    observation_samples = []
    for _ in range(3):
        started = time.perf_counter()
        detail = sidecar.call("getDivergence", {"divergence_id": seed["big_divergence_id"]})
        observation_samples.append((time.perf_counter() - started) * 1000)
        assert len(detail["detail"]) >= 5 * 1024 * 1024, "seeded payload is not 5 MB"

    time.sleep(1.0)  # let post-workload work settle before the idle window
    pid = sidecar.proc.pid
    rss_mb = _rss_mb(pid)
    cpu_before, wall_before = _cputime_seconds(pid), time.perf_counter()
    time.sleep(5.0)
    idle_cpu_pct = (
        (_cputime_seconds(pid) - cpu_before) / (time.perf_counter() - wall_before) * 100.0
    )
    sidecar.stop()

    return {
        "cold_launch_s": round(min(cold_samples), 4),
        "list10k_ms": round(statistics.median(list_samples), 2),
        "observation_5mb_ms": round(statistics.median(observation_samples), 2),
        "idle_rss_mb": round(rss_mb, 1),
        "idle_cpu_pct": round(idle_cpu_pct, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10_000)
    parser.add_argument("--out", type=Path, default=Path("bench") / "bench.json")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="tempest-bench-") as tmp:
        data_dir = Path(tmp) / "data"
        print(f"bench: seeding {args.runs} runs + one 5 MB observation…", file=sys.stderr)
        seeded = subprocess.run(
            [
                sys.executable,
                "-m",
                "tempest_api.devseed",
                "--data-dir",
                str(data_dir),
                "--runs",
                str(args.runs),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        seed = json.loads(seeded.stdout)
        metrics = _measure(data_dir, seed)

    payload = {
        "platform": platform.system().lower(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "runs_seeded": args.runs,
        "metrics": metrics,
        "pending": ["desktop-e2e: webview first-paint + app-level cold launch"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
