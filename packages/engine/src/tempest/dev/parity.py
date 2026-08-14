"""THE CLI↔DESKTOP PARITY GATE: `python -m tempest.dev.parity --cli-vs-desktop`.

The CLI (in-process `run_prove`) and the FROZEN desktop sidecar (the shipped PyInstaller
binary, driven over its real stdio JSON-RPC transport) prove the same commit pair of the same
repository at the same budget and seed. The two bundles must be byte-identical: `targets.json`
and every repro script exactly equal, manifests equal apart from `created_at` (timestamps are
recorded, never compared). Divergence here means the desktop app ships different results than
the CLI for identical inputs — the §4 "never diverge" invariant, tested rather than promised.

The fixture is pure-function only, deliberately: impure targets embed per-run recorded values
in their observations (each run records its own cassette — correct under L3), so cross-run
byte-parity is a pure-target property.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, cast

_MARKER = "tempest-first-party-fixture-v1"
_BUDGET = 20


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _default_server_bin(root: Path) -> Path:
    triple = {
        "arm64": "aarch64-apple-darwin",
        "x86_64": "x86_64-apple-darwin",
    }.get(platform.machine(), "aarch64-apple-darwin")
    return root / "packages" / "desktop" / "src-tauri" / "binaries" / f"tempest-server-{triple}"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _fixture_repo(parent: Path) -> Path:
    repo = parent / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".tempest-first-party").write_text(_MARKER + "\n")
    (repo / "shape.py").write_text(
        "def clamp(x: int) -> int:\n    return max(0, min(100, x))\n\n\n"
        "def total(xs: list[int]) -> int:\n    s = 0\n"
        "    for x in xs:\n        s += x\n    return s\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    (repo / "shape.py").write_text(
        "def clamp(x: int) -> int:\n    return max(1, min(100, x))\n\n\n"
        "def total(xs: list[int]) -> int:\n    return sum(xs)\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")
    return repo


def _cli_bundle(repo: Path, out: Path) -> Path:
    from tempest.prove import ProveConfig, run_prove

    result = run_prove(
        ProveConfig(repo=repo, base="base", head="head", max_inputs=_BUDGET, seed=0, out=out)
    )
    return result.bundle_dir


class _StdioClient:
    """Minimal JSON-RPC client over the frozen sidecar's pipes (the real desktop transport)."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        self.proc = proc
        self._next_id = 0

    def call(self, method: str, params: dict[str, object]) -> object:
        from tempest_api.stdiorpc import read_frame, write_frame

        assert self.proc.stdin is not None and self.proc.stdout is not None
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        write_frame(cast(BinaryIO, self.proc.stdin), json.dumps(request).encode())
        payload = read_frame(cast(BinaryIO, self.proc.stdout))
        if payload is None:
            raise SystemExit("frozen sidecar closed the RPC channel")
        response = json.loads(payload)
        if "error" in response:
            raise SystemExit(f"frozen sidecar error on {method}: {response['error']}")
        return response["result"]


def _desktop_bundle(server_bin: Path, repo: Path, data_dir: Path) -> Path:
    env = {**os.environ, "TEMPEST_DEV": "1"}  # first-party fixture rule (ADR-0008)
    proc = subprocess.Popen(
        [str(server_bin), "--stdio", "--data-dir", str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    try:
        rpc = _StdioClient(proc)
        started = rpc.call(
            "startLocalProve",
            {
                "body": {
                    "repo_path": str(repo),
                    "base": "base",
                    "head": "head",
                    "max_inputs": _BUDGET,
                }
            },
        )
        assert isinstance(started, dict)
        run_id = started["run_id"]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            run = rpc.call("getRun", {"run_id": run_id})
            assert isinstance(run, dict)
            if run["status"] in ("COMPLETE", "ERROR"):
                if run["status"] != "COMPLETE":
                    raise SystemExit(f"desktop prove errored: {run}")
                break
            time.sleep(0.5)
        else:
            raise SystemExit("desktop prove never completed")
        rpc.call("rpc.shutdown", {})
        proc.wait(timeout=30)
        return data_dir / "local-runs" / f"run-{run_id}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def _compare(cli_dir: Path, desktop_dir: Path) -> list[str]:
    import difflib

    problems: list[str] = []
    for name in ("targets.json",):
        cli_text = (cli_dir / name).read_text()
        desk_text = (desktop_dir / name).read_text()
        if cli_text != desk_text:
            hunk = list(
                difflib.unified_diff(
                    cli_text.splitlines(), desk_text.splitlines(), "cli", "desktop", lineterm=""
                )
            )[:24]
            problems.append(f"{name} differs:\n" + "\n".join(hunk))
    cli_repros = sorted(p.name for p in (cli_dir / "repros").iterdir())
    desk_repros = sorted(p.name for p in (desktop_dir / "repros").iterdir())
    if cli_repros != desk_repros:
        problems.append(f"repro sets differ: {cli_repros} vs {desk_repros}")
    else:
        for name in cli_repros:
            if (cli_dir / "repros" / name).read_bytes() != (
                desktop_dir / "repros" / name
            ).read_bytes():
                problems.append(f"repros/{name} differs")
    cli_manifest = json.loads((cli_dir / "manifest.json").read_text())
    desk_manifest = json.loads((desktop_dir / "manifest.json").read_text())
    cli_manifest.pop("created_at")
    desk_manifest.pop("created_at")
    if cli_manifest != desk_manifest:
        problems.append("manifests differ beyond created_at")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-vs-desktop", action="store_true", required=True)
    parser.add_argument("--server-bin", type=Path, default=None)
    args = parser.parse_args()

    root = _repo_root()
    server_bin = args.server_bin or _default_server_bin(root)
    if not server_bin.is_file():
        raise SystemExit(
            f"frozen sidecar not found at {server_bin} — run packages/desktop/build-server.sh"
        )

    os.environ["TEMPEST_DEV"] = "1"
    with tempfile.TemporaryDirectory(prefix="tempest-parity-") as workdir:
        base = Path(workdir)
        repo = _fixture_repo(base)
        cli_dir = _cli_bundle(repo, base / "cli-bundle")
        desktop_dir = _desktop_bundle(server_bin, repo, base / "desktop-data")
        problems = _compare(cli_dir, desktop_dir)
        cli_targets = json.loads((cli_dir / "targets.json").read_text())
        verdicts = {t["qualname"]: t["verdict"] for t in cli_targets}
        print(f"parity fixture verdicts: {verdicts}")
        if problems:
            for problem in problems:
                print(f"  PARITY BROKEN: {problem}")
            sys.exit(1)
        repro_count = len(sorted((cli_dir / "repros").iterdir()))
        print(
            "cli-vs-desktop parity: byte-identical bundles (targets.json, "
            f"{repro_count} repro script(s), manifest minus created_at) — the shipped sidecar and "
            "the CLI produce the same evidence"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
