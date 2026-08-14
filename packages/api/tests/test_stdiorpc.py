"""Boundary A transport, exercised for real (Law L4): framing round-trips at the byte level,
and a REAL `tempest-server --stdio` subprocess speaks JSON-RPC 2.0 over its pipes — health,
a full local prove on a real git repo (honest all-UNPROVEN without a sandbox, and the changed
.ts file surfaced, never skipped), events, error paths, and a clean shutdown. No sockets."""

import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tempest_api.app import create_app
from tempest_api.stdiorpc import FrameProtocolError, operation_table, read_frame, write_frame

REPO_ROOT = Path(__file__).resolve().parents[3]
DEADLINE_S = 120.0


class TestFraming:
    def test_round_trip(self) -> None:
        buf = io.BytesIO()
        write_frame(buf, b'{"jsonrpc":"2.0"}')
        write_frame(buf, "unicode: ⛈".encode())
        buf.seek(0)
        assert read_frame(buf) == b'{"jsonrpc":"2.0"}'
        assert read_frame(buf) == "unicode: ⛈".encode()
        assert read_frame(buf) is None  # clean EOF at a frame boundary

    def test_eof_inside_header_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError):
            read_frame(io.BytesIO(b"Content-Length: 10\r\n"))

    def test_eof_inside_payload_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError):
            read_frame(io.BytesIO(b"Content-Length: 10\r\n\r\nabc"))

    def test_missing_length_header_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError):
            read_frame(io.BytesIO(b"X-Other: 1\r\n\r\n"))

    def test_absurd_length_is_a_protocol_error(self) -> None:
        with pytest.raises(FrameProtocolError):
            read_frame(io.BytesIO(b"Content-Length: 999999999999\r\n\r\n"))


class TestOperationTable:
    def test_every_ui_operation_is_dispatchable(self) -> None:
        table = operation_table(create_app())
        for op in (
            "getHealth",
            "listRuns",
            "getRun",
            "listRunEvents",
            "getTarget",
            "getDivergence",
            "getDivergenceRepro",
            "startLocalProve",
        ):
            assert op in table, f"operation {op} missing from the derived dispatch table"
        assert table["getRun"].path_template == "/v1/runs/{run_id}"
        assert table["startLocalProve"].http_method == "POST"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _mixed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    (repo / "app.ts").write_text("export const rate = (n: number): number => n * 2;\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    (repo / "core.py").write_text("def double(x: int) -> int:\n    return x * 2 + 1\n")
    (repo / "app.ts").write_text("export const rate = (n: number): number => n * 3;\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")
    return repo


class _RpcClient:
    """Frames over a live subprocess's pipes; sequential ids; one response per request."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        self._proc = proc
        self._next_id = 1

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        rpc_id = self._next_id
        self._next_id += 1
        request = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
        assert self._proc.stdin is not None and self._proc.stdout is not None
        write_frame(self._proc.stdin, json.dumps(request).encode())
        payload = read_frame(self._proc.stdout)
        assert payload is not None, "sidecar closed the RPC channel mid-conversation"
        response = json.loads(payload)
        assert response["id"] == rpc_id
        assert isinstance(response, dict)
        return response

    def result(self, method: str, params: dict[str, object] | None = None) -> object:
        response = self.call(method, params)
        assert "error" not in response, f"{method} failed: {response.get('error')}"
        return response["result"]


def test_stdio_sidecar_end_to_end(tmp_path: Path) -> None:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    assert Path(uv).exists(), "uv is required to launch the entrypoint under test"
    repo = _mixed_repo(tmp_path)
    data_dir = tmp_path / "made" / "by-the-server"
    env = {
        **os.environ,
        "PATH": f"{Path.home() / '.local' / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    env.pop("TEMPEST_DEV", None)  # production posture: no dev sandbox, honesty must hold
    # Force the genuine no-tier path so the assertions below hold on every OS (on macOS T2
    # Seatbelt would otherwise contain core.py and report DIVERGENT — that path is covered by
    # the CLI T2 test and the escape suite). This test's job is the honest all-UNPROVEN wiring.
    env["TEMPEST_NO_SEATBELT"] = "1"
    env["TEMPEST_DOCKER"] = "/nonexistent/docker"
    proc = subprocess.Popen(
        [uv, "run", "--no-sync", "tempest-server", "--stdio", "--data-dir", str(data_dir)],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        rpc = _RpcClient(proc)

        assert rpc.result("rpc.ping") == {"pong": True}

        health = rpc.result("getHealth")
        assert isinstance(health, dict) and health["status"] == "ok"
        assert (data_dir / "tempest.db").is_file()  # created by the server itself

        # Unknown method: precise JSON-RPC error, channel stays alive.
        unknown = rpc.call("noSuchMethod")
        assert isinstance(unknown.get("error"), dict)
        assert unknown["error"]["code"] == -32601

        # Missing path param: invalid-params, not a crash.
        bad = rpc.call("getRun", {})
        assert isinstance(bad.get("error"), dict)
        assert bad["error"]["code"] == -32602

        # HTTP-layer error surfaces the API's stable envelope in error.data.
        missing = rpc.call("getRun", {"run_id": 999999})
        assert isinstance(missing.get("error"), dict)
        assert missing["error"]["code"] == -32000
        assert missing["error"]["data"]["status"] == 404

        started = rpc.result(
            "startLocalProve",
            {"body": {"repo_path": str(repo), "base": "base", "head": "head", "max_inputs": 6}},
        )
        assert isinstance(started, dict)
        run_id = started["run_id"]

        deadline = time.monotonic() + DEADLINE_S
        run: dict[str, object] = {}
        while time.monotonic() < deadline:
            got = rpc.result("getRun", {"run_id": run_id})
            assert isinstance(got, dict)
            run = got
            if run["status"] in ("COMPLETE", "ERROR"):
                break
            time.sleep(0.5)
        assert run.get("status") == "COMPLETE", f"prove never completed: {run}"
        assert run["verdict"] == "UNPROVEN"  # no sandbox here — honest, never unsandboxed
        targets = run["targets"]
        assert isinstance(targets, list)
        by_path = {t["file_path"]: t for t in targets}
        assert by_path["core.py"]["reason_code"] == "SANDBOX_UNAVAILABLE"
        assert by_path["app.ts"]["reason_code"] == "RECORD_REPLAY_UNAVAILABLE"  # never skipped

        events = rpc.result("listRunEvents", {"run_id": run_id})
        assert isinstance(events, list) and len(events) >= 2  # started + terminal

        assert rpc.result("rpc.shutdown") == {"ok": True}
        assert proc.wait(timeout=30) == 0  # clean exit, no signal needed
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
