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
import http.client
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from tempest import netcancel
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
        if self.total_bytes <= 0:
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


def partial_bytes(entry: CatalogEntry) -> int:
    """How much of `entry` is already on disk as a resumable partial. 0 when there is none."""
    partial = _partial_path(installed_path(entry))
    return partial.stat().st_size if partial.exists() else 0


def stray_bytes(entry: CatalogEntry) -> int:
    """The size of a file sitting at the installed path that is NOT this row's model.

    0 when the path is empty or holds the recorded model. Non-zero is a state the panel has
    to be able to show and act on: `installed` used to be a bare `.exists()`, so a file of
    the wrong size — a truncated copy, or a model whose row was refreshed after an upstream
    re-upload — was reported installed for ever and handed to the model server unreviewed.
    """
    final = installed_path(entry)
    if not final.exists():
        return 0
    size = final.stat().st_size
    return 0 if size == entry.size_bytes else size


def is_installed(entry: CatalogEntry) -> bool:
    """Whether the recorded model is on disk.

    The size is checked because it is free and because bare existence answered a different
    question than the one every caller was asking. The sha256 is NOT re-checked here: this is
    called on every catalogue read, and hashing gigabytes to paint a settings panel is a cost
    with no buyer. Integrity is established once, at install, before the file is ever named
    installed — and a size that disagrees with the row is enough to stop calling it this
    model.
    """
    return stray_bytes(entry) == 0 and installed_path(entry).exists()


def _host_is_allowed(host: str) -> bool:
    """True when `host` is one of the recorded CDN hosts, or a subdomain of one.

    A named predicate rather than an inline `any(...)`, because the tuple it reads is the
    entire safety of the redirect allowance and every test that exercised the follow or the
    refuse path replaced the tuple first — so its CONTENTS were pinned by nothing at all. The
    match is anchored on both ends by construction: equality, or a dot-prefixed suffix. That
    is what keeps `evilhuggingface.co` and `huggingface.co.evil.example` out, and it is the
    property a one-line edit (`"co"` added while chasing a 302) would otherwise destroy
    silently.
    """
    host = host.lower()
    return any(
        host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_REDIRECT_SUFFIXES
    )


class _AllowListedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a host in the closed ledger, and only for a request that
    carries no credential.

    The second half is the part that matters and the part a later reader will be tempted to
    drop: this handler is safe BECAUSE the request has no key on it. Reusing it for anything
    authenticated re-opens exactly the hole `_RefuseRedirects` was written to close.
    """

    #: ADR-0080 §2 bounds the allowance to ONE hop. `HTTPRedirectHandler` defaults to ten,
    #: and inheriting that default meant the ADR's sentence had no code behind it: ten hops
    #: is ten chances for an on-path attacker to walk the request somewhere else.
    max_redirections = 1

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urlparse(newurl)
        host = (target.hostname or "").lower()
        if not _host_is_allowed(host):
            raise DownloadRefused(
                f"the download was redirected to {host or newurl!r}, which is not in the "
                f"allowed set {sorted(_ALLOWED_REDIRECT_SUFFIXES)} — refusing rather than "
                f"following an unaudited host (L32)"
            )
        # The host was checked and the SCHEME was not, so a 302 to `http://` on a ledger host
        # pulled the whole file in cleartext — and from a cleartext hop an on-path attacker
        # picks every later hop and every byte. The sha256 catches the bytes; it does not
        # un-send them, and it does not cover the ftp:// handler `build_opener` installs for
        # free.
        #
        # The rule is "never weaken", not "https only": a redirect may hold the request's own
        # scheme or upgrade it, never drop below it. Stated that way it needs no exemption for
        # the loopback peers this module is tested against — an http request redirecting to
        # http loses nothing, because there was nothing to lose.
        may_go_to = ("https",) if req.type == "https" else ("https", "http")
        if target.scheme not in may_go_to:
            raise DownloadRefused(
                f"the download was redirected from {req.type}:// to "
                f"{target.scheme or 'an unnamed scheme'}://{host}, which weakens or leaves "
                f"the transport — refusing, because a cleartext hop hands every later hop to "
                f"whoever is on the path"
            )
        # `req.headers` is not where urllib keeps a credential. `add_unredirected_header` and
        # urllib's own `HTTPBasicAuthHandler` / `HTTPDigestAuthHandler` write into
        # `unredirected_hdrs`, so reading only the first dict meant the IDIOMATIC way to
        # attach a key was the one way past this guard. Both dicts, both spellings.
        carried = {key.lower() for key in req.headers} | {
            key.lower() for key in getattr(req, "unredirected_hdrs", {})
        }
        if carried & {"authorization", "cookie", "proxy-authorization"}:
            raise DownloadRefused(
                "a credentialed request must not follow a redirect; that is the leak "
                "`_RefuseRedirects` exists to prevent"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_AllowListedRedirects)


_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-")


def _require_range_starts_at(response: Any, have: int, entry: CatalogEntry) -> None:
    """A 206 must be sending the bytes we asked for, not merely calling itself partial.

    A peer can honour `Range:` in its status line and ignore it in its body — a caching proxy
    that serves a whole object for a ranged request does exactly this — and appending that
    body splices the file's head into its middle. The status alone cannot tell;
    `Content-Range` can, and it was never read. The old path ran all the way to a checksum
    mismatch, which DELETED the partial and blamed an upstream re-upload: the wrong cause, and
    the user pays for the whole download twice (L15.3).

    A 206 with no parseable `Content-Range` is refused rather than guessed at: the header is
    mandatory for that status, and a peer omitting it has told us nothing about what it sent.
    """
    header = response.headers.get("Content-Range", "") or ""
    found = _CONTENT_RANGE.search(header)
    if found is None:
        raise DownloadRefused(
            f"{entry.label}: the server answered 206 Partial Content with no usable "
            f"Content-Range header ({header!r}), so there is no way to know which bytes it "
            f"sent. The partial download is kept; nothing was appended to it."
        )
    start = int(found.group(1))
    if start != have:
        raise DownloadRefused(
            f"{entry.label}: resuming asked for byte {have} onward and the server answered "
            f"with byte {start} onward. Appending that would splice the file — a proxy in the "
            f"path may be ignoring range requests. The partial download is kept untouched."
        )


@contextlib.contextmanager
def _watching(cancel: threading.Event | None, response: Any) -> Iterator[None]:
    """Make `cancel` observable while a read is BLOCKED, not merely between reads (trap 58).

    The flag used to be read once per chunk, which is only reachable when chunks arrive: a
    peer dribbling bytes slower than one `read()` fills leaves the thread inside the read,
    where `urlopen(timeout=)` never fires because bytes do keep arriving. Measured before the
    fix: a cancel against a ten-second dribble took 10.2 s — the whole transfer.

    `tempest.netcancel` owns the mechanism, because `inference/client.py` paid for it first
    and one copy of a guard this subtle is all this tree should carry.
    """
    if cancel is None:
        yield
        return
    try:
        with netcancel.watch_cancel(cancel, response):
            yield
    # The shut-down read surfaces as an I/O error, or as an AttributeError when the response
    # Nones its `fp` mid-read. Either is a cancel if and only if the caller cancelled; a
    # genuine upstream fault keeps its own face and is reported by the caller's OSError arm.
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        if cancel.is_set():
            raise DownloadCancelled(
                "the download was stopped; the partial download is kept and resuming will "
                "continue from where it stopped"
            ) from None
        raise


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
    stray = stray_bytes(entry)
    if stray:
        # `if final.exists(): return final` applied no test at all — not the hash, not even
        # the free size comparison — so a refreshed catalogue hash never re-verified what was
        # already on disk. Refusing rather than deleting: Tempest did not necessarily write
        # this file, and silently removing a file it cannot identify is the wrong half of the
        # choice. The panel offers Remove for exactly this state.
        raise DownloadRefused(
            f"there is already a file at {final} that is not the model this row records "
            f"({stray} bytes on disk, {entry.size_bytes} recorded). It may be a model that "
            f"was re-uploaded upstream, or a partial copy from another tool. Remove it and "
            f"download again — Tempest will not install over a file it cannot identify."
        )
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
            # A 416 means "your offset is past the end of my file", which is only "you
            # already have all of it" when the partial is the row's full size. Against an
            # upstream file that was re-uploaded SHORTER, this arm used to promote a
            # too-small partial to the installed path, hash it there, and — because `_verify`
            # unlinks what it rejects — delete the user's own resume progress.
            if have != entry.size_bytes:
                raise DownloadRefused(
                    f"{entry.label}: the server has nothing past byte {have}, but this row "
                    f"records {entry.size_bytes} bytes. The file upstream is shorter than "
                    f"the catalogue says — the row needs refreshing, not a retry. The "
                    f"partial download is kept."
                ) from err
            # Verify FIRST, then promote: the rename is the commit point (same discipline as
            # the tail of this function).
            _verify(partial, entry)
            partial.replace(final)
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
    if resuming and have:
        _require_range_starts_at(response, have, entry)
    mode = "ab" if resuming and have else "wb"

    def stopped() -> DownloadCancelled:
        return DownloadCancelled(
            f"{entry.label} was stopped at {have} of {entry.size_bytes} bytes; "
            f"the partial download is kept and resuming will continue from there"
        )

    try:
        with (
            response,
            _watching(cancel, response),
            partial.open(mode) as handle,
        ):
            if on_progress is not None:
                on_progress(DownloadProgress(have, entry.size_bytes))
            # Bounded by the ROW, not by the peer. The loop used to break only on an empty
            # chunk, so the number of bytes committed to disk was the server's choice: a peer
            # answering a 639 MB row with a 500 GB body filled the disk, because
            # `have != size_bytes` is checked once and only after every byte is written
            # (L15.4 — no unbounded operations). Reading exactly the remainder also means a
            # peer that appends junk past the real file still yields the real file.
            while have < entry.size_bytes:
                if cancel is not None and cancel.is_set():
                    raise stopped()
                chunk = response.read(min(_CHUNK, entry.size_bytes - have))
                if not chunk:
                    break
                handle.write(chunk)
                have += len(chunk)
                if on_progress is not None:
                    on_progress(DownloadProgress(have, entry.size_bytes))
            # A shut-down socket ends the read as a clean-looking EOF, so the flag is
            # re-checked after the loop: a cancelled transfer must never impersonate a
            # completed one (the same re-check `inference/client.py` carries, for the same
            # reason).
            if cancel is not None and cancel.is_set():
                raise stopped()
    except DownloadCancelled:
        raise
    except OSError as err:
        # The read loop and the WRITE both live in here, and both fail in ordinary ways that
        # are not defects: the wifi drops (ConnectionResetError), the socket times out
        # (TimeoutError — the stall guard this module relies on), the body ends early
        # (IncompleteRead), the disk fills (ENOSPC on `handle.write`).
        #
        # None of those were caught before: the guard around `_opener().open()` covers the
        # CONNECT only, so every one of them escaped as a bare OSError into the job layer's
        # last-resort arm — the one reserved for "a defect in us" — and a user who had simply
        # walked out of wifi range was told "the download failed inside Tempest". That is
        # L15.3 exactly: a real condition, reported as an internal fault, with no next step.
        raise DownloadRefused(
            f"{entry.label} stopped after {have} of {entry.size_bytes} bytes: {err}. The "
            f"partial download is kept, so resuming will continue from where it stopped "
            f"rather than starting again."
        ) from err

    if have != entry.size_bytes:
        raise DownloadRefused(
            f"{entry.label} arrived incomplete ({have} of {entry.size_bytes} bytes). The "
            f"partial download is kept; resuming will continue from where it stopped."
        )
    # VERIFY FIRST, then promote. The rename is the commit point: doing it first leaves a
    # full-size, unverified file at the installed path for the whole duration of a sha256 over
    # gigabytes, and anything that ends the process in that window — a quit, a supervised
    # restart, a crash — leaves it there looking installed. `_verify` deletes what it rejects,
    # so a mismatch now removes a `.partial` and never an "installed" model.
    _verify(partial, entry)
    partial.replace(final)
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
