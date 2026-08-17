"""Redaction at the sync boundary (Phase 13, L9): source never crosses by default.

Repro scripts are user source, and so are the source-derived strings in targets.json:
`args_literal`/`kwargs_literal`/`minimized_*`/`shrink_path` carry string constants MINED from
the repo (generate/mining.py), while the summaries and detail fields embed return values and
user exception text. With the default policy the scripts become a stub, every mined-literal
field becomes a deterministic short-hash placeholder (`[stripped:<sha12>]` — comparable
across pushes, reversible by nobody), and the summary/detail fields pass through the
redaction engine with their quoted spans hashed. Structure survives untouched: verdicts,
counts, classes, severities, and repro filenames — so a stripped bundle still passes
`parse_bundle_zip` and real server ingest. `TEMPEST_SYNC_SHARE_SOURCE=1` is the explicit org
opt-in (pushed org policy proper arrives with Phase 14) and passes bytes through untouched.
The strip re-writes the zip with the engine's own writer and hashes only content, so a
stripped bundle is as deterministic as any other — and stripping twice is a no-op."""

import dataclasses
import hashlib
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path

from tempest.bundle.bundle import DivergenceRecord, RunBundle, read_bundle, write_bundle
from tempest.redact import RedactionContext, production_context, redact_text

_STUB = (
    "# repro script stripped at the sync boundary — org source-sharing policy is OFF\n"
    "# (default; see docs/PRIVACY.md). Run the prove locally to regenerate it.\n"
)

_PLACEHOLDER = re.compile(r"\[stripped:[0-9a-f]{12}\]")
# A quoted span in a summary/detail string is where mined literals and user exception text
# live; DOTALL because captured values legitimately embed newlines.
_QUOTED = re.compile(r"(['\"])((?:(?!\1).)+)\1", re.DOTALL)


def source_sharing_enabled() -> bool:
    return os.environ.get("TEMPEST_SYNC_SHARE_SOURCE") == "1"


def _short_hash(value: str) -> str:
    """Deterministic, wall-clock-independent placeholder: same value, same hash — delta sync
    and cross-push comparison keep working; the value itself cannot be recovered."""
    return f"[stripped:{hashlib.sha256(value.encode()).hexdigest()[:12]}]"


def _stripped_literal(value: str) -> str:
    # Idempotent: an already-stripped placeholder must not be re-hashed into a new one.
    return value if _PLACEHOLDER.fullmatch(value) else _short_hash(value)


def _scrub_summary(text: str, context: RedactionContext) -> str:
    """Summaries/detail keep their sentence structure (the evidence framing) but lose every
    quoted span to a hash, on top of a full redaction-engine pass."""

    def _hash_quoted(match: re.Match[str]) -> str:
        quote, body = match.group(1), match.group(2)
        if _PLACEHOLDER.fullmatch(body):
            return match.group(0)
        return f"{quote}{_short_hash(body)}{quote}"

    return _QUOTED.sub(_hash_quoted, redact_text(text, context))


def _strip_divergence(d: DivergenceRecord, context: RedactionContext) -> DivergenceRecord:
    # Writer-enforced integrity (spec §7) guarantees minimized fields on every stored bundle;
    # the assert narrows the Optional types.
    assert d.minimized_args is not None and d.minimized_kwargs is not None
    return dataclasses.replace(
        d,
        detail=_scrub_summary(d.detail, context),
        args_literal=_stripped_literal(d.args_literal),
        kwargs_literal=_stripped_literal(d.kwargs_literal),
        minimized_args=_stripped_literal(d.minimized_args),
        minimized_kwargs=_stripped_literal(d.minimized_kwargs),
        shrink_path=tuple(_stripped_literal(step) for step in d.shrink_path),
        base_summary=_scrub_summary(d.base_summary, context),
        head_summary=_scrub_summary(d.head_summary, context),
        # ADR-0029: the narrative PARAPHRASES observed values — under source-strip it is
        # dropped whole (a paraphrase cannot be reliably scrubbed span-by-span; L9).
        ai_narrative=None,
    )


def _strip_bundle(bundle: RunBundle) -> RunBundle:
    context = production_context()
    targets = tuple(
        dataclasses.replace(
            target,
            reason_detail=(
                None
                if target.reason_detail is None
                else _scrub_summary(target.reason_detail, context)
            ),
            divergences=tuple(_strip_divergence(d, context) for d in target.divergences),
        )
        for target in bundle.targets
    )
    return dataclasses.replace(
        bundle, targets=targets, repro_scripts=dict.fromkeys(bundle.repro_scripts, _STUB)
    )


def strip_source_for_sync(zip_bytes: bytes) -> bytes:
    """The only path by which bundle bytes may leave this machine (sync push)."""
    if source_sharing_enabled():
        return zip_bytes
    with tempfile.TemporaryDirectory(prefix="tempest-sync-strip-") as tmp:
        src = Path(tmp) / "in"
        src.mkdir()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            archive.extractall(src)  # trusted local bytes: our own store, not an upload
        bundle = read_bundle(src)
        return write_bundle(_strip_bundle(bundle), Path(tmp) / "out").read_bytes()
