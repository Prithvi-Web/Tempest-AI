"""Target shapes, mirroring `TargetRecord` in docs/BUNDLE_SCHEMA.md field-for-field."""

from pydantic import BaseModel

from tempest.model import Lang, ReasonCode, TargetClassification, Verdict
from tempest_api.schemas.divergences import DivergenceSummary


class TargetSummary(BaseModel):
    id: int
    run_id: int
    file_path: str
    module: str
    qualname: str
    lang: Lang
    classification: TargetClassification
    verdict: Verdict
    reason_code: ReasonCode | None
    changed_line_coverage: float
    divergence_count: int


class TargetDetail(TargetSummary):
    reason_detail: str | None
    inputs_run: int
    equivalent_inputs: int
    unprovable_inputs: int
    divergences: list[DivergenceSummary]
