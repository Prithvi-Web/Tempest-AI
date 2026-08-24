"""Local open-source models: the curated catalogue, and the fetch that installs one (ADR-0080).

This is the acquisition half of L18. "BYO inference" has always permitted a local model and
has never helped anyone obtain one; a `llama-server` on its default port already appears in
the picker through the `llamacpp` registry row and the catalog's live local probe, so what was
missing was never a second inference path — it was the download.

Nothing here talks to a model. `catalog` is data, `download` is bytes and a hash.
"""

from tempest.models.catalog import CATALOG, CatalogEntry, entry_for
from tempest.models.download import (
    DownloadCancelled,
    DownloadProgress,
    DownloadRefused,
    download_entry,
    installed_path,
    model_root,
    safe_leaf,
)

__all__ = [
    "CATALOG",
    "CatalogEntry",
    "DownloadCancelled",
    "DownloadProgress",
    "DownloadRefused",
    "download_entry",
    "entry_for",
    "installed_path",
    "model_root",
    "safe_leaf",
]
