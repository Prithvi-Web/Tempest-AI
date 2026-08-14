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
