"""Fetching a catalogue model: resume, verify, cancel, delete (ADR-0080 sections 2-5).

The downloader lives in the engine because it is the only place with both an HTTP client and
the egress discipline to use one: the Rust host has no HTTP client at all, and the webview's
CSP blocks the host this fetches from.

Three things here are deliberate and easy to get wrong later, so they are stated once:

**The redirect allowance is narrow, and its safety rests on one clause.** `client.py`'s
`_RefuseRedirects` refuses every redirect, because a redirect is how an API key leaks to a
host nobody configured. Hugging Face answers `302` to a CDN, so a downloader reusing that
policy unchanged cannot fetch a byte. The allowance here is not "downloads may redirect" —
it is that *this request carries no credential of any kind*, and a request with no key cannot
leak one. The keyed model client keeps refusing every redirect, untouched.

**The hash is checked before the file is usable, and a mismatch deletes.** A partial or
substituted model is not a model. Verification failure removes the file rather than leaving
something on disk that looks installed.

**Cancellation keeps the partial file.** That is what makes `Range:` resume worth having: a
download stopped at 80% and resumed later should cost the remaining 20%, not start again.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlparse

from tempest.models.catalog import CatalogEntry

#: Hosts a model download may be redirected TO. Hugging Face serves file bytes from a CDN, so
#: refusing every redirect (the keyed client's policy) would refuse every download. The ledger
#: is a suffix match on the HOST only, closed, and checked by `egress_check` alongside the one
#: in `catalog.py` — a new CDN is an audited row, never an absorbed surprise (L32).
_ALLOWED_REDIRECT_SUFFIXES = ("hf.co", "huggingface.co", "cdn-lfs.huggingface.co")

#: Read size. Big enough that a 2.5 GB file is not a million callbacks, small enough that a
#: cancel is observed promptly — the flag is checked once per chunk (L15.4).
_CHUNK = 1024 * 1024

#: No separate stall timeout. `urlopen(timeout=…)` sets the SOCKET timeout, which applies to
#: every subsequent `read()` — a connection that goes quiet raises there. A hand-rolled
#: watchdog beside it was written first and was dead on arrival: it reset its own deadline
#: after each chunk and then compared against the value it had just set, so it could never
#: fire. A guard that cannot fire is worse than none, because it reads like cover.


class DownloadRefused(RuntimeError):
    """A download that will not be attempted, or whose result cannot be trusted, with a
    reason a person can act on (L15.3, L23)."""


class DownloadCancelled(RuntimeError):
    """The caller asked to stop. The partial file is kept for `Range:` resume."""


@dataclass(frozen=True)
class DownloadProgress:
    """One progress report. `total` is the catalogue's size, never the server's claim: the
    row is what the user agreed to spend, and a server that reports something else is a
    reason to refuse rather than a reason to re-plan."""

    done_bytes: int
    total_bytes: int

    @property
    def fraction(self) -> float:
        if self.total_bytes <= 0:  # pragma: no cover — catalogue rows always carry a size
            return 0.0
        return min(1.0, self.done_bytes / self.total_bytes)


def model_root() -> Path:
    """Where installed models live. Under the app's data dir, so uninstalling the app takes
    them with it and no repository of the user's is ever written to."""
    base = os.environ.get("TEMPEST_DATA_DIR")
    root = Path(base) if base else Path.home() / ".tempest"
    return root / "models"


def safe_leaf(name: str) -> str:
    """One path component, or a refusal.

    Written rather than imported: the reconnaissance for this work said to reuse an existing
    `safe_leaf`, and there is no such function in the tree — the nearest precedent is
    `ingest.py`'s `_safe_extract`. Since it had to be written, it refuses rather than
    sanitises. A sanitiser rewrites a hostile name into a plausible one and leaves the reader
    to reason about what it produced for every input; a refusal has one behaviour.

    The ids this guards are catalogue-authored today, so nothing hostile reaches it yet. It
    exists because the day a model id comes from anywhere else — a user-supplied URL, a
    marketplace row — is the day this becomes the only thing between a name and the filesystem.
    """
    if not name or name in (".", ".."):
        raise DownloadRefused(f"{name!r} is not a usable name")
    if "/" in name or "\\" in name or "\0" in name:
        raise DownloadRefused(f"{name!r} contains a path separator and cannot name one file")
    # Checked under BOTH flavours, on every platform. `Path` is the running platform's, so a
    # POSIX-only check calls `C:model.gguf` a fine leaf — and on Windows that is a
    # DRIVE-RELATIVE path, which resolves somewhere entirely else. A catalogue is shared
    # across platforms, so a name is safe only if it is safe under both sets of rules; doing
    # it this way also means the guard is reachable in tests wherever they run, rather than
    # being a branch that only a Windows CI could ever enter.
    for flavour in (PurePosixPath, PureWindowsPath):
        candidate = flavour(name)
        if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name != name:
            raise DownloadRefused(
                f"{name!r} does not resolve to a single path component under "
                f"{flavour.__name__} rules"
            )
    return name


def installed_path(entry: CatalogEntry) -> Path:
    """Where this entry's file lives once installed."""
    return model_root() / safe_leaf(entry.id) / safe_leaf(entry.filename)


def _partial_path(final: Path) -> Path:
    return final.with_name(final.name + ".partial")


class _AllowListedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a host in the closed ledger, and only for a request that
    carries no credential.

    The second half is the part that matters and the part a later reader will be tempted to
    drop: this handler is safe BECAUSE the request has no key on it. Reusing it for anything
    authenticated re-opens exactly the hole `_RefuseRedirects` was written to close.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        host = (urlparse(newurl).hostname or "").lower()
        if not any(
            host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_REDIRECT_SUFFIXES
        ):
            raise DownloadRefused(
                f"the download was redirected to {host or newurl!r}, which is not in the "
                f"allowed set {sorted(_ALLOWED_REDIRECT_SUFFIXES)} — refusing rather than "
                f"following an unaudited host (L32)"
            )
        if any(key.lower() in ("authorization", "cookie") for key in req.headers):
            raise DownloadRefused(  # pragma: no cover — this client never sets one
                "a credentialed request must not follow a redirect; that is the leak "
                "`_RefuseRedirects` exists to prevent"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_AllowListedRedirects)


def _verify(path: Path, entry: CatalogEntry) -> None:
    """Hash the file and refuse if it is not the one the catalogue named."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != entry.sha256:
        path.unlink(missing_ok=True)
        raise DownloadRefused(
            f"{entry.label} did not match its recorded checksum (expected {entry.sha256[:12]}…, "
            f"got {actual[:12]}…). The file has been removed. This means the download was "
            f"corrupted, or the model was re-uploaded upstream — it is not something to retry "
            f"blindly, and Tempest will not install a model it cannot identify."
        )


def download_entry(
    entry: CatalogEntry,
    *,
    on_progress: Callable[[DownloadProgress], None] | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 30.0,
) -> Path:
    """Fetch `entry` into the models directory and return its path.

    Resumes from a `.partial` left by an earlier attempt. Verifies the sha256 before the file
    becomes usable. Observes `cancel` once per chunk, keeping the partial so resuming costs
    only the remainder.
    """
    final = installed_path(entry)
    if final.exists():
        return final
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(final)

    have = partial.stat().st_size if partial.exists() else 0
    if have > entry.size_bytes:
        # Longer than the catalogue says: this is not a resumable prefix of the right file.
        partial.unlink()
        have = 0

    request = urllib.request.Request(entry.url, method="GET")
    if have:
        request.add_header("Range", f"bytes={have}-")

    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("cancelled before the download started")

    try:
        response = _opener().open(request, timeout=timeout)
    except DownloadRefused:
        raise
    except urllib.error.HTTPError as err:
        if have and err.code == 416:
            # The server says our partial is already the whole file. Promote and verify.
            partial.replace(final)
            _verify(final, entry)
            return final
        raise DownloadRefused(
            f"{entry.label} could not be downloaded: {entry.url} answered HTTP {err.code}. "
            f"The catalogue row may be stale — a model repository that moves a file needs the "
            f"row refreshed, not a retry."
        ) from err
    except OSError as err:
        raise DownloadRefused(
            f"{entry.label} could not be downloaded: {err}. Check the network connection; "
            f"nothing has been installed and any partial download is kept for resuming."
        ) from err

    # A server that ignores `Range:` answers 200 and starts from zero; appending then would
    # splice the file's head into its middle. Trust the STATUS, not the request.
    resuming = response.status == 206
    if have and not resuming:
        have = 0
    mode = "ab" if resuming and have else "wb"

    with response, partial.open(mode) as handle:
        if on_progress is not None:
            on_progress(DownloadProgress(have, entry.size_bytes))
        while True:
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled(
                    f"{entry.label} was stopped at {have} of {entry.size_bytes} bytes; "
                    f"the partial download is kept and resuming will continue from there"
                )
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            have += len(chunk)
            if on_progress is not None:
                on_progress(DownloadProgress(have, entry.size_bytes))

    if have != entry.size_bytes:
        raise DownloadRefused(
            f"{entry.label} arrived incomplete ({have} of {entry.size_bytes} bytes). The "
            f"partial download is kept; resuming will continue from where it stopped."
        )
    partial.replace(final)
    _verify(final, entry)
    return final


def delete_entry(entry: CatalogEntry) -> bool:
    """Remove an installed model and any partial. True if anything was there.

    Deletion exists from the first version on purpose: a feature that can fill a disk and not
    empty it is not finished (ADR-0080 §3).
    """
    final = installed_path(entry)
    partial = _partial_path(final)
    removed = final.exists() or partial.exists()
    final.unlink(missing_ok=True)
    partial.unlink(missing_ok=True)
    with contextlib.suppress(OSError):  # only if now empty; a shared dir is left alone
        final.parent.rmdir()
    return removed


def disk_free_bytes() -> int:
    """Free space where models are stored — shown BEFORE a download starts (L21)."""
    root = model_root()
    probe = root if root.exists() else root.parent
    probe.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(probe).free
