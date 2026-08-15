"""Direct tests for the in-sandbox worker (stage 6), coverage-visible.

`run_batch` exercises the worker through scrubbed-env sandbox children, which the parent
tracer cannot see. Here the same file is tested two honest ways (Law L4 — no mocks):

- its importable pieces run in-process against real modules, frames, and a real loopback
  HTTP server;
- the `python _worker.py job.json` protocol runs as a real subprocess that inherits this
  environment, so the child records its own coverage when the parent is measuring.
"""

import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.error import HTTPError

import coverage
import pytest

import tempest.compare.canonical as canonical_module
from tempest.execute import _worker

REPO_ROOT = Path(__file__).resolve().parents[4]


def write_module(tmp_path: Path, name: str, src: str) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / f"{name}.py").write_text(src)
    return proj


def make_scratch(tmp_path: Path) -> Path:
    """Mirror the runner's scratch layout: canonical.py copied next to the worker."""
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    shutil.copyfile(cast(str, canonical_module.__file__), scratch / "canonical.py")
    return scratch


def run_worker(tmp_path: Path, job: dict[str, object]) -> list[dict[str, Any]]:
    """Execute the real worker as a subprocess and parse its protocol lines.

    Invoked via `-m` so the child's __main__ carries the real module spec: a path-invoked
    script has no spec, and the child's coverage would attribute nothing to the package.
    The argv protocol (`... worker job.json`) is identical either way.
    """
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    env = os.environ.copy()
    if coverage.Coverage.current() is not None:
        env["COVERAGE_PROCESS_START"] = str(REPO_ROOT / "pyproject.toml")
    proc = subprocess.run(
        [sys.executable, "-m", "tempest.execute._worker", str(job_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payloads = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    # Review finding 1: the FIRST protocol line is always the boot announcement — the runner
    # uses it to tell "worker never ran" (infrastructure) apart from real target crashes.
    # Every test below keeps asserting on the result payloads that follow it.
    assert payloads and payloads[0] == {"boot": True}
    return payloads[1:]


def invoke_job(
    proj: Path, scratch: Path, module: str, inputs: list[tuple[str, str]]
) -> dict[str, object]:
    return {
        "mode": "invoke",
        "module": module,
        "qualname": "f",
        "target_file": str(proj / f"{module}.py"),
        "sys_path": [str(proj)],
        "scratch": str(scratch),
        "inputs": [{"index": i, "args": a, "kwargs": k} for i, (a, k) in enumerate(inputs)],
    }


class TestFormatAnnotation:
    def test_missing_annotation_is_none(self) -> None:
        assert _worker._format_annotation(inspect.Parameter.empty) is None

    def test_string_annotations_pass_through(self) -> None:
        assert _worker._format_annotation("int | None") == "int | None"

    def test_runtime_types_are_formatted(self) -> None:
        assert _worker._format_annotation(int) == "int"
        assert _worker._format_annotation(list[int]) == "list[int]"


class TestDefaultLiteral:
    def test_missing_default_is_none(self) -> None:
        assert _worker._default_literal(inspect.Parameter.empty) is None

    def test_literal_defaults_round_trip(self) -> None:
        assert _worker._default_literal(3) == "3"
        assert _worker._default_literal("x") == "'x'"

    def test_non_literal_defaults_are_none(self) -> None:
        assert _worker._default_literal(object()) is None


class TestResolve:
    def test_resolves_nested_qualnames(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        proj = write_module(
            tmp_path,
            "wdirect_resolve",
            "CONST = 41\n\n\nclass Box:\n    def get(self) -> int:\n        return CONST\n",
        )
        monkeypatch.syspath_prepend(str(proj))
        assert _worker._resolve("wdirect_resolve", "CONST") == 41
        method = _worker._resolve("wdirect_resolve", "Box.get")
        assert callable(method)
        assert method.__name__ == "get"


class TestDoIntrospectInProcess:
    def test_emits_params_with_annotations_and_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        proj = write_module(
            tmp_path, "wdirect_intro", "def f(a: int, b: str = 'x') -> str:\n    return b * a\n"
        )
        monkeypatch.syspath_prepend(str(proj))
        _worker.do_introspect("wdirect_intro", "f")
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert [p["name"] for p in payload["params"]] == ["a", "b"]
        assert payload["params"][0]["annotation"] == "int"
        assert payload["params"][1]["default_literal"] == "'x'"

    def test_unresolvable_target_reports_the_traceback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _worker.do_introspect("wdirect_definitely_missing", "f")
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert "ModuleNotFoundError" in payload["error"]


class TestTracer:
    def test_collects_lines_and_arcs_for_the_target_file(self) -> None:
        frame = sys._getframe()
        tracer = _worker._Tracer(frame.f_code.co_filename)
        local = tracer.global_trace(frame, "call", None)
        assert local == tracer.local_trace
        assert local(frame, "line", None) == tracer.local_trace  # first line: no arc yet
        first_line = next(iter(tracer.lines))
        assert local(frame, "line", None) == tracer.local_trace  # f_lineno moved with us
        assert len(tracer.lines) == 2
        assert len(tracer.arcs) == 1
        arc = next(iter(tracer.arcs))
        assert arc[0] == first_line

    def test_other_files_and_other_events_are_ignored(self) -> None:
        frame = sys._getframe()
        tracer = _worker._Tracer("/nonexistent/other_file.py")
        assert tracer.global_trace(frame, "call", None) is None
        matching = _worker._Tracer(frame.f_code.co_filename)
        assert matching.global_trace(frame, "return", None) is None
        assert matching.local_trace(frame, "return", None) == matching.local_trace
        assert matching.lines == set()


class TestLoopbackServer:
    def test_serves_canned_routes_and_404s_unknown_paths(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        routes = {"/greet": {"status": 200, "body": "hi there", "content_type": "text/plain"}}
        server: Any = _worker._start_loopback(routes, port)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/greet", timeout=10) as resp:
                assert resp.status == 200
                assert resp.headers["Content-Type"] == "text/plain"
                assert resp.read() == b"hi there"
            with pytest.raises(HTTPError) as excinfo:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=10)
            assert excinfo.value.code == 404
            assert excinfo.value.read() == b"not found"
        finally:
            server.shutdown()
            server.server_close()


class TestLoopbackSubstitution:
    def test_placeholder_is_rewritten_across_nested_containers(self) -> None:
        value = {
            "url": "__LOOPBACK__/api",
            "nested": ["__LOOPBACK__/a", ("__LOOPBACK__/b", 7)],
            "n": 3,
        }
        out = _worker._substitute_loopback(value, 8123)
        assert out["url"] == "http://127.0.0.1:8123/api"
        assert out["nested"][0] == "http://127.0.0.1:8123/a"
        assert out["nested"][1] == ("http://127.0.0.1:8123/b", 7)
        assert out["n"] == 3


class TestEffectsPayload:
    def test_fingerprints_are_stable_and_sensitive_to_payload(self) -> None:
        def entry(payload: object) -> SimpleNamespace:
            return SimpleNamespace(surface="NET", call="GET /x", ordinal=0, payload=payload)

        session_a = SimpleNamespace(ledger=[entry({"body": b"\x01" * 100, "n": [1, {"k": 2}]})])
        session_b = SimpleNamespace(ledger=[entry({"body": b"\x01" * 100, "n": [1, {"k": 2}]})])
        session_c = SimpleNamespace(ledger=[entry({"body": b"\x02" * 100, "n": [1, {"k": 2}]})])
        (a,) = _worker._effects_payload(session_a, None)
        (b,) = _worker._effects_payload(session_b, None)
        (c,) = _worker._effects_payload(session_c, None)
        assert a["surface"] == "NET"
        assert a["call"] == "GET /x"
        assert a["ordinal"] == 0
        assert len(cast(str, a["args_fingerprint"])) == 16
        assert a["args_fingerprint"] == b["args_fingerprint"]
        assert a["args_fingerprint"] != c["args_fingerprint"]

    def test_bytes_are_fingerprinted_by_length_and_head(self) -> None:
        encoded = _worker._encode_for_fingerprint({"blob": b"\xffabc", "xs": [b"", 1]})
        assert encoded == {
            "blob": {"__b64_len": 4, "__b64_head": b"\xffabc".hex()},
            "xs": [{"__b64_len": 0, "__b64_head": ""}, 1],
        }


class TestWorkerProtocolSubprocess:
    """The real `python worker.py job.json` contract, one JSON line per result."""

    def test_introspect_job_reports_the_signature(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path, "wmod", "def f(a: int, b: str = 'x') -> str:\n    return b * a\n"
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(
            tmp_path,
            {
                "mode": "introspect",
                "module": "wmod",
                "qualname": "f",
                "sys_path": [str(proj)],
                "scratch": str(scratch),
            },
        )
        assert payload["ok"] is True
        assert [p["name"] for p in payload["params"]] == ["a", "b"]
        assert payload["params"][0]["annotation"] == "int"
        assert payload["params"][1]["default_literal"] == "'x'"

    def test_introspect_of_missing_symbol_reports_failure(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "def f() -> None:\n    return None\n")
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(
            tmp_path,
            {
                "mode": "introspect",
                "module": "wmod",
                "qualname": "missing",
                "sys_path": [str(proj)],
                "scratch": str(scratch),
            },
        )
        assert payload["ok"] is False
        assert "AttributeError" in payload["error"]

    def test_invoke_observes_return_streams_timing_and_trace(self, tmp_path: Path) -> None:
        src = (
            "def f(x: int) -> int:\n"
            "    print('seen', x)\n"
            "    if x > 0:\n"
            "        return x * 2\n"
            "    return -x\n"
        )
        proj = write_module(tmp_path, "wmod", src)
        scratch = make_scratch(tmp_path)
        first, second = run_worker(
            tmp_path, invoke_job(proj, scratch, "wmod", [("(3,)", "{}"), ("(-4,)", "{}")])
        )
        assert first["outcome"] == "COMPLETED"
        assert first["return_present"] is True
        assert first["return_canon"] == canonical_module.canonicalize(6)
        assert first["stdout"] == "seen 3\n"
        assert first["raised"] is None
        assert first["wall_ns"] > 0
        assert first["cassette_miss"] is None
        assert first["uninterceptable"] is None
        assert "effects" not in first  # determinism off: no session, no cassette
        assert 4 in first["lines"] and 4 not in second["lines"]
        assert second["return_canon"] == canonical_module.canonicalize(4)
        assert any(arc[1] == 5 for arc in second["arcs"])

    def test_invoke_captures_exceptions_as_observations(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path, "wmod", "def f(x: int) -> int:\n    raise ValueError('nope %d' % x)\n"
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wmod", [("(5,)", "{}")]))
        assert payload["outcome"] == "COMPLETED"
        assert payload["return_present"] is False
        assert payload["raised"] == {
            "type": "ValueError",
            "module": "builtins",
            "message": "nope 5",
        }

    def test_invoke_applies_keyword_arguments(self, tmp_path: Path) -> None:
        proj = write_module(
            tmp_path,
            "wmod",
            "def f(x: int, *, flip: bool = False) -> int:\n    return -x if flip else x\n",
        )
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(
            tmp_path, invoke_job(proj, scratch, "wmod", [("(9,)", "{'flip': True}")])
        )
        assert payload["return_canon"] == canonical_module.canonicalize(-9)

    def test_unrepresentable_return_is_flagged_not_silently_equal(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "def f() -> object:\n    return lambda: 1\n")
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wmod", [("()", "{}")]))
        assert payload["return_present"] is False
        assert payload["unrepresentable"] is not None

    def test_bad_input_literal_is_fatal_for_that_input_only(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "def f(x: int) -> int:\n    return x\n")
        scratch = make_scratch(tmp_path)
        first, second = run_worker(
            tmp_path, invoke_job(proj, scratch, "wmod", [("(unclosed", "{}"), ("(4,)", "{}")])
        )
        assert first["fatal"] == "input"
        assert first["index"] == 0
        assert second["return_canon"] == canonical_module.canonicalize(4)

    def test_import_failure_is_fatal_with_a_traceback(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "raise RuntimeError('boom at import')\n")
        scratch = make_scratch(tmp_path)
        (payload,) = run_worker(tmp_path, invoke_job(proj, scratch, "wmod", [("()", "{}")]))
        assert payload["fatal"] == "import"
        assert "boom at import" in payload["error"]

    def test_a_batch_of_only_bad_literals_still_reports_each_input(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "def f(x: int) -> int:\n    return x\n")
        scratch = make_scratch(tmp_path)
        payloads = run_worker(
            tmp_path, invoke_job(proj, scratch, "wmod", [("(bad", "{}"), ("{oops", "{}")])
        )
        assert [p["fatal"] for p in payloads] == ["input", "input"]
        assert [p["index"] for p in payloads] == [0, 1]

    def test_loopback_placeholder_is_substituted_into_inputs(self, tmp_path: Path) -> None:
        proj = write_module(tmp_path, "wmod", "def f(url: str) -> str:\n    return url\n")
        scratch = make_scratch(tmp_path)
        job = invoke_job(proj, scratch, "wmod", [("('__LOOPBACK__/api',)", "{}")])
        job["determinism"] = {"mode": "off", "loopback_port": 8123}
        (payload,) = run_worker(tmp_path, job)
        expected = canonical_module.canonicalize("http://127.0.0.1:8123/api")
        assert payload["return_canon"] == expected
