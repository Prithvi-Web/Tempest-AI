"""The in-sandbox worker. STDLIB-ONLY — this file is copied into the scratch mount and executed
by the target repo's interpreter, where tempest is not installed. It imports `canonical` from a
sibling copy the runner places next to it (single source of truth: tempest/compare/canonical.py).

Protocol: `python worker.py job.json`; one JSON line per result on stdout, flushed immediately
(the runner uses line arrival for hang detection). Target stdout/stderr are captured per input;
the real stdout belongs to the protocol.
"""

import ast
import importlib
import inspect
import io
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from types import FrameType
from typing import Any, Protocol, cast


class _CanonicalModule(Protocol):
    class Unrepresentable(Exception):
        reason: str

    @staticmethod
    def canonicalize(obj: object) -> object: ...


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


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


def do_invoke(job: dict[str, Any], canonical: _CanonicalModule) -> None:
    module_name: str = job["module"]
    qualname: str = job["qualname"]
    target_file: str = job["target_file"]
    try:
        fn = _resolve(module_name, qualname)
    except BaseException:
        _emit({"fatal": "import", "error": traceback.format_exc(limit=5)})
        return

    for entry in job["inputs"]:
        index: int = entry["index"]
        try:
            args = tuple(ast.literal_eval(entry["args"]))
            kwargs = dict(ast.literal_eval(entry["kwargs"]))
        except (ValueError, SyntaxError):
            _emit({"index": index, "fatal": "input", "error": traceback.format_exc(limit=2)})
            continue

        out_buf, err_buf = io.StringIO(), io.StringIO()
        tracer = _Tracer(target_file)
        raised: dict[str, str] | None = None
        return_present = False
        return_canon: object = None
        unrepresentable: str | None = None

        wall0 = time.perf_counter_ns()
        cpu0 = time.process_time_ns()
        sys.settrace(tracer.global_trace)
        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                result = fn(*args, **kwargs)
        except BaseException as exc:
            raised = {
                "type": type(exc).__name__,
                "module": type(exc).__module__,
                "message": str(exc),
            }
        finally:
            sys.settrace(None)
        wall = time.perf_counter_ns() - wall0
        cpu = time.process_time_ns() - cpu0

        if raised is None:
            try:
                return_canon = canonical.canonicalize(result)
                return_present = True
            except Exception as exc:
                reason = getattr(exc, "reason", None)
                unrepresentable = reason if isinstance(reason, str) else repr(exc)

        _emit(
            {
                "index": index,
                "outcome": "COMPLETED",
                "return_present": return_present,
                "return_canon": return_canon,
                "raised": raised,
                "stdout": out_buf.getvalue(),
                "stderr": err_buf.getvalue(),
                "wall_ns": wall,
                "cpu_ns": cpu,
                "lines": sorted(tracer.lines),
                "arcs": sorted(list(a) for a in tracer.arcs),
                "unrepresentable": unrepresentable,
            }
        )


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as fh:
        job: dict[str, Any] = json.load(fh)
    for entry in reversed(job["sys_path"]):
        sys.path.insert(0, entry)
    sys.path.insert(0, job["scratch"])
    canonical = cast(_CanonicalModule, importlib.import_module("canonical"))
    if job["mode"] == "introspect":
        do_introspect(job["module"], job["qualname"])
    else:
        do_invoke(job, canonical)


if __name__ == "__main__":
    main()
