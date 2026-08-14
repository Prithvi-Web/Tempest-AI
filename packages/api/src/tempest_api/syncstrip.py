"""Redaction at the sync boundary (Phase 13, L9): source never crosses by default.

Repro scripts are user source (the engine renders them from the target's own code and
inputs). With the default policy they are replaced by a stub — filenames survive so bundle
integrity holds (a divergence must still reference an existing script) and the receiving
server ingests the bundle unchanged otherwise. `TEMPEST_SYNC_SHARE_SOURCE=1` is the explicit
org opt-in (pushed org policy proper arrives with Phase 14) and passes bytes through
untouched. The strip re-writes the zip with the engine's own writer, so a stripped bundle is
as deterministic as any other."""

import dataclasses
import io
import os
import tempfile
import zipfile
from pathlib import Path

from tempest.bundle.bundle import read_bundle, write_bundle

_STUB = (
    "# repro script stripped at the sync boundary — org source-sharing policy is OFF\n"
    "# (default; see docs/PRIVACY.md). Run the prove locally to regenerate it.\n"
)


def source_sharing_enabled() -> bool:
    return os.environ.get("TEMPEST_SYNC_SHARE_SOURCE") == "1"


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
        stripped = dataclasses.replace(
            bundle, repro_scripts=dict.fromkeys(bundle.repro_scripts, _STUB)
        )
        return write_bundle(stripped, Path(tmp) / "out").read_bytes()
