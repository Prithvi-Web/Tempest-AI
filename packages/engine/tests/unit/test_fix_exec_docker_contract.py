"""Docker CLI argv contract (review findings 1a + 5), pinned against FAKE `docker` binaries
that execute as REAL subprocesses (no daemon on this machine, none needed to pin the argv):

- `docker run` must carry `-i` — without it the container's stdin is EOF, PersistentWorker
  serve batches die instantly on BOTH revisions, and identical synthetic crashes would have
  compared Equal (finding 1's L2/L4 catastrophe).
- `docker run` must carry a unique `--name tempest-<token>`, and every kill path must also
  `docker kill <token>`: SIGKILLing the docker CLI's process group stops only the client —
  the container keeps running and `--rm` never fires (finding 5).
"""

import re
import stat
import subprocess
import time
from pathlib import Path

from tempest.execute import runner
from tempest.execute.cancel import CancelScope
from tempest.execute.sandbox import DockerSandbox, kill_container

_NAME_RE = re.compile(r"--name (tempest-[0-9a-f]{12})")


def _fake_docker(tmp_path: Path, *, run_sleeps: bool) -> tuple[Path, Path]:
    """A real executable named docker that appends every argv to a record file; `docker run`
    optionally stays alive (something for the kill paths to kill), everything else exits 0."""
    record = tmp_path / "docker-invocations.txt"
    binary = tmp_path / "bin" / "docker"
    binary.parent.mkdir(parents=True, exist_ok=True)
    sleep_line = "  sleep 30\n" if run_sleeps else ""
    binary.write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" >> "{record}"\n'
        f'if [ "$1" = "run" ]; then\n{sleep_line}fi\n'
        "exit 0\n"
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binary, record


def _spawn(sandbox: DockerSandbox, tmp_path: Path) -> subprocess.Popen[bytes]:
    return sandbox.popen(
        ["/usr/bin/python3", "-s", "worker.py"], cwd=tmp_path, env={}, scratch=tmp_path
    )


def _run_line(record: Path) -> str:
    lines = [line for line in record.read_text().splitlines() if line.startswith("run ")]
    assert len(lines) >= 1
    return lines[0]


def _wait_for_run_line(record: Path) -> None:
    """The fake client needs a beat to append its argv before a kill test SIGKILLs it."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if record.exists() and any(
            line.startswith("run ") for line in record.read_text().splitlines()
        ):
            return
        time.sleep(0.02)
    raise AssertionError("fake docker never recorded its run invocation")


class TestWrapCommandContract:
    def test_run_carries_interactive_stdin_and_the_container_name(self) -> None:
        sandbox = DockerSandbox()
        cmd = sandbox.wrap_command(
            ["python3", "/scratch/worker.py"],
            workdir=Path("/r"),
            scratch=Path("/s"),
            name="tempest-0123456789ab",
        )
        assert "-i" in cmd
        assert cmd[cmd.index("--name") + 1] == "tempest-0123456789ab"
        # both must be run OPTIONS, i.e. sit before the image name
        image = cmd.index(sandbox.image)
        assert cmd.index("-i") < image
        assert cmd.index("--name") < image
        # the L6 flags are untouched by the additions
        joined = " ".join(cmd)
        for flag in (
            "--rm",
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--pids-limit",
            "--memory",
            "--user 10001",
            "no-new-privileges",
        ):
            assert flag in joined, flag

    def test_popen_delivers_i_and_a_unique_name_to_the_real_binary(self, tmp_path: Path) -> None:
        binary, record = _fake_docker(tmp_path, run_sleeps=False)
        sandbox = DockerSandbox(docker_binary=str(binary))
        first = _spawn(sandbox, tmp_path)
        first.wait()
        second = _spawn(sandbox, tmp_path)
        second.wait()
        run_lines = [ln for ln in record.read_text().splitlines() if ln.startswith("run ")]
        assert len(run_lines) == 2
        names = []
        for line in run_lines:
            assert " -i " in line
            match = _NAME_RE.search(line)
            assert match is not None, line
            names.append(match.group(1))
        assert names[0] != names[1], "container names must be unique per spawn"
        runner._kill(first)  # drop the registry entries so this test leaks nothing
        runner._kill(second)


class TestKillPathsReachTheContainer:
    def test_runner_kill_also_docker_kills_the_named_container(self, tmp_path: Path) -> None:
        binary, record = _fake_docker(tmp_path, run_sleeps=True)
        proc = _spawn(DockerSandbox(docker_binary=str(binary)), tmp_path)
        _wait_for_run_line(record)
        runner._kill(proc)
        assert proc.returncode is not None  # the client group died
        name = _NAME_RE.search(_run_line(record))
        assert name is not None
        kill_lines = [ln for ln in record.read_text().splitlines() if ln.startswith("kill ")]
        assert kill_lines == [f"kill {name.group(1)}"]

    def test_cancel_scope_also_docker_kills_the_named_container(self, tmp_path: Path) -> None:
        binary, record = _fake_docker(tmp_path, run_sleeps=True)
        proc = _spawn(DockerSandbox(docker_binary=str(binary)), tmp_path)
        _wait_for_run_line(record)
        scope = CancelScope()
        scope.register(proc)
        scope.cancel()
        proc.wait(timeout=2.0)
        name = _NAME_RE.search(_run_line(record))
        assert name is not None
        kill_lines = [ln for ln in record.read_text().splitlines() if ln.startswith("kill ")]
        assert kill_lines == [f"kill {name.group(1)}"]

    def test_kill_container_is_a_noop_for_non_docker_processes(self, tmp_path: Path) -> None:
        proc = subprocess.Popen(["sleep", "0"], start_new_session=True)
        proc.wait()
        kill_container(proc)  # nothing registered: must not invoke anything or raise

    def test_second_kill_never_docker_kills_twice(self, tmp_path: Path) -> None:
        binary, record = _fake_docker(tmp_path, run_sleeps=True)
        proc = _spawn(DockerSandbox(docker_binary=str(binary)), tmp_path)
        _wait_for_run_line(record)
        runner._kill(proc)
        runner._kill(proc)  # registry entry already consumed
        kill_lines = [ln for ln in record.read_text().splitlines() if ln.startswith("kill ")]
        assert len(kill_lines) == 1

    def test_kill_survives_the_docker_binary_vanishing(self, tmp_path: Path) -> None:
        binary, _record = _fake_docker(tmp_path, run_sleeps=True)
        proc = _spawn(DockerSandbox(docker_binary=str(binary)), tmp_path)
        binary.unlink()  # daemonless best-effort: OSError inside docker kill is suppressed
        runner._kill(proc)
        assert proc.returncode is not None
