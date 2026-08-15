"""Sandbox backends (Law L6 + ADR-0003 + ADR-0015 tiered isolation).

Tier ladder (selected at runtime by `select_sandbox`, tier recorded in every bundle):
  T1  DockerSandbox         — no network, read-only rootfs, scratch tmpfs, mem/pids limits,
                              non-root, seccomp. The strongest backend.
  T2  SeatbeltSandbox (mac) — OS-native: sandbox-exec deny-default profile — no network, home
                              denied except the repo, writes only to the scratch mount, children
                              inherit the sandbox. No Docker required.
  T3  ProcessSandbox        — separate process + rlimits + session isolation. Reduced assurance,
                              reported as such; first-party fixtures always, user repos only when
                              no stronger tier exists AND the user has opted in.
Never silently unsandboxed: with no tier available the run is UNPROVEN(SANDBOX_UNAVAILABLE).
"""

import contextlib
import resource
import shutil
import subprocess
import sys
import uuid
import weakref
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
    if sys.platform == "linux":  # pragma: no cover — Linux-only
        # Address-space limits and per-sandbox process caps are only reliable on Linux (macOS
        # RLIMIT_NPROC is per-UID, so capping it would throttle the whole login session, not just
        # the runner). On macOS a fork bomb is bounded instead by the per-input wall timeout plus
        # the SIGKILL of the runner's whole process group — proven by tempest.dev.escape_suite.
        resource.setrlimit(resource.RLIMIT_AS, (1 << 31, 1 << 31))
        _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
        target = 256 if hard == resource.RLIM_INFINITY else min(256, hard)
        resource.setrlimit(resource.RLIMIT_NPROC, (target, hard))


@dataclass(frozen=True)
class ProcessSandbox:
    """Separate process, scrubbed env, rlimits, session isolation. First-party fixtures only."""

    def available(self) -> bool:
        return True

    def translate_job(  # pragma: darwin-only — invoked only under a live Seatbelt run
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


def _sb_quote(path: Path) -> str:  # pragma: darwin-only — Seatbelt executes only on macOS
    """A path as an SBPL string literal. Backslash and double-quote are the only metacharacters
    inside an SBPL "..." literal; escape them so a crafted worktree path cannot break out."""
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def seatbelt_profile(  # pragma: darwin-only — Seatbelt executes only on macOS
    *, repo: Path, scratch: Path, read_roots: tuple[Path, ...]
) -> str:
    """Deny-default Seatbelt (SBPL) profile — the macOS T2 containment (ADR-0015).

    Reads are broadly allowed (a no-network sandbox cannot exfiltrate what it reads) EXCEPT the
    whole home directory, which is denied and then re-allowed only for the repo worktree and the
    interpreter's own install — so no `~` path outside the target repo is reachable. Writes are
    denied everywhere but the single scratch mount, the network is denied outright, and exec'd
    children inherit this same profile (no `no-sandbox`). Last-matching-rule-wins ordering is
    load-bearing: the home deny sits above the repo/interpreter/scratch re-allows.
    """
    # Resolve to canonical paths: macOS temp dirs come back as /var/folders/... but Seatbelt
    # evaluates the real /private/var/folders/..., so an unresolved subpath silently never
    # matches (the scratch mount would not actually be writable).
    home = Path.home().resolve()
    repo = repo.resolve()
    scratch = scratch.resolve()
    read_roots = tuple(r.resolve() for r in read_roots)
    carve = "\n".join(
        f'(allow file-read* (subpath "{_sb_quote(root)}"))' for root in (repo, *read_roots)
    )
    return f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec*)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(deny file-read* (subpath "{_sb_quote(home)}"))
{carve}
(allow file-read* file-write* (subpath "{_sb_quote(scratch)}"))
(deny network*)
"""


@dataclass(frozen=True)
class SeatbeltSandbox:
    """macOS T2 (ADR-0015): OS-native isolation via `sandbox-exec`, no Docker required.

    The worker runs as `sandbox-exec -f <profile> <python> ...` under a deny-default profile
    (see `seatbelt_profile`). Runs on the host, so `translate_job` is the identity. Escape
    containment (no network, no write outside scratch, no home read outside the repo, children
    inherit the sandbox) is proven by `tempest.dev.escape_suite`.
    """

    sandbox_exec: str = "/usr/bin/sandbox-exec"
    tier: str = "T2"

    def _binary(self) -> str | None:
        if Path(self.sandbox_exec).exists():
            return self.sandbox_exec
        return shutil.which("sandbox-exec")

    def available(self) -> bool:
        return sys.platform == "darwin" and self._binary() is not None

    def translate_job(
        self, job: dict[str, object], *, workdir: Path, scratch: Path
    ) -> dict[str, object]:
        return job  # pragma: darwin-only — invoked only under a live Seatbelt run

    def _read_roots(self, interpreter: Path) -> tuple[Path, ...]:
        """Every path the sandboxed worker must be able to READ to even start: the interpreter
        being exec'd (which may be a symlink under ~/.local/bin), its resolved binary, and its
        install prefix — plus the engine process's own prefixes and the uv python store. Without
        the interpreter carve, a home-based CPython cannot be read and the worker never launches
        (HARNESS_SYNTHESIS_FAILED) even though the sandbox is otherwise fine."""
        real = interpreter.resolve()
        roots = {
            Path(sys.base_prefix),
            Path(sys.prefix),
            interpreter,
            interpreter.parent,  # the bin/ dir holding the symlink
            real,
            real.parent.parent,  # <prefix> of a <prefix>/bin/python layout
        }
        uv = Path.home() / ".local" / "share" / "uv"
        if uv.exists():  # pragma: darwin-only — a real uv store is probed by live T2 runs
            roots.add(uv)
        return tuple(sorted(roots))

    def popen(  # pragma: darwin-only — Seatbelt executes only on macOS (escape suite asserts it)
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        scratch: Path,
        stdin_pipe: bool = False,
    ) -> subprocess.Popen[bytes]:
        binary = self._binary()
        if binary is None:  # available() is checked before selection; belt-and-braces
            raise RuntimeError("sandbox-exec vanished between selection and launch")
        interpreter = Path(cmd[0])
        profile = seatbelt_profile(
            repo=cwd, scratch=scratch, read_roots=self._read_roots(interpreter)
        )
        profile_path = scratch / "tempest.sb"
        profile_path.write_text(profile, encoding="utf-8")
        wrapped = [binary, "-f", str(profile_path), *cmd]
        return subprocess.Popen(
            wrapped,
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

# Docker-backed client process → (docker binary, unique container name). Weak keys: an
# unkillled Popen that gets garbage-collected must not pin registry entries forever.
_CONTAINERS: weakref.WeakKeyDictionary[subprocess.Popen[bytes], tuple[str, str]] = (
    weakref.WeakKeyDictionary()
)


def kill_container(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort `docker kill` of the container behind a Docker-backed client process.

    SIGKILLing the docker CLI's process group stops only the CLIENT: the container keeps
    running in the daemon and `--rm` never fires. Every kill path (`runner._kill`,
    `CancelScope` cancellation) therefore also asks the daemon to kill the uniquely named
    container. A no-op for processes no Docker backend registered; failures (binary gone,
    daemon down, container already dead) are suppressed — kill paths must never raise. The
    registry entry is consumed on first use, so a double kill never signals the daemon twice.
    """
    entry = _CONTAINERS.pop(proc, None)
    if entry is None:
        return
    binary, name = entry
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([binary, "kill", name], capture_output=True, timeout=10, check=False)


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

    def wrap_command(self, cmd: list[str], *, workdir: Path, scratch: Path, name: str) -> list[str]:
        return [
            self.docker_binary,
            "run",
            "--rm",
            # -i keeps the container's stdin attached to the client's stdin. Without it the
            # worker's stdin is EOF: PersistentWorker serve batches die instantly on BOTH
            # revisions and the identical synthetic crashes would have compared Equal — a
            # blessing with zero user code executed (review finding 1).
            "-i",
            # Unique name so kill paths can `docker kill` the container itself — SIGKILLing
            # the CLI client alone leaves the container running (review finding 5).
            "--name",
            name,
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
        name = f"tempest-{uuid.uuid4().hex[:12]}"
        wrapped = self.wrap_command(container_cmd, workdir=cwd, scratch=scratch, name=name)
        proc = subprocess.Popen(
            wrapped,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            start_new_session=True,
        )
        _CONTAINERS[proc] = (self.docker_binary, name)
        return proc


@dataclass(frozen=True)
class SandboxSelection:
    """The chosen backend, its tier (T1/T2/T3/none), and — when none — the actionable reason
    the run is UNPROVEN(SANDBOX_UNAVAILABLE). The tier is recorded in every bundle and shown in
    the UI; degradation is never silent (failure-mode #3)."""

    sandbox: "Sandbox | None"
    tier: str
    kind: str
    reason: str | None = None
    assurance: str = "full"  # "full" (T1/T2) | "reduced" (T3) | "none"


def select_sandbox(
    *, docker_binary: str = "docker", allow_seatbelt: bool = True
) -> SandboxSelection:
    """Tier ladder for USER repos (ADR-0015), strongest first. First-party fixtures pick
    ProcessSandbox directly (trusted code) and never come here.

    T3 (rlimit-only ProcessSandbox) is deliberately NOT offered for untrusted user code: it does
    not contain network or filesystem, so handing it arbitrary repos would be the exact "silent
    degrade" failure this ladder exists to prevent. On macOS T2 (Seatbelt) is always available,
    so the degraded rung is effectively unreachable here; the genuine T3 (separate-user) path is
    a Linux/Windows follow-up tracked in docs/PLAN-DESKTOP.md.
    """
    docker = DockerSandbox(docker_binary=docker_binary)
    if docker.available():
        return SandboxSelection(docker, tier="T1", kind="docker", assurance="full")
    if allow_seatbelt:
        seatbelt = SeatbeltSandbox()
        # pragma-justification: available() is constant per OS (macOS always ships
        # sandbox-exec; the sys.platform gate is always False elsewhere), so each CI leg can
        # only ever observe one arm — excluding the rung keeps the measured set identical.
        if seatbelt.available():  # pragma: no cover — one-arm-per-OS branch (T2 is macOS-only)
            return SandboxSelection(seatbelt, tier="T2", kind="seatbelt", assurance="full")
    return SandboxSelection(
        None,
        tier="none",
        kind="none",
        assurance="none",
        reason=(
            "no OS-native sandbox tier available (Law L6 forbids unsandboxed execution of repo "
            "code): install Docker Desktop for T1, or run on macOS for the T2 Seatbelt backend, "
            "or in CI with a container runtime"
        ),
    )
