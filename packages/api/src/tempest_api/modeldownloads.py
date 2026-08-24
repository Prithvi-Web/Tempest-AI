"""Download jobs: start, poll, cancel (ADR-0080 section 4).

The engine's `download_entry` is a blocking call that reports progress through a callback.
This is the job layer around it — a worker thread, a status a client can poll, and a cancel
flag — modelled on `localprove.py`'s active-run registry, which is how every other long
operation in this sidecar is managed.

**Polling, not a second stream.** The app already has exactly one push mechanism for long
work: the engine appends to a ledger, the host polls it, and the webview reads tauri events.
A download is a progress bar, not a conversation, so it needs less than that — a status a
caller can read whenever it likes. Adding a second streaming path for it would mean two
answers to "how does the UI learn things", which is the shape L29 forbids for runtimes and
which is no better here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

from tempest.models import (
    CatalogEntry,
    DownloadCancelled,
    DownloadProgress,
    DownloadRefused,
    download_entry,
    entry_for,
    installed_path,
)
from tempest.models.download import delete_entry, disk_free_bytes

State = Literal["running", "done", "failed", "cancelled"]


class ModelDownloadRejected(RuntimeError):
    """A request that will not start, with a reason the client can render (L15.3)."""


@dataclass
class _Job:
    entry: CatalogEntry
    cancel: threading.Event = field(default_factory=threading.Event)
    state: State = "running"
    done_bytes: int = 0
    total_bytes: int = 0
    #: Set on every terminal state except `done` — an empty error on a failure would be a
    #: spinner that stopped moving, which L23 forbids.
    error: str = ""
    thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "modelId": self.entry.id,
            "state": self.state,
            "doneBytes": self.done_bytes,
            "totalBytes": self.total_bytes,
            "error": self.error,
        }


_jobs: dict[str, _Job] = {}
_lock = threading.Lock()


def _entry_or_reject(model_id: str) -> CatalogEntry:
    entry = entry_for(model_id)
    if entry is None:
        raise ModelDownloadRejected(
            f"{model_id!r} is not in the model catalogue — it may have been removed in an "
            f"update, or the id is stale"
        )
    return entry


def catalogue(*, include_installed: bool = True) -> list[dict[str, Any]]:
    """Every row, with what a person needs BEFORE spending gigabytes (L21).

    `installed` and `freeBytes` ride along so the UI never has to make a second call to answer
    "do I already have this, and will it fit".
    """
    from tempest.models import CATALOG

    free = disk_free_bytes()
    rows: list[dict[str, Any]] = []
    for entry in CATALOG:
        with _lock:
            job = _jobs.get(entry.id)
        rows.append(
            {
                "id": entry.id,
                "label": entry.label,
                "goodAt": entry.good_at,
                "license": entry.license,
                "sizeBytes": entry.size_bytes,
                "ramNote": entry.ram_note,
                "installed": include_installed and installed_path(entry).exists(),
                "freeBytes": free,
                "fitsOnDisk": free > entry.size_bytes,
                "download": job.snapshot() if job is not None else None,
            }
        )
    return rows


def start(model_id: str) -> dict[str, Any]:
    """Begin a download, or return the running one. Never starts a second worker for the same
    model: two writers on one path is a corrupted file, not a faster download."""
    entry = _entry_or_reject(model_id)
    if installed_path(entry).exists():
        return {
            "modelId": entry.id,
            "state": "done",
            "doneBytes": entry.size_bytes,
            "totalBytes": entry.size_bytes,
            "error": "",
        }

    with _lock:
        existing = _jobs.get(model_id)
        if existing is not None and existing.state == "running":
            return existing.snapshot()
        job = _Job(entry=entry, total_bytes=entry.size_bytes)
        _jobs[model_id] = job

    def report(progress: DownloadProgress) -> None:
        job.done_bytes = progress.done_bytes
        job.total_bytes = progress.total_bytes

    def run() -> None:
        try:
            download_entry(entry, on_progress=report, cancel=job.cancel)
            job.done_bytes = entry.size_bytes
            job.state = "done"
        except DownloadCancelled as exc:
            job.state, job.error = "cancelled", str(exc)
        except DownloadRefused as exc:
            job.state, job.error = "failed", str(exc)
        except Exception as exc:  # a defect in us, surfaced in-band rather than swallowed
            job.state, job.error = "failed", f"the download failed inside Tempest: {exc!r}"

    job.thread = threading.Thread(target=run, name=f"model-download-{model_id}", daemon=True)
    job.thread.start()
    return job.snapshot()


def status(model_id: str) -> dict[str, Any]:
    """The current state, whether or not a job was ever started for it."""
    entry = _entry_or_reject(model_id)
    with _lock:
        job = _jobs.get(model_id)
    if job is not None:
        return job.snapshot()
    installed = installed_path(entry).exists()
    return {
        "modelId": entry.id,
        "state": "done" if installed else "failed",
        "doneBytes": entry.size_bytes if installed else 0,
        "totalBytes": entry.size_bytes,
        "error": "" if installed else "not downloaded",
    }


def cancel(model_id: str) -> dict[str, Any]:
    """Ask a running download to stop. The partial is kept so resuming costs the remainder."""
    entry = _entry_or_reject(model_id)
    with _lock:
        job = _jobs.get(model_id)
    if job is None or job.state != "running":
        raise ModelDownloadRejected(f"no download is running for {entry.label}")
    job.cancel.set()
    return job.snapshot()


def remove(model_id: str) -> dict[str, Any]:
    """Delete an installed model and any partial.

    Refuses while a download is running rather than deleting the file out from under its
    worker — which on a slow link is the difference between "I changed my mind" and a
    half-written file left behind by a thread that no longer has anywhere to put its bytes.
    """
    entry = _entry_or_reject(model_id)
    with _lock:
        job = _jobs.get(model_id)
    if job is not None and job.state == "running":
        raise ModelDownloadRejected(
            f"{entry.label} is still downloading — stop it first, then remove it"
        )
    removed = delete_entry(entry)
    with _lock:
        _jobs.pop(model_id, None)
    return {"modelId": entry.id, "removed": removed}


def reset_for_test() -> None:
    """Drop the registry between tests. Named for what it is; nothing else calls it."""
    with _lock:
        _jobs.clear()
