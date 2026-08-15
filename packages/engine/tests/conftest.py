"""Suite-wide defaults. The battery/thermal pause (L11) must never stall the test suite on an
unplugged laptop — tests that exercise the pause force it explicitly via
TEMPEST_FORCE_POWER_PAUSE, which outranks this opt-out. Subprocess coverage (100% gate):
python children started by tests collect coverage too, via scripts/covstart/sitecustomize.py."""

import os
from pathlib import Path

os.environ.setdefault("TEMPEST_NO_POWER_PAUSE", "1")

_REPO = Path(__file__).resolve().parents[3]
os.environ.setdefault("COVERAGE_PROCESS_START", str(_REPO / "pyproject.toml"))
_COVSTART = str(_REPO / "scripts" / "covstart")
if _COVSTART not in os.environ.get("PYTHONPATH", ""):
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (_COVSTART, os.environ.get("PYTHONPATH", "")) if p
    )
