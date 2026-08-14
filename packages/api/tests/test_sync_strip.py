"""Redaction at the sync boundary (Phase 13, L9): with the DEFAULT policy, no source text
crosses — proven by planting distinctive source in a real bundle. Stripped bundles remain
fully ingestible; enabling org source-sharing is an explicit opt-in that passes bytes through
untouched."""

import pytest

from tempest_api.ingest import parse_bundle_zip
from tempest_api.syncstrip import source_sharing_enabled, strip_source_for_sync

PLANTED_SOURCE = "return secret_business_logic(x) * PLANTED_CONSTANT_777"


def _bundle_zip_with_planted_source(api) -> bytes:
    import dataclasses

    bundle = api.make_bundle()
    scripts = dict.fromkeys(bundle.repro_scripts, f"#!/usr/bin/env python3\n{PLANTED_SOURCE}\n")
    return api.zip_bytes(dataclasses.replace(bundle, repro_scripts=scripts))


def _member_texts(zip_bytes: bytes) -> dict[str, str]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return {n: archive.read(n).decode("utf-8", errors="replace") for n in archive.namelist()}


def test_default_policy_strips_all_source(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    assert source_sharing_enabled() is False
    original = _bundle_zip_with_planted_source(api)
    assert any(PLANTED_SOURCE in text for text in _member_texts(original).values()), (
        "the plant must exist before stripping"
    )

    stripped = strip_source_for_sync(original)
    for name, text in _member_texts(stripped).items():
        assert PLANTED_SOURCE not in text, f"source text crossed the boundary in {name}"

    bundle = parse_bundle_zip(stripped)  # still a valid, ingestible bundle
    for target in bundle.targets:
        for d in target.divergences:
            assert d.repro_filename in bundle.repro_scripts, "filenames survive for integrity"
    assert all("stripped" in body for body in bundle.repro_scripts.values())


def test_verdict_evidence_survives_stripping(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    original_bundle = parse_bundle_zip(_bundle_zip_with_planted_source(api))
    stripped_bundle = parse_bundle_zip(strip_source_for_sync(_bundle_zip_with_planted_source(api)))
    assert stripped_bundle.manifest == original_bundle.manifest
    assert stripped_bundle.targets == original_bundle.targets, (
        "verdicts, divergences, minimized inputs — the evidence — must survive"
    )


def test_opt_in_passes_bytes_through_untouched(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")
    assert source_sharing_enabled() is True
    original = _bundle_zip_with_planted_source(api)
    assert strip_source_for_sync(original) == original, "opt-in sharing is byte-exact"
