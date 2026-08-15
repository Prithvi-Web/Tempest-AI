"""Subprocess coverage bootstrap (100% gate): when the test session exports
COVERAGE_PROCESS_START, every python child on PYTHONPATH-including-this-dir starts coverage
too — the spawned sidecar server and stdio loop are MEASURED, not excused. No-op otherwise."""

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    import coverage

    coverage.process_startup()
