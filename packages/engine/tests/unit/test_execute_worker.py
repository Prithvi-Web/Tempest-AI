"""Stage 6 substrate: the stdlib-only worker protocol + ProcessSandbox, via REAL subprocesses.

Law L4: every assertion here corresponds to an actual child process invocation — no mocks.
ProcessSandbox is the first-party-fixture backend (ADR-0003); DockerSandbox ships alongside and
is exercised for command assembly + availability detection only on Docker-less machines.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import coverage

from tempest.execute.runner import introspect_target, run_batch
from tempest.execute.sandbox import DockerSandbox, ProcessSandbox
from tempest.model import InputOutcome

REPO_ROOT = Path(__file__).resolve().parents[4]


def write_module(tmp_path: Path, name: str, src: str) -> Path:
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    (root / f"{name}.py").write_text(src)
    return root


SANDBOX = ProcessSandbox()


class TestIntrospect:
    def test_signature_and_annotations_come_back(self, tmp_path: Path) -> None:
        root = write_module(
            tmp_path, "m", "def f(a: int, b: str = 'x') -> str:\n    return b * a\n"
        )
        info = introspect_target(root, "m", "f", SANDBOX)
        assert info is not None
        assert [p.name for p in info.params] == ["a", "b"]
        assert info.params[0].annotation == "int"
        assert info.params[1].annotation == "str"
        assert info.params[1].default_literal == "'x'"

    def test_untyped_params_have_no_annotation(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "def f(a, b=3):\n    return a\n")
        info = introspect_target(root, "m", "f", SANDBOX)
        assert info is not None
        assert info.params[0].annotation is None
        assert info.params[1].default_literal == "3"

    def test_broken_module_import_returns_failure_not_crash(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "raise RuntimeError('boom at import')\n")
        info = introspect_target(root, "m", "f", SANDBOX)
        assert info is None


class TestRunBatch:
    def test_return_values_and_streams_are_observed(self, tmp_path: Path) -> None:
        root = write_module(
            tmp_path, "m", "def f(x: int) -> int:\n    print('seen', x)\n    return x * 2\n"
        )
        obs = run_batch(root, "m", "f", [("(3,)", "{}"), ("(10,)", "{}")], SANDBOX)
        assert [o.outcome for o in obs] == [InputOutcome.COMPLETED] * 2
        assert obs[0].return_present and obs[1].return_present
        assert obs[0].stdout == "seen 3\n"
        from tempest.compare.canonical import canonicalize

        assert obs[0].return_canon == canonicalize(6)
        assert obs[1].return_canon == canonicalize(20)

    def test_target_exception_is_an_observation_not_a_failure(self, tmp_path: Path) -> None:
        root = write_module(
            tmp_path, "m", "def f(x: int) -> int:\n    raise ValueError('nope %d' % x)\n"
        )
        (o,) = run_batch(root, "m", "f", [("(5,)", "{}")], SANDBOX)
        assert o.outcome is InputOutcome.COMPLETED
        assert o.raised is not None
        assert o.raised.type_name == "ValueError"
        assert o.raised.message == "nope 5"
        assert not o.return_present

    def test_hang_is_detected_and_batch_continues(self, tmp_path: Path) -> None:
        src = (
            "def f(x: int) -> int:\n"
            "    if x == 1:\n"
            "        while True:\n"
            "            pass\n"
            "    return x\n"
        )
        root = write_module(tmp_path, "m", src)
        obs = run_batch(
            root,
            "m",
            "f",
            [("(0,)", "{}"), ("(1,)", "{}"), ("(2,)", "{}")],
            SANDBOX,
            per_input_timeout=1.0,
        )
        assert [o.outcome for o in obs] == [
            InputOutcome.COMPLETED,
            InputOutcome.HUNG,
            InputOutcome.COMPLETED,
        ]

    def test_hard_crash_is_an_observation(self, tmp_path: Path) -> None:
        src = "import ctypes\n\n\ndef f(x: int) -> int:\n    ctypes.string_at(0)\n    return x\n"
        root = write_module(tmp_path, "m", src)
        obs = run_batch(root, "m", "f", [("(1,)", "{}"), ("(2,)", "{}")], SANDBOX)
        assert obs[0].outcome is InputOutcome.CRASHED
        assert (
            obs[1].outcome is InputOutcome.CRASHED
        )  # crash killed the worker; both inputs rerun/observed

    def test_unrepresentable_return_is_flagged(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "def f() -> object:\n    return lambda: 1\n")
        (o,) = run_batch(root, "m", "f", [("()", "{}")], SANDBOX)
        assert o.outcome is InputOutcome.COMPLETED
        assert o.unrepresentable is not None

    def test_changed_line_arcs_are_reported(self, tmp_path: Path) -> None:
        src = "def f(x: int) -> str:\n    if x > 0:\n        return 'pos'\n    return 'neg'\n"
        root = write_module(tmp_path, "m", src)
        obs = run_batch(root, "m", "f", [("(5,)", "{}"), ("(-5,)", "{}")], SANDBOX)
        assert 3 in obs[0].executed_lines
        assert 3 not in obs[1].executed_lines
        assert 4 in obs[1].executed_lines

    def test_env_is_scrubbed_no_parent_leakage(self, tmp_path: Path) -> None:
        import os

        os.environ["TEMPEST_LEAK_CANARY"] = "leaked"
        try:
            src = (
                "import os\n\n\ndef f() -> str:\n"
                "    return os.environ.get('TEMPEST_LEAK_CANARY', 'clean')\n"
            )
            root = write_module(tmp_path, "m", src)
            (o,) = run_batch(root, "m", "f", [("()", "{}")], SANDBOX)
            from tempest.compare.canonical import canonicalize

            assert o.return_canon == canonicalize("clean")
        finally:
            del os.environ["TEMPEST_LEAK_CANARY"]


class TestProcessSandbox:
    def test_first_party_backend_is_always_available(self) -> None:
        assert ProcessSandbox().available() is True

    def test_child_rlimits_are_applied_in_a_real_child(self) -> None:
        # _set_child_limits normally runs as preexec_fn inside the forked worker; here a real
        # child applies it and reports the resulting limits back over stdout.
        code = (
            "import resource\n"
            "from tempest.execute.sandbox import _set_child_limits\n"
            "_set_child_limits()\n"
            "print(resource.getrlimit(resource.RLIMIT_CPU),\n"
            "      resource.getrlimit(resource.RLIMIT_CORE))\n"
        )
        env = os.environ.copy()
        if coverage.Coverage.current() is not None:
            env["COVERAGE_PROCESS_START"] = str(REPO_ROOT / "pyproject.toml")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "(120, 120) (0, 0)" in proc.stdout


class TestDockerSandbox:
    def test_unavailable_docker_reports_honestly(self) -> None:
        sandbox = DockerSandbox(docker_binary="/nonexistent/docker")
        assert sandbox.available() is False

    def test_available_reflects_the_probe_exit_status(self) -> None:
        # availability is `<binary> info` exiting 0; pointing the binary at real true/false
        # executables exercises the probe as a real subprocess without needing a Docker daemon.
        true_bin = shutil.which("true")
        false_bin = shutil.which("false")
        assert true_bin is not None and false_bin is not None
        assert DockerSandbox(docker_binary=true_bin).available() is True
        assert DockerSandbox(docker_binary=false_bin).available() is False

    def test_popen_launches_the_wrapped_argv(self, tmp_path: Path) -> None:
        # substituting `echo` for docker makes the child print the exact argv popen assembled,
        # proving the L6 flags survive from wrap_command into the spawned process.
        echo = shutil.which("echo")
        assert echo is not None
        sandbox = DockerSandbox(docker_binary=echo)
        with sandbox.popen(
            ["python", "/scratch/worker.py"], cwd=tmp_path, env={}, scratch=tmp_path
        ) as proc:
            assert proc.stdout is not None
            out = proc.stdout.read().decode()
            proc.wait()
        assert out.startswith("run --rm --network none --read-only")
        assert "--cap-drop ALL" in out
        assert f"{tmp_path}:/scratch" in out
        assert out.rstrip().endswith("tempest-sandbox:latest python /scratch/worker.py")

    def test_command_assembly_enforces_l6(self) -> None:
        sandbox = DockerSandbox()
        cmd = sandbox.wrap_command(
            ["python", "/scratch/worker.py", "/scratch/job.json"],
            workdir=Path("/repo"),
            scratch=Path("/tmp/s"),
        )
        joined = " ".join(cmd)
        assert "--network none" in joined
        assert "--read-only" in joined
        assert "--cap-drop ALL" in joined
        assert "--memory" in joined
        assert "--pids-limit" in joined
        assert "--user" in joined
