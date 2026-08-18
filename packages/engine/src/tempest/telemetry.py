"""Aggregate telemetry (Phase 17): counters only, strictly opt-in, local-first.

What is counted: run totals, verdict distribution, sandbox-tier distribution, UNPROVEN
reason distribution, total duration. Nothing else exists in the payload — no paths, no repo
names, no source, no timestamps per run (L9 by construction, and re-proven by test). OFF by
default; the user opts in from Settings (`settings.json`) or with `TEMPEST_TELEMETRY=1`, which
outranks the file (tempest.settings). The file never leaves the machine by itself: it is
carried only inside the user-inspectable diagnostic bundle, and network transmission arrives
with the opt-in team sync server (Phase 13) — local mode keeps the L10 zero-egress proof.
"""

import json
import os
from pathlib import Path

from tempest.settings import load_effective_or_defaults

__all__ = ["record_run_aggregate", "telemetry_enabled", "telemetry_path"]


def _data_dir() -> Path:
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest")))


def telemetry_path() -> Path:
    return _data_dir() / "telemetry.json"


def telemetry_enabled() -> bool:
    return load_effective_or_defaults().telemetry_enabled


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
    fresh: dict[str, object] = {
        "runs": 0,
        "verdicts": {},
        "tiers": {},
        "unproven_reasons": {},
        "duration_ms_total": 0,
    }
    try:
        path = telemetry_path()
        try:
            # Review M2: a torn/hand-edited file raised JSONDecodeError past the OSError
            # guard and flipped finished proves to ERROR. Unreadable state = start fresh.
            payload = json.loads(path.read_text()) if path.exists() else fresh
            if not isinstance(payload, dict):
                payload = fresh
        except (OSError, ValueError):
            payload = fresh

        def _count(value: object) -> int:
            return value if isinstance(value, int) else 0

        payload["runs"] = _count(payload.get("runs")) + 1
        for field, key in (("verdicts", verdict), ("tiers", sandbox_tier)):
            bucket = payload.setdefault(field, {})
            if isinstance(bucket, dict):
                bucket[key] = _count(bucket.get(key)) + 1
        reasons = payload.setdefault("unproven_reasons", {})
        if isinstance(reasons, dict):
            for reason in unproven_reasons:
                reasons[reason] = _count(reasons.get(reason)) + 1
        payload["duration_ms_total"] = _count(payload.get("duration_ms_total")) + duration_ms
        path.parent.mkdir(parents=True, exist_ok=True)
        # Review m4: a per-process unique tmp name — two writers sharing one fixed .tmp
        # could publish each other's torn state.
        tmp = path.with_suffix(f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        tmp.replace(path)
    except OSError:
        return
