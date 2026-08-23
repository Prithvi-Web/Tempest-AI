"""Cancellation for a running prove (L11: the user's machine is not your CI runner).

One `CancelScope` per prove. Every child the engine spawns is registered here (the single
choke point is `runner._spawn`); `cancel()` SIGKILLs every registered process group instantly
from ANY thread, and a cancelled scope refuses new spawns — worker respawn paths raise
`ProveCancelled` instead of resurrecting children, so the prove thread unwinds at its next
read or checkpoint. Registration after cancel kills the late child immediately, closing the
cancel/spawn race.
"""

import contextlib
import os
import signal
import subprocess
import threading
from collections.abc import Iterator
from contextvars import ContextVar

from tempest.execute.sandbox import kill_container


class ProveCancelled(RuntimeError):
    """The user cancelled this prove; unwind without producing a bundle."""


class CancelScope:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procs: dict[int, subprocess.Popen[bytes]] = {}
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def event(self) -> threading.Event:
        """The underlying flag, for APIs that watch a `threading.Event` (`inference.complete`
        and `stream` take one). Read-only by convention: setting it directly would skip the
        process-group sweep that `cancel()` performs — cancel through `cancel()`, always."""
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise ProveCancelled("prove cancelled by the user")

    def register(self, proc: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._procs[proc.pid] = proc
            if self._cancelled.is_set():
                _kill_group(proc)

    def unregister(self, proc: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._procs.pop(proc.pid, None)

    def cancel(self) -> int:
        """Set the flag and SIGKILL every live registered process group. Idempotent; safe from
        any thread; returns how many processes were signalled. The snapshot is taken under the
        lock but the kills run outside it, so a slow kill can never serialize registrations —
        and a register() racing this flag kills its own late child immediately."""
        self._cancelled.set()
        with self._lock:
            live = [p for p in self._procs.values() if p.poll() is None]
        for proc in live:
            _kill_group(proc)
        return len(live)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    # T1 first: even a client that already exited may have left its container running — the
    # docker kill below is registry-driven and consumes the entry, so it never fires twice.
    kill_container(proc)
    # killpg-after-reap guard (TOCTOU): `returncode` is set only by the reaping wait()/poll()
    # on OUR child, and the kernel keeps the pid/pgid reserved (zombie) until that reap — so
    # `returncode is None`, checked immediately before killpg, proves the pgid is still ours.
    # The other thread (the prove thread's `proc.wait()`) can still reap between this check
    # and the syscall; the unavoidable residue is the instruction window inside Popen.wait()
    # between the OS-level waitpid and the returncode assignment. That window cannot be closed
    # from outside Popen; the guard shrinks the race from "any time after reap" to that
    # assignment gap, and every wait-then-kill call site is now signal-free by construction.
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: darwin-only — see below
        # A dead-but-unreaped group raises EPERM only on macOS; Linux keeps a zombie leader's
        # pgid signalable, so this fallback is unreachable there by kernel design.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


_current: ContextVar[CancelScope | None] = ContextVar("tempest_cancel_scope", default=None)


def current_scope() -> CancelScope | None:
    return _current.get()


@contextlib.contextmanager
def cancel_scope(scope: CancelScope) -> Iterator[CancelScope]:
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
