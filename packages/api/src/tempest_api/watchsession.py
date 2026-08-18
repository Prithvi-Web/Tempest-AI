"""The continuous agent, in the app (HANDOFF-WORLD-CLASS §3.2 / ADR-0029).

`tempest watch` in the CLI proves every new commit incrementally. This is the same behavior
driven from the desktop: one background thread per store polls the repo's HEAD and, on a new
commit, creates an ordinary run and proves `previous → new` through the ordinary local-prove
machinery. That last point is the whole design — a watched commit produces a REAL run row, so
the run list, the ledger, cancellation, bundles, search, and the host's progress events all
keep working with no second code path and no second kind of evidence.

L11 runs through the loop: it yields to battery/thermal pause before every poll, it proves one
commit at a time and never overlaps, its sleep is interruptible so Stop is immediate, and the
thread is a daemon that dies with the process. A repo that stops being readable (deleted,
unmounted) stops the session with the reason recorded, rather than spinning silently.
"""

import asyncio
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.execute.powerstate import wait_while_paused
from tempest.obslog import get_logger
from tempest.prove import ProveConfig
from tempest_api.localprove import (
    is_prove_active,
    local_run_out_dir,
    request_cancel,
    resolve_local_repo,
    spawn_prove_thread,
)

_MIN_INTERVAL_S = 1.0
_PROVE_POLL_S = 0.2

_log = get_logger("api.watch")


class WatchError(Exception):
    """The session cannot start; the message states exactly what to fix."""


# The ledger event type that MARKS a run as watch-produced. The feed is a query over these
# rows, not an in-memory list: it survives an app restart, it cannot drift from the runs it
# describes, and there is exactly one source of truth (L1).
WATCH_EVENT_TYPE = "watch.commit"


@dataclass
class WatchState:
    """The LIVE half of watch: what the loop is doing right now. The proven-commit feed is
    not here — it is read from the run rows (see WATCH_EVENT_TYPE), so this snapshot can
    never disagree with the evidence."""

    watching: bool = False
    repo_path: str | None = None
    repo_name: str | None = None
    interval_seconds: float = 0.0
    last_sha: str | None = None
    active_run_id: int | None = None
    problem: str | None = None


class _Session:
    """One watch loop and the state it publishes. Guarded by a lock: the HTTP thread reads a
    snapshot while the loop thread writes."""

    def __init__(self) -> None:
        # Reentrant: `start` publishes its new state and returns a snapshot while still
        # holding the lock — a plain Lock would deadlock the caller against itself.
        self._lock = threading.RLock()
        self._stop = threading.Event()
        # The battery/thermal hold blocks inside `wait_while_paused`; only a cancel unblocks
        # it. Stop must mean stop even on an unplugged laptop (L11), so the session owns a
        # scope it cancels alongside the stop flag.
        self._pause_scope = CancelScope()
        self._thread: threading.Thread | None = None
        self._state = WatchState()

    def snapshot(self) -> WatchState:
        with self._lock:
            return WatchState(
                watching=self._state.watching,
                repo_path=self._state.repo_path,
                repo_name=self._state.repo_name,
                interval_seconds=self._state.interval_seconds,
                last_sha=self._state.last_sha,
                active_run_id=self._state.active_run_id,
                problem=self._state.problem,
            )

    def start(
        self,
        *,
        repo: Path,
        head_sha: str,
        interval_seconds: float,
        max_inputs: int,
        database_url: str,
    ) -> WatchState:
        with self._lock:
            if self._state.watching:
                raise WatchError(
                    f"already watching {self._state.repo_path} — stop that session first"
                )
            self._stop = threading.Event()
            self._pause_scope = CancelScope()
            self._state = WatchState(
                watching=True,
                repo_path=str(repo),
                repo_name=repo.name,
                interval_seconds=interval_seconds,
                last_sha=head_sha,
            )
            self._thread = threading.Thread(
                target=self._loop,
                args=(repo, interval_seconds, max_inputs, database_url),
                name=f"tempest-watch-{repo.name}",
                daemon=True,
            )
            self._thread.start()
            return self.snapshot()

    def stop(self) -> WatchState:
        """Idempotent: stopping an idle session is a no-op that answers with the same shape.
        An in-flight prove is cancelled (L11) — Stop must mean stop, not "stop eventually"."""
        with self._lock:
            active_run_id = self._state.active_run_id
            self._state.watching = False
        self._stop.set()
        self._pause_scope.cancel()
        if active_run_id is not None:
            request_cancel(active_run_id)
        return self.snapshot()

    def _loop(
        self, repo: Path, interval_seconds: float, max_inputs: int, database_url: str
    ) -> None:
        while not self._stop.is_set():
            try:
                # L11: never start work while the machine is on battery or thermally paused —
                # and leave the moment Stop is pressed, even mid-hold.
                wait_while_paused(cancel=self._pause_scope, notify=None)
            except ProveCancelled:
                break
            try:
                head = head_sha(repo)
            except WatchError as exc:
                self._fail(str(exc))
                return
            with self._lock:
                last = self._state.last_sha
            if head != last and last is not None:
                self._prove_commit(repo, last, head, max_inputs, database_url)
            self._stop.wait(interval_seconds)
        with self._lock:
            self._state.watching = False
            self._state.active_run_id = None

    def _prove_commit(
        self, repo: Path, base: str, head: str, max_inputs: int, database_url: str
    ) -> None:
        try:
            run_id = create_watch_run(repo, base, head, max_inputs, database_url)
        except Exception as exc:  # a failed row creation must not kill the session
            self._fail(f"could not start a run for {head[:12]}: {exc}")
            return
        with self._lock:
            # The commit is TAKEN here, not when the prove ends: each commit is attempted
            # exactly once, so a cancelled or failed prove cannot make the loop re-prove the
            # same commit forever — and the published state can never say COMPLETE while
            # still pointing at the previous commit.
            self._state.last_sha = head
            self._state.active_run_id = run_id
        _log.info("watch proving %s..%s as run %s", base[:12], head[:12], run_id)
        cfg = ProveConfig(
            repo=repo,
            base=base,
            head=head,
            max_inputs=max_inputs,
            out=local_run_out_dir(run_id),
        )
        spawn_prove_thread(run_id, cfg, database_url)
        while is_prove_active(run_id, database_url) and not self._stop.is_set():
            time.sleep(_PROVE_POLL_S)
        with self._lock:
            self._state.active_run_id = None

    def _fail(self, problem: str) -> None:
        with self._lock:
            self._state.watching = False
            self._state.active_run_id = None
            self._state.problem = problem
        self._stop.set()
        self._pause_scope.cancel()
        _log.warning("watch stopped: %s", problem)


# One session per store (the key `_active_proves` uses), so tests and stores never collide.
_sessions: dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _session(database_url: str) -> _Session:
    with _sessions_lock:
        return _sessions.setdefault(database_url, _Session())


def head_sha(repo: Path) -> str:
    """HEAD as a full sha, or WatchError naming the repo and git's own reason."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise WatchError(f"cannot read HEAD in {repo}: {proc.stderr.strip() or 'git failed'}")
    return proc.stdout.strip()


def start_watch(
    *, repo_path: str, interval_seconds: float, max_inputs: int, database_url: str
) -> WatchState:
    """Validate the repo the same way a manual prove does, then arm the loop."""
    if interval_seconds < _MIN_INTERVAL_S:
        raise WatchError(
            f"the poll interval must be at least {_MIN_INTERVAL_S:g}s — got {interval_seconds:g}s"
        )
    repo, _, sha = resolve_local_repo(repo_path, "HEAD", "HEAD")
    return _session(database_url).start(
        repo=repo,
        head_sha=sha,
        interval_seconds=interval_seconds,
        max_inputs=max_inputs,
        database_url=database_url,
    )


def stop_watch(database_url: str) -> WatchState:
    return _session(database_url).stop()


def watch_state(database_url: str) -> WatchState:
    return _session(database_url).snapshot()


def create_watch_run(repo: Path, base: str, head: str, max_inputs: int, database_url: str) -> int:
    """Create the PENDING run row + its first ledger event, exactly as `startLocalProve` does,
    from a plain thread (its own loop, its own engine)."""
    return asyncio.run(_create_watch_run(repo, base, head, max_inputs, database_url))


async def _create_watch_run(
    repo: Path, base: str, head: str, max_inputs: int, database_url: str
) -> int:
    from tempest_api.db.models import Run
    from tempest_api.db.session import create_engine_and_factory
    from tempest_api.ledger import append_run_event
    from tempest_api.routers.runs import get_or_create_repo
    from tempest_api.schemas.enums import RunStatus

    engine, factory = create_engine_and_factory(database_url)
    try:
        async with factory() as session:
            repo_row = await get_or_create_repo(session, repo.name)
            run = Run(
                repo_id=repo_row.id,
                base_sha=base,
                head_sha=head,
                status=RunStatus.PENDING,
            )
            session.add(run)
            await session.flush()
            await append_run_event(
                session,
                run.id,
                WATCH_EVENT_TYPE,
                stage="started",
                message=(
                    f"new commit {head[:12]} in {repo.name} — proving {base[:12]}..{head[:12]}, "
                    f"budget {max_inputs} inputs"
                ),
                extra={"repo_path": str(repo), "base_sha": base, "head_sha": head},
            )
            await session.commit()
            return run.id
    finally:
        await engine.dispose()
