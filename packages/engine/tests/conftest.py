"""Suite-wide defaults. The battery/thermal pause (L11) must never stall the test suite on an
unplugged laptop — tests that exercise the pause force it explicitly via
TEMPEST_FORCE_POWER_PAUSE, which outranks this opt-out."""

import os

os.environ.setdefault("TEMPEST_NO_POWER_PAUSE", "1")
