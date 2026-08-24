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

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

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
    #: Where this row's bytes come from, when it is NOT the recorded model host. `None` on
    #: every shipped row — the only thing that sets it is `_dev_entry`, and only to a loopback
    #: address. It exists so the e2e suite can drive a real download through the real UI
    #: without a shipped row ever pointing anywhere but `HUGGINGFACE_HOST`.
    base_url: str | None = None

    @property
    def url(self) -> str:
        base = self.base_url or f"https://{HUGGINGFACE_HOST}"
        return f"{base}/{self.repo}/resolve/main/{self.filename}"

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1e9, 2)


#: Licences this catalogue may carry. A row outside this set is a build failure, not a
#: judgement call at review time: "free to download" and "free to use" are different claims,
#: and only the second one is the promise being made to the user here.
#:
#: **This was widened once, to admit Llama and Gemma, and the widening was REVERTED** — owner
#: decision, 24 Aug 2026: nothing that is not open source ships in this list. Meta's Llama
#: Community Licence and Google's Gemma Terms are freely downloadable but carry conditions
#: (acceptable-use policies, and in Llama's case a user-count threshold), which makes them
#: open WEIGHTS, not open SOURCE. Listing them inside a product would put those conditions on
#: the product's users without their ever having read them. The argument for widening was that
#: excluding them sends people elsewhere; the answer is that "somewhere else lists them too"
#: has never been a licence.
#:
#: Two properties every row must have, both checked against Hugging Face's own metadata when
#: the row is authored, never from memory: an OSI-permissive `license`, and `gated: false` —
#: a model behind an access request is not one a user with no account can fetch.
_PERMISSIVE = frozenset({"apache-2.0", "mit"})


CATALOG: tuple[CatalogEntry, ...] = (
    # Smallest first, on purpose: someone on a slow link can have a working local model in a
    # couple of minutes and decide whether they want a bigger one, rather than committing to
    # five gigabytes to find out. Every licence below was read from Hugging Face's own
    # metadata at authoring time, not from memory — DeepSeek's distill declares apache-2.0
    # there, which is not what a confident guess would have written.
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
        id="deepseek-r1-distill-qwen-1.5b-q4",
        label="DeepSeek-R1 Distill 1.5B",
        good_at="Showing its working. A reasoning model small enough to stay quick.",
        license="apache-2.0",
        repo="unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        filename="DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        size_bytes=1_117_321_312,
        sha256="f3bdf9cf31dee4b57ae4e455a1cb0d01b5c2c1b50d72d3112141c195506c2840",
        ram_note="Wants about 3 GB of memory free.",
    ),
    CatalogEntry(
        id="qwen3-1.7b-q8",
        label="Qwen3 1.7B",
        good_at="One step up from the 0.6B for the same kind of work, and still fast.",
        license="apache-2.0",
        repo="Qwen/Qwen3-1.7B-GGUF",
        filename="Qwen3-1.7B-Q8_0.gguf",
        size_bytes=1_834_426_016,
        sha256="061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
        ram_note="Wants about 4 GB of memory free.",
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
    CatalogEntry(
        id="mistral-7b-instruct-v0.3-q4",
        label="Mistral 7B Instruct",
        good_at="Long-form writing and explanation. A well-known all-rounder.",
        license="apache-2.0",
        repo="bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        filename="Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        size_bytes=4_372_812_000,
        sha256="1270d22c0fbb3d092fb725d4d96c457b7b687a5f5a715abe1e818da303e562b6",
        ram_note="Wants about 8 GB of memory free.",
    ),
    CatalogEntry(
        id="qwen3-8b-q4",
        label="Qwen3 8B",
        good_at="The best answers here, and the slowest. Worth it on 16 GB or more.",
        license="apache-2.0",
        repo="Qwen/Qwen3-8B-GGUF",
        filename="Qwen3-8B-Q4_K_M.gguf",
        size_bytes=5_027_783_488,
        sha256="d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
        ram_note="Wants about 10 GB of memory free.",
    ),
)


# ── the e2e row ──────────────────────────────────────────────────────────────────────────────
#
# A download is the one thing in this feature that cannot be proven by unit tests alone: the
# question "does pressing Download in the real panel move a real progress bar and end with a
# real file" crosses the engine, boundary A, the host, boundary B, react-query's poll and the
# panel's own states. Answering it needs a row whose bytes come from somewhere a test can serve.
#
# TWO conditions, the same shape as `select_sandbox_for_repo`'s first-party rule (ADR-0008):
# `TEMPEST_DEV=1` in the environment AND an explicit loopback base URL. Either alone does
# nothing. A base that is not loopback REFUSES rather than falling back, because a silent
# fallback is how a misconfigured harness ends up quietly downloading from the real host.
#
# Loopback is not egress, so this adds no surface to `egress_check`'s check 8 ledger — and the
# integrity check stays fully live, because the row carries the real sha256 of the real bytes
# the peer serves. Nothing here weakens verification; it only changes where the bytes come from.

#: The dev payload, as a unit and a repeat count, so a peer in another language can produce the
#: same bytes without a hash being copied by hand anywhere. The bridge's peer builds the same
#: two values; if they ever disagree the download fails its real sha256 check, which is the
#: loud failure rather than a quiet one.
DEV_PAYLOAD_UNIT = b"tempest-e2e-gguf\n"
#: Deliberately larger than `download._CHUNK` (1 MiB), and by more than one whole chunk.
#:
#: The first cut of this row was 68 KB, which is smaller than a single read — so the whole
#: transfer arrived in ONE `response.read()` and progress went 0 → 100 with nothing in
#: between. A real 639 MB model produces 639 reports; a payload under the chunk size produces
#: one, so a spec written against it could not tell a working progress bar from a broken one.
#: 4.25 MiB is five reads: enough for the panel's 500 ms poll to observe movement.
DEV_PAYLOAD_REPEATS = 262_144
DEV_PAYLOAD = DEV_PAYLOAD_UNIT * DEV_PAYLOAD_REPEATS

#: Hosts a dev base URL may name. Anything else is refused.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DEV_MODEL_ID = "tempest-e2e-tiny"
DEV_BASE_ENV = "TEMPEST_DEV_MODEL_BASE"


class CatalogueMisconfigured(RuntimeError):
    """A dev catalogue base that will not be used, with the reason (L15.3)."""


def _dev_entry() -> CatalogEntry | None:
    """The e2e row, or None. Raises when the environment asks for something unsafe."""
    if os.environ.get("TEMPEST_DEV") != "1":
        return None
    base = os.environ.get(DEV_BASE_ENV, "").strip().rstrip("/")
    if not base:
        return None
    host = (urlsplit(base).hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise CatalogueMisconfigured(
            f"{DEV_BASE_ENV} is {base!r}, whose host {host!r} is not loopback. This variable "
            f"exists so a test can serve model bytes from this machine; pointing it anywhere "
            f"else would make Tempest fetch a model from an unaudited host, so it is refused "
            f"rather than ignored."
        )
    return CatalogEntry(
        id=DEV_MODEL_ID,
        label="Tempest E2E Tiny",
        good_at="Nothing at all — it exists so the download path can be tested for real.",
        license="apache-2.0",
        repo="tempest/e2e",
        filename="tiny.gguf",
        size_bytes=len(DEV_PAYLOAD),
        sha256=hashlib.sha256(DEV_PAYLOAD).hexdigest(),
        ram_note="Runs in no memory worth measuring.",
        base_url=base,
    )


def active_catalog() -> tuple[CatalogEntry, ...]:
    """Every row a caller may act on: the shipped catalogue, plus the e2e row when the two
    conditions above are both met. Every other caller reads THIS, not `CATALOG`, so the
    downloader, the job layer and the panel cannot disagree about what exists."""
    dev = _dev_entry()
    return CATALOG if dev is None else (*CATALOG, dev)


def entry_for(model_id: str) -> CatalogEntry | None:
    """The catalogue row with this id, or None. Never raises for an unknown id: that is a 404
    to answer, not an exception to translate. It DOES propagate a misconfigured dev base,
    because a caller that cannot be told which rows exist must not be told "not found"."""
    for entry in active_catalog():
        if entry.id == model_id:
            return entry
    return None
