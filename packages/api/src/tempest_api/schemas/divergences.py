"""Divergence shapes, mirroring `DivergenceRecord` in docs/BUNDLE_SCHEMA.md field-for-field.

`minimized_args` / `minimized_kwargs` / `repro_filename` are non-optional here exactly as they
are NOT NULL in the database and required by the bundle writer — the whole pipeline refuses a
divergence without its evidence (Law L1).
"""

from pydantic import BaseModel

from tempest.model import DivergenceClass, Severity


class DivergenceSummary(BaseModel):
    id: int
    target_id: int
    divergence_class: DivergenceClass
    severity: Severity
    detail: str
    minimized_args: str
    minimized_kwargs: str


class DivergenceDetail(DivergenceSummary):
    run_id: int
    args_literal: str
    kwargs_literal: str
    shrink_path: list[str]
    base_summary: str
    head_summary: str
    repro_filename: str
