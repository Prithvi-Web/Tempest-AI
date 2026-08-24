"""The local-model catalogue and its downloader (ADR-0080).

Every test here drives the REAL downloader against a real loopback HTTP peer. Nothing is
mocked out of the path: the redirect is a real 302, the resume is a real `Range:` request, and
the checksum is a real sha256 over real bytes. The only thing that is not real is the model,
because a 2.5 GB file is not what any of this is testing.
"""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from tempest.dev._fake_peer import FakeHuggingFace, fake_huggingface_server
from tempest.models import catalog as catalog_mod
from tempest.models import download as dl
from tempest.models.catalog import CATALOG, CatalogEntry, entry_for

PAYLOAD = b"GGUF" + bytes(range(256)) * 40  # ~10 KB, deterministic
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def models_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "models"


def _entry(base: str, **over: object) -> CatalogEntry:
    spec = CatalogEntry(
        id="fake-model",
        label="Fake Model",
        good_at="being small",
        license="apache-2.0",
        repo="repo",
        filename="model.gguf",
        size_bytes=len(PAYLOAD),
        sha256=DIGEST,
        ram_note="none to speak of",
    )
    return replace(spec, **over)  # type: ignore[arg-type]


def _point_at(entry: CatalogEntry, base: str, monkeypatch: pytest.MonkeyPatch) -> CatalogEntry:
    """Re-point the entry's URL at the loopback peer by swapping the host constant."""
    monkeypatch.setattr(catalog_mod, "HUGGINGFACE_HOST", base.removeprefix("http://"))
    monkeypatch.setattr(
        CatalogEntry,
        "url",
        property(lambda self: f"{base}/{self.repo}/resolve/main/{self.filename}"),
    )
    return entry


class TestTheCatalogueIsHonestData:
    def test_every_row_is_permissively_licensed(self) -> None:
        """ "Free to download" and "free to use" are different claims, and only the second is
        the promise this feature makes. A row outside the permissive set is a build failure,
        not a judgement call at review time."""
        for entry in CATALOG:
            assert entry.license in catalog_mod._PERMISSIVE, (
                f"{entry.id} carries {entry.license!r}, which is not a permissive licence"
            )

    def test_every_row_carries_what_a_user_needs_before_spending_gigabytes(self) -> None:
        for entry in CATALOG:
            assert entry.good_at and not entry.good_at.startswith("A "), entry.id
            assert entry.ram_note, entry.id
            assert entry.size_bytes > 0, entry.id
            assert len(entry.sha256) == 64 and entry.sha256.islower(), entry.id
            assert int(entry.sha256, 16) >= 0, f"{entry.id}: sha256 is not hex"
            assert 0.1 < entry.size_gb < 100, entry.id

    def test_ids_are_unique_and_filesystem_safe(self) -> None:
        ids = [e.id for e in CATALOG]
        assert len(set(ids)) == len(ids)
        for entry in CATALOG:
            assert dl.safe_leaf(entry.id) == entry.id
            assert dl.safe_leaf(entry.filename) == entry.filename

    def test_every_url_is_the_one_recorded_host(self) -> None:
        """The host lives in exactly one constant so `egress_check` can close a ledger over
        it. A row that hard-codes a different host would be a second egress surface."""
        for entry in CATALOG:
            assert entry.url.startswith(f"https://{catalog_mod.HUGGINGFACE_HOST}/"), entry.id

    def test_an_unknown_id_is_a_none_not_an_exception(self) -> None:
        assert entry_for(CATALOG[0].id) is CATALOG[0]
        assert entry_for("no-such-model") is None

    def test_the_smallest_row_really_is_small(self) -> None:
        """The catalogue is small-first on purpose: someone on a slow link should be able to
        see a local model work in minutes rather than committing to 2.5 GB to find out."""
        assert min(e.size_bytes for e in CATALOG) < 1_000_000_000


class TestSafeLeaf:
    @pytest.mark.parametrize(
        "hostile",
        [
            "",
            ".",
            "..",
            "../etc/passwd",
            "a/b",
            "a\\b",
            "/abs",
            "x\0y",
            # Windows drive-relative: harmless-looking on macOS, and on Windows it resolves
            # against the drive's CURRENT directory rather than under the models root.
            "C:model.gguf",
            "a:b",
        ],
    )
    def test_a_name_that_is_not_one_component_is_refused(self, hostile: str) -> None:
        """It REFUSES rather than sanitises. A sanitiser rewrites a hostile name into a
        plausible one and leaves every reader to reason about what it produced for every
        input; a refusal has exactly one behaviour."""
        with pytest.raises(dl.DownloadRefused):
            dl.safe_leaf(hostile)

    def test_ordinary_names_pass_through_unchanged(self) -> None:
        for name in ("qwen3-0.6b-q8", "model.gguf", "a_b.c-1"):
            assert dl.safe_leaf(name) == name


class TestDownloading:
    def test_a_download_verifies_its_checksum_and_lands(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            seen: list[dl.DownloadProgress] = []
            path = dl.download_entry(entry, on_progress=seen.append)

        assert path.read_bytes() == PAYLOAD
        assert path == models_root / "fake-model" / "model.gguf"
        assert seen and seen[-1].done_bytes == len(PAYLOAD)
        assert seen[-1].fraction == 1.0
        assert not path.with_name(path.name + ".partial").exists(), "the partial must be gone"

    def test_the_real_302_to_a_cdn_is_followed(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The hop that made this downloader need a redirect policy at all. The keyed model
        client refuses every redirect, deliberately; this one follows exactly one, to a host
        in the closed ledger, on a request that carries no credential."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            fake.redirect_to = f"{base}/cdn/model.gguf"
            entry = _point_at(_entry(base), base, monkeypatch)
            monkeypatch.setattr(
                dl, "_ALLOWED_REDIRECT_SUFFIXES", (base.removeprefix("http://").split(":")[0],)
            )
            path = dl.download_entry(entry)

        assert path.read_bytes() == PAYLOAD
        assert [p for p, _ in fake.requests] == ["/repo/resolve/main/model.gguf", "/cdn/model.gguf"]

    def test_a_redirect_off_the_ledger_is_refused_by_host(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unaudited host is where a download becomes an egress surface nobody reviewed."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            fake.redirect_to = "http://example.invalid/model.gguf"
            entry = _point_at(_entry(base), base, monkeypatch)
            monkeypatch.setattr(dl, "_ALLOWED_REDIRECT_SUFFIXES", ("huggingface.co",))
            with pytest.raises(dl.DownloadRefused, match="not in the allowed set"):
                dl.download_entry(entry)

    def test_a_wrong_checksum_refuses_AND_removes_the_file(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A partial or substituted model is not a model. Leaving it on disk would leave
        something that LOOKS installed, which is worse than nothing."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base, sha256="0" * 64), base, monkeypatch)
            with pytest.raises(dl.DownloadRefused, match="did not match its recorded checksum"):
                dl.download_entry(entry)

            # BOTH paths, because verification now happens BEFORE the promote and asserting
            # only on the installed path would be satisfied for free — the file never gets
            # there. That is the assertion this test had until the reorder made it vacuous
            # (trap 60), and the partial is the one that actually needs checking.
            assert not dl.installed_path(entry).exists(), "nothing may sit at the installed path"
            assert not dl._partial_path(dl.installed_path(entry)).exists(), (
                "a file that failed its hash must be REMOVED, not left as a partial that the "
                "next attempt would happily resume from and re-verify forever"
            )

    def test_an_interrupted_download_resumes_from_its_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason `Range:` is worth having: a download stopped at 80% should cost the
        remaining 20%, not start again. The peer's recorded Range header is the proof — a
        client that silently restarted would look identical in the final file."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        # A chunk small enough that this payload takes many reads: with the shipped 1 MB
        # chunk a 10 KB file arrives whole and there is no partial to resume FROM, so the
        # test would be green about a path it never took.
        monkeypatch.setattr(dl, "_CHUNK", 1024)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            cancel = threading.Event()

            def stop_once_bytes_have_landed(progress: dl.DownloadProgress) -> None:
                # NOT on the first callback: that one reports zero, before any read, and
                # cancelling there would leave an empty partial and prove nothing.
                if progress.done_bytes > 0:
                    cancel.set()

            with pytest.raises(dl.DownloadCancelled):
                dl.download_entry(entry, on_progress=stop_once_bytes_have_landed, cancel=cancel)

            partial = dl._partial_path(dl.installed_path(entry))
            assert partial.exists(), (
                "a cancelled download must KEEP its partial, or resume is a lie"
            )
            kept = partial.stat().st_size
            assert 0 < kept < len(PAYLOAD)

            path = dl.download_entry(entry)  # resume

        assert path.read_bytes() == PAYLOAD
        ranges = [r for _p, r in fake.requests]
        assert ranges[0] is None, "the first attempt asks for the whole file"
        assert ranges[-1] == f"bytes={kept}-", (
            f"the resume must ask for the REMAINDER; it asked {ranges[-1]!r}"
        )

    def test_a_peer_that_ignores_range_does_not_splice_the_file(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The corruption this would cause is silent and total: appending a full body onto a
        partial writes the file's head into its middle, and only the checksum would notice.
        The client trusts the response STATUS (206), never its own request.
        """
        fake = FakeHuggingFace(payload=PAYLOAD, honour_range=False)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(PAYLOAD[:100])  # a plausible earlier attempt

            path = dl.download_entry(entry)

        assert path.read_bytes() == PAYLOAD, "the file was spliced rather than restarted"

    def test_a_partial_longer_than_the_row_is_discarded(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Longer than the catalogue says means it is not a prefix of the right file — most
        likely a leftover from a row that has since been refreshed."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(PAYLOAD + b"leftover junk")

            path = dl.download_entry(entry)

        assert path.read_bytes() == PAYLOAD
        assert [r for _p, r in fake.requests] == [None], "a junk partial must not be resumed from"

    def test_an_already_installed_model_is_not_downloaded_again(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            first = dl.download_entry(entry)
            calls = len(fake.requests)
            again = dl.download_entry(entry)

        assert first == again
        assert len(fake.requests) == calls, "an installed model must cost nothing to 'download'"

    def test_a_cancel_before_the_first_byte_reaches_no_host(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            cancel = threading.Event()
            cancel.set()
            with pytest.raises(dl.DownloadCancelled, match="before the download started"):
                dl.download_entry(entry, cancel=cancel)
        assert fake.requests == [], "a cancelled download must not touch the network at all"

    def test_a_truncated_body_refuses_and_keeps_the_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A short read is not a small model. It refuses, and keeps what it has so the retry
        is a resume rather than a restart."""
        fake = FakeHuggingFace(payload=PAYLOAD, truncate_at=512)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            with pytest.raises(dl.DownloadRefused, match="arrived incomplete"):
                dl.download_entry(entry)
            assert dl._partial_path(dl.installed_path(entry)).stat().st_size == 512

    def test_a_missing_file_names_a_stale_row_rather_than_suggesting_a_retry(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L23: the reason has to be actionable. A 404 here means the catalogue row is stale,
        and retrying will never fix that — so the message says so instead of apologising."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base, filename="absent.gguf"), base, monkeypatch)
            with pytest.raises(dl.DownloadRefused, match="stale"):
                dl.download_entry(entry)

    def test_a_disk_that_fills_mid_download_is_a_refusal_not_a_tempest_defect(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L15.3. ENOSPC on the WRITE is an ordinary condition with an obvious next step, and
        it used to escape as a bare OSError into the job layer's last-resort arm — the one
        reserved for "a defect in us" — so a user with a full disk was told the download failed
        inside Tempest."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        monkeypatch.setattr(dl, "_CHUNK", 512)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)

            real_open = Path.open

            def full_disk(self: Path, *args: object, **kwargs: object) -> object:
                handle = real_open(self, *args, **kwargs)  # type: ignore[arg-type]
                if self.suffix == ".partial":
                    original_write = handle.write

                    def boom(data: object) -> int:
                        original_write(data)  # type: ignore[arg-type]
                        raise OSError(28, "No space left on device")

                    handle.write = boom  # type: ignore[method-assign,assignment]
                return handle

            monkeypatch.setattr(Path, "open", full_disk)
            with pytest.raises(dl.DownloadRefused, match="No space left on device"):
                dl.download_entry(entry)

    def test_a_connection_dropped_mid_body_is_a_refusal_that_keeps_the_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Walking out of wifi range is not a Tempest defect. The read loop lives outside the
        guard that owns the friendly message, so a `ConnectionResetError` used to reach the
        user as an internal fault with no next step."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        monkeypatch.setattr(dl, "_CHUNK", 512)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            reads = {"n": 0}
            import http.client

            real_read = http.client.HTTPResponse.read

            def drop(self: object, amt: int | None = None) -> bytes:
                reads["n"] += 1
                if reads["n"] > 2:
                    raise ConnectionResetError(54, "Connection reset by peer")
                return real_read(self, amt)  # type: ignore[arg-type]

            monkeypatch.setattr(http.client.HTTPResponse, "read", drop)
            with pytest.raises(dl.DownloadRefused, match="Connection reset by peer"):
                dl.download_entry(entry)

        kept = dl._partial_path(dl.installed_path(entry))
        assert kept.exists() and kept.stat().st_size > 0, (
            "the bytes already downloaded must survive, or the retry is a restart"
        )

    def test_an_unreachable_host_says_so_and_keeps_what_it_had(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L23: a network failure is reported with a reason and a next step, never a spinner
        and never a stack trace. The partial survives, because the retry after the wifi comes
        back should resume rather than restart.
        """
        import socket

        # A port nothing is listening on: bind, read the number, close. Deterministic, and
        # not a guess that could collide with a real service.
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        base = f"http://127.0.0.1:{dead_port}"

        entry = _point_at(_entry(base), base, monkeypatch)
        partial = dl._partial_path(dl.installed_path(entry))
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(PAYLOAD[:64])

        with pytest.raises(dl.DownloadRefused, match="Check the network connection"):
            dl.download_entry(entry)

        assert partial.read_bytes() == PAYLOAD[:64], (
            "an unreachable host must not cost the user the bytes they already had"
        )

    def test_a_server_that_says_the_partial_is_already_complete_promotes_it(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 416 for a partial the size of the whole file means the bytes are already here."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(PAYLOAD)

            path = dl.download_entry(entry)

        assert path.read_bytes() == PAYLOAD


class TestDeletingAndSpace:
    def test_delete_removes_the_model_and_its_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deletion exists in the first version because a feature that can fill a disk and not
        empty it is not finished."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            path = dl.download_entry(entry)
            assert path.exists()
            assert dl.delete_entry(entry) is True
            assert not path.exists()
            assert not path.parent.exists(), "the model's own directory goes with it"
            assert dl.delete_entry(entry) is False, "deleting nothing reports nothing"

    def test_free_space_is_measurable_before_a_download(self, models_root: Path) -> None:
        """L21 applied to disk: gigabytes are a cost, and the size is shown before the spend.
        The lower bound matters — a zero here would satisfy any 'enough room?' check."""
        free = dl.disk_free_bytes()
        assert free > 0
        assert free > CATALOG[0].size_bytes or free > 0


class TestTheServerDoesNotDecideWhatReachesTheDisk:
    """The second adversarial review over this module (ADR-0080 §2 amendment).

    Every finding here has one shape: a number the SERVER chose was trusted where the
    catalogue row is what the user actually agreed to. The row is the contract, and a peer
    that disagrees with it is a reason to refuse — which `DownloadProgress`'s own docstring
    already claimed and nothing enforced (trap 45).
    """

    def test_a_body_longer_than_the_row_writes_only_the_row(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L15.4. The loop broke only on an empty chunk, so the byte count committed to disk
        was the server's choice: a peer answering a 639 MB row with a 500 GB body filled the
        disk, because `have != size_bytes` is checked once, AFTER every byte is written."""
        fake = FakeHuggingFace(payload=PAYLOAD, overrun_bytes=40_000)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            path = dl.download_entry(entry)

        assert path.stat().st_size == entry.size_bytes, (
            "the row is the budget — not one byte beyond it may reach the disk"
        )
        assert path.read_bytes() == PAYLOAD
        assert not dl._partial_path(path).exists()

    def test_a_206_that_serves_the_wrong_offset_refuses_and_keeps_the_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A peer can honour `Range:` in its STATUS and ignore it in its body — a caching
        proxy serving a whole object for a ranged request does exactly that. `Content-Range`
        is the only header that can tell, and it was never read. The old path spliced the
        head into the middle, reached a checksum mismatch, DELETED the partial, and blamed an
        upstream re-upload (L15.3: the wrong cause, and the user pays for it twice)."""
        keep = 4_000
        fake = FakeHuggingFace(payload=PAYLOAD, serve_from=0)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(PAYLOAD[:keep])

            with pytest.raises(dl.DownloadRefused) as caught:
                dl.download_entry(entry)

        assert "range" in str(caught.value).lower(), (
            f"the refusal must name the range the server ignored, not a checksum: {caught.value}"
        )
        assert partial.read_bytes() == PAYLOAD[:keep], (
            "a server that ignored our range must not cost the user the bytes they had"
        )
        assert not dl.installed_path(entry).exists()

    def test_the_416_arm_verifies_before_promoting_and_keeps_a_short_partial(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 416 means "your offset is past the end" — which is only "you already have it all"
        when the partial is the row's full size. Against an upstream file that was re-uploaded
        SHORTER, the arm promoted a too-small partial to the installed path, hashed it there,
        and `_verify`'s unlink then deleted the user's own resume progress."""
        short = PAYLOAD[:3_000]  # upstream is now shorter than the row records
        fake = FakeHuggingFace(payload=short)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(short)  # a 416 next: our offset is at the end of THEIR file

            with pytest.raises(dl.DownloadRefused) as caught:
                dl.download_entry(entry)

        assert not dl.installed_path(entry).exists(), (
            "nothing unverified may ever appear at the installed path — the rename is the "
            "commit point"
        )
        assert partial.read_bytes() == short, "the partial is the user's, and it is kept"
        assert "checksum" not in str(caught.value).lower(), (
            f"a short upstream file is a stale ROW, not a corrupt download: {caught.value}"
        )

    def test_a_file_at_the_installed_path_that_is_not_the_row_is_refused(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`if final.exists(): return final` applied no test at all — not the hash, not even
        the free size comparison. A refreshed catalogue hash therefore never re-verified what
        was already on disk, so a model the user installed before an upstream re-upload stayed
        `installed` for ever and was handed to the model server unreviewed."""
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            final = dl.installed_path(entry)
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(b"not the model the row records")

            with pytest.raises(dl.DownloadRefused) as caught:
                dl.download_entry(entry)

        message = str(caught.value)
        assert str(final) in message, f"the refusal names the file to remove: {message}"
        assert final.read_bytes() == b"not the model the row records", (
            "a file Tempest did not write is not Tempest's to delete — it says so instead"
        )

    def test_a_cancel_lands_while_the_read_is_blocked_on_a_dribbling_peer(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trap 58, in this module. The flag was read once per chunk, which is only reachable
        when chunks arrive: a peer dribbling bytes slower than one `read()` fills leaves the
        thread blocked INSIDE the read, where `urlopen(timeout=)` never fires because bytes
        keep arriving. Stop was unobservable for the length of the whole transfer."""
        # 40 pieces, a quarter-second apart: ten seconds of dribble, and one `read()` of the
        # full chunk size spans all of it.
        fake = FakeHuggingFace(payload=PAYLOAD, chunk_size=len(PAYLOAD) // 40, chunk_delay_s=0.25)
        cancel = threading.Event()
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            threading.Timer(0.6, cancel.set).start()
            started = time.monotonic()
            with pytest.raises(dl.DownloadCancelled):
                dl.download_entry(entry, cancel=cancel, timeout=30.0)
            took = time.monotonic() - started

        # The bound is deliberately loose against the 10 s dribble: what fails here is a
        # cancel that waits for the transfer, not a cancel that is merely unhurried (trap 61).
        assert took < 5.0, f"cancel waited for the peer instead of shutting the socket: {took:.1f}s"
        assert dl._partial_path(dl.installed_path(entry)).exists(), (
            "a cancelled download keeps its partial — that is what makes resume worth having"
        )


class TestTheRedirectAllowanceIsWhatItClaims:
    """`_ALLOWED_REDIRECT_SUFFIXES` is the entire safety of `_AllowListedRedirects`, and every
    test that exercised the follow or the refuse path monkeypatched it away — so the shipped
    tuple's CONTENTS were pinned by nothing, and `egress_check`'s check 8 reads only the
    identifier's name. These tests read the real thing."""

    def test_the_ledger_admits_the_recorded_cdn_hosts_and_nothing_that_merely_resembles_them(
        self,
    ) -> None:
        admitted = ("huggingface.co", "cdn-lfs.huggingface.co", "us.aws.cdn.hf.co", "hf.co")
        refused = (
            "huggingface.co.evil.example",  # the ledger entry as a PREFIX of a hostile name
            "evilhuggingface.co",  # the ledger entry as a SUFFIX of a hostile name
            "co",  # the shape a careless one-line edit adds while chasing a 302
            "hf.co.attacker.net",
            "notthf.co",
        )
        for host in admitted:
            assert dl._host_is_allowed(host), host
        for host in refused:
            assert not dl._host_is_allowed(host), host

    def test_a_credentialed_request_never_follows_a_redirect_however_the_header_was_added(
        self,
    ) -> None:
        """The clause the module docstring calls load-bearing was `# pragma: no cover` with the
        justification "this client never sets one" — which is circular, since the clause exists
        for the future caller who does. It also read only `req.headers`, and urllib's own auth
        handlers put `Authorization` in `unredirected_hdrs`, so the idiomatic way to attach a
        credential was the one way past the guard."""
        handler = dl._AllowListedRedirects()
        target = "https://cdn-lfs.huggingface.co/model.gguf"

        plain = urllib.request.Request("https://huggingface.co/repo/resolve/main/model.gguf")
        assert handler.redirect_request(plain, None, 302, "Found", {}, target) is not None

        for attach in ("add_header", "add_unredirected_header"):
            credentialed = urllib.request.Request(
                "https://huggingface.co/repo/resolve/main/model.gguf"
            )
            getattr(credentialed, attach)("Authorization", "Bearer sk-not-a-real-key")
            with pytest.raises(dl.DownloadRefused) as caught:
                handler.redirect_request(credentialed, None, 302, "Found", {}, target)
            assert "credential" in str(caught.value), attach

    def test_a_redirect_may_not_downgrade_the_transport(self) -> None:
        """The host was checked and the SCHEME was not, so a 302 to `http://` on a ledger host
        pulled 639 MB in cleartext — and from a cleartext hop an on-path attacker chooses
        every later hop. ADR-0080 §2 bounds the allowance to one hop; the handler inherited
        urllib's default of ten."""
        handler = dl._AllowListedRedirects()
        secure = urllib.request.Request("https://huggingface.co/repo/resolve/main/model.gguf")
        with pytest.raises(dl.DownloadRefused) as caught:
            handler.redirect_request(
                secure, None, 302, "Found", {}, "http://cdn-lfs.huggingface.co/model.gguf"
            )
        assert "https" in str(caught.value)
        assert handler.max_redirections == 1, (
            "ADR-0080 §2 says at most one hop; urllib's default is ten"
        )


class TestTheGuardsThatOnlyFireOnAHostilePeer:
    """Arms a well-behaved loopback peer cannot produce, asserted directly.

    Every one of these is a guard whose whole reason to exist is a peer that misbehaves in a
    way `http.server` will not. Left untested they are the shape this feature has already
    been burned by twice — a comment claiming a check that never runs (trap 45).
    """

    def test_a_206_with_no_content_range_is_refused_rather_than_guessed_at(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keep = 2_000
        fake = FakeHuggingFace(payload=PAYLOAD, omit_content_range=True)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            partial = dl._partial_path(dl.installed_path(entry))
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(PAYLOAD[:keep])

            with pytest.raises(dl.DownloadRefused, match="no usable Content-Range"):
                dl.download_entry(entry)

        assert partial.read_bytes() == PAYLOAD[:keep], "nothing was appended to it"

    def test_a_read_that_ends_as_a_clean_eof_under_cancel_reports_the_cancel(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The clean-EOF half of trap 58. `shutdown(2)` can make a blocked read return an
        empty bytes object rather than raise, and an empty read is how the loop learns a body
        ENDED. Without the re-check after the loop, a stopped download reports "arrived
        incomplete" — a stale row, in a message that tells the user to blame upstream — for
        what the user themselves just asked for.

        Driven at the response seam because a loopback peer cannot be made to produce it on
        demand; the peer, the file and the write are all real.
        """
        cancel = threading.Event()
        fake = FakeHuggingFace(payload=PAYLOAD)
        with fake_huggingface_server(fake) as base:
            entry = _point_at(_entry(base), base, monkeypatch)
            opened = dl._opener().open(entry.url, timeout=10.0)

            class EofUnderCancel:
                """The response, with its read hijacked exactly once — the way a socket that
                was shut down mid-read behaves."""

                status = opened.status
                headers = opened.headers

                def read(self, _size: int) -> bytes:
                    cancel.set()
                    return b""

                def fileno(self) -> int:
                    return opened.fileno()

                def close(self) -> None:
                    opened.close()

                def __enter__(self) -> EofUnderCancel:
                    return self

                def __exit__(self, *_: object) -> None:
                    self.close()

            monkeypatch.setattr(dl, "_opener", lambda: _OpenerReturning(EofUnderCancel()))
            with pytest.raises(dl.DownloadCancelled, match="was stopped at"):
                dl.download_entry(entry, cancel=cancel)

    def test_an_io_error_under_cancel_is_a_cancel_and_otherwise_keeps_its_own_face(self) -> None:
        """`_watching`'s translation, both ways. A shut-down read surfaces as an I/O error;
        that is a cancel if and only if the caller cancelled. A genuine upstream fault must
        keep its own exception so the caller's own arm can report the real cause (L15.3)."""

        class Response:
            def fileno(self) -> int:
                raise OSError("no descriptor in this stand-in")

        cancel = threading.Event()
        cancel.set()
        with pytest.raises(dl.DownloadCancelled, match="was stopped"):
            with dl._watching(cancel, Response()):
                raise OSError("the read came back broken")

        quiet = threading.Event()
        with pytest.raises(OSError, match="a real upstream fault"):
            with dl._watching(quiet, Response()):
                raise OSError("a real upstream fault")

        # No cancel event at all: the guard is a pass-through, not a rewrapper.
        with pytest.raises(OSError, match="untouched"):
            with dl._watching(None, Response()):
                raise OSError("untouched")


class _OpenerReturning:
    """The one seam these two tests replace: an opener that hands back a prepared response."""

    def __init__(self, response: object) -> None:
        self._response = response

    def open(self, _request: object, timeout: float = 0.0) -> object:
        return self._response


class TestWhatIsOnDiskIsAnsweredHonestly:
    """`installed` was a bare `.exists()`, which answered a different question than every
    caller was asking, and nothing could see a partial at all."""

    def test_a_partial_is_measurable_and_an_absent_one_is_zero(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _point_at(_entry("http://unused.invalid"), "http://unused.invalid", monkeypatch)
        assert dl.partial_bytes(entry) == 0
        partial = dl._partial_path(dl.installed_path(entry))
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(PAYLOAD[:1_234])
        assert dl.partial_bytes(entry) == 1_234

    def test_a_file_of_the_wrong_size_is_stray_and_is_not_installed(
        self, models_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _point_at(_entry("http://unused.invalid"), "http://unused.invalid", monkeypatch)
        final = dl.installed_path(entry)
        assert dl.stray_bytes(entry) == 0 and not dl.is_installed(entry)

        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"three bytes short of the row")
        assert dl.stray_bytes(entry) == len(b"three bytes short of the row")
        assert not dl.is_installed(entry), (
            "a file whose size disagrees with the row is not this model, and the panel must "
            "not offer to serve it"
        )

        final.write_bytes(PAYLOAD)
        assert dl.stray_bytes(entry) == 0
        assert dl.is_installed(entry)


class TestProgressArithmetic:
    def test_a_fraction_of_nothing_is_zero_rather_than_a_division(self) -> None:
        """Catalogue rows always carry a size, so this arm is unreachable through the
        downloader — which is exactly the argument that had it marked `pragma: no cover`. It
        is one line to assert, and a `pragma` on a testable branch is a coverage number
        standing in for a test."""
        assert dl.DownloadProgress(0, 0).fraction == 0.0

    def test_a_fraction_never_exceeds_one_even_if_a_peer_overruns(self) -> None:
        assert dl.DownloadProgress(500, 100).fraction == 1.0
        assert dl.DownloadProgress(50, 100).fraction == 0.5
