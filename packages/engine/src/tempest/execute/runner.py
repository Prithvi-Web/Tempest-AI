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
from functools import lru_cache
from pathlib import Path
from typing import cast

import tempest.compare.canonical as _canonical_module
import tempest.determinism._shims as _shims_module
import tempest.execute._worker as _worker_module
from tempest.compare.compare import SyntheticObservation
from tempest.config import TempestConfig, TempestConfigError
from tempest.envrepro.worktree import normalized_env
from tempest.execute.cancel import current_scope
from tempest.execute.interpreter import find_worker_python
from tempest.execute.sandbox import Sandbox, kill_container
from tempest.model import EffectEntry, InputOutcome, Observation, RaisedInfo, Timing

# One-time cost of bringing a worker up (process spawn + interpreter boot + target import).
# It is NOT per-input latency, so the first result after a spawn gets this on top of the
# per-input budget. Without it a cold or loaded machine mismarks a perfectly fast first input
# as HUNG — a wrong `DivergenceClass.HANG` verdict, not merely a slow run.
_STARTUP_GRACE_S = 20.0


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


@lru_cache(maxsize=256)
def _source_roots_of(root: str) -> tuple[str, ...]:
    """`[roots].source` from the WORKTREE's own tempest.toml — each checked-out revision
    self-describes its import layout, so every worker (detection, minimization, synthesis
    probes) resolves paths identically with no caller threading. A broken historical
    config never crashes job building: the working-tree copy is validated at run start,
    and a revision whose layout cannot be read simply gets no extra roots (an import
    failure there surfaces as an honest UNPROVEN, never a crash)."""
    try:
        return TempestConfig.load(Path(root)).source_roots
    except TempestConfigError:
        return ()


def _sys_path_for(root: Path) -> list[str]:
    entries = [str(root)]
    if (root / "src").is_dir():
        entries.append(str(root / "src"))
    for source_root in _source_roots_of(str(root)):
        candidate = root / source_root
        if candidate.is_dir():
            entries.append(str(candidate))
    deps = root / ".tempest-deps"  # attach_deps' symlink — stage-2 materialized wheels/shim
    if deps.is_dir():
        entries.append(str(deps))
    return entries


def module_name_for(rel_path: str, source_roots: tuple[str, ...] = ()) -> str:
    """Repo path → importable module. A configured `[roots].source` prefix is stripped
    (longest match first, whole segments only); otherwise the conventional bare `src/`
    layout is handled. This mirrors exactly what the worker puts on sys.path.

    Public and living HERE rather than in `prove`, because two callers now need it — the
    proof pipeline and F3's load probe — and a second copy of the rule would be a second
    answer to "which module is this file", free to drift from the one the workers use.
    """
    parts = Path(rel_path).with_suffix("").parts
    for root in sorted(source_roots, key=len, reverse=True):
        root_parts = Path(root).parts
        if parts[: len(root_parts)] == root_parts and len(parts) > len(root_parts):
            return ".".join(parts[len(root_parts) :])
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def module_for_path(root: Path, rel_path: str) -> str:
    """`module_name_for`, reading the layout from the worktree the file actually lives in."""
    return module_name_for(rel_path, _source_roots_of(str(root)))


@dataclass(frozen=True)
class LoadProbe:
    """Whether one module imports, and the traceback when it does not."""

    module: str
    loads: bool
    error: str


def module_loads(
    root: Path,
    module: str,
    sandbox: Sandbox,
    *,
    expect_file: Path | None = None,
    python: str | None = None,
    timeout: float = 20.0,
) -> LoadProbe:
    """Import `module` inside the sandbox and report whether it worked.

    Real execution, in the same sandbox every other stage uses (L4). No static check can answer
    this: `import no_such_module_xyz` parses perfectly, and `ast.parse` is happy right up to the
    moment the interpreter is not.

    **`expect_file` is not optional in spirit.** A dotted name is not a file, and several things
    can answer to a name ahead of the file you meant: the scratch mount that carries the worker's
    own `canonical.py` and `shims.py`, a `[roots].source` entry from the worktree's `tempest.toml`
    — which an agent can write, since it is not a credential path — or simply a top-level module
    of the same name. A review reproduced both bypasses: a repo with `lib/app.py` broken, a
    healthy `shim/app.py`, and `source = ["shim", "lib"]` reported the module as loading fine.
    When `expect_file` is given, a name that resolves anywhere else is a FAILURE, and the error
    says which file answered instead.

    A worker that produces no verdict line — killed, timed out, or exited before `_emit` — is
    reported as a load FAILURE. That is the conservative direction for the only caller: a module
    nobody could load is not evidence that the module is fine.
    """
    worker_python = python if python is not None else find_worker_python()
    with tempfile.TemporaryDirectory(prefix="tempest-scratch-") as scratch_dir:
        scratch = Path(scratch_dir)
        _prepare_scratch(scratch)
        job: dict[str, object] = {
            "mode": "import",
            "module": module,
            "qualname": "",
            "sys_path": _sys_path_for(root),
            "scratch": str(scratch),
        }
        proc = _spawn(sandbox, scratch, root, job, worker_python)
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return LoadProbe(module=module, loads=False, error=f"import timed out after {timeout}s")
        finally:
            _kill(proc)
    for raw in stdout.splitlines():
        payload = _parse_line(raw)
        if payload is None or "ok" not in payload:
            continue
        if payload.get("ok"):
            return _check_resolved(module, str(payload.get("file", "")), expect_file)
        return LoadProbe(module=module, loads=False, error=str(payload.get("error", "")).strip())
    return LoadProbe(
        module=module, loads=False, error="the worker produced no answer about this import"
    )


def _check_resolved(module: str, resolved: str, expect_file: Path | None) -> LoadProbe:
    """The import worked — but did it import the file we are judging?

    A name that resolves elsewhere is reported as a failure rather than a pass, because the
    caller's question is about a FILE. Answering "yes, something called `app` imports fine" to
    "does this changed app.py still load?" is the shape of every bypass this check exists for.
    """
    if expect_file is None:
        return LoadProbe(module=module, loads=True, error="")
    if not resolved:
        return LoadProbe(
            module=module,
            loads=False,
            error=(
                f"{module!r} imported but reports no file of its own (a namespace package or a "
                f"built-in), so nothing proves it is {expect_file}"
            ),
        )
    try:
        same = Path(resolved).resolve() == expect_file.resolve()
    except OSError:  # pragma: no cover — a path that cannot be resolved is not the one we want
        same = False
    if same:
        return LoadProbe(module=module, loads=True, error="")
    return LoadProbe(
        module=module,
        loads=False,
        error=(
            f"the name {module!r} resolved to {resolved}, not to {expect_file} — the file under "
            f"judgement was never imported, so nothing here says whether it still loads"
        ),
    )


def _target_file(root: Path, module: str) -> str:
    rel = Path(*module.split("."))
    bases = [root, root / "src", *(root / r for r in _source_roots_of(str(root)))]
    for base in bases:
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
    scope = current_scope()
    if scope is not None:
        # L11: a cancelled prove must never breed a new child — worker respawn paths unwind
        # with ProveCancelled instead of resurrecting what cancel() just killed.
        scope.raise_if_cancelled()
    # Backends that execute elsewhere (DockerSandbox) rewrite host paths inside the job to
    # their container mount points; ProcessSandbox is the identity.
    job_path.write_text(
        json.dumps(sandbox.translate_job(job, workdir=root, scratch=scratch)), encoding="utf-8"
    )
    proc = sandbox.popen(
        [python, "-s", "-B", str(scratch / "worker.py"), str(job_path)],
        cwd=root,
        env=normalized_env(scratch),
        scratch=scratch,
        stdin_pipe=stdin_pipe,
    )
    if scope is not None:
        scope.register(proc)  # registering after a racing cancel() kills proc immediately
    return proc


def _kill(proc: subprocess.Popen[bytes]) -> None:
    # killpg-after-reap guard: `returncode` is set only by the `wait()`/`poll()` that reaps OUR
    # child, and the kernel cannot recycle a pid/pgid before its owner reaps it — so
    # `returncode is None` proves the pgid is still ours to signal. Once it is set, the pgid
    # may already belong to a stranger and must never be signalled again (double-kill call
    # sites and wait-then-kill paths become signal-free no-ops instead of TOCTOU kills).
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: darwin-only — see below
            # A dead-but-unreaped group raises EPERM only on macOS; Linux keeps a zombie
            # leader's pgid signalable, so this fallback is unreachable there by kernel design.
            proc.kill()
    kill_container(proc)  # T1: killing the docker CLI alone leaves the container running
    proc.wait()
    scope = current_scope()
    if scope is not None:
        scope.unregister(proc)


def _read_lines(proc: subprocess.Popen[bytes], out: "queue.Queue[bytes | None]") -> None:
    assert proc.stdout is not None
    for raw in proc.stdout:
        out.put(raw)
    out.put(None)


def _parse_line(raw: bytes) -> dict[str, object] | None:
    """One protocol line → its payload dict, or None for anything that is not a JSON object.
    The runner must never crash on a garbled stream (review finding 4): a None here means
    the line carries no trustworthy index, so the caller decides how much of the stream to
    distrust — never `json.loads` raising through the whole prove."""
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return cast("dict[str, object]", payload)


def _await_boot(
    lines: "queue.Queue[bytes | None]", proc: subprocess.Popen[bytes], budget: float
) -> str | None:
    """None once the worker announces itself; otherwise why it never did.

    A worker that dies, hangs, or garbles BEFORE its boot line has executed no user code —
    the failure is pure infrastructure (container cannot start, interpreter cannot launch)
    and must never be attributed to an input or compared as evidence (review finding 1)."""
    try:
        raw = lines.get(timeout=budget)
    except queue.Empty:
        return "worker did not boot within the startup budget"
    if raw is None:
        return f"worker died before booting (exit {proc.wait()})"
    payload = _parse_line(raw)
    if payload is None or not payload.get("boot"):
        return "worker protocol slip before boot"
    return None


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
            return None
        finally:
            # Finding 3: EVERY unwind path (timeout, KeyboardInterrupt, ProveCancelled)
            # reaps the session-leader worker — an orphan would outlive the whole CLI.
            _kill(proc)
    for raw in stdout.splitlines():
        payload = _parse_line(raw)  # finding 4: skip garbled lines instead of raising
        if payload is None:
            continue
        if payload.get("ok"):
            return TargetIntrospection(
                params=tuple(
                    ParamInfo(
                        name=p["name"],
                        kind=p["kind"],
                        annotation=p["annotation"],
                        default_literal=p["default_literal"],
                    )
                    for p in cast("list[dict[str, str]]", payload["params"])
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
    trace_module: str | None = None,
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
                # Synthesized adapters (harness/llm.py) invoke a generated module while the
                # changed lines live in the REAL module — trace the latter so changed-line
                # coverage stays honest through an adapter.
                "target_file": _target_file(root, trace_module or module),
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

            # Finding 3: the worker is a session leader — an exception unwinding out of this
            # block (KeyboardInterrupt at the queue read, ProveCancelled from a checkpoint)
            # used to leak it alive past the whole CLI. The finally reaps it on EVERY path;
            # _kill is signal-free once the process is already reaped, so the normal paths
            # pay nothing extra.
            try:
                boot_failure = _await_boot(lines, proc, _STARTUP_GRACE_S)
                if boot_failure is not None:
                    # No user code ran: every pending input gets a MARKED synthetic
                    # observation (compare maps it to Unprovable), never a comparable
                    # crash (finding 1).
                    for i in pending:
                        results[i] = _synthetic_observation(boot_failure)
                    pending = []
                    continue

                cursor = 0  # position in `pending` we expect a result for next
                while cursor < len(pending):
                    expected = pending[cursor]
                    # Only the first result carries the worker's one-time startup cost.
                    budget = per_input_timeout + (_STARTUP_GRACE_S if cursor == 0 else 0.0)
                    try:
                        raw = lines.get(timeout=budget)
                    except queue.Empty:
                        results[expected] = _hung_observation(per_input_timeout)
                        cursor += 1
                        break
                    if raw is None:  # worker died (crash or clean exit) mid-batch
                        exit_status = proc.wait()
                        results[expected] = _crashed_observation(exit_status)
                        cursor += 1
                        break
                    payload = _parse_line(raw)
                    if payload is None:
                        # Finding 4: a garbled line poisons only THIS input, but the stream
                        # can no longer be trusted for index alignment — kill the worker and
                        # let the remainder re-run on a fresh process.
                        results[expected] = _fatal_observation(
                            {"error": "garbled worker protocol line"}
                        )
                        cursor += 1
                        break
                    if "fatal" in payload:
                        results[expected] = _fatal_observation(payload)
                        cursor += 1
                        continue
                    results[cast(int, payload["index"])] = _completed_observation(payload)
                    cursor += 1
                else:
                    pending = []
                    continue
            finally:
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
        trace_module: str | None = None,
    ) -> None:
        self._root = root
        self._module = module
        self._qualname = qualname
        self._trace_module = trace_module
        self._sandbox = sandbox
        self._python = python if python is not None else find_worker_python()
        self._tmp = tempfile.TemporaryDirectory(prefix="tempest-scratch-")
        self._scratch = Path(self._tmp.name)
        _prepare_scratch(self._scratch)
        self._proc: subprocess.Popen[bytes] | None = None
        self._lines: queue.Queue[bytes | None] | None = None
        self.spawns = 0  # observability: tests assert spawn economics

    def _ensure(self) -> bool:
        """True when a live, BOOTED worker is available. False when a fresh spawn died,
        hung, or garbled before its boot line — pure infrastructure, never attributable to
        an input (review finding 1); the caller's respawn budget decides how often to retry."""
        if self._proc is not None and self._proc.poll() is None:
            return True
        job: dict[str, object] = {
            "mode": "serve",
            "module": self._module,
            "qualname": self._qualname,
            "target_file": _target_file(self._root, self._trace_module or self._module),
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
        if _await_boot(self._lines, self._proc, _STARTUP_GRACE_S) is not None:
            self._retire()
            return False
        return True

    def _await_ack(self, per_input_timeout: float, spawned_now: bool) -> bool:
        """The worker echoes `batch_ack` after reading a batch request and BEFORE any user
        code. No ack → the request never reached a living worker (the docker-eats-stdin
        class of dead-on-arrival failure): retire without attributing anything to an input
        and let the respawn budget decide (review finding 1)."""
        proc, lines = self._proc, self._lines
        assert proc is not None and lines is not None
        budget = per_input_timeout + (_STARTUP_GRACE_S if spawned_now else 0.0)
        try:
            raw = lines.get(timeout=budget)
        except queue.Empty:
            self._retire()
            return False
        if raw is None:
            self._retire()
            return False
        payload = _parse_line(raw)
        if payload is None or not payload.get("batch_ack"):
            self._retire()
            return False
        return True

    def _retire(self) -> None:
        if self._proc is not None:
            _kill(self._proc)
        self._proc = None
        self._lines = None

    def run(
        self, inputs: list[tuple[str, str]], *, per_input_timeout: float = 10.0
    ) -> list[Observation]:
        try:
            return self._run_batches(inputs, per_input_timeout)
        except BaseException:
            # Finding 3 (L11): an unwinding run() — KeyboardInterrupt at a queue read,
            # ProveCancelled from a respawn checkpoint, anything — must not leak a live
            # session-leader worker. Retire (idempotent) and re-raise.
            self._retire()
            raise

    def _run_batches(
        self, inputs: list[tuple[str, str]], per_input_timeout: float
    ) -> list[Observation]:
        results: dict[int, Observation] = {}
        pending = list(range(len(inputs)))
        respawns = 0

        while pending:
            spawned_now = self._proc is None or self._proc.poll() is not None
            if not self._ensure():
                # The spawn never booted: infrastructure, not evidence (finding 1).
                respawns += 1
                if respawns > self._MAX_RESPAWNS_PER_RUN:
                    for i in pending:
                        results[i] = _synthetic_observation(
                            "worker died or hung before booting; respawn budget exhausted"
                        )
                    break
                continue
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
                        results[i] = _synthetic_observation(
                            "worker stdin unwritable; respawn budget exhausted"
                        )
                    break
                continue
            if not self._await_ack(per_input_timeout, spawned_now):
                # The request never reached a living worker: no user code started, nothing
                # is attributable — retry within the budget (finding 1).
                respawns += 1
                if respawns > self._MAX_RESPAWNS_PER_RUN:
                    for i in pending:
                        results[i] = _synthetic_observation(
                            "worker never acknowledged a batch (dead-on-arrival stdin); "
                            "respawn budget exhausted"
                        )
                    break
                continue

            cursor = 0
            broke = False
            ended_early = False
            while cursor < len(pending):
                expected = pending[cursor]
                # Startup grace applies only to the first result off a freshly spawned worker;
                # a warm worker's batches pay no startup cost.
                budget = per_input_timeout + (
                    _STARTUP_GRACE_S if (spawned_now and cursor == 0) else 0.0
                )
                try:
                    raw = lines.get(timeout=budget)
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
                payload = _parse_line(raw)
                if payload is None:
                    # Finding 4: the garbled line poisons only THIS input, but index
                    # alignment is gone — retire and resume the remainder on a fresh worker.
                    results[expected] = _fatal_observation(
                        {"error": "garbled worker protocol line"}
                    )
                    self._retire()
                    cursor += 1
                    broke = True
                    break
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
                results[cast(int, payload["index"])] = _completed_observation(payload)
                cursor += 1
            if not broke and not ended_early and cursor >= len(pending):
                self._drain_sentinel(per_input_timeout)
            if broke:
                respawns += 1
                if respawns > self._MAX_RESPAWNS_PER_RUN:
                    for i in pending:
                        if i not in results:
                            # These inputs never ran at all — synthetic, not evidence.
                            results[i] = _synthetic_observation(
                                "respawn budget exhausted before this input could run"
                            )
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
        if raw is None:
            self._retire()  # the stream died under us — never reuse it
            return
        payload = _parse_line(raw)  # finding 4: a garbled sentinel must not raise
        if payload is None or not payload.get("batch_end"):
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


def _synthetic_observation(reason: str) -> SyntheticObservation:
    """Marked stand-in for an input the worker INFRASTRUCTURE failed to run (dead-on-arrival
    worker, pre-boot hang, respawn exhaustion). compare() refuses it as evidence — identical
    infrastructure failures on base and head surface as UNPROVEN, never as equivalence
    (review finding 1). Real user-code crashes keep using `_crashed_observation`."""
    return SyntheticObservation(
        outcome=InputOutcome.CRASHED,
        return_present=False,
        return_canon=None,
        raised=None,
        exit_status=-1,
        timing=Timing(wall_ns=0, cpu_ns=0),
        synthetic_reason=reason,
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
