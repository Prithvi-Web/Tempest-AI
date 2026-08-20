"""The in-sandbox worker. STDLIB-ONLY — this file is copied into the scratch mount and executed
by the target repo's interpreter, where tempest is not installed. It imports `canonical` (and,
for impure targets, `shims`) from sibling copies the runner places next to it.

Protocol: `python worker.py job.json`; one JSON line per result on stdout, flushed immediately
(the runner uses line arrival for hang detection). Target stdout/stderr are captured per input.

Determinism (job["determinism"]): mode "off" | "record" | "replay". Record wraps every input in
a fresh shim Session and emits its cassette; replay feeds the recorded cassette back in. A
cassette miss or an un-interceptable surface is reported as a dedicated field — evidence,
never a silent pass.
"""

import ast
import hashlib
import importlib
import inspect
import io
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from types import FrameType
from typing import Any, Protocol, cast

# The worker's own instrumentation must survive shim installation.
_PERF_NS = time.perf_counter_ns
_CPU_NS = time.process_time_ns

# Fd-level protocol isolation (review finding 4), installed by `_isolate_protocol_fd` when the
# worker runs as a real subprocess. None → in-process harnesses: _emit falls back to
# sys.stdout and no fd capture exists.
_PROTOCOL_OUT: "io.TextIOWrapper | None" = None
_FD1_READER: "io.BufferedReader | None" = None


def _isolate_protocol_fd(scratch: str) -> None:
    """Lock user code out of the protocol stream (review finding 4).

    `redirect_stdout` is Python-level only: `os.write(1, ...)`, a spawned subprocess
    inheriting stdout, or an import-time print all reach REAL fd 1 and would interleave with
    the JSONL protocol — forging results or garbling lines. So: keep a private dup of the
    original stdout for protocol lines, and repoint fd 1 itself at a capture file in the
    scratch mount. Everything user code writes to the real fd becomes per-input observed
    stdout (evidence), never protocol."""
    global _PROTOCOL_OUT, _FD1_READER
    protocol_fd = os.dup(1)
    capture_path = os.path.join(scratch, f"fd1-{os.getpid()}.capture")
    capture_fd = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(capture_fd, 1)
    os.close(capture_fd)
    _PROTOCOL_OUT = os.fdopen(protocol_fd, "w", encoding="utf-8")
    # Deliberately no context manager: the reader lives for the whole worker process
    # (drained per input); a `with` would close it before the first batch even runs.
    _FD1_READER = open(capture_path, "rb")  # noqa: SIM115


def _drain_fd1_capture() -> str:
    """New bytes user code wrote to REAL fd 1 since the last drain — folded into the current
    input's observed stdout. Bytes written between inputs (import-time prints, stray threads)
    ride with the NEXT input on both revisions, so the attribution is deterministic."""
    if _FD1_READER is None:
        return ""
    sys.stdout.flush()  # buffered Python-level writes outside the redirect ride the real fd
    data = _FD1_READER.read()
    if not data:
        return ""
    return data.decode("utf-8", errors="replace")


class _CanonicalModule(Protocol):
    class Unrepresentable(Exception):
        reason: str

    @staticmethod
    def canonicalize(obj: object) -> object: ...

    @staticmethod
    def parse_input_literal(text: str) -> object: ...


def _emit(payload: dict[str, object]) -> None:
    out = _PROTOCOL_OUT if _PROTOCOL_OUT is not None else sys.stdout
    out.write(json.dumps(payload) + "\n")
    out.flush()


def _resolve(module_name: str, qualname: str) -> Any:  # arbitrary user callable
    obj: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def _format_annotation(ann: object) -> str | None:
    if ann is inspect.Parameter.empty:
        return None
    if isinstance(ann, str):
        return ann
    return inspect.formatannotation(cast(Any, ann))


def _default_literal(default: object) -> str | None:
    if default is inspect.Parameter.empty:
        return None
    text = repr(default)
    try:
        ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    return text


def do_introspect(module_name: str, qualname: str) -> None:
    try:
        fn = _resolve(module_name, qualname)
        sig = inspect.signature(fn)
    except BaseException:
        _emit({"ok": False, "error": traceback.format_exc(limit=3)})
        return
    params = [
        {
            "name": p.name,
            "kind": p.kind.name,
            "annotation": _format_annotation(p.annotation),
            "default_literal": _default_literal(p.default),
        }
        for p in sig.parameters.values()
    ]
    _emit({"ok": True, "params": params})


def do_import(module_name: str) -> None:
    """Does this module still load? One question, one answer, nothing else measured.

    A file can change with no changed SYMBOL — a new import, a module-level statement, a
    decorator evaluated at load time — and then no target exists and the proof has nothing to
    say. That silence is not the same as "nothing happened": a module that no longer imports
    has stopped doing everything it used to do, and F3 treats a repair that leaves one behind
    as a destroyed target rather than a fixed one.

    `BaseException` on purpose. A module-level `sys.exit()` or a `KeyboardInterrupt` raised by
    import-time code is a load failure exactly like an `ImportError`; narrowing to `Exception`
    would report the worst ones as successes. A module that kills the process outright emits
    no line at all, which the runner reads as a failure — the conservative direction.

    The answer carries the resolved `__file__`, because "the name imported" and "the file
    imported" are different facts and only the second one is the question.
    """
    try:
        module = importlib.import_module(module_name)
    except BaseException:
        _emit({"ok": False, "error": traceback.format_exc(limit=5)})
        return
    # WHICH file answered to that name. A dotted name is not a file: the scratch mount, a
    # `[roots].source` entry the agent can write, or a top-level module of the same name can all
    # win the import and report a healthy load for a file nobody asked about. The caller compares
    # this against the path it is actually judging.
    _emit({"ok": True, "file": str(getattr(module, "__file__", "") or "")})


class _Tracer:
    """Line + arc collection restricted to the target file (sys.settrace, stdlib-only)."""

    def __init__(self, target_file: str) -> None:
        self.target_file = target_file
        self.lines: set[int] = set()
        self.arcs: set[tuple[int, int]] = set()
        self._last: dict[int, int] = {}

    def global_trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "call" and frame.f_code.co_filename == self.target_file:
            self._last[id(frame)] = -1
            return self.local_trace
        return None

    def local_trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if event == "line":
            line = frame.f_lineno
            self.lines.add(line)
            prev = self._last.get(id(frame), -1)
            if prev != -1:
                self.arcs.add((prev, line))
            self._last[id(frame)] = line
        return self.local_trace


def _start_loopback(routes: dict[str, Any], port: int, shims: Any = None) -> object:
    """Serve canned routes on 127.0.0.1 for the HTTP corpus (record mode only)."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self) -> None:
            # Handler threads are spawned per request; their own clock/env use is server
            # machinery, not target behavior — keep it out of the ledger.
            if shims is not None:
                shims.allow_internal_in_this_thread()
            super().setup()

        def do_GET(self) -> None:  # http.server API name
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
                return
            body = str(route.get("body", "")).encode()
            self.send_response(int(route.get("status", 200)))
            self.send_header("Content-Type", str(route.get("content_type", "text/plain")))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # silence request logging
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)

    def serve() -> None:
        if shims is not None:
            shims.allow_internal_in_this_thread()
        server.serve_forever()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server


def _substitute_loopback(value: Any, port: int) -> Any:
    if isinstance(value, str):
        return value.replace("__LOOPBACK__", f"http://127.0.0.1:{port}")
    if isinstance(value, tuple):
        return tuple(_substitute_loopback(v, port) for v in value)
    if isinstance(value, list):
        return [_substitute_loopback(v, port) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_loopback(v, port) for k, v in value.items()}
    return value


def _effects_payload(session: Any, shims: Any) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for e in session.ledger:
        encoded = json.dumps(_encode_for_fingerprint(e.payload), sort_keys=True, default=repr)
        out.append(
            {
                "surface": e.surface,
                "call": e.call,
                "ordinal": e.ordinal,
                "args_fingerprint": hashlib.sha256(encoded.encode()).hexdigest()[:16],
            }
        )
    return out


def _encode_for_fingerprint(payload: Any) -> Any:
    if isinstance(payload, bytes):
        return {"__b64_len": len(payload), "__b64_head": payload[:64].hex()}
    if isinstance(payload, list):
        return [_encode_for_fingerprint(p) for p in payload]
    if isinstance(payload, dict):
        return {k: _encode_for_fingerprint(v) for k, v in payload.items()}
    return payload


def do_invoke(job: dict[str, Any], canonical: _CanonicalModule) -> None:
    module_name: str = job["module"]
    qualname: str = job["qualname"]
    target_file: str = job["target_file"]
    det: dict[str, Any] = job.get("determinism") or {"mode": "off"}
    mode: str = det.get("mode", "off")

    shims: Any = None
    if mode in ("record", "replay"):
        shims = importlib.import_module("shims")

    loopback_port = int(det.get("loopback_port") or 0)
    if mode == "record" and det.get("loopback_routes"):
        _start_loopback(det["loopback_routes"], loopback_port, shims)

    cassettes: dict[str, Any] = det.get("cassettes") or {}

    # Patches must be live BEFORE the target module is imported, so `from time import time`
    # style bindings capture the shims. Import-time interactions ride in every input's cassette
    # under "import" so replay workers reproduce the exact same module-load world.
    import_session: Any = None
    if shims is not None:
        import_cassette = None
        if mode == "replay":
            for value in cassettes.values():
                if isinstance(value, dict) and "import" in value:
                    import_cassette = value["import"]
                    break
        import_session = shims.Session(mode=mode, cassette=import_cassette)
        shims.install(import_session)

    try:
        fn = _resolve(module_name, qualname)
    except BaseException as exc:
        if shims is not None:
            detail = str(exc)
            if isinstance(exc, shims.UninterceptableEffect):
                shims.uninstall()
                _emit({"fatal": "import", "uninterceptable": detail})
                return
            if isinstance(exc, shims.CassetteMiss):
                shims.uninstall()
                _emit({"fatal": "import", "cassette_miss": detail})
                return
            shims.uninstall()
        _emit({"fatal": "import", "error": traceback.format_exc(limit=5)})
        return

    for entry in job["inputs"]:
        index: int = entry["index"]
        try:
            args = tuple(cast("tuple[Any, ...]", canonical.parse_input_literal(entry["args"])))
            kwargs = dict(cast("dict[str, Any]", canonical.parse_input_literal(entry["kwargs"])))
        except (ValueError, SyntaxError):
            _emit({"index": index, "fatal": "input", "error": traceback.format_exc(limit=2)})
            continue
        if loopback_port:
            args = _substitute_loopback(args, loopback_port)
            kwargs = _substitute_loopback(kwargs, loopback_port)

        out_buf, err_buf = io.StringIO(), io.StringIO()
        tracer = _Tracer(target_file)
        raised: dict[str, str] | None = None
        return_present = False
        return_canon: object = None
        unrepresentable: str | None = None
        cassette_miss: str | None = None
        uninterceptable: str | None = None
        session: Any = None

        if shims is not None:
            input_cassette = None
            if mode == "replay":
                raw_cassette = cassettes.get(str(index))
                if isinstance(raw_cassette, dict):
                    input_cassette = raw_cassette.get("input")
                else:
                    input_cassette = raw_cassette
            session = shims.Session(mode=mode, cassette=input_cassette)
            shims.set_session(session)

        wall0 = _PERF_NS()
        cpu0 = _CPU_NS()
        sys.settrace(tracer.global_trace)
        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                if inspect.iscoroutinefunction(fn):
                    # ADR-0026: async targets run to completion on a fresh loop per call —
                    # the coroutine's frames still trace (coverage) and its effects still
                    # hit the determinism shims like any synchronous callable.
                    import asyncio

                    result = asyncio.run(fn(*args, **kwargs))
                else:
                    result = fn(*args, **kwargs)
        except BaseException as exc:
            if shims is not None and isinstance(exc, shims.CassetteMiss):
                cassette_miss = str(exc)
            elif shims is not None and isinstance(exc, shims.UninterceptableEffect):
                uninterceptable = str(exc)
            else:
                raised = {
                    "type": type(exc).__name__,
                    "module": type(exc).__module__,
                    "message": str(exc),
                }
        finally:
            sys.settrace(None)
            if shims is not None:
                shims.set_session(import_session)  # keep patches; park interactions harmlessly
        wall = _PERF_NS() - wall0
        cpu = _CPU_NS() - cpu0

        if raised is None and cassette_miss is None and uninterceptable is None:
            try:
                return_canon = canonical.canonicalize(result)
                return_present = True
            except Exception as exc:
                reason = getattr(exc, "reason", None)
                unrepresentable = reason if isinstance(reason, str) else repr(exc)

        payload: dict[str, object] = {
            "index": index,
            "outcome": "COMPLETED",
            "return_present": return_present,
            "return_canon": return_canon,
            "raised": raised,
            # Python-level capture first, then whatever the input wrote to REAL fd 1
            # (os.write / inherited-subprocess stdout) — honest output, never protocol.
            "stdout": out_buf.getvalue() + _drain_fd1_capture(),
            "stderr": err_buf.getvalue(),
            "wall_ns": wall,
            "cpu_ns": cpu,
            "lines": sorted(tracer.lines),
            "arcs": sorted(list(a) for a in tracer.arcs),
            "unrepresentable": unrepresentable,
            "cassette_miss": cassette_miss,
            "uninterceptable": uninterceptable,
        }
        if session is not None:
            payload["effects"] = _effects_payload(session, shims)
            if mode == "record":
                payload["cassette"] = {
                    "import": import_session.cassette_data(),
                    "input": session.cassette_data(),
                }
        _emit(payload)


def do_serve(job: dict[str, Any], canonical: _CanonicalModule) -> None:
    """Persistent pure-path worker: one process, many batches over stdin (JSONL), a
    `batch_end` sentinel after each. The target module imports once and stays loaded — the
    same state model as one large batch, which the pure path already runs. Determinism
    (record/replay) batches never use serve mode: their shim install/uninstall lifecycle owns
    process boundaries and stays one-process-per-batch."""
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        request: dict[str, Any] = json.loads(text)
        if request.get("shutdown"):
            return
        # Ack BEFORE any user code: the runner uses this to tell "worker died while running
        # an input" (real evidence) apart from "the request never reached a living worker"
        # (infrastructure — e.g. a container whose stdin was EOF; review finding 1).
        _emit({"batch_ack": True})
        batch = dict(job)
        batch["inputs"] = request["inputs"]
        batch["determinism"] = None
        do_invoke(batch, canonical)
        _emit({"batch_end": True})


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as fh:
        job: dict[str, Any] = json.load(fh)
    for entry in reversed(job["sys_path"]):
        sys.path.insert(0, entry)
    sys.path.insert(0, job["scratch"])
    _isolate_protocol_fd(job["scratch"])  # finding 4: user code never touches the protocol fd
    canonical = cast(_CanonicalModule, importlib.import_module("canonical"))
    # First protocol line, before ANY target code can run: the runner treats a worker that
    # dies without it as infrastructure failure, never as target evidence (finding 1).
    _emit({"boot": True})
    if job["mode"] == "introspect":
        do_introspect(job["module"], job["qualname"])
    elif job["mode"] == "import":
        do_import(job["module"])
    elif job["mode"] == "serve":
        do_serve(job, canonical)
    else:
        do_invoke(job, canonical)


if __name__ == "__main__":
    main()
