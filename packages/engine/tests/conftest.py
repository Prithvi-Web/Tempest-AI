"""Suite-wide defaults. The battery/thermal pause (L11) must never stall the test suite on an
unplugged laptop — tests that exercise the pause force it explicitly via
TEMPEST_FORCE_POWER_PAUSE, which outranks this opt-out. Subprocess coverage (100% gate):
python children started by tests collect coverage too, via scripts/covstart/sitecustomize.py."""

import os
from pathlib import Path

os.environ.setdefault("TEMPEST_NO_POWER_PAUSE", "1")

# Hermetic keyless default (L10): a developer's real Anthropic key in the shell must never
# reach the suite — an instance-method target would silently attempt real egress. Synthesis
# tests opt in with a planted fake key pointed at a local Messages-API peer.
for _synth_var in (
    "ANTHROPIC_API_KEY",
    "TEMPEST_SYNTHESIS_BASE_URL",
    "TEMPEST_SYNTHESIS_MODEL",
    "TEMPEST_NO_SYNTHESIS",
):
    os.environ.pop(_synth_var, None)

_REPO = Path(__file__).resolve().parents[3]
os.environ.setdefault("COVERAGE_PROCESS_START", str(_REPO / "pyproject.toml"))
_COVSTART = str(_REPO / "scripts" / "covstart")
if _COVSTART not in os.environ.get("PYTHONPATH", ""):
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (_COVSTART, os.environ.get("PYTHONPATH", "")) if p
    )
