"""The local-model catalogue and its downloader (ADR-0080).

Every test here drives the REAL downloader against a real loopback HTTP peer. Nothing is
mocked out of the path: the redirect is a real 302, the resume is a real `Range:` request, and
the checksum is a real sha256 over real bytes. The only thing that is not real is the model,
because a 2.5 GB file is not what any of this is testing.
"""

from __future__ import annotations

import hashlib
import threading
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
            assert not dl.installed_path(entry).exists(), "a file that failed its hash must go"

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
