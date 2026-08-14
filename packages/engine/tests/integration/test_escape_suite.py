"""Phase 10 containment gate as a test (Law L6 on Docker-less machines): every adversarial
payload must be CONTAINED by the macOS T2 Seatbelt backend, and T3 (ProcessSandbox) must be
demonstrably weaker so the tier distinction is real, not cosmetic. Real sandboxes, real
payloads (Law L4). Linux/Windows legs are CI-gated and skipped elsewhere."""

import sys
from pathlib import Path

import pytest

from tempest.dev.escape_suite import PAYLOADS, run_matrix

_MACOS = sys.platform == "darwin"
_HAS_SEATBELT = Path("/usr/bin/sandbox-exec").exists()


@pytest.mark.skipif(not (_MACOS and _HAS_SEATBELT), reason="T2 Seatbelt is macOS-only (CI matrix)")
class TestT2Containment:
    def test_every_payload_is_contained_on_t2(self) -> None:
        outcomes = run_matrix("T2")
        breaches = [o for o in outcomes if not o.contained]
        assert not breaches, "T2 BREACHED: " + ", ".join(
            f"{o.payload.name} ({o.detail})" for o in breaches
        )
        assert len(outcomes) == len(PAYLOADS) >= 25  # the master prompt's 25+ payload bar

    def test_controls_prove_the_sandbox_is_not_just_denying_everything(self) -> None:
        # If the "control" payloads (write scratch, read repo) were blocked, a profile that
        # denies EVERYTHING would pass the hostile checks for the wrong reason. They must pass.
        outcomes = {o.payload.name: o for o in run_matrix("T2")}
        assert outcomes["write_scratch_is_allowed"].contained
        assert outcomes["read_repo_is_allowed"].contained

    def test_t3_is_strictly_weaker_than_t2(self) -> None:
        # ProcessSandbox (T3) contains almost nothing — that is exactly why it is never offered
        # for user repos. If this ever "passes" like T2, tier selection has a hole.
        breaches = [o for o in run_matrix("T3") if not o.contained]
        assert len(breaches) >= 10, "T3 unexpectedly strong — tier selection may be miswired"
