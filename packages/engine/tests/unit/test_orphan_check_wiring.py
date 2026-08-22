"""The orphan gate must be RUNNABLE as `python -m` — a module without its main guard imports
cleanly, prints nothing, and exits 0, which reads exactly like a pass (trap-47's class: a
ruler that measured nothing reporting green). Caught live at C2: the --all-children run's
first invocation produced zero output and exit 0; only the silence gave it away."""

import subprocess
import sys


def test_the_gate_runs_main_under_python_dash_m() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tempest.dev.orphan_check", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--all-children" in result.stdout, (
        "argparse help must render — silence here means the __main__ guard is gone and "
        "`python -m` would exit 0 having checked nothing"
    )
