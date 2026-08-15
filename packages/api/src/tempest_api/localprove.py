"""Local prove orchestration: validate a repo on this machine, then prove + ingest it in a
background thread. `POST /v1/local/prove` answers 202 immediately; the desktop polls
`getRun` + `listRunEvents`.

The engine writes its bundle under the app data dir, and the worker ingests that zip through
the exact upload code path (`ingest_zip_bytes`) — one fan-out, one integrity gate, zero
duplicated ingestion logic. Sandbox selection stays the engine's own (`_select_sandbox`,
ADR-0003/ADR-0008): a repo it cannot sandbox yields an honest all-UNPROVEN run, which is a
*result*, not an error. Verdict ERROR is reserved for Tempest itself failing (Law L2), and the
ledger then carries the traceback for the UI.
"""

import asyncio
import contextlib
import os
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tempest.execute.cancel import CancelScope, ProveCancelled
from tempest.model import Verdict
from tempest.obslog import get_logger
from tempest.prove import ProveConfig, run_prove
from tempest.telemetry import record_run_aggregate
from tempest_api.bundlestore import bundle_store, collect_garbage
from tempest_api.db.models import Run
from tempest_api.db.session import create_engine_and_factory
from tempest_api.errors import ApiError
from tempest_api.ingest import ingest_zip_bytes
from tempest_api.ledger import append_run_event
from tempest_api.schemas.enums import ErrorCode, RunStatus


@dataclass
class _ActiveProve:
    thread: threading.Thread
    scope: CancelScope


# Keyed by (database_url, run_id): run ids are only unique within one database, and this
# registry is process-global — a bare run_id key would let one store cancel another's prove.
_active_proves: dict[tuple[str, int], _ActiveProve] = {}
_active_lock = threading.Lock()


def _registry_key(run_id: int, database_url: str | None) -> tuple[str, int]:
    from tempest_api.db.session import database_url as current_database_url

    return (database_url if database_url is not None else current_database_url(), run_id)


def is_prove_active(run_id: int, database_url: str | None = None) -> bool:
    with _active_lock:
        return _registry_key(run_id, database_url) in _active_proves


def request_cancel(run_id: int, database_url: str | None = None) -> bool:
    """Cancel the active prove for `run_id` (L11): children are SIGKILLed immediately from
    this thread; the prove thread unwinds and records CANCELLED. False if nothing is active."""
    with _active_lock:
        active = _active_proves.get(_registry_key(run_id, database_url))
    if active is None:
        return False
    active.scope.cancel()
    return True


def data_dir() -> Path:
    """App data root. The desktop shell sets `TEMPEST_DATA_DIR` (its per-app data dir); the
    fallback keeps bundles out of the user's repos when the API runs bare."""
    return Path(os.environ.get("TEMPEST_DATA_DIR", str(Path.home() / ".tempest")))


def local_run_out_dir(run_id: int) -> Path:
    return data_dir() / "local-runs" / f"run-{run_id}"


def _git(repo: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def resolve_local_repo(repo_path: str, base: str, head: str) -> tuple[Path, str, str]:
    """400 with a stable code unless `repo_path` is an existing git repo directory and both
    refs resolve to commits. Returns (resolved repo dir, base sha, head sha)."""
    repo = Path(repo_path)
    if not repo.is_dir():
        raise ApiError(
            400,
            ErrorCode.REPO_NOT_FOUND,
            f"repo_path {repo_path!r} is not an existing directory on this machine",
            {"repo_path": repo_path},
        )
    repo = repo.resolve()
    if _git(repo, "rev-parse", "--git-dir") is None:
        raise ApiError(
            400,
            ErrorCode.REPO_NOT_FOUND,
            f"{str(repo)!r} is not a git repository — point repo_path at the repository root",
            {"repo_path": str(repo)},
        )
    shas: list[str] = []
    for name, ref in (("base", base), ("head", head)):
        sha = _git(
            repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"
        )
        if sha is None:
            raise ApiError(
                400,
                ErrorCode.REF_NOT_FOUND,
                f"{name} ref {ref!r} does not resolve to a commit in {repo} — "
                "check the branch/tag/sha spelling",
                {"which": name, "ref": ref, "repo_path": str(repo)},
            )
        shas.append(sha)
    return repo, shas[0], shas[1]


def spawn_prove_thread(run_id: int, cfg: ProveConfig, database_url: str) -> bool:
    """Start the daemon prove thread for `run_id`. Returns False (and starts nothing) if a
    thread is already registered — the registry prevents duplicate concurrent proves of one run.
    Every prove gets a CancelScope so `request_cancel` can stop it (L11)."""
    scope = CancelScope()
    cfg = replace(cfg, cancel=scope)
    key = (database_url, run_id)
    with _active_lock:
        if key in _active_proves:
            return False
        thread = threading.Thread(
            target=_thread_main,
            args=(run_id, cfg, database_url),
            name=f"tempest-local-prove-{run_id}",
            daemon=True,
        )
        _active_proves[key] = _ActiveProve(thread=thread, scope=scope)
        try:
            thread.start()
        except Exception:
            _active_proves.pop(key, None)
            raise
    return True


def _thread_main(run_id: int, cfg: ProveConfig, database_url: str) -> None:
    try:
        asyncio.run(_prove_and_ingest(run_id, cfg, database_url))
    finally:
        with _active_lock:
            _active_proves.pop((database_url, run_id), None)


async def _prove_and_ingest(run_id: int, cfg: ProveConfig, database_url: str) -> None:
    # The thread owns its event loop, so it needs its own loop-bound engine; the API process's
    # engine belongs to the server loop and is never touched from here.
    # Review m2: the pause task and this coroutine both append run events with max(seq)+1 in
    # separate sessions — the lock serializes every ledger writer for this run on this loop.
    ledger_lock = asyncio.Lock()
    engine, factory = create_engine_and_factory(database_url)
    try:
        try:
            await _event(
                factory,
                run_id,
                stage="proving",
                lock=ledger_lock,
                message=(
                    f"differential execution running: {cfg.base[:12]} vs {cfg.head[:12]} "
                    f"under identical conditions, budget {cfg.max_inputs} inputs"
                ),
            )
            # The battery/thermal pause (L11) reports its reason from the prove thread into the
            # run ledger through this loop — the UI shows WHY the run is holding, live.
            loop = asyncio.get_running_loop()

            def on_pause(reason: str) -> None:
                asyncio.run_coroutine_threadsafe(
                    _event(
                        factory,
                        run_id,
                        stage="paused",
                        message=f"prove paused: {reason}",
                        lock=ledger_lock,
                    ),
                    loop,
                )

            started = time.monotonic()
            result = await asyncio.to_thread(run_prove, replace(cfg, on_pause=on_pause))
            duration_ms = int((time.monotonic() - started) * 1000)
            await _event(
                factory,
                run_id,
                stage="ingesting",
                lock=ledger_lock,
                message=(
                    f"prove finished (sandbox: {result.sandbox_kind}) — "
                    f"ingesting {result.zip_path.name}"
                ),
            )
            async with ledger_lock, factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    # The run row vanished mid-prove; nothing to record on. Executed by
                    # test_prove_coroutine_returns_when_run_vanished and the endpoint vanish
                    # test, but the tracer mis-attributes the first line after this greenlet
                    # crossing — a measurement artifact, not a gap.
                    return  # pragma: no cover — attribution artifact; behavior is pinned
                bundle = await ingest_zip_bytes(session, run, result.zip_path.read_bytes())
                await session.commit()
                # Review C1: blob GC only after commit, against committed truth.
                await collect_garbage(
                    session, bundle_store(), candidates=session.info.pop("pruned_digests", [])
                )
            # Phase 17 telemetry: counters only, and only when the user opted in (no-op OFF).
            record_run_aggregate(
                verdict=bundle.manifest.verdict.value,
                sandbox_tier=result.sandbox_tier,
                unproven_reasons=tuple(
                    t.reason_code.value
                    for t in bundle.targets
                    if t.verdict is Verdict.UNPROVEN and t.reason_code is not None
                ),
                duration_ms=duration_ms,
            )
            divergence_total = sum(len(t.divergences) for t in bundle.targets)
            await _event(
                factory,
                run_id,
                stage="complete",
                lock=ledger_lock,
                message=(
                    f"run complete: verdict {bundle.manifest.verdict.value}, "
                    f"{len(bundle.targets)} targets, {divergence_total} divergences"
                ),
            )
        except ProveCancelled:
            # The user stopped it (L11) — an honest terminal state, never an ERROR (L2).
            await _mark_cancelled(factory, run_id)
        except Exception:
            # Tempest itself failed (Law L2: ERROR). The ledger carries the traceback — the
            # desktop renders it verbatim from the events endpoint.
            await _mark_error(factory, run_id, traceback.format_exc())
    finally:
        await engine.dispose()


async def _event(
    factory: async_sessionmaker[AsyncSession],
    run_id: int,
    *,
    stage: str,
    message: str,
    lock: asyncio.Lock | None = None,
) -> None:
    # Every run-ledger event also lands in the structured log (Phase 17) — the in-app viewer
    # shows engine activity across runs; the per-run ledger stays the replayable record.
    get_logger("prove").info(message, extra={"tempest_extra": {"run_id": run_id, "stage": stage}})
    async with lock if lock is not None else contextlib.nullcontext(), factory() as session:
        await append_run_event(session, run_id, f"local.{stage}", stage=stage, message=message)
        await session.commit()


async def _mark_cancelled(factory: async_sessionmaker[AsyncSession], run_id: int) -> None:
    async with factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = RunStatus.CANCELLED
        await append_run_event(
            session,
            run_id,
            "local.cancelled",
            stage="cancelled",
            message="prove cancelled by the user — all workers stopped, no verdict claimed",
        )
        await session.commit()


async def _mark_error(factory: async_sessionmaker[AsyncSession], run_id: int, trace: str) -> None:
    async with factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = RunStatus.COMPLETE
        run.verdict = Verdict.ERROR
        await append_run_event(
            session, run_id, "local.error", stage="error", level="error", message=trace
        )
        await session.commit()
