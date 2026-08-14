"""Sandbox backends (Law L6 + ADR-0003).

DockerSandbox is the only backend for user repos: no network, read-only rootfs, scratch tmpfs,
memory/pids limits, non-root, seccomp. ProcessSandbox exists solely so Tempest's own first-party
fixtures and corpus can run on machines without a container runtime; the CLI refuses it for
arbitrary repos and reports UNPROVEN(SANDBOX_UNAVAILABLE) instead.
"""

import resource
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol


class Sandbox(Protocol):
    def available(self) -> bool: ...

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        """Rewrite host paths inside a worker job for wherever the backend executes.

        ProcessSandbox runs on the host → identity. DockerSandbox runs in a container where
        the host paths do not exist → maps them onto the container mounts.
        """
        ...

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]: ...


def _set_child_limits() -> None:
    # Hard CPU ceiling so a spinning child dies even if the parent does; no core dumps.
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform == "linux":
        # Address-space limits are only reliable on Linux; macOS dev runs rely on the
        # per-input timeout, production runs rely on the container's --memory limit.
        resource.setrlimit(resource.RLIMIT_AS, (1 << 31, 1 << 31))  # pragma: no cover — Linux-only


@dataclass(frozen=True)
class ProcessSandbox:
    """Separate process, scrubbed env, rlimits, session isolation. First-party fixtures only."""

    def available(self) -> bool:
        return True

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        return job

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=_set_child_limits,
        )


_CONTAINER_REPO = PurePosixPath("/repo")
_CONTAINER_SCRATCH = PurePosixPath("/scratch")
_CONTAINER_PYTHON = "python3"


@dataclass(frozen=True)
class DockerSandbox:
    """The production backend. Every flag here is load-bearing for L6; none are optional."""

    image: str = "tempest-sandbox:latest"
    docker_binary: str = "docker"
    memory: str = "512m"
    pids_limit: int = 128
    seccomp_profile: str = "docker/seccomp-tempest.json"

    def available(self) -> bool:
        binary = shutil.which(self.docker_binary)
        if binary is None:
            return False
        probe = subprocess.run([binary, "info"], capture_output=True, timeout=10, check=False)
        return probe.returncode == 0

    @staticmethod
    def _map_path(text: str, *, workdir: Path, scratch: Path) -> str:
        """Host path → container path via the /repo and /scratch mounts; non-paths pass through."""
        path = Path(text)
        if not path.is_absolute():
            return text
        if path.is_relative_to(scratch):
            return str(_CONTAINER_SCRATCH.joinpath(*path.relative_to(scratch).parts))
        if path.is_relative_to(workdir):
            return str(_CONTAINER_REPO.joinpath(*path.relative_to(workdir).parts))
        return text

    def translate_command(self, cmd: list[str], *, workdir: Path, scratch: Path) -> list[str]:
        """Host argv → container argv: the interpreter (argv[0]) becomes the image's `python3`;
        every path under a mount is rewritten onto that mount. The host interpreter path would
        be meaningless inside the container — the image ships its own CPython."""
        translated = [_CONTAINER_PYTHON]
        translated.extend(self._map_path(arg, workdir=workdir, scratch=scratch) for arg in cmd[1:])
        return translated

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        """The job file rides into the container too: sys_path/scratch/target_file are host
        paths when written and must resolve inside the container's mounts."""
        translated = dict(job)
        sys_path = translated.get("sys_path")
        if isinstance(sys_path, list):
            translated["sys_path"] = [
                self._map_path(str(entry), workdir=workdir, scratch=scratch) for entry in sys_path
            ]
        for key in ("scratch", "target_file"):
            value = translated.get(key)
            if isinstance(value, str):
                translated[key] = self._map_path(value, workdir=workdir, scratch=scratch)
        return translated

    def wrap_command(self, cmd: list[str], *, workdir: Path, scratch: Path) -> list[str]:
        return [
            self.docker_binary,
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:size=64m",
            "--volume",
            f"{workdir}:/repo:ro",
            "--volume",
            f"{scratch}:/scratch",
            "--workdir",
            "/repo",
            "--memory",
            self.memory,
            "--pids-limit",
            str(self.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--security-opt",
            f"seccomp={self.seccomp_profile}",
            "--user",
            "10001",
            self.image,
            *cmd,
        ]

    def popen(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        container_cmd = self.translate_command(cmd, workdir=cwd, scratch=scratch)
        wrapped = self.wrap_command(container_cmd, workdir=cwd, scratch=scratch)
        return subprocess.Popen(
            wrapped,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            start_new_session=True,
        )
