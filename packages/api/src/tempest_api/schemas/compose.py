"""F12 composer shapes — a change as rows, each row carrying the behaviour it is responsible for.

The third column is the whole feature, so the schema is built so a UI **cannot** render a row
without saying what the engine found. `verdict` is required and its vocabulary is the engine's
(L2); `reason` explains an `UNPROVEN` in words a person can act on. There is no nullable
"impact" field, because an optional column is a column a UI will eventually leave blank, and a
blank cell next to a code change reads as reassurance nobody produced.
"""

from pydantic import BaseModel, Field

from tempest.model import Verdict


class ComposeRequest(BaseModel):
    """Show me this change as rows, with `accepted` applied.

    `accepted=None` means "all of them" — the state the composer opens in. An empty LIST is a
    different request: it means the user has rejected everything, and the honest answer to that
    is a proof of the baseline against itself, not a proof of the whole diff.
    """

    repo_path: str = Field(min_length=1)
    base: str = Field(min_length=1, max_length=200)
    head: str = Field(min_length=1, max_length=200)
    accepted: list[str] | None = Field(
        default=None,
        description="hunk ids to include; null means every hunk",
    )
    max_inputs: int = Field(default=50, ge=1)


class HunkRow(BaseModel):
    """One row of the composer: what changed, and what the engine found it does."""

    id: str
    path: str
    summary: str
    #: The hunk's own patch, exactly as git produced it. Sent so the UI renders the same bytes
    #: `git apply` would take — a re-rendered diff is a diff git may decline to apply.
    patch: str
    accepted: bool
    verdict: Verdict
    qualnames: list[str]
    divergence_count: int
    changed_line_coverage: float
    #: Why this row is UNPROVEN, when it is. Empty for a row the engine could speak about.
    reason: str = ""


class ComposeView(BaseModel):
    """Every hunk in the change, plus what this particular selection was proved to do."""

    hunks: list[HunkRow]
    #: The commit the accepted subset was materialized as, and proved. Not the user's head:
    #: accepting three of ten hunks is a different change from the whole diff (ADR-0061).
    selection_head: str
    #: Hunks `git apply` refused on top of the accepted ones. Reported, never dropped.
    rejected_ids: list[str] = Field(default_factory=list)
    #: Which files this request re-executed, and which carried evidence forward from the
    #: previous selection. A reader is entitled to know which rows were run just now.
    reproved_paths: list[str] = Field(default_factory=list)
    carried_paths: list[str] = Field(default_factory=list)
    bundle_id: str = ""
