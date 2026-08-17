"""Redaction at the sync boundary (Phase 13, L9): with the DEFAULT policy, no source text
crosses — proven by planting distinctive source in a real bundle, in the repro scripts AND in
every source-derived string field of targets.json (mined literals in *_literal/shrink_path,
return values and exception text in the summaries — finding 4). Stripped bundles remain fully
ingestible; enabling org source-sharing is an explicit opt-in that passes bytes through
untouched."""

import dataclasses
import re

import pytest

from tempest_api.ingest import parse_bundle_zip
from tempest_api.syncstrip import source_sharing_enabled, strip_source_for_sync

PLANTED_SOURCE = "return secret_business_logic(x) * PLANTED_CONSTANT_777"
# Shaped like what generate/mining.py harvests: a string constant lifted from user source.
PLANTED_MINED = "PLANTED_MINED_STRING_CONSTANT_4242"

_PLACEHOLDER = re.compile(r"\[stripped:[0-9a-f]{12}\]")


def _planted_bundle(api):
    """A real bundle carrying the plant everywhere source-derived text travels."""
    bundle = api.make_bundle()
    scripts = dict.fromkeys(bundle.repro_scripts, f"#!/usr/bin/env python3\n{PLANTED_SOURCE}\n")
    targets = []
    for t in bundle.targets:
        divergences = tuple(
            dataclasses.replace(
                d,
                detail=f"return values differ for '{PLANTED_MINED}'",
                args_literal=f"('{PLANTED_MINED}',)",
                kwargs_literal=f"{{'key': '{PLANTED_MINED}'}}",
                minimized_args=f"('{PLANTED_MINED}',)",
                minimized_kwargs="{}",
                shrink_path=(f"args[0]: '{PLANTED_MINED}-longer'→'{PLANTED_MINED}'",),
                base_summary=f"returned '{PLANTED_MINED}'",
                head_summary=f"raised ValueError('{PLANTED_MINED}')",
                ai_narrative=f"The function used to return '{PLANTED_MINED}' verbatim.",
            )
            for d in t.divergences
        )
        reason = (
            t.reason_detail
            if t.reason_detail is None
            else f"`inner` is a closure over '{PLANTED_MINED}'"
        )
        targets.append(dataclasses.replace(t, divergences=divergences, reason_detail=reason))
    return dataclasses.replace(bundle, targets=tuple(targets), repro_scripts=scripts)


def _bundle_zip_with_planted_source(api) -> bytes:
    return api.zip_bytes(_planted_bundle(api))


def _member_texts(zip_bytes: bytes) -> dict[str, str]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return {n: archive.read(n).decode("utf-8", errors="replace") for n in archive.namelist()}


def test_default_policy_strips_all_source(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    assert source_sharing_enabled() is False
    original = _bundle_zip_with_planted_source(api)
    texts = _member_texts(original).values()
    assert any(PLANTED_SOURCE in text for text in texts), "the plant must exist before stripping"
    assert any(PLANTED_MINED in text for text in texts), "the mined plant must exist too"

    stripped = strip_source_for_sync(original)
    for name, text in _member_texts(stripped).items():
        assert PLANTED_SOURCE not in text, f"source text crossed the boundary in {name}"
        assert PLANTED_MINED not in text, f"a mined source literal crossed in {name} (finding 4)"

    bundle = parse_bundle_zip(stripped)  # still a valid, ingestible bundle
    for target in bundle.targets:
        for d in target.divergences:
            assert d.repro_filename in bundle.repro_scripts, "filenames survive for integrity"
    assert all("stripped" in body for body in bundle.repro_scripts.values())


def test_structure_survives_stripping(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verdicts, counts, classes, severities — the evidence STRUCTURE — must survive; the
    string-bearing fields become deterministic short-hash placeholders."""
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    original = parse_bundle_zip(_bundle_zip_with_planted_source(api))
    stripped = parse_bundle_zip(strip_source_for_sync(_bundle_zip_with_planted_source(api)))
    assert stripped.manifest == original.manifest
    assert len(stripped.targets) == len(original.targets)
    for before, after in zip(original.targets, stripped.targets, strict=True):
        assert after.verdict is before.verdict
        assert after.reason_code is before.reason_code
        assert after.classification is before.classification
        assert (after.inputs_run, after.equivalent_inputs, after.unprovable_inputs) == (
            before.inputs_run,
            before.equivalent_inputs,
            before.unprovable_inputs,
        )
        assert after.changed_line_coverage == before.changed_line_coverage
        for b, a in zip(before.divergences, after.divergences, strict=True):
            assert a.divergence_class is b.divergence_class
            assert a.severity is b.severity
            assert a.repro_filename == b.repro_filename
            assert a.minimized_args is not None and a.minimized_kwargs is not None
            for literal in (a.args_literal, a.kwargs_literal, a.minimized_args):
                assert _PLACEHOLDER.fullmatch(literal), f"not a placeholder: {literal!r}"
            assert len(a.shrink_path) == len(b.shrink_path), "shrink structure is preserved"
            for step in a.shrink_path:
                assert _PLACEHOLDER.fullmatch(step)


def test_stripped_bundle_ingests_end_to_end(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    stripped = strip_source_for_sync(_bundle_zip_with_planted_source(api))
    run_id = api.create_run_for(parse_bundle_zip(stripped))
    assert api.upload_zip(run_id, stripped).status_code == 200, (
        "a stripped bundle must still pass real server ingest"
    )


def test_strip_is_deterministic_and_idempotent(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    original = _bundle_zip_with_planted_source(api)
    once = strip_source_for_sync(original)
    assert strip_source_for_sync(original) == once, "same input, same wire bytes"
    assert strip_source_for_sync(once) == once, (
        "placeholders must not be re-hashed into new placeholders"
    )


def test_opt_in_passes_bytes_through_untouched(api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEMPEST_SYNC_SHARE_SOURCE", "1")
    assert source_sharing_enabled() is True
    original = _bundle_zip_with_planted_source(api)
    assert strip_source_for_sync(original) == original, "opt-in sharing is byte-exact"


def test_wire_bytes_are_wall_clock_independent(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Delta-sync hashes the zip CONTAINER, so it must be a pure function of bundle content.
    Zip entry timestamps have 2-second granularity — the sleep forces the two strips across a
    timestamp boundary, which is exactly how Linux CI caught the mtime leak this test pins."""
    import time

    monkeypatch.delenv("TEMPEST_SYNC_SHARE_SOURCE", raising=False)
    original = _bundle_zip_with_planted_source(api)
    first = strip_source_for_sync(original)
    time.sleep(2.1)
    second = strip_source_for_sync(original)
    assert first == second, "same content seconds apart must produce identical wire bytes"
