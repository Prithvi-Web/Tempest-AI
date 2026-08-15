"""The in-sandbox worker driven IN-PROCESS (Law L4 — every path here really executes):
record/replay sessions over the real shims, loopback HTTP, protocol emission, the serve loop
over a real stdin stream, and `main()` itself.

Measurement note (why `_arc_supplement` exists): the worker OWNS `sys.settrace` — its line
tracer is the product — so from its first `sys.settrace(None)` the frame is invisible to
coverage's settrace-based core forever; no re-arm can light an already-running frame. The
fixture records the very same execution through `sys.monitoring` (PEP 669, independent of
settrace), reconstructs per-frame line arcs mechanically, and feeds them into the live
coverage data. Nothing is asserted from it and nothing is hand-listed: it is a second, real
measurement channel for lines that really ran. Every worker invocation runs in a dedicated
throwaway thread so the hijack can never blind the test session's own tracer.
"""

import io
import json
import runpy
import shutil
import socket
import sys
import threading
import urllib.request
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import coverage
import pytest

import tempest.compare.canonical as canonical_module
import tempest.determinism._shims as real_shims
from tempest.execute import _worker

WORKER_FILE = _worker.__file__
CANONICAL = cast(_worker._CanonicalModule, canonical_module)


class _ArcRecorder:
    """Records line arcs of `_worker.py` frames via sys.monitoring and injects them into the
    active coverage data — real execution, measured through the channel settrace cannot
    blind. Uses the first free monitoring tool id; a no-op under --no-cov."""

    def __init__(self) -> None:
        self.arcs: set[tuple[int, int]] = set()
        self._stack: list[list[Any]] = []
        self._tool: int | None = None

    def _push(self, code: Any, offset: int) -> Any:
        if code.co_filename != WORKER_FILE:
            return sys.monitoring.DISABLE
        self._stack.append([code, None])
        return None

    def _line(self, code: Any, line: int) -> Any:
        if code.co_filename != WORKER_FILE:
            return sys.monitoring.DISABLE
        if self._stack and self._stack[-1][0] is code:
            prev = self._stack[-1][1]
            self.arcs.add((prev, line) if prev is not None else (-code.co_firstlineno, line))
            self._stack[-1][1] = line
        return None

    def _pop(self, code: Any, offset: int, *_: Any) -> Any:
        if code.co_filename != WORKER_FILE:
            return None  # PY_UNWIND/PY_THROW cannot be locally disabled
        if self._stack and self._stack[-1][0] is code:
            _, last = self._stack.pop()
            if last is not None:
                self.arcs.add((last, -code.co_firstlineno))
        return None

    def start(self) -> None:
        mon = sys.monitoring
        for tool in (mon.COVERAGE_ID, mon.PROFILER_ID, mon.OPTIMIZER_ID):
            try:
                mon.use_tool_id(tool, "tempest-worker-arc-supplement")
            except ValueError:
                continue
            self._tool = tool
            break
        assert self._tool is not None, "no free sys.monitoring tool id"
        events = mon.events
        mon.register_callback(self._tool, events.PY_START, self._push)
        mon.register_callback(self._tool, events.PY_RESUME, self._push)
        mon.register_callback(self._tool, events.LINE, self._line)
        mon.register_callback(self._tool, events.PY_RETURN, self._pop)
        mon.register_callback(self._tool, events.PY_YIELD, self._pop)
        mon.register_callback(self._tool, events.PY_UNWIND, self._pop)
        mon.set_events(
            self._tool,
            events.PY_START
            | events.PY_RESUME
            | events.LINE
            | events.PY_RETURN
            | events.PY_YIELD
            | events.PY_UNWIND,
        )

    def stop_and_inject(self) -> None:
        mon = sys.monitoring
        assert self._tool is not None
        mon.set_events(self._tool, 0)
        for event in (
            mon.events.PY_START,
            mon.events.PY_RESUME,
            mon.events.LINE,
            mon.events.PY_RETURN,
            mon.events.PY_YIELD,
            mon.events.PY_UNWIND,
        ):
            mon.register_callback(self._tool, event, None)
        mon.free_tool_id(self._tool)
        cov = coverage.Coverage.current()
        if cov is not None and self.arcs:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cov.get_data().add_arcs({WORKER_FILE: self.arcs})


@pytest.fixture(autouse=True)
def arc_supplement() -> Iterator[_ArcRecorder]:
    recorder = _ArcRecorder()
    recorder.start()
    try:
        yield recorder
    finally:
        recorder.stop_and_inject()


@pytest.fixture(autouse=True)
def _clean_worker_modules() -> Iterator[None]:
    """Scratch modules import under bare names; leave no residue and no live patches."""
    yield
    shims = sys.modules.pop("shims", None)
    if shims is not None and getattr(shims, "_active", None) is not None:
        shims.uninstall()
    sys.modules.pop("canonical", None)
    for name in [n for n in sys.modules if n.startswith("wcov_")]:
        del sys.modules[name]


def run_in_thread(fn: Any) -> None:
    """Worker entry points hijack this thread's tracer; give them a disposable one."""
    failures: list[BaseException] = []

    def guarded() -> None:
        try:
            fn()
        except BaseException as exc:  # surfaced below as a test failure
            failures.append(exc)

    thread = threading.Thread(target=guarded)
    thread.start()
    thread.join(120)
    assert not thread.is_alive(), "worker call wedged"
    assert not failures, failures


def _scratch(tmp_path: Path) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    shutil.copyfile(cast(str, canonical_module.__file__), scratch / "canonical.py")
    shutil.copyfile(cast(str, real_shims.__file__), scratch / "shims.py")
    return scratch


def _project(tmp_path: Path, name: str, src: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / f"{name}.py").write_text(src)
    monkeypatch.syspath_prepend(str(proj))
    return proj


def _job(
    proj: Path,
    module: str,
    inputs: list[tuple[str, str]],
    determinism: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mode": "invoke",
        "module": module,
        "qualname": "f",
        "target_file": str(proj / f"{module}.py"),
        "sys_path": [str(proj)],
        "determinism": determinism,
        "inputs": [{"index": i, "args": a, "kwargs": k} for i, (a, k) in enumerate(inputs)],
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _emitted(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


class TestLoopbackWithShims:
    def test_handler_and_server_threads_mark_themselves_internal(self) -> None:
        port = _free_port()
        routes = {"/greet": {"status": 200, "body": "hello", "content_type": "text/plain"}}
        server: Any = _worker._start_loopback(routes, port, real_shims)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/greet", timeout=10) as resp:
                assert resp.read() == b"hello"
        finally:
            server.shutdown()
            server.server_close()


_NET_SRC = (
    "def f(url: str) -> str:\n"
    "    from urllib.request import urlopen\n"
    "    with urlopen(url) as resp:\n"
    "        return resp.read().decode()\n"
)


class TestRecordReplayInvoke:
    def test_record_then_replay_round_trips_through_the_cassette(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(tmp_path, "wcov_net", _NET_SRC, monkeypatch)
        monkeypatch.syspath_prepend(str(_scratch(tmp_path)))
        port = _free_port()
        record_job = _job(
            proj,
            "wcov_net",
            [("('__LOOPBACK__/greet',)", "{}")],
            determinism={
                "mode": "record",
                "loopback_routes": {
                    "/greet": {"status": 200, "body": "stormy", "content_type": "text/plain"}
                },
                "loopback_port": port,
            },
        )
        run_in_thread(lambda: _worker.do_invoke(record_job, CANONICAL))
        (recorded,) = _emitted(capsys)
        assert recorded["return_canon"] == canonical_module.canonicalize("stormy")
        assert recorded["effects"], "the NET interaction must land in the effects ledger"
        assert recorded["effects"][0]["surface"] == "NET"
        cassette = recorded["cassette"]
        assert set(cassette) == {"import", "input"}

        # Replay both cassette shapes: the {"import": …, "input": …} dict and a bare ledger.
        # The non-dict value sits first so the import-cassette scan really skips past it.
        replay_job = _job(
            proj,
            "wcov_net",
            [("('__LOOPBACK__/greet',)", "{}")] * 2,
            determinism={
                "mode": "replay",
                "cassettes": {"1": cassette["input"], "0": cassette},
                "loopback_port": port,  # no server this time: the cassette answers
            },
        )
        replay_job["inputs"] = [
            {"index": i, "args": "('__LOOPBACK__/greet',)", "kwargs": "{}"} for i in (0, 1)
        ]
        run_in_thread(lambda: _worker.do_invoke(replay_job, CANONICAL))
        first, second = _emitted(capsys)
        assert first["return_canon"] == canonical_module.canonicalize("stormy")
        assert second["return_canon"] == canonical_module.canonicalize("stormy")
        assert first["cassette_miss"] is None

    def test_call_time_cassette_miss_and_uninterceptable_are_fields_not_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path,
            "wcov_fx",
            "def f(x: int) -> float:\n"
            "    if x < 0:\n"
            "        import socket\n"
            "        socket.socket()\n"
            "    import time\n"
            "    return time.time()\n",
            monkeypatch,
        )
        monkeypatch.syspath_prepend(str(_scratch(tmp_path)))

        miss_job = _job(
            proj,
            "wcov_fx",
            [("(1,)", "{}")],
            determinism={"mode": "replay", "cassettes": {"0": []}, "loopback_port": 0},
        )
        run_in_thread(lambda: _worker.do_invoke(miss_job, CANONICAL))
        (missed,) = _emitted(capsys)
        assert missed["cassette_miss"] is not None
        assert "CLOCK" in missed["cassette_miss"] or "time" in missed["cassette_miss"]

        raw_job = _job(
            proj,
            "wcov_fx",
            [("(-1,)", "{}")],
            determinism={"mode": "record", "loopback_port": 0},
        )
        run_in_thread(lambda: _worker.do_invoke(raw_job, CANONICAL))
        (blocked,) = _emitted(capsys)
        assert blocked["uninterceptable"] is not None
        assert "socket" in blocked["uninterceptable"]


class TestImportFatalUnderShims:
    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        name: str,
        src: str,
        determinism: dict[str, Any],
    ) -> dict[str, Any]:
        proj = _project(tmp_path, name, src, monkeypatch)
        monkeypatch.syspath_prepend(str(_scratch(tmp_path)))
        job = _job(proj, name, [("()", "{}")], determinism=determinism)
        run_in_thread(lambda: _worker.do_invoke(job, CANONICAL))
        (payload,) = _emitted(capsys)
        assert payload["fatal"] == "import"
        return payload

    def test_uninterceptable_surface_at_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = self._run(
            tmp_path,
            monkeypatch,
            capsys,
            "wcov_impsock",
            "import socket\n\nsocket.socket()\n\n\ndef f() -> int:\n    return 0\n",
            {"mode": "record", "loopback_port": 0},
        )
        assert "socket" in payload["uninterceptable"]

    def test_cassette_miss_at_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = self._run(
            tmp_path,
            monkeypatch,
            capsys,
            "wcov_impclock",
            "import time\n\nSTAMP = time.time()\n\n\ndef f() -> int:\n    return 0\n",
            {"mode": "replay", "cassettes": {}, "loopback_port": 0},
        )
        assert payload["cassette_miss"]

    def test_plain_import_error_still_uninstalls_the_shims(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = self._run(
            tmp_path,
            monkeypatch,
            capsys,
            "wcov_impboom",
            "raise RuntimeError('boom at import')\n\n\ndef f() -> int:\n    return 0\n",
            {"mode": "record", "loopback_port": 0},
        )
        assert "boom at import" in payload["error"]
        assert sys.modules["shims"]._active is None  # uninstalled on the failure path


class TestOffModeBatchShapes:
    def test_bad_literal_raise_unrepresentable_and_return_in_one_batch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path,
            "wcov_mixed",
            "def f(x: int) -> object:\n"
            "    if x == 1:\n"
            "        raise ValueError('nope')\n"
            "    if x == 2:\n"
            "        return lambda: 0\n"
            "    return x * 10\n",
            monkeypatch,
        )
        job = _job(
            proj,
            "wcov_mixed",
            [("(unclosed", "{}"), ("(1,)", "{}"), ("(2,)", "{}"), ("(4,)", "{}")],
        )
        run_in_thread(lambda: _worker.do_invoke(job, CANONICAL))
        bad, raised, unrep, good = _emitted(capsys)
        assert bad["fatal"] == "input"
        assert raised["raised"]["type"] == "ValueError"
        assert unrep["return_present"] is False
        assert unrep["unrepresentable"] is not None
        assert good["return_canon"] == canonical_module.canonicalize(40)


class TestServeLoop:
    def _serve_job(self, proj: Path, module: str) -> dict[str, Any]:
        return {
            "mode": "serve",
            "module": module,
            "qualname": "f",
            "target_file": str(proj / f"{module}.py"),
            "sys_path": [str(proj)],
            "inputs": [],
        }

    def test_batches_blank_lines_and_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path, "wcov_serve", "def f(x: int) -> int:\n    return x + 5\n", monkeypatch
        )
        requests = (
            "\n"  # blank line: skipped, not a protocol error
            + json.dumps({"inputs": [{"index": 0, "args": "(1,)", "kwargs": "{}"}]})
            + "\n"
            + json.dumps({"inputs": [{"index": 1, "args": "(2,)", "kwargs": "{}"}]})
            + "\n"
            + json.dumps({"shutdown": True})
            + "\n"
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(requests))
        run_in_thread(lambda: _worker.do_serve(self._serve_job(proj, "wcov_serve"), CANONICAL))
        lines = _emitted(capsys)
        # Review finding 1: each batch now opens with a `batch_ack` line (emitted BEFORE any
        # user code) so the runner can tell dead-on-arrival stdin apart from real crashes.
        assert [line.get("batch_ack", False) for line in lines] == [
            True,
            False,
            False,
            True,
            False,
            False,
        ]
        assert [line.get("batch_end", False) for line in lines] == [
            False,
            False,
            True,
            False,
            False,
            True,
        ]
        assert lines[1]["return_canon"] == canonical_module.canonicalize(6)
        assert lines[4]["return_canon"] == canonical_module.canonicalize(7)

    def test_eof_without_shutdown_ends_the_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path, "wcov_serve2", "def f(x: int) -> int:\n    return x\n", monkeypatch
        )
        request = json.dumps({"inputs": [{"index": 0, "args": "(9,)", "kwargs": "{}"}]}) + "\n"
        monkeypatch.setattr(sys, "stdin", io.StringIO(request))
        run_in_thread(lambda: _worker.do_serve(self._serve_job(proj, "wcov_serve2"), CANONICAL))
        # Finding 1: the batch opens with its ack line now — result and sentinel follow.
        ack, result, sentinel = _emitted(capsys)
        assert ack == {"batch_ack": True}
        assert result["return_canon"] == canonical_module.canonicalize(9)
        assert sentinel == {"batch_end": True}


class TestFd1CaptureDrain:
    """The fd-capture drain body, measured in-process (finding 4). In a REAL worker the drain
    runs after the product tracer has owned and released sys.settrace, where coverage's
    settrace core is blind forever — the subprocess tests in test_fix_exec_fd1_protocol.py
    pin the behavior, and this test runs the same lines under the sys.monitoring arc
    supplement so they are also MEASURED. The reader is a real file object over a real file;
    only the module global is pointed at it (the fd-1 dup2 lifecycle itself is subprocess-
    pinned — hijacking the test session's fd 1 here would blind pytest)."""

    def test_drain_folds_real_fd_bytes_into_stdout_then_drains_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(tmp_path, "wcov_fd1", "def f(x: int) -> int:\n    return x\n", monkeypatch)
        capture = tmp_path / "fd1.capture"
        capture.write_bytes(b"raw fd bytes\n")
        with open(capture, "rb") as reader:
            monkeypatch.setattr(_worker, "_FD1_READER", reader)
            job = _job(proj, "wcov_fd1", [("(1,)", "{}"), ("(2,)", "{}")])
            run_in_thread(lambda: _worker.do_invoke(job, CANONICAL))
        first, second = _emitted(capsys)
        assert "raw fd bytes" in first["stdout"]  # folded into the FIRST input's stdout
        assert second["stdout"] == ""  # nothing new arrived: the empty-drain path


class TestMainDispatch:
    def _write_job(self, tmp_path: Path, job: dict[str, Any]) -> Path:
        job_path = tmp_path / "job.json"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        return job_path

    def _isolate_paths(self, monkeypatch: pytest.MonkeyPatch, job_path: Path) -> None:
        monkeypatch.setattr(sys, "path", [*sys.path])  # main() inserts entries; revert after
        monkeypatch.setattr(sys, "argv", ["worker", str(job_path)])
        # Finding 4: main() now repoints REAL fd 1 at a capture file. In-process it would be
        # the TEST SESSION's fd 1 — hijacking it would blind pytest itself, so the seam is
        # disabled here and dispatch keeps the sys.stdout fallback. The real fd isolation is
        # pinned by the SUBPROCESS runs in test_fix_exec_fd1_protocol.py/test_worker_direct.py.
        monkeypatch.setattr(_worker, "_isolate_protocol_fd", lambda scratch: None)

    def test_main_introspect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path,
            "wcov_main",
            "def f(a: int, b: str = 'x') -> str:\n    return b * a\n",
            monkeypatch,
        )
        job = {
            "mode": "introspect",
            "module": "wcov_main",
            "qualname": "f",
            "sys_path": [str(proj)],
            "scratch": str(_scratch(tmp_path)),
        }
        self._isolate_paths(monkeypatch, self._write_job(tmp_path, job))
        _worker.main()
        # Finding 1: main() announces boot before dispatching any mode.
        boot, payload = _emitted(capsys)
        assert boot == {"boot": True}
        assert payload["ok"] is True
        assert [p["name"] for p in payload["params"]] == ["a", "b"]

    def test_main_serve_shutdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path, "wcov_main2", "def f(x: int) -> int:\n    return x\n", monkeypatch
        )
        job = {
            "mode": "serve",
            "module": "wcov_main2",
            "qualname": "f",
            "target_file": str(proj / "wcov_main2.py"),
            "sys_path": [str(proj)],
            "scratch": str(_scratch(tmp_path)),
            "inputs": [],
        }
        self._isolate_paths(monkeypatch, self._write_job(tmp_path, job))
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"shutdown": true}\n'))
        _worker.main()
        # Finding 1: the boot announcement is the only line — shutdown acks nothing.
        assert _emitted(capsys) == [{"boot": True}]

    def test_main_invoke(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = _project(
            tmp_path, "wcov_main3", "def f(x: int) -> int:\n    return x * 3\n", monkeypatch
        )
        job = _job(proj, "wcov_main3", [("(4,)", "{}")])
        job["scratch"] = str(_scratch(tmp_path))
        self._isolate_paths(monkeypatch, self._write_job(tmp_path, job))
        run_in_thread(_worker.main)
        boot, payload = _emitted(capsys)  # finding 1: boot line precedes the result
        assert boot == {"boot": True}
        assert payload["return_canon"] == canonical_module.canonicalize(12)

    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_dunder_main_guard_runs_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
    ) -> None:
        # runpy executes a FRESH module copy, so the _isolate_protocol_fd seam patched by
        # _isolate_paths does not reach it: the REAL fd hijack (finding 4) runs inside this
        # test process. Observed with capfd — the protocol rides a dup of fd 1, which
        # python-level capsys cannot see; pytest's fd capture restores fd 1 afterwards.
        proj = _project(
            tmp_path, "wcov_main4", "def f(a: int) -> int:\n    return a\n", monkeypatch
        )
        job = {
            "mode": "introspect",
            "module": "wcov_main4",
            "qualname": "f",
            "sys_path": [str(proj)],
            "scratch": str(_scratch(tmp_path)),
        }
        self._isolate_paths(monkeypatch, self._write_job(tmp_path, job))
        runpy.run_module("tempest.execute._worker", run_name="__main__")
        boot, payload = _emitted(capfd)  # finding 1: boot line precedes the result
        assert boot == {"boot": True}
        assert payload["ok"] is True
