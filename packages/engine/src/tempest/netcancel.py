"""Making a cancel observable while a thread is blocked inside a socket read (trap 58).

This is the one hard-won piece of the streaming work, extracted so it exists once. It was
written for `inference/client.py`, and the local-model downloader needed exactly the same
thing for exactly the same reason: a cancel check *between* reads is only reachable when reads
return, so a peer that goes quiet — or dribbles bytes slower than one buffer fills — leaves
the reader blocked where no deadline around the loop can reach it.

**Why `shutdown(2)` and not `close()`.** `response.close()` from another thread queues behind
the buffered reader's own lock, which the blocked read is holding: the close cannot run until
the read it is trying to interrupt returns. Measured, on the streaming path, as a 10 s stall
served in full. `shutdown(2)` touches no Python buffering and makes the OS read return at
once. The downloader paid the same bill independently — a cancel against a dribbling peer took
10.2 s, the whole length of the transfer.

**What the caller still owes.** This module makes the read RETURN; it does not decide what
that means. The unblocked read surfaces either as an I/O error or as a clean EOF, so every
caller must re-check the cancel flag afterwards — a shut-down stream must never impersonate a
completed one. Translating to the caller's own exception is the caller's job, because
`Cancelled` and `DownloadCancelled` are different promises to different users.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from typing import Any

#: How often the watcher looks up. It bounds how long a cancel can go unnoticed while the
#: reading thread is blocked — NOT how often anything polls the wire.
CANCEL_POLL_S = 0.1


def shutdown_fd(fd: int) -> None:
    """`shutdown(2)` on a socket fd, borrowing — never owning — the descriptor."""
    sock = socket.socket(fileno=fd)
    try:
        sock.shutdown(socket.SHUT_RDWR)
    finally:
        # The fd still belongs to the response; detaching stops this wrapper's GC from
        # closing it a second time under whoever reuses the number next.
        sock.detach()


@contextlib.contextmanager
def watch_cancel(cancel: threading.Event, response: Any) -> Iterator[None]:
    """Shut `response`'s socket down the moment `cancel` fires, for the body of the `with`.

    The fd is captured while nothing is blocked, and the watcher is joined before this
    returns, so it can never touch the descriptor after the response is closed and the number
    reused.
    """
    fd: int = -1
    with contextlib.suppress(OSError, ValueError):
        fd = response.fileno()
    finished = threading.Event()

    def watch() -> None:
        while not finished.wait(CANCEL_POLL_S):
            if cancel.is_set():
                if fd >= 0:
                    with contextlib.suppress(OSError):
                        shutdown_fd(fd)
                return

    watcher = threading.Thread(target=watch, name="tempest-cancel-watch", daemon=True)
    watcher.start()
    try:
        yield
    finally:
        finished.set()
        watcher.join(timeout=1.0)
