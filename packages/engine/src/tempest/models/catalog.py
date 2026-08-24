"""The curated local-model catalogue — DATA, beside `PROVIDERS` (ADR-0080 §3, §5).

Every row is a free, permissively licensed, ungated GGUF, and every row carries the four
things a user needs before spending gigabytes on it: what it is good at, what it costs in
disk and RAM, what licence it carries, and a hash that says the bytes are the bytes.

**The hashes and sizes here were verified against two independent sources** at authoring time
— the Hugging Face API's `lfs.oid` and the `x-linked-etag` response header on the resolve
URL — because a registry that ships a plausible-looking hash is worse than one that ships
none: it turns a verification failure into a silent pass.

Refreshing these rows is an upstream-merge-shaped obligation, not a background task. A model
repository that re-uploads a file changes its hash, and the download will REFUSE loudly rather
than install something nobody reviewed. That is the intended failure.

Small-first on purpose. The 0.6 B row exists so that a person on a laptop with a slow link can
have a working local model in a couple of minutes and decide whether they want a bigger one,
rather than committing to a 2.5 GB download to find out.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The single host these files come from. It lives here and nowhere else: `egress_check`'s
#: huggingface ledger is closed over this one constant, so a second hard-coded host anywhere
#: in the tree is a gate failure rather than an absorbed surprise (L32, ADR-0080 §7).
HUGGINGFACE_HOST = "huggingface.co"


@dataclass(frozen=True)
class CatalogEntry:
    """One downloadable model. Frozen: a catalogue row a caller can edit is not a catalogue."""

    #: Stable id, and the on-disk leaf. Kept lowercase-and-dashes so `safe_leaf` accepts it.
    id: str
    #: What a person sees.
    label: str
    #: One line, in plain words, about what it is FOR. Not benchmark scores.
    good_at: str
    #: SPDX identifier. Permissive only — see `_PERMISSIVE`.
    license: str
    #: The HF repository and the file inside it.
    repo: str
    filename: str
    #: Exact bytes, so a size can be shown BEFORE the spend (L21) and a truncated download
    #: is detectable without hashing the whole file.
    size_bytes: int
    #: Lowercase hex sha256 of the file's contents.
    sha256: str
    #: Honest guidance, not a hard gate: a machine with less will swap rather than refuse.
    ram_note: str

    @property
    def url(self) -> str:
        return f"https://{HUGGINGFACE_HOST}/{self.repo}/resolve/main/{self.filename}"

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1e9, 2)


#: Licences this catalogue may carry. A row outside this set is a build failure, not a
#: judgement call at review time: "free to download" and "free to use" are different claims,
#: and only the second one is the promise being made to the user here.
_PERMISSIVE = frozenset({"apache-2.0", "mit"})


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="qwen3-0.6b-q8",
        label="Qwen3 0.6B",
        good_at="Quick replies and simple edits. The fastest way to see a local model work.",
        license="apache-2.0",
        repo="Qwen/Qwen3-0.6B-GGUF",
        filename="Qwen3-0.6B-Q8_0.gguf",
        size_bytes=639_446_688,
        sha256="9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
        ram_note="Runs comfortably in about 2 GB of memory.",
    ),
    CatalogEntry(
        id="smollm3-3b-q4",
        label="SmolLM3 3B",
        good_at="General conversation and summarising, at a size most laptops handle.",
        license="apache-2.0",
        repo="ggml-org/SmolLM3-3B-GGUF",
        filename="SmolLM3-Q4_K_M.gguf",
        size_bytes=1_915_305_312,
        sha256="8334b850b7bd46238c16b0c550df2138f0889bf433809008cc17a8b05761863e",
        ram_note="Wants about 4 GB of memory free.",
    ),
    CatalogEntry(
        id="phi-4-mini-q4",
        label="Phi-4 Mini",
        good_at="Reasoning and step-by-step explanation for its size.",
        license="mit",
        repo="unsloth/Phi-4-mini-instruct-GGUF",
        filename="Phi-4-mini-instruct-Q4_K_M.gguf",
        size_bytes=2_491_874_272,
        sha256="88c00229914083cd112853aab84ed51b87bdf6b9ce42f532d8c85c7c63b1730a",
        ram_note="Wants about 6 GB of memory free.",
    ),
    CatalogEntry(
        id="qwen3-4b-instruct-q4",
        label="Qwen3 4B Instruct",
        good_at="Following instructions carefully; the strongest of these at writing code.",
        license="apache-2.0",
        repo="unsloth/Qwen3-4B-Instruct-2507-GGUF",
        filename="Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        size_bytes=2_497_281_120,
        sha256="3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
        ram_note="Wants about 6 GB of memory free.",
    ),
)


def entry_for(model_id: str) -> CatalogEntry | None:
    """The catalogue row with this id, or None. Never raises: an unknown id is a 404 to
    answer, not an exception to translate."""
    for entry in CATALOG:
        if entry.id == model_id:
            return entry
    return None
