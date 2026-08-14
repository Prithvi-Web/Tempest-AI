"""Thin JSON-RPC client for the TypeScript analysis sidecar (`packages/ts-sidecar`).

Launch strategy — run from source, no build step:

    node --experimental-strip-types src/index.ts        (cwd = packages/ts-sidecar)

The sidecar's sources use explicit `.ts` import specifiers and only erasable TypeScript syntax
(`erasableSyntaxOnly` is enforced in its tsconfig), so Node's native type stripping runs them
directly: the repo's Node 24 strips types by default and treats the flag as a harmless no-op,
while the explicit flag keeps Node 22.6+ working. There is no `dist/` and nothing to compile.

Protocol: newline-delimited JSON-RPC 2.0 over stdio — one request line in, one response line out.
Any failure to spawn or converse (missing node, missing `pnpm install`, crash, timeout) raises
:class:`TsSidecarUnavailableError` with an actionable message; the caller maps that to
``UNPROVEN``, never to a silent skip.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO

DEFAULT_TIMEOUT_SECONDS = 30.0
_STDERR_TAIL_CHARS = 2000


class TsSidecarUnavailableError(Exception):
    """The sidecar could not be spawned or spoken to. The message says exactly what to fix."""


class TsSidecarRpcError(Exception):
    """The sidecar answered with a JSON-RPC error (bad params, unknown symbol, ...)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"ts-sidecar error {code}: {message}")
        self.code = code


@dataclass(frozen=True)
class TsChangedFile:
    """One changed TypeScript file, with head-side changed line numbers."""

    path: str
    changed_lines: tuple[int, ...]


def default_sidecar_dir() -> Path:
    """`packages/ts-sidecar` next to this engine checkout; `TEMPEST_TS_SIDECAR_DIR` overrides."""
    override = os.environ.get("TEMPEST_TS_SIDECAR_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "ts-sidecar"


class TsSidecarClient:
    """A long-lived sidecar process; one client = one `node` process, JSON-RPC over its stdio."""

    def __init__(
        self,
        sidecar_dir: Path | None = None,
        node_executable: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._sidecar_dir = sidecar_dir if sidecar_dir is not None else default_sidecar_dir()
        self._node_executable = node_executable
        self._timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        self._stdout_lines: queue.Queue[str | None] = queue.Queue()
        self._stderr_chunks: list[str] = []
        self._next_id = 1

    def __enter__(self) -> "TsSidecarClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def request(self, method: str, params: Mapping[str, object] | None = None) -> object:
        """One JSON-RPC call. Raises TsSidecarUnavailableError / TsSidecarRpcError."""
        process = self._ensure_started()
        request_id = self._next_id
        self._next_id += 1
        frame: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            frame["params"] = dict(params)
        assert process.stdin is not None  # PIPE by construction
        try:
            process.stdin.write(json.dumps(frame) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as err:
            raise self._died(f"could not write request: {err}") from err
        return self._read_response(request_id, method)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _read_response(self, request_id: int, method: str) -> object:
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise TsSidecarUnavailableError(
                    f"ts-sidecar timed out after {self._timeout:.0f}s answering `{method}` — "
                    "the analyzed project may be pathologically large, or the sidecar hung."
                )
            try:
                line = self._stdout_lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise self._died("process exited before answering")
            try:
                parsed: object = json.loads(line)
            except ValueError:
                continue  # not a JSON-RPC frame (defensive: stray output must not kill the run)
            if not isinstance(parsed, dict) or parsed.get("id") != request_id:
                continue
            error = parsed.get("error")
            if error is not None:
                if isinstance(error, dict):
                    code = error.get("code")
                    message = error.get("message")
                    raise TsSidecarRpcError(
                        code if isinstance(code, int) else -1,
                        message if isinstance(message, str) else repr(error),
                    )
                raise TsSidecarRpcError(-1, repr(error))
            result: object = parsed.get("result")
            return result

    def _ensure_started(self) -> subprocess.Popen[str]:
        process = self._process
        if process is not None and process.poll() is None:
            return process
        entry = self._sidecar_dir / "src" / "index.ts"
        if not entry.is_file():
            raise TsSidecarUnavailableError(
                f"ts-sidecar entry not found: {entry} — set TEMPEST_TS_SIDECAR_DIR to the "
                "packages/ts-sidecar checkout to analyze TypeScript targets."
            )
        if not (self._sidecar_dir / "node_modules" / "ts-morph").exists():
            raise TsSidecarUnavailableError(
                f"ts-sidecar dependencies are not installed under {self._sidecar_dir} — "
                "run `pnpm install` in the repo root."
            )
        node = self._node_executable or shutil.which("node")
        if node is None:
            raise TsSidecarUnavailableError(
                "Node.js was not found on PATH — install Node >= 22 to analyze TypeScript targets."
            )
        try:
            process = subprocess.Popen(
                [node, "--experimental-strip-types", "src/index.ts"],
                cwd=self._sidecar_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        except OSError as err:
            raise TsSidecarUnavailableError(
                f"could not launch the ts-sidecar via `{node}`: {err}"
            ) from err
        self._process = process
        assert process.stdout is not None and process.stderr is not None  # PIPE by construction
        threading.Thread(
            target=_pump_lines, args=(process.stdout, self._stdout_lines), daemon=True
        ).start()
        threading.Thread(
            target=_pump_chunks, args=(process.stderr, self._stderr_chunks), daemon=True
        ).start()
        return process

    def _died(self, what: str) -> TsSidecarUnavailableError:
        stderr_tail = "".join(self._stderr_chunks)[-_STDERR_TAIL_CHARS:].strip()
        self.close()
        detail = f"\nsidecar stderr:\n{stderr_tail}" if stderr_tail else ""
        return TsSidecarUnavailableError(f"ts-sidecar became unavailable: {what}{detail}")


def _pump_lines(stream: IO[str], sink: queue.Queue[str | None]) -> None:
    for line in stream:
        sink.put(line)
    sink.put(None)


def _pump_chunks(stream: IO[str], sink: list[str]) -> None:
    for line in stream:
        sink.append(line)


def select_ts_targets(
    project_root: str | Path,
    changed_files: Sequence[TsChangedFile],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    """Changed lines → classified TS targets (`selectTargets`), one sidecar process per call."""
    params: dict[str, object] = {
        "projectRoot": str(project_root),
        "changedFiles": [
            {"path": f.path, "changedLines": list(f.changed_lines)} for f in changed_files
        ],
    }
    with TsSidecarClient(timeout=timeout) as client:
        result = client.request("selectTargets", params)
    targets = result.get("targets") if isinstance(result, dict) else None
    if not isinstance(targets, list):
        raise TsSidecarUnavailableError(
            f"ts-sidecar returned a malformed selectTargets result: {result!r}"
        )
    return [_as_str_keyed_dict(target, "selectTargets target") for target in targets]


def ts_value_pools(
    project_root: str | Path,
    file_path: str,
    symbol: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Per-parameter JSON value pools for one symbol (`valuePools`)."""
    params: dict[str, object] = {
        "projectRoot": str(project_root),
        "filePath": file_path,
        "symbol": symbol,
    }
    with TsSidecarClient(timeout=timeout) as client:
        result = client.request("valuePools", params)
    return _as_str_keyed_dict(result, "valuePools result")


def _as_str_keyed_dict(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TsSidecarUnavailableError(f"ts-sidecar returned a malformed {what}: {value!r}")
    return {str(key): item for key, item in value.items()}
