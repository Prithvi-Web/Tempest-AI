"""The local-model surface over boundary A (ADR-0080).

Real router, real job threads, real HTTP against a loopback peer. The catalogue is swapped for
a one-row fixture pointed at that peer, because the point of these tests is the SURFACE — the
shapes a client reads, the states a job moves through, and the refusals — not whether Hugging
Face is up.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tempest.dev._fake_peer import FakeHuggingFace, fake_huggingface_server
from tempest.models import download as dl
from tempest.models.catalog import CatalogEntry
from tempest_api import modeldownloads

PAYLOAD = b"GGUF" + bytes(range(256)) * 40
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def peer() -> Iterator[tuple[FakeHuggingFace, str]]:
    fake = FakeHuggingFace(payload=PAYLOAD)
    with fake_huggingface_server(fake) as base:
        yield fake, base


@pytest.fixture
def catalogue(
    peer: tuple[FakeHuggingFace, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CatalogEntry:
    """One catalogue row, served by the loopback peer, stored under a fresh data root."""
    _fake, base = peer
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
    entry = CatalogEntry(
        id="fixture-model",
        label="Fixture Model",
        good_at="being downloaded in a test",
        license="apache-2.0",
        repo="repo",
        filename="model.gguf",
        size_bytes=len(PAYLOAD),
        sha256=DIGEST,
        ram_note="none to speak of",
    )
    monkeypatch.setattr(
        CatalogEntry,
        "url",
        property(lambda self: f"{base}/{self.repo}/resolve/main/{self.filename}"),
    )
    from tempest.models import catalog as catalog_mod

    monkeypatch.setattr(catalog_mod, "CATALOG", (entry,))
    monkeypatch.setattr("tempest.models.CATALOG", (entry,))
    monkeypatch.setattr(catalog_mod, "entry_for", lambda mid: entry if mid == entry.id else None)
    monkeypatch.setattr(modeldownloads, "entry_for", lambda mid: entry if mid == entry.id else None)
    modeldownloads.reset_for_test()
    yield entry
    modeldownloads.reset_for_test()


def _settle(api: Any, model_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Poll the download to a terminal state — the same poll a client makes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = api.client.get(f"/v1/models/{model_id}/download").json()
        if body["state"] != "running":
            return body  # type: ignore[no-any-return]
        time.sleep(0.02)
    raise AssertionError(f"download of {model_id} never settled")


class TestTheCatalogueSurface:
    def test_the_size_and_the_room_for_it_are_on_screen_before_the_spend(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        """L21 applied to disk. A user is about to spend gigabytes, so the row carries the
        size, whether it is already installed, and whether it will actually fit — all in the
        FIRST response, so the UI never has to make a second call to answer 'can I?'."""
        rows = api.client.get("/v1/models/catalog").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == catalogue.id
        assert row["sizeBytes"] == len(PAYLOAD)
        assert row["license"] == "apache-2.0"
        assert row["goodAt"], "a row with no plain-words description is a row nobody can choose"
        assert row["ramNote"]
        assert row["installed"] is False
        assert row["freeBytes"] > 0, "a zero here would satisfy any 'does it fit' check"
        assert row["fitsOnDisk"] is True
        assert row["download"] is None, "nothing has been started yet"


class TestDownloadingThroughTheWire:
    def test_a_download_runs_to_done_and_shows_as_installed(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        started = api.client.post(f"/v1/models/{catalogue.id}/download")
        assert started.status_code == 200, started.text
        assert started.json()["state"] in ("running", "done")

        final = _settle(api, catalogue.id)
        assert final["state"] == "done", final
        assert final["doneBytes"] == len(PAYLOAD)
        assert final["error"] == ""

        row = api.client.get("/v1/models/catalog").json()[0]
        assert row["installed"] is True
        assert dl.installed_path(catalogue).read_bytes() == PAYLOAD

    def test_a_second_start_does_not_open_a_second_writer(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        """Two workers on one path is a corrupted file, not a faster download."""
        api.client.post(f"/v1/models/{catalogue.id}/download")
        again = api.client.post(f"/v1/models/{catalogue.id}/download")
        assert again.status_code == 200
        _settle(api, catalogue.id)
        assert dl.installed_path(catalogue).read_bytes() == PAYLOAD

    def test_starting_an_installed_model_is_a_no_op_that_costs_nothing(
        self, api: Any, catalogue: CatalogEntry, peer: tuple[FakeHuggingFace, str]
    ) -> None:
        fake, _base = peer
        api.client.post(f"/v1/models/{catalogue.id}/download")
        _settle(api, catalogue.id)
        requests_after_first = len(fake.requests)

        body = api.client.post(f"/v1/models/{catalogue.id}/download").json()
        assert body["state"] == "done"
        assert len(fake.requests) == requests_after_first, (
            "an installed model must not be fetched again"
        )

    def test_a_checksum_mismatch_surfaces_as_a_readable_failure(
        self, api: Any, catalogue: CatalogEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure a user must never see silently: bytes that are not the model. It fails
        LOUDLY with a reason, and nothing is left on disk pretending to be installed."""
        wrong = replace(catalogue, sha256="0" * 64)
        monkeypatch.setattr(
            modeldownloads, "entry_for", lambda mid: wrong if mid == wrong.id else None
        )

        api.client.post(f"/v1/models/{wrong.id}/download")
        final = _settle(api, wrong.id)
        assert final["state"] == "failed"
        assert "checksum" in final["error"]
        assert "removed" in final["error"], "the message must say the file is gone"
        assert not dl.installed_path(wrong).exists()

    def test_a_defect_inside_tempest_becomes_a_readable_failed_state(
        self, api: Any, catalogue: CatalogEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L15.3: a defect in US is reported, never swallowed into a job that stops moving.
        A worker thread that dies with an unhandled exception leaves a download stuck on
        `running` forever, which reads to a user as a hang and to a poller as progress."""

        def boom(*_args: Any, **_kwargs: Any) -> Any:
            raise ZeroDivisionError("a defect that is ours, not the network's")

        monkeypatch.setattr(modeldownloads, "download_entry", boom)
        api.client.post(f"/v1/models/{catalogue.id}/download")
        final = _settle(api, catalogue.id)

        assert final["state"] == "failed", "the job must reach a terminal state, not hang"
        assert "failed inside Tempest" in final["error"]
        assert "ZeroDivisionError" in final["error"], (
            "the diagnostic must name the real cause, or nobody can act on it"
        )

    def test_an_unknown_model_is_a_400_naming_the_id(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        for call in (
            lambda: api.client.post("/v1/models/ghost/download"),
            lambda: api.client.get("/v1/models/ghost/download"),
            lambda: api.client.post("/v1/models/ghost/download/cancel"),
            lambda: api.client.delete("/v1/models/ghost"),
        ):
            resp = call()
            assert resp.status_code == 400, resp.text
            assert "ghost" in resp.text

    def test_the_status_of_a_model_nobody_started_is_honest(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        body = api.client.get(f"/v1/models/{catalogue.id}/download").json()
        assert body["state"] == "failed"
        assert body["error"] == "not downloaded"
        assert body["totalBytes"] == len(PAYLOAD), "the size is known even before a download"


class TestCancelAndRemove:
    def test_cancelling_keeps_the_partial_so_resuming_costs_the_remainder(
        self,
        api: Any,
        catalogue: CatalogEntry,
        peer: tuple[FakeHuggingFace, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake, _base = peer
        # Small chunks on BOTH sides, and a throttled producer. With the shipped 1 MB chunk
        # this payload arrives whole; and even chunked, loopback delivers 10 KB faster than a
        # test can react, so the cancel would race the network stack. Making the PEER the slow
        # one turns "cancel lands mid-download" from a coin flip into a fact (trap 61).
        monkeypatch.setattr(dl, "_CHUNK", 512)
        fake.chunk_size = 512
        fake.chunk_delay_s = 0.05
        api.client.post(f"/v1/models/{catalogue.id}/download")

        # Cancel only once bytes have ACTUALLY landed. Cancelling immediately races the
        # worker's first read, and the download then refuses before it starts — leaving no
        # partial and a test that proves nothing about resuming (trap 61).
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            body = api.client.get(f"/v1/models/{catalogue.id}/download").json()
            if body["doneBytes"] > 0 or body["state"] != "running":
                break
            time.sleep(0.01)
        assert body["doneBytes"] > 0, "no bytes ever landed, so there is nothing to resume from"
        api.client.post(f"/v1/models/{catalogue.id}/download/cancel")

        final = _settle(api, catalogue.id)
        assert final["state"] == "cancelled"
        assert "resuming" in final["error"], "the message must say the progress was kept"

        api.client.post(f"/v1/models/{catalogue.id}/download")
        assert _settle(api, catalogue.id)["state"] == "done"
        assert dl.installed_path(catalogue).read_bytes() == PAYLOAD
        assert any(r is not None for _p, r in fake.requests), (
            "the resume must have asked for a byte RANGE; without one it silently restarted"
        )

    def test_cancelling_nothing_is_a_refusal_not_a_pretend_success(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        resp = api.client.post(f"/v1/models/{catalogue.id}/download/cancel")
        assert resp.status_code == 400
        assert "no download is running" in resp.text

    def test_remove_deletes_the_model_and_reports_it(
        self, api: Any, catalogue: CatalogEntry
    ) -> None:
        """Deletion exists in the first version because a feature that can fill a disk and
        not empty it is not finished."""
        api.client.post(f"/v1/models/{catalogue.id}/download")
        _settle(api, catalogue.id)
        assert dl.installed_path(catalogue).exists()

        body = api.client.delete(f"/v1/models/{catalogue.id}").json()
        assert body["removed"] is True
        assert not dl.installed_path(catalogue).exists()
        assert api.client.get("/v1/models/catalog").json()[0]["installed"] is False

        again = api.client.delete(f"/v1/models/{catalogue.id}").json()
        assert again["removed"] is False, "removing nothing must report nothing"

    def test_remove_refuses_while_a_download_is_running(
        self, api: Any, catalogue: CatalogEntry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting the file out from under its own worker is not "I changed my mind" — it is
        a half-written file left by a thread that no longer has anywhere to put its bytes."""
        monkeypatch.setattr(dl, "_CHUNK", 256)
        api.client.post(f"/v1/models/{catalogue.id}/download")
        resp = api.client.delete(f"/v1/models/{catalogue.id}")
        assert resp.status_code == 400
        assert "stop it first" in resp.text
        api.client.post(f"/v1/models/{catalogue.id}/download/cancel")
        _settle(api, catalogue.id)


class TestTheKeylessTurnOffersAWayOut:
    """ADR-0080 §8. A user with no API key is exactly the user who wants to hear that this app
    can run a model with no key at all — so the refusal carries a machine-readable remedy, and
    the client branches on THAT rather than on the sentence.

    The distinction is the point: an affordance keyed on prose breaks the moment the prose
    improves, which is precisely the wrong incentive to build into an error message.
    """

    def test_missing_key_carries_a_structured_remedy_not_just_a_sentence(self) -> None:
        from tempest.inference.client import MissingKey, ModelError

        err = MissingKey("no API key for Anthropic. Set it in Settings…")
        assert isinstance(err, ModelError)
        assert err.remedy == "local-model", (
            "the way out has to be a VALUE — a client cannot branch on a paragraph"
        )

    def test_the_error_part_carries_the_remedy_to_the_client(self) -> None:
        from tempest_api import chatwire

        with_remedy = chatwire.error_content_part("no API key", remedy="local-model")
        assert with_remedy == {"type": "error", "error": "no API key", "remedy": "local-model"}

    def test_an_error_with_no_way_out_carries_no_remedy_key_at_all(self) -> None:
        """Absent, not empty. A present-but-blank field is a UI that renders an affordance
        leading nowhere — the mystery state L36.12 forbids."""
        from tempest_api import chatwire

        plain = chatwire.error_content_part("the disk is full")
        assert plain == {"type": "error", "error": "the disk is full"}
        assert "remedy" not in plain

    def test_a_keyless_turn_reaches_the_client_with_the_remedy_attached(
        self, api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole path, not the pieces: a real turn against a provider with no key, and the
        persisted message carries the remedy beside the sentence."""
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "appdata"))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from tempest_api.routers import chat as chat_router

        chat_router._REGISTRY.clear()

        ack = api.client.post(
            "/v1/chat/turns",
            json={"text": "hello", "endpoint": "anthropic", "model_parameters": {"model": "m"}},
        )
        assert ack.status_code == 200, ack.text
        stream_id = ack.json()["streamId"]

        deadline = time.monotonic() + 30.0
        payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            payload = api.client.get(f"/v1/chat/turns/{stream_id}/events?after=0").json()
            if payload["status"] not in ("active", "unknown"):
                break
            time.sleep(0.05)

        final = payload["events"][-1]["frame"]
        parts = final["responseMessage"]["content"]
        errors = [p for p in parts if p.get("type") == "error"]
        assert errors, f"a keyless turn must surface an error part; got {parts}"
        assert "no API key" in errors[0]["error"]
        assert errors[0].get("remedy") == "local-model", (
            "the client offers 'get a local model' by branching on this field, never by "
            f"reading the sentence; got {errors[0]}"
        )
