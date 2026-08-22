"""Phase 11 perf bench: `make bench` → `bench/bench.json`, judged by `tempest.dev.bench_guard`.

Measures the engine/API half of the Phase 11 targets against a REAL seeded store served by the
REAL stdio sidecar entrypoint (`tempest_api.server --stdio` — the same process the desktop
supervises, minus PyInstaller freezing):

- `cold_launch_s`      — spawn → first getHealth response over stdio (best of 3 cold spawns)
- `list10k_ms`         — listRuns first page against a 10,000-run store (median of 5)
- `observation_5mb_ms` — getDivergence carrying a ~5 MB observation payload (median of 3)
- `idle_rss_mb`        — resident set after the workload, idle
- `idle_cpu_pct`       — CPU over a 5 s idle window
- `conditions`         — what ELSE the machine was doing, so a number carries its own error bars
- `open_file_ms`       — editor: request → document on screen (desktop E2E, Phase 20.1b)
- `keystroke_ms`       — editor: keydown → the frame that shows it (desktop E2E, Phase 20.1b)
- `completion_ms`      — editor: F11 → ghost text on screen (desktop E2E, Phase 20.3c)

The last two are WEBVIEW facts and cannot be measured from here: they come from
`bench/editor-metrics.json`, which the Playwright leg writes (`make bench-editor`). When that
file is absent the keys are simply omitted, and `perf_suite` reports the budgets as
NOT-YET-MEASURED. A missing measurement must never read as a met budget — and neither must a
STALE one: a file recorded against a different commit is discarded, not merged.

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


#: The metrics `_measure` takes in THIS process, and therefore the only ones the load sample in
#: `conditions` can speak for. The editor metrics are deliberately absent — see `conditions_block`.
MEASURED_IN_PROCESS: frozenset[str] = frozenset(
    {"cold_launch_s", "list10k_ms", "observation_5mb_ms", "idle_rss_mb", "idle_cpu_pct"}
)


def machine_conditions() -> dict[str, Any]:
    """One sample of what else this machine was doing, as a fact with a stated source.

    `os.getloadavg()[0]` is the 1-minute run-queue average — the standard "how contended is this
    box" number. When it cannot be had the answer is a recorded `unavailable` **with the reason**,
    never a `0.0`: a fabricated zero reads as a perfectly idle machine, which is the most
    flattering lie this module could tell and precisely the failure it exists to prevent (L22).

    **Two different failures, and an earlier version of this code caught only one.** CPython
    defines `getloadavg` only under `HAVE_GETLOADAVG`, so on Windows the attribute *does not
    exist* and the lookup raises `AttributeError` — which is **not** a subclass of `OSError`.
    A bare `except OSError` therefore let the very platform this branch was written for crash
    `make bench` at its first statement, before any measurement was taken, while the docstring
    promised a recorded `unavailable`. Both are caught now, and both are tested. (Trap 45: the
    prose explaining why something is safe is a claim, and this one was false.)

    `cpu_count` rides along because a load average alone means nothing — 4.0 is idle on 32 cores
    and saturated on 2. `os.cpu_count()` may itself answer `None`; that is carried through as
    `None` rather than defaulted to 1, which would divide by 1 and call a quiet machine saturated.

    This function records. It does NOT judge: what counts as "quiet" is `perf_suite`'s bar, so
    that changing the bar does not require re-taking every measurement, and so that a measurement
    file never carries a verdict its own author chose (trap 47).
    """
    cpu_count = os.cpu_count()
    try:
        load_1m = os.getloadavg()[0]
    except (OSError, AttributeError) as exc:
        # AttributeError is the Windows case (the symbol is absent, not failing); OSError is the
        # documented failure where it exists. Catching only OSError crashed the former.
        return {
            "source": "unavailable",
            "reason": f"{type(exc).__name__}: {exc}",
            "load_avg_1m": None,
            "cpu_count": cpu_count,
        }
    return {"source": "os.getloadavg", "load_avg_1m": round(load_1m, 3), "cpu_count": cpu_count}


def conditions_block(*, background: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    """Merge the two samples into the block `bench.json` carries, naming which one may be judged.

    **Only the background sample is honest about foreign load.** It is taken before a single byte
    of bench work happens; every later sample includes this process seeding `--runs` runs (10,000
    by default), so a later reading cannot tell someone else's compile from our own `devseed`.
    The final sample is recorded anyway — a large gap between the two is informative to a human —
    but the gate is told, in the payload itself, that `background` is the one it may use.

    A limitation this cannot see, stated rather than left implicit: load that STARTS after the
    background sample is invisible here. The background reading answers "was the machine busy when
    we began", which is the question that has actually been costing this project sessions.
    """
    block: dict[str, Any] = {
        "source": background["source"],
        "cpu_count": background.get("cpu_count"),
        "load_avg_1m_background": background.get("load_avg_1m"),
        "load_avg_1m_final": final.get("load_avg_1m"),
        "judged_on": "load_avg_1m_background",
        # WHICH METRICS THIS SAMPLE IS ABOUT. Not decoration: `open_file_ms`, `keystroke_ms` and
        # `completion_ms` are NOT measured by this process. They are merged out of
        # `bench/editor-metrics.json`, which `make bench-editor` writes in a separate Playwright
        # run, gated only on a matching HEAD — so it can be hours old and taken under entirely
        # different load. A sample taken here says nothing about that run, in either direction,
        # and a gate that qualified those rows with it would be answering about the wrong process.
        # `perf_suite` qualifies only the metrics named here.
        "covers": sorted(MEASURED_IN_PROCESS),
        "note": (
            "the final sample includes this bench's own seeding work and cannot separate foreign "
            "load from our own, so it is recorded and never judged on; load that starts after "
            "the background sample is invisible to both"
        ),
    }
    if "reason" in background:
        block["reason"] = background["reason"]
    return block


def _editor_measurements(
    path: Path,
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, Any] | None]:
    """Read the webview measurements the desktop E2E leg wrote, if it has run.

    Returns `({}, {}, None)` when the file is absent or unusable, which leaves the editor budgets
    NOT-YET-MEASURED rather than met. Silence is the honest answer to "nobody measured it"; a
    zero, a default, or a skipped row would all read as success (L22).
    """
    if not path.is_file():
        return {}, {}, None
    try:
        doc: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}, None
    if not isinstance(doc, dict):
        return {}, {}, None
    raw: Any = doc.get("samples")
    if not isinstance(raw, dict):
        return {}, {}, None

    metrics: dict[str, float] = {}
    samples: dict[str, list[float]] = {}
    for name in ("open_file_ms", "keystroke_ms", "completion_ms"):
        series: Any = raw.get(name)
        if not isinstance(series, list):
            continue
        numeric = [float(v) for v in series if isinstance(v, (int, float))]
        # One sample is an anecdote: a p50 over a single reading is that reading, and it would
        # arm a budget on the strength of one keystroke.
        if len(numeric) < 5:
            continue
        metrics[name] = round(statistics.median(numeric), 3)
        samples[name] = numeric
    if not metrics:
        return {}, {}, None

    # Provenance is CHECKED, not merely recorded. The first version wrote the commit into
    # bench.json and claimed that "a stale file cannot pass as this run's work" — but nothing
    # ever read it back, so a measurement from three commits ago merged silently and armed the
    # budgets with numbers describing code that no longer exists. Recording is not rejecting.
    head = _head_commit()
    measured_at_commit = doc.get("commit")
    if head is not None and isinstance(measured_at_commit, str) and measured_at_commit != head:
        return {}, {}, None

    provenance = {
        "commit": measured_at_commit,
        "measured_at": doc.get("measured_at"),
        "counts": {name: len(series) for name, series in samples.items()},
    }
    return metrics, samples, provenance


def _merged_measurements(
    path: Path,
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, Any] | None]:
    """Read the merged-app cold-launch samples `tempest.dev.bench_merged` wrote, if it ran.

    Same contract as the editor leg: absent or unusable → `({}, {}, None)` and the budget
    stays NOT-YET-MEASURED; a file from another commit is rejected, not merged (provenance is
    checked, not merely recorded). The metric is the BEST launch, the same aggregate
    `cold_launch_s` already uses — the floor is what the budget governs.
    """
    if not path.is_file():
        return {}, {}, None
    try:
        doc: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}, None
    if not isinstance(doc, dict):
        return {}, {}, None
    raw: Any = doc.get("samples")
    if not isinstance(raw, dict):
        return {}, {}, None
    series: Any = raw.get("merged_cold_launch_ms")
    if not isinstance(series, list):
        return {}, {}, None
    numeric = [float(v) for v in series if isinstance(v, (int, float))]
    # Best-of-three mirrors bench's own cold_launch sampling; fewer launches is an anecdote
    # about a warm cache, not a cold-launch measurement.
    if len(numeric) < 3:
        return {}, {}, None
    head = _head_commit()
    measured_at_commit = doc.get("commit")
    if head is not None and isinstance(measured_at_commit, str) and measured_at_commit != head:
        return {}, {}, None
    metrics = {"merged_cold_launch_s": round(min(numeric) / 1000.0, 4)}
    samples = {"merged_cold_launch_ms": numeric}
    provenance = {
        "commit": measured_at_commit,
        "measured_at": doc.get("measured_at"),
        "app": doc.get("app"),
        "counts": {"merged_cold_launch_ms": len(numeric)},
    }
    return metrics, samples, provenance


def _head_commit() -> str | None:
    """The commit the tree is on, or None when that cannot be established.

    None means "do not judge": a tarball or a detached checkout without git is not a reason to
    throw away a real measurement. A MISMATCH is a reason.
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10_000)
    parser.add_argument("--out", type=Path, default=Path("bench") / "bench.json")
    parser.add_argument(
        "--editor-metrics", type=Path, default=Path("bench") / "editor-metrics.json"
    )
    parser.add_argument(
        "--merged-metrics", type=Path, default=Path("bench") / "merged-metrics.json"
    )
    args = parser.parse_args(argv)

    # BEFORE anything: the only reading that is about the machine rather than about us.
    background = machine_conditions()

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

    editor_metrics, editor_samples, editor_provenance = _editor_measurements(args.editor_metrics)
    metrics.update(editor_metrics)
    merged_metrics, merged_samples, merged_provenance = _merged_measurements(args.merged_metrics)
    metrics.update(merged_metrics)

    payload: dict[str, Any] = {
        "platform": platform.system().lower(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "runs_seeded": args.runs,
        "conditions": conditions_block(background=background, final=machine_conditions()),
        "metrics": metrics,
        "pending": ["desktop-e2e: webview first-paint"],
    }
    if editor_samples:
        # Raw samples, not an aggregate: a p95 cannot be derived from a mean, and perf_suite
        # refuses to invent one (it reports NOT-YET-MEASURED instead).
        payload["samples"] = editor_samples
    if merged_samples:
        existing = payload.get("samples")
        payload["samples"] = {
            **(existing if isinstance(existing, dict) else {}),
            **merged_samples,
        }
    if editor_provenance is not None:
        # Where the webview numbers came from, so a stale file cannot pass as this run's work.
        payload["editor_metrics_from"] = editor_provenance
    elif not editor_metrics:
        payload["pending"].append(
            "editor: run `make bench-editor` — open_file_ms/keystroke_ms are NOT-YET-MEASURED"
        )
    if merged_provenance is not None:
        payload["merged_metrics_from"] = merged_provenance
    elif not merged_metrics:
        payload["pending"].append(
            "merged app: install the bundle and run `make bench-merged` — "
            "merged_cold_launch_s is NOT-YET-MEASURED"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
