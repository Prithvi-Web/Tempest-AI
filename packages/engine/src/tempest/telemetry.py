"""Aggregate telemetry (Phase 17): counters only, strictly opt-in, local-first.

What is counted: run totals, verdict distribution, sandbox-tier distribution, UNPROVEN
reason distribution, total duration. Nothing else exists in the payload — no paths, no repo
names, no source, no timestamps per run (L9 by construction, and re-proven by test). OFF by
default; `TEMPEST_TELEMETRY=1` opts in. The file never leaves the machine by itself: it is
carried only inside the user-inspectable diagnostic bundle, and network transmission arrives
with the opt-in team sync server (Phase 13) — local mode keeps the L10 zero-egress proof.
"""

import json
import os
from pathlib import Path


def _data_dir() -> Path:
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest")))


def telemetry_path() -> Path:
    return _data_dir() / "telemetry.json"


def telemetry_enabled() -> bool:
    return os.environ.get("TEMPEST_TELEMETRY") == "1"


def record_run_aggregate(
    *,
    verdict: str,
    sandbox_tier: str,
    unproven_reasons: tuple[str, ...],
    duration_ms: int,
) -> None:
    """Fold one finished run into the counters. A failure to write is swallowed — telemetry
    must never break a prove."""
    if not telemetry_enabled():
        return
    try:
        path = telemetry_path()
        if path.exists():
            payload = json.loads(path.read_text())
        else:
            payload = {
                "runs": 0,
                "verdicts": {},
                "tiers": {},
                "unproven_reasons": {},
                "duration_ms_total": 0,
            }
        payload["runs"] += 1
        payload["verdicts"][verdict] = payload["verdicts"].get(verdict, 0) + 1
        payload["tiers"][sandbox_tier] = payload["tiers"].get(sandbox_tier, 0) + 1
        for reason in unproven_reasons:
            payload["unproven_reasons"][reason] = payload["unproven_reasons"].get(reason, 0) + 1
        payload["duration_ms_total"] += duration_ms
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        tmp.replace(path)
    except OSError:
        return
