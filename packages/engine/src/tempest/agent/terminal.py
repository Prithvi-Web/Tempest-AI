"""F14 — the sandboxed agent terminal (Phase 23).

**What L19 actually says**, and what the first version of `run_command` did instead: *agent
terminal commands run at the same isolation tier as differential runners.* Phase 21 shipped a
bare `subprocess.run(argv, cwd=shadow)` — the user's own uid, environment, network and whole
filesystem, bounded by nothing but a working directory — under a committed manifest declaring
`writes: shadow_worktree` and `touches_network: false`. Neither was true. The tool was refused
rather than left running (ADR-0053, trap 53); this module is what makes refusing unnecessary.

**The tier ladder is not negotiable and not silent.** A command executes through the same
`Sandbox` the proof for this repository would use — T1 Docker (`--network none`, `--read-only`,
`--cap-drop ALL`, a pids limit, an unprivileged uid), T2 Seatbelt (deny-default profile, no
network, no write outside scratch), and **nothing at all when no tier is available**, which is a
refusal rather than a fallback. A degraded tier that ran anyway would be exactly failure mode 3.

**What the agent gives up, stated plainly.** Under T1 the repository is mounted READ-ONLY, so a
command that writes into the worktree fails. That is not an oversight: an agent's writes belong in
`write_file`, where they are staged, journalled and proved. A command whose side effects the proof
never sees is a change reaching the user without evidence, which is the one thing this product
exists to prevent. Scratch space is writable, and `/tmp` inside the container is a 64 MB tmpfs.

**Everything is bounded (L15.4).** Wall clock, output bytes, and the process GROUP — a command
that spawns children and dies leaves nothing behind, because the kill goes to the session the
command was started in, not to one pid.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tempest.envrepro.worktree import normalized_env
from tempest.execute.sandbox import Sandbox, kill_container


@contextmanager
def _scratch_dir(supplied: Path | None) -> Iterator[Path]:
    """The command's writable space: the caller's, or a temporary one that is removed after."""
    if supplied is not None:
        yield supplied
        return
    with tempfile.TemporaryDirectory(prefix="tempest-terminal-") as made:
        yield Path(made)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    """Kill the SESSION, not the pid.

    `popen` starts every command in its own session, so a command that backgrounds a child and
    then hangs leaves that child alive if only the direct child is signalled — which is what the
    first version of this did, and what its own docstring claimed it did not. The test that
    backgrounds a `touch` and then sleeps is the one that caught it.

    The guard is the runner's, for the runner's reason: `returncode` is set only by the wait that
    reaps OUR child, and the kernel cannot recycle a pgid before its owner reaps it — so
    `returncode is None` is what proves the group is still ours to signal.
    """
    kill_container(proc)  # T1: killing the docker CLI alone leaves the container running
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: darwin-only — see runner._kill
            proc.kill()


@dataclass(frozen=True)
class CommandResult:
    """What a command did. `exit_status` is the command's; a refusal never reaches here."""

    exit_status: int
    stdout: str
    stderr: str
    truncated: bool
    #: True when the command was killed for exceeding its wall-clock budget. The output captured
    #: up to that point is still returned: a model debugging a hang needs the last thing printed.
    timed_out: bool = False

    def render(self, *, tier: str) -> str:
        body = (
            f"tier={tier} exit={self.exit_status}\n"
            f"--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"
        )
        if self.timed_out:
            body = f"[the command was killed for exceeding its time budget]\n{body}"
        if self.truncated:
            body += "\n[output truncated by the host's budget]"
        return body


def run(
    argv: list[str],
    *,
    root: Path,
    sandbox: Sandbox,
    timeout: float,
    max_bytes: int,
    scratch: Path | None = None,
) -> CommandResult:
    """Run `argv` inside `sandbox`, rooted at `root`, bounded in time and output.

    The scratch directory is the command's only writable space and, by default, is thrown away
    afterwards — so a command cannot leave state behind for the next one to find, and two calls
    are independent whatever the model believes.

    A caller may supply `scratch` when it needs to look at what the command wrote. The escape
    suite is that caller: proving the agent terminal is contained means running hostile payloads
    through THIS function and then inspecting the space they were allowed to touch. Supplying it
    does not widen anything — the same directory is the same single writable carve — it only
    means the caller, rather than this function, decides when it goes away.
    """
    with _scratch_dir(scratch) as scratch_path:
        scratch = scratch_path
        proc = sandbox.popen(
            argv,
            cwd=root,
            env=normalized_env(scratch),
            scratch=scratch,
            capture_stderr=True,
        )
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            out, err = proc.communicate()

    stdout = out.decode("utf-8", errors="replace") if out else ""
    stderr = err.decode("utf-8", errors="replace") if err else ""
    truncated = len(stdout) > max_bytes or len(stderr) > max_bytes
    return CommandResult(
        exit_status=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout[:max_bytes],
        stderr=stderr[:max_bytes],
        truncated=truncated,
        timed_out=timed_out,
    )
