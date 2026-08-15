"""ts_sidecar error/edge paths against REAL scripted node sidecars (Law L4: every test here
spawns an actual `node --experimental-strip-types src/index.ts` child and talks JSON-RPC to it).

Each scripted sidecar reproduces one concrete failure a user machine can hit: stray stdout
noise, alien response ids, malformed results, error frames, crashes before answering, a closed
stdin pipe, a hang, a SIGTERM-ignoring process, and missing node/dependencies."""

import shutil
import time
from pathlib import Path

import pytest

from tempest.targets.ts_sidecar import (
    TsChangedFile,
    TsSidecarClient,
    TsSidecarRpcError,
    TsSidecarUnavailableError,
    default_sidecar_dir,
    select_ts_targets,
    ts_value_pools,
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

_READLINE = "const rl = require('node:readline').createInterface({ input: process.stdin });\n"


def _sidecar(tmp_path: Path, script: str) -> Path:
    """A real launchable sidecar checkout: entry file + the ts-morph dependency marker."""
    d = tmp_path / "sidecar"
    (d / "src").mkdir(parents=True)
    (d / "src" / "index.ts").write_text(script, encoding="utf-8")
    (d / "node_modules" / "ts-morph").mkdir(parents=True)
    return d


def _responder(body_js: str) -> str:
    """A sidecar that parses each request line and runs `body_js` with `req` in scope."""
    prologue = "rl.on('line', (line) => {\n  const req = JSON.parse(line);\n"
    return _READLINE + prologue + body_js + "});\n"


class TestFrameFiltering:
    def test_stray_output_and_alien_ids_are_skipped_env_override_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write('warming up: not JSON\\n');\n"
                "  process.stdout.write('[1, 2, 3]\\n');\n"
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: 999999, result: { alien: true } }) + '\\n');\n"
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, result: { pong: true } }) + '\\n');\n"
            ),
        )
        monkeypatch.setenv("TEMPEST_TS_SIDECAR_DIR", str(d))
        assert default_sidecar_dir() == d
        with TsSidecarClient() as client:
            result = client.request("ping")
        assert result == {"pong": True}, "noise and alien ids must never be taken as the answer"


class TestMalformedResults:
    def test_select_ts_targets_non_dict_targets_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, result: { targets: 'nope' } }) + '\\n');\n"
            ),
        )
        monkeypatch.setenv("TEMPEST_TS_SIDECAR_DIR", str(d))
        with pytest.raises(TsSidecarUnavailableError, match="malformed selectTargets result"):
            select_ts_targets(tmp_path, [TsChangedFile(path="a.ts", changed_lines=(1,))])

    def test_select_ts_targets_non_dict_entry_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, result: { targets: [42] } }) + '\\n');\n"
            ),
        )
        monkeypatch.setenv("TEMPEST_TS_SIDECAR_DIR", str(d))
        with pytest.raises(TsSidecarUnavailableError, match="malformed selectTargets target"):
            select_ts_targets(tmp_path, [TsChangedFile(path="a.ts", changed_lines=(1,))])

    def test_value_pools_non_dict_result_is_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, result: [1, 2] }) + '\\n');\n"
            ),
        )
        monkeypatch.setenv("TEMPEST_TS_SIDECAR_DIR", str(d))
        with pytest.raises(TsSidecarUnavailableError, match="malformed valuePools result"):
            ts_value_pools(tmp_path, "a.ts", "f")


class TestErrorFrames:
    def test_non_dict_error_payload_becomes_rpc_error(self, tmp_path: Path) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, error: 'boom' }) + '\\n');\n"
            ),
        )
        with (
            TsSidecarClient(sidecar_dir=d) as client,
            pytest.raises(TsSidecarRpcError, match="boom") as err,
        ):
            client.request("ping")
        assert err.value.code == -1

    def test_error_dict_with_wrong_shapes_degrades_to_repr(self, tmp_path: Path) -> None:
        d = _sidecar(
            tmp_path,
            _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, error: { code: 'weird', message: 7 } }) + '\\n');\n"
            ),
        )
        with (
            TsSidecarClient(sidecar_dir=d) as client,
            pytest.raises(TsSidecarRpcError, match="weird") as err,
        ):
            client.request("ping")
        assert err.value.code == -1, "a non-int error code must degrade to -1, not crash"


class TestProcessDeath:
    def test_exit_before_answering_carries_the_stderr_tail(self, tmp_path: Path) -> None:
        d = _sidecar(
            tmp_path,
            "process.stderr.write('sidecar exploded: dependency missing\\n');\n"
            "setTimeout(() => process.exit(3), 200);\n",
        )
        with (
            TsSidecarClient(sidecar_dir=d) as client,
            pytest.raises(TsSidecarUnavailableError, match="exited before answering") as err,
        ):
            client.request("ping")
        assert "sidecar exploded: dependency missing" in str(err.value), (
            "the stderr tail is the actionable part of the error and must survive"
        )

    def test_write_failure_after_peer_closes_stdin(self, tmp_path: Path) -> None:
        d = _sidecar(
            tmp_path,
            "const fs = require('node:fs');\n"
            + _READLINE
            + "process.stdin.on('error', () => {});\n"
            "rl.once('line', (line) => {\n"
            "  const req = JSON.parse(line);\n"
            "  process.stdout.write(JSON.stringify("
            "{ jsonrpc: '2.0', id: req.id, result: { pong: true } }) + '\\n');\n"
            "  rl.close();\n"
            "  process.stdin.destroy();\n"
            "  fs.closeSync(0);\n"  # really closes the pipe's read end (destroy() does not)
            "  setInterval(() => {}, 1000);\n"
            "});\n",
        )
        with TsSidecarClient(sidecar_dir=d, timeout=10) as client:
            assert client.request("ping") == {"pong": True}
            time.sleep(0.4)  # let node finish destroying its stdin before the next write
            with pytest.raises(TsSidecarUnavailableError, match="could not write request"):
                client.request("ping")

    def test_hang_times_out_with_an_actionable_message(self, tmp_path: Path) -> None:
        d = _sidecar(tmp_path, _READLINE + "rl.on('line', () => {});\n")
        with (
            TsSidecarClient(sidecar_dir=d, timeout=1.0) as client,
            pytest.raises(TsSidecarUnavailableError, match="timed out after 1s"),
        ):
            client.request("selectTargets", {"projectRoot": str(tmp_path)})


class TestCloseLifecycle:
    def test_close_kills_a_sigterm_ignoring_process(self, tmp_path: Path) -> None:
        d = _sidecar(
            tmp_path,
            "process.on('SIGTERM', () => {});\n"
            + _responder(
                "  process.stdout.write(JSON.stringify("
                "{ jsonrpc: '2.0', id: req.id, result: { pong: true } }) + '\\n');\n"
            ),
        )
        client = TsSidecarClient(sidecar_dir=d)
        assert client.request("ping") == {"pong": True}
        process = client._process
        assert process is not None and process.poll() is None
        client.close()  # SIGTERM is ignored → the 2s grace expires → SIGKILL
        assert process.poll() is not None, "close() must leave nothing running"
        client.close()  # idempotent: no process left → early return, no error


class TestSpawnPreconditions:
    def test_missing_node_modules_says_pnpm_install(self, tmp_path: Path) -> None:
        d = tmp_path / "sidecar"
        (d / "src").mkdir(parents=True)
        (d / "src" / "index.ts").write_text("// entry\n", encoding="utf-8")
        client = TsSidecarClient(sidecar_dir=d)
        with pytest.raises(TsSidecarUnavailableError, match="pnpm install"):
            client.request("ping")

    def test_node_missing_from_path_is_actionable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _sidecar(tmp_path, "// never spawned\n")
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        monkeypatch.setenv("PATH", str(empty_bin))
        client = TsSidecarClient(sidecar_dir=d)
        with pytest.raises(TsSidecarUnavailableError, match=r"Node\.js was not found on PATH"):
            client.request("ping")
