"""Battery/thermal pause (L11): a prove yields to the machine, never fights it.

`power_pause_reason()` answers "should new work pause right now?" — precedence:
`TEMPEST_FORCE_POWER_PAUSE` (tests force a reason) > `TEMPEST_NO_POWER_PAUSE=1` (user opt-out;
also set by the repo's own gates so verification never hangs on an unplugged laptop) > the real
probes (macOS `pmset`: battery power, thermal CPU speed limit; other platforms report nothing
yet — the Linux/Windows probes ride those Phase 10 CI legs). Probe failures mean "don't pause":
a broken pmset must never stall a prove.

`wait_while_paused` is the checkpoint `run_prove` calls between units of work: it holds while
a reason persists, reports the reason once, and a cancel unblocks it immediately.
"""

import os
import subprocess
import sys
import time
from collections.abc import Callable

from tempest.execute.cancel import CancelScope

_PROBE_CACHE_S = 5.0
_probe_cache: tuple[float, str | None] | None = None


def _pmset(*args: str) -> str:
    return subprocess.run(
        ["pmset", *args], capture_output=True, text=True, timeout=5, check=False
    ).stdout


def _darwin_probe() -> str | None:
    try:
        if "Battery Power" in _pmset("-g", "batt"):
            return "on battery power"
        for line in _pmset("-g", "therm").splitlines():
            if "CPU_Speed_Limit" in line:
                limit = int(line.split("=")[1].strip())
                if limit < 100:
                    return f"thermal pressure (CPU speed limited to {limit}%)"
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None  # a broken probe must never stall a prove
    return None


def power_pause_reason() -> str | None:
    forced = os.environ.get("TEMPEST_FORCE_POWER_PAUSE")
    if forced:
        return forced
    if os.environ.get("TEMPEST_NO_POWER_PAUSE"):
        return None
    if sys.platform != "darwin":
        return None
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and now - _probe_cache[0] < _PROBE_CACHE_S:
        return _probe_cache[1]
    reason = _darwin_probe()
    _probe_cache = (now, reason)
    return reason


def wait_while_paused(
    *,
    cancel: CancelScope | None,
    notify: Callable[[str], None] | None,
    poll_s: float = 1.0,
) -> None:
    """Hold while a pause condition persists. Reports the reason once per pause episode;
    cancellation unblocks immediately (raises ProveCancelled)."""
    notified = False
    while True:
        if cancel is not None:
            cancel.raise_if_cancelled()
        reason = power_pause_reason()
        if reason is None:
            return
        if not notified and notify is not None:
            notify(reason)
            notified = True
        step = min(poll_s, 0.05)
        slept = 0.0
        while slept < poll_s:
            if cancel is not None:
                cancel.raise_if_cancelled()
            time.sleep(step)
            slept += step
