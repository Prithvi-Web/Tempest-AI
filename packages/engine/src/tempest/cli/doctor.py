"""`tempest doctor` (Phase 17): health self-check with a copy-pasteable report.

Verifies what a support thread needs on line one: versions, git, the sandbox tier this
machine would actually get (same ladder and env overrides as a real prove), an execution
smoke test, data-dir writability + disk headroom, and the power-pause state. Exit 0 only
when every load-bearing check passes; a pause condition is a warning, not a failure."""

import json as jsonlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

import tempest
from tempest.execute.powerstate import power_pause_reason
from tempest.execute.sandbox import select_sandbox


def _data_dir() -> Path:
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest")))


def _git_version() -> str | None:
    try:
        out = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except OSError:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _execution_smoke() -> bool:
    """Can this machine spawn a worker interpreter at all?"""
    try:
        probe = subprocess.run(
            [sys.executable, "-S", "-c", "print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError:
        return False
    return probe.returncode == 0 and probe.stdout.strip() == "ok"


def _data_dir_writable(data_dir: Path) -> bool:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".doctor-"):
            return True
    except OSError:
        return False


def collect_payload() -> dict[str, Any]:
    """The full health report as data — shared by `doctor` and the diagnostic bundle."""
    selection = select_sandbox(
        docker_binary=os.environ.get("TEMPEST_DOCKER", "docker"),
        allow_seatbelt=os.environ.get("TEMPEST_NO_SEATBELT") != "1",
    )
    data_dir = _data_dir()
    disk_free_gb = shutil.disk_usage(data_dir if data_dir.exists() else Path.home()).free / 1e9
    git = _git_version()
    checks: dict[str, bool] = {
        "sandbox_available": selection.sandbox is not None,
        "git_available": git is not None,
        "execution_smoke": _execution_smoke(),
        "data_dir_writable": _data_dir_writable(data_dir),
        "disk_headroom_1gb": disk_free_gb >= 1.0,
    }
    return {
        "ok": all(checks.values()),
        "tempest": tempest.__version__,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "git": git,
        "sandbox": {
            "tier": selection.tier,
            "kind": selection.kind,
            "assurance": selection.assurance,
            "reason": selection.reason,
        },
        "data_dir": str(data_dir),
        "disk_free_gb": round(disk_free_gb, 1),
        "power_pause": power_pause_reason(),
        "checks": checks,
    }


def run_doctor(json_output: bool) -> int:
    console = Console()
    payload = collect_payload()
    ok: bool = payload["ok"]
    checks = payload["checks"]
    pause = payload["power_pause"]
    data_dir, disk_free_gb = payload["data_dir"], payload["disk_free_gb"]
    selection_view: dict[str, Any] = payload["sandbox"]
    git = payload["git"]
    if json_output:
        console.print_json(jsonlib.dumps(payload))
        return 0 if ok else 1

    console.print(f"tempest {tempest.__version__} · python {payload['python']}")
    console.print(f"platform: {payload['platform']} · git: {git or 'MISSING'}")
    if checks["sandbox_available"]:
        console.print(
            f"sandbox: {selection_view['tier']} ({selection_view['kind']}, "
            f"assurance {selection_view['assurance']})"
        )
    else:
        console.print(f"sandbox: NONE — {selection_view['reason']}")
    console.print(f"data dir: {data_dir} · disk free: {disk_free_gb:.1f} GB")
    if pause is not None:
        console.print(f"power: would pause — {pause}")
    else:
        console.print("power: ok")
    for name, passed in checks.items():
        console.print(f"  {'ok  ' if passed else 'FAIL'} {name}")
    console.print("doctor: all checks passed" if ok else "doctor: FAIL — see above")
    return 0 if ok else 1


def register(app: typer.Typer) -> None:
    @app.command()
    def doctor(
        json_output: bool = typer.Option(False, "--json", help="machine-readable report"),
    ) -> None:
        """Health self-check: sandbox tier, execution, disk, power — copy-pasteable."""
        raise typer.Exit(run_doctor(json_output))
