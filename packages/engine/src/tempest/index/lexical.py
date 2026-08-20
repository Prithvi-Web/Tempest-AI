"""The lexical/vector index — retrieval over what a symbol is CALLED and what it SAYS.

**What "vector" honestly means here.** F13 names sqlite-vec or LanceDB with a local embedding
model. Neither is available to this build: both are native extensions that would have to be built
for three platforms and loaded inside a frozen PyInstaller binary, and an embedding model is a
download the app does not make and cannot make offline (L23). So the space is built from the text
itself — word tokens and character trigrams — and scored with BM25 over an inverted index. That
is a real vector space with a deterministic, dependency-free embedding, and it is described that
way rather than being called something it is not. Swapping in a learned embedding is a change of
`document_terms`, and the seam is deliberately that narrow (ADR-0054).

**Why trigrams as well as words.** A question says "refund rounding" and the code says
`round_refund_amount`. Word tokens catch that only after splitting identifiers, which this module
does; trigrams catch the rest — misspellings, partial names, `refnd`. They are stored in the same
inverted index under a `3:` prefix so one scorer serves both, and so the index has one shape.

**No model is in this path.** Retrieval is arithmetic over stored counts. A model may later put
prose around an answer; it may not choose the answer (L17).
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

#: BM25's two knobs, at the values the literature settles on for short documents. They are named
#: rather than inlined because a future measurement may move them, and a magic 1.2 in an
#: expression is a number nobody can argue with.
_K1 = 1.2
_B = 0.75

#: Trigram terms are worth less than word terms: they fire constantly and a match on `ref` is
#: weaker evidence than a match on `refund`. Measured only in the sense that the retrieval
#: benchmark is the thing that would go red if this were wrong.
_TRIGRAM_WEIGHT = 0.35

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: Words that carry no retrieval signal in a codebase and appear in nearly every docstring.
# fmt: off
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "to", "was", "were", "will", "with", "this", "these", "those",
    # Not English stop words: identifiers that appear in nearly every Python symbol and
    # therefore separate nothing.
    "self", "cls", "return", "returns", "none", "true", "false",
})
# fmt: on


def words(text: str) -> list[str]:
    """Identifier-aware tokens: `round_refund_amount` and `roundRefundAmount` both become
    ["round", "refund", "amount"], lowercased, with stop words dropped."""
    out: list[str] = []
    for match in _WORD.finditer(text):
        for piece in _CAMEL.sub(" ", match.group(0)).replace("_", " ").split():
            lowered = piece.lower()
            if lowered and lowered not in _STOP and not lowered.isdigit():
                out.append(lowered)
    return out


def trigrams(text: str) -> list[str]:
    """Character trigrams over the identifier text, prefixed so they share the inverted index."""
    flat = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    out: list[str] = []
    for token in flat.split():
        padded = f" {token} "
        out.extend(f"3:{padded[i : i + 3]}" for i in range(len(padded) - 2))
    return out


def document_terms(*, qualname: str, signature: str, doc: str, text: str) -> Counter[str]:
    """The term counts for one symbol.

    The name is counted three times over. That is not a hack: a symbol's name is the single
    strongest statement about what it is for, a docstring is the second, and the body is a long
    tail of things it happens to mention. Weighting them equally makes a 200-line function that
    says `refund` once outrank the function actually named `refund`.
    """
    counts: Counter[str] = Counter()
    counts.update(words(qualname) * 3)
    counts.update(words(signature))
    counts.update(words(doc))
    counts.update(words(text))
    counts.update(trigrams(qualname))
    return counts


def index_symbol(conn: sqlite3.Connection, symbol_id: int, counts: Counter[str]) -> None:
    conn.execute("DELETE FROM terms WHERE symbol_id = ?", (symbol_id,))
    conn.executemany(
        "INSERT INTO terms (symbol_id, term, count) VALUES (?, ?, ?)",
        [(symbol_id, term, count) for term, count in sorted(counts.items())],
    )
    total = sum(counts.values())
    conn.execute(
        "INSERT OR REPLACE INTO lengths (symbol_id, tokens, norm) VALUES (?, ?, ?)",
        (symbol_id, total, math.sqrt(sum(c * c for c in counts.values())) or 1.0),
    )


@dataclass(frozen=True)
class Scored:
    symbol_id: int
    score: float


def search(conn: sqlite3.Connection, question: str, *, limit: int = 10) -> list[Scored]:
    """BM25 over the inverted index. Touches only symbols that share a term with the question.

    The candidate set is what keeps this fast on a large repository: a query never scores a symbol
    it has no term in common with, so cost is proportional to the postings of the query's terms
    rather than to the size of the index.
    """
    # Trigrams come from the SURVIVING words, not from the raw question. Taking them from the
    # raw text let "the and of" match a symbol through the character shapes of its stop words —
    # a question with no content retrieving something is worse than retrieving nothing.
    kept = words(question)
    query = Counter(kept)
    query.update(trigrams(" ".join(kept)))
    if not query:
        return []

    corpus = conn.execute("SELECT COUNT(*), COALESCE(AVG(tokens), 0) FROM lengths").fetchone()
    total_docs = int(corpus[0] or 0)
    if total_docs == 0:
        return []
    avg_len = float(corpus[1] or 1.0) or 1.0

    lengths = {int(r[0]): int(r[1]) for r in conn.execute("SELECT symbol_id, tokens FROM lengths")}
    scores: dict[int, float] = {}
    for term in query:
        rows = conn.execute("SELECT symbol_id, count FROM terms WHERE term = ?", (term,)).fetchall()
        if not rows:
            continue
        df = len(rows)
        idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
        weight = _TRIGRAM_WEIGHT if term.startswith("3:") else 1.0
        for symbol_id, count in rows:
            length = lengths.get(int(symbol_id), 1) or 1
            tf = float(count)
            contribution = idf * (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * length / avg_len))
            scores[int(symbol_id)] = scores.get(int(symbol_id), 0.0) + weight * contribution

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Scored(symbol_id=sid, score=score) for sid, score in ranked[:limit]]
