"""Divergence search shapes (Phase 11 FTS)."""

from pydantic import BaseModel

from tempest.model import DivergenceClass, Severity


class SearchHit(BaseModel):
    divergence_id: int
    target_id: int
    run_id: int
    module: str
    qualname: str
    divergence_class: DivergenceClass
    severity: Severity
    snippet: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


class SymbolDivergence(BaseModel):
    """One divergence recorded against a symbol, carrying the symbol it was recorded FOR.

    `qualname` and `module` are on every hit deliberately: a bare identifier in an editor can
    match more than one recorded symbol (two classes with a `post` method), and a badge that
    said "3 divergences recorded here" without being able to name them would be over-claiming.
    """

    divergence_id: int
    target_id: int
    run_id: int
    module: str
    qualname: str
    divergence_class: DivergenceClass
    severity: Severity
    detail: str


class SymbolDivergences(BaseModel):
    """What Tempest has RECORDED for one symbol — the query the editor's risk badge needs.

    Deliberately NOT `SearchResults`. Free-text search answers "which divergences mention this
    string", over an FTS index built on `detail`, `base_summary` and `head_summary`; `qualname`
    is not in that index and never was. Every detail string the comparator emits is value-shaped
    ("return values differ", "stdout differs"), so asking that endpoint about a symbol name
    returned nothing for symbols Tempest had watched diverge — and the badge rendered
    "unmeasured", which is the failure looking exactly like the honest answer.
    """

    symbol: str
    hits: list[SymbolDivergence]
