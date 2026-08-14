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
        any thread; returns how many processes were signalled."""
        self._cancelled.set()
        with self._lock:
            live = [p for p in self._procs.values() if p.poll() is None]
            for proc in live:
                _kill_group(proc)
        return len(live)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
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
