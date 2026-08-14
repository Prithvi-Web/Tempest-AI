"""Phase 11 soak: `python -m tempest.dev.soak --minutes 480` (the 8-hour gate).

One real stdio sidecar process, hours of mixed REAL work — repeated micro-proves (full engine
loop: worker spawning, sandboxing, ingest), run listings, FTS searches, and periodic 5 MB
observation pulls — with RSS sampled throughout. PASS iff memory growth from the post-warmup
baseline to the final stretch stays under --max-growth-pct (default 10, the PLAN target).

Writes `bench/soak.json` and prints it. TEMPEST_NO_POWER_PAUSE is set for the sidecar: a soak
must measure leaks, not the battery pause (which has its own tests).
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tempest.dev.bench import Sidecar, _rss_mb


def _micro_repo(parent: Path) -> Path:
    repo = parent / "soak-repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "soak",
                "GIT_AUTHOR_EMAIL": "s@s",
                "GIT_COMMITTER_NAME": "soak",
                "GIT_COMMITTER_EMAIL": "s@s",
                "PATH": "/usr/bin:/bin",
                "HOME": str(repo),
            },
        )

    git("init", "-b", "main")
    (repo / ".tempest-first-party").write_text("tempest-first-party-fixture-v1\n")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    git("add", "-A")
    git("commit", "-m", "base", "--no-gpg-sign")
    git("branch", "base")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    git("add", "-A")
    git("commit", "-m", "head", "--no-gpg-sign")
    git("branch", "head")
    return repo


def _wait_run_terminal(sidecar: Sidecar, run_id: int, timeout_s: float = 120.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = str(sidecar.call("getRun", {"run_id": run_id})["status"])
        if status != "PENDING":
            return status
        time.sleep(0.25)
    return "TIMEOUT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=480.0)
    parser.add_argument("--max-growth-pct", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("bench") / "soak.json")
    args = parser.parse_args(argv)

    os.environ.setdefault("TEMPEST_DEV", "1")  # first-party micro repo under ProcessSandbox
    os.environ.setdefault("TEMPEST_NO_POWER_PAUSE", "1")

    with tempfile.TemporaryDirectory(prefix="tempest-soak-") as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tempest_api.devseed",
                "--data-dir",
                str(data_dir),
                "--runs",
                "1000",
            ],
            check=True,
            capture_output=True,
        )
        repo = _micro_repo(Path(tmp))
        sidecar = Sidecar(data_dir)
        sidecar.call("getHealth", {})
        pid = sidecar.proc.pid

        started = time.monotonic()
        deadline = started + args.minutes * 60
        samples: list[tuple[float, float]] = []  # (elapsed_s, rss_mb)
        iterations = proves = failures = 0
        last_sample = 0.0

        while time.monotonic() < deadline:
            iterations += 1
            page = sidecar.call("listRuns", {})
            sidecar.call("getRun", {"run_id": page["items"][0]["id"]})
            sidecar.call("searchDivergences", {"q": "payload", "limit": 10})
            if iterations % 10 == 1:  # periodic 5 MB observation pull
                hits = sidecar.call("searchDivergences", {"q": "offset", "limit": 1})["hits"]
                if hits:
                    sidecar.call("getDivergence", {"divergence_id": hits[0]["divergence_id"]})
            created = sidecar.call(
                "startLocalProve",
                {
                    "body": {
                        "repo_path": str(repo),
                        "base": "base",
                        "head": "head",
                        "max_inputs": 4,
                    }
                },
            )
            proves += 1
            if _wait_run_terminal(sidecar, created["run_id"]) not in ("COMPLETE",):
                failures += 1
            elapsed = time.monotonic() - started
            if elapsed - last_sample >= 30.0:
                samples.append((round(elapsed, 1), _rss_mb(pid)))
                last_sample = elapsed
                print(
                    f"soak: {elapsed / 60:.1f}m rss={samples[-1][1]:.1f}MB "
                    f"iters={iterations} proves={proves} failures={failures}",
                    file=sys.stderr,
                )
        samples.append((round(time.monotonic() - started, 1), _rss_mb(pid)))
        sidecar.stop()

    tail = max(1, len(samples) // 10)
    warmup_cut = max(1, len(samples) // 10)  # discard the first 10% as warmup
    baseline = statistics.mean(rss for _, rss in samples[warmup_cut : warmup_cut + tail])
    final = statistics.mean(rss for _, rss in samples[-tail:])
    growth_pct = (final - baseline) / baseline * 100.0 if baseline > 0 else 0.0
    ok = growth_pct < args.max_growth_pct and failures == 0

    payload = {
        "minutes": args.minutes,
        "iterations": iterations,
        "proves": proves,
        "prove_failures": failures,
        "baseline_rss_mb": round(baseline, 1),
        "final_rss_mb": round(final, 1),
        "growth_pct": round(growth_pct, 2),
        "max_growth_pct": args.max_growth_pct,
        "samples": samples,
        "pass": ok,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "samples"}, indent=2))
    verdict = "PASS" if ok else "FAIL"
    print(f"soak: {verdict} (growth {growth_pct:.2f}%, bar {args.max_growth_pct}%)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
