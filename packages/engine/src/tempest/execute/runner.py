"""Drives sandboxed workers: introspection and batch invocation with hang/crash recovery.

Hang and crash are observations (master spec stage 6): a worker death marks the in-flight input
CRASHED and a fresh worker resumes the remainder; a per-input timeout marks it HUNG the same way.
"""

import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import tempest.compare.canonical as _canonical_module
import tempest.determinism._shims as _shims_module
import tempest.execute._worker as _worker_module
from tempest.envrepro.worktree import normalized_env
from tempest.execute.interpreter import find_worker_python
from tempest.execute.sandbox import Sandbox
from tempest.model import EffectEntry, InputOutcome, Observation, RaisedInfo, Timing


@dataclass(frozen=True)
class DeterminismJob:
    """Determinism instructions for one batch: record fresh cassettes, or replay given ones."""

    mode: str  # "record" | "replay"
    cassettes: dict[int, object] | None = None  # input index → recorded ledger (replay)
    loopback_routes: dict[str, object] | None = None  # corpus HTTP fixtures (record only)
    loopback_port: int = 0

    def to_job(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "cassettes": {str(k): v for k, v in (self.cassettes or {}).items()},
            "loopback_routes": self.loopback_routes,
            "loopback_port": self.loopback_port,
        }


@dataclass(frozen=True)
class ParamInfo:
    name: str
    kind: str
    annotation: str | None
    default_literal: str | None


@dataclass(frozen=True)
class TargetIntrospection:
    params: tuple[ParamInfo, ...]


def _prepare_scratch(scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_worker_module.__file__, scratch / "worker.py")
    shutil.copyfile(_canonical_module.__file__, scratch / "canonical.py")
    shutil.copyfile(_shims_module.__file__, scratch / "shims.py")


def _sys_path_for(root: Path) -> list[str]:
    entries = [str(root)]
    if (root / "src").is_dir():
        entries.append(str(root / "src"))
    return entries


def _target_file(root: Path, module: str) -> str:
    rel = Path(*module.split("."))
    for base in (root, root / "src"):
        for candidate in (base / f"{rel}.py", base / rel / "__init__.py"):
            if candidate.exists():
                return str(candidate)
    return str(root / f"{rel}.py")


def _spawn(
    sandbox: Sandbox,
    scratch: Path,
    root: Path,
    job: dict[str, object],
    python: str,
    *,
    stdin_pipe: bool = False,
) -> subprocess.Popen[bytes]:
    job_path = scratch / "job.json"
    # Backends that execute elsewhere (DockerSandbox) rewrite host paths inside the job to
    # their container mount points; ProcessSandbox is the identity.
    job_path.write_text(
        json.dumps(sandbox.translate_job(job, workdir=root, scratch=scratch)), encoding="utf-8"
    )
    return sandbox.popen(
        [python, "-s", "-B", str(scratch / "worker.py"), str(job_path)],
        cwd=root,
        env=normalized_env(scratch),
        scratch=scratch,
        stdin_pipe=stdin_pipe,
    )


def _kill(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def _read_lines(proc: subprocess.Popen[bytes], out: "queue.Queue[bytes | None]") -> None:
    assert proc.stdout is not None
    for raw in proc.stdout:
        out.put(raw)
    out.put(None)


def introspect_target(
    root: Path,
    module: str,
    qualname: str,
    sandbox: Sandbox,
    *,
    python: str | None = None,
    timeout: float = 20.0,
) -> TargetIntrospection | None:
    worker_python = python if python is not None else find_worker_python()
    with tempfile.TemporaryDirectory(prefix="tempest-scratch-") as scratch_dir:
        scratch = Path(scratch_dir)
        _prepare_scratch(scratch)
        job: dict[str, object] = {
            "mode": "introspect",
            "module": module,
            "qualname": qualname,
            "sys_path": _sys_path_for(root),
            "scratch": str(scratch),
        }
        proc = _spawn(sandbox, scratch, root, job, worker_python)
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            return None
    for raw in stdout.splitlines():
        payload = json.loads(raw)
        if payload.get("ok"):
            return TargetIntrospection(
                params=tuple(
                    ParamInfo(
                        name=p["name"],
                        kind=p["kind"],
                        annotation=p["annotation"],
                        default_literal=p["default_literal"],
                    )
                    for p in payload["params"]
                )
            )
    return None


def run_batch(
    root: Path,
    module: str,
    qualname: str,
    inputs: list[tuple[str, str]],
    sandbox: Sandbox,
    *,
    per_input_timeout: float = 10.0,
    python: str | None = None,
    determinism: DeterminismJob | None = None,
) -> list[Observation]:
    """Execute every (args_literal, kwargs_literal) input, restarting workers across crashes."""
    worker_python = python if python is not None else find_worker_python()
    results: dict[int, Observation] = {}
    pending = list(range(len(inputs)))

    while pending:
        with tempfile.TemporaryDirectory(prefix="tempest-scratch-") as scratch_dir:
            scratch = Path(scratch_dir)
            _prepare_scratch(scratch)
            job: dict[str, object] = {
                "mode": "invoke",
                "module": module,
                "qualname": qualname,
                "target_file": _target_file(root, module),
                "sys_path": _sys_path_for(root),
                "scratch": str(scratch),
                "determinism": determinism.to_job() if determinism else None,
                "inputs": [
                    {"index": i, "args": inputs[i][0], "kwargs": inputs[i][1]} for i in pending
                ],
            }
            proc = _spawn(sandbox, scratch, root, job, worker_python)
            lines: queue.Queue[bytes | None] = queue.Queue()
            reader = threading.Thread(target=_read_lines, args=(proc, lines), daemon=True)
            reader.start()

            cursor = 0  # position in `pending` we expect a result for next
            while cursor < len(pending):
                expected = pending[cursor]
                try:
                    raw = lines.get(timeout=per_input_timeout)
                except queue.Empty:
                    _kill(proc)
                    results[expected] = _hung_observation(per_input_timeout)
                    cursor += 1
                    break
                if raw is None:  # worker died (crash or clean exit) before finishing the batch
                    exit_status = proc.wait()
                    results[expected] = _crashed_observation(exit_status)
                    cursor += 1
                    break
                payload = json.loads(raw)
                if "fatal" in payload:
                    results[expected] = _fatal_observation(payload)
                    cursor += 1
                    continue
                results[payload["index"]] = _completed_observation(payload)
                cursor += 1
            else:
                _kill(proc)
                pending = []
                continue
            _kill(proc)
            pending = [i for i in pending if i not in results]

    return [results[i] for i in range(len(inputs))]


class PersistentWorker:
    """One long-lived PURE-path worker per (root, module): batches ride over stdin (JSONL,
    `batch_end` sentinel per batch), so spawn cost is paid once per target instead of once per
    batch — the measured pyfix run spent ~110 of 118 s on 4,070 interpreter spawns. Crash and
    hang recovery match `run_batch`: the in-flight input is marked and a fresh process resumes
    the remainder. Determinism (record/replay) batches never use this class; their shim
    lifecycle owns process boundaries (one process per batch, unchanged).

    State model: the target module imports once and stays loaded across batches — exactly the
    model the pure path already accepts within one large batch. Fresh-process semantics where
    they are load-bearing (§14.2 divergence confirmation) stay on `run_batch`.
    """

    _MAX_RESPAWNS_PER_RUN = 3

    def __init__(
        self,
        root: Path,
        module: str,
        qualname: str,
        sandbox: Sandbox,
        *,
        python: str | None = None,
    ) -> None:
        self._root = root
        self._module = module
        self._qualname = qualname
        self._sandbox = sandbox
        self._python = python if python is not None else find_worker_python()
        self._tmp = tempfile.TemporaryDirectory(prefix="tempest-scratch-")
        self._scratch = Path(self._tmp.name)
        _prepare_scratch(self._scratch)
        self._proc: subprocess.Popen[bytes] | None = None
        self._lines: queue.Queue[bytes | None] | None = None
        self.spawns = 0  # observability: tests assert spawn economics

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        job: dict[str, object] = {
            "mode": "serve",
            "module": self._module,
            "qualname": self._qualname,
            "target_file": _target_file(self._root, self._module),
            "sys_path": _sys_path_for(self._root),
            "scratch": str(self._scratch),
            "inputs": [],
        }
        self._proc = _spawn(
            self._sandbox, self._scratch, self._root, job, self._python, stdin_pipe=True
        )
        self.spawns += 1
        self._lines = queue.Queue()
        reader = threading.Thread(target=_read_lines, args=(self._proc, self._lines), daemon=True)
        reader.start()

    def _retire(self) -> None:
        if self._proc is not None:
            _kill(self._proc)
        self._proc = None
        self._lines = None

    def run(
        self, inputs: list[tuple[str, str]], *, per_input_timeout: float = 10.0
    ) -> list[Observation]:
        results: dict[int, Observation] = {}
        pending = list(range(len(inputs)))
        respawns = 0

        while pending:
            self._ensure()
            proc, lines = self._proc, self._lines
            assert proc is not None and proc.stdin is not None and lines is not None
            request = {
                "inputs": [
                    {"index": i, "args": inputs[i][0], "kwargs": inputs[i][1]} for i in pending
                ]
            }
            try:
                proc.stdin.write((json.dumps(request) + "\n").encode())
                proc.stdin.flush()
            except OSError:
                self._retire()
                respawns += 1
                if respawns > self._MAX_RESPAWNS_PER_RUN:
                    for i in pending:
                        results[i] = _crashed_observation(-1)
                    break
                continue

            cursor = 0
            broke = False
            ended_early = False
            while cursor < len(pending):
                expected = pending[cursor]
                try:
                    raw = lines.get(timeout=per_input_timeout)
                except queue.Empty:
                    self._retire()
                    results[expected] = _hung_observation(per_input_timeout)
                    cursor += 1
                    broke = True
                    break
                if raw is None:  # worker died mid-batch
                    exit_status = proc.wait()
                    self._retire()
                    results[expected] = _crashed_observation(exit_status)
                    cursor += 1
                    broke = True
                    break
                payload = json.loads(raw)
                if payload.get("batch_end"):
                    # The worker ended the batch early (import-level fatal emits one line for
                    # the whole batch): every unanswered input inherits a fatal observation.
                    for i in pending[cursor:]:
                        results[i] = _fatal_observation({"error": "worker ended batch early"})
                    cursor = len(pending)
                    ended_early = True
                    break
                if "fatal" in payload:
                    results[expected] = _fatal_observation(payload)
                    cursor += 1
                    continue
                results[payload["index"]] = _completed_observation(payload)
                cursor += 1
            if not broke and not ended_early and cursor >= len(pending):
                self._drain_sentinel(per_input_timeout)
            if broke:
                respawns += 1
                if respawns > self._MAX_RESPAWNS_PER_RUN:
                    for i in pending:
                        if i not in results:
                            results[i] = _crashed_observation(-1)
                    break
            pending = [i for i in pending if i not in results]

        return [results[i] for i in range(len(inputs))]

    def _drain_sentinel(self, timeout: float) -> None:
        """Consume the batch_end line so the next batch starts on a clean stream."""
        lines = self._lines
        if lines is None:
            return
        try:
            raw = lines.get(timeout=timeout)
        except queue.Empty:
            self._retire()
            return
        if raw is None or not json.loads(raw).get("batch_end"):
            self._retire()  # protocol slip — never reuse a stream we cannot trust

    def close(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None and proc.stdin is not None:
            try:
                proc.stdin.write(b'{"shutdown": true}\n')
                proc.stdin.flush()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._retire()
        self._tmp.cleanup()

    def __enter__(self) -> "PersistentWorker":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _completed_observation(p: dict[str, object]) -> Observation:
    raised_raw = p.get("raised")
    raised = None
    if isinstance(raised_raw, dict):
        raised = RaisedInfo(
            type_name=str(raised_raw["type"]),
            module=str(raised_raw["module"]),
            message=str(raised_raw["message"]),
        )
    lines_raw = cast("list[object]", p.get("lines", []))
    arcs_raw = cast("list[list[int]]", p.get("arcs", []))
    unrep = p.get("unrepresentable")
    miss = p.get("cassette_miss")
    unint = p.get("uninterceptable")
    effects_raw = cast("list[dict[str, object]]", p.get("effects", []))
    return Observation(
        outcome=InputOutcome.COMPLETED,
        return_present=bool(p["return_present"]),
        return_canon=p["return_canon"],
        raised=raised,
        effects=tuple(
            EffectEntry(
                surface=str(e["surface"]),
                call=str(e["call"]),
                ordinal=int(str(e["ordinal"])),
                args_fingerprint=str(e["args_fingerprint"]),
            )
            for e in effects_raw
        ),
        stdout=str(p["stdout"]),
        stderr=str(p["stderr"]),
        exit_status=0,
        timing=Timing(wall_ns=int(str(p["wall_ns"])), cpu_ns=int(str(p["cpu_ns"]))),
        unrepresentable=unrep if isinstance(unrep, str) else None,
        executed_lines=frozenset(int(x) for x in lines_raw if isinstance(x, int)),
        executed_arcs=frozenset(
            (int(a[0]), int(a[1])) for a in arcs_raw if isinstance(a, list) and len(a) == 2
        ),
        cassette_miss=miss if isinstance(miss, str) else None,
        uninterceptable=unint if isinstance(unint, str) else None,
        cassette=p.get("cassette"),
    )


def _crashed_observation(exit_status: int) -> Observation:
    return Observation(
        outcome=InputOutcome.CRASHED,
        return_present=False,
        return_canon=None,
        raised=None,
        exit_status=exit_status,
        timing=Timing(wall_ns=0, cpu_ns=0),
    )


def _hung_observation(timeout_s: float) -> Observation:
    return Observation(
        outcome=InputOutcome.HUNG,
        return_present=False,
        return_canon=None,
        raised=None,
        exit_status=-int(signal.SIGKILL),
        timing=Timing(wall_ns=int(timeout_s * 1e9), cpu_ns=0),
    )


def _fatal_observation(payload: dict[str, object]) -> Observation:
    return Observation(
        outcome=InputOutcome.CRASHED,
        return_present=False,
        return_canon=None,
        raised=None,
        stderr=str(payload.get("error", "")),
        exit_status=1,
        timing=Timing(wall_ns=0, cpu_ns=0),
    )
