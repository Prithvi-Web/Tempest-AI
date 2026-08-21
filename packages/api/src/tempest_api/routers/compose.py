"""F12's composer endpoint: a change as rows, each proved for the selection it belongs to.

One route, and it is synchronous on purpose. `startLocalProve` is 202-and-poll because a full
proof of a real repository is a minutes-long job with progress worth streaming; a composer toggle
is a sub-second incremental re-proof (ADR-0061) and a poll loop around it would add more latency
than it hides. The work still runs in a thread, so the sidecar's event loop is never blocked.

**The row and the verdict are produced together, by one call.** Splitting them into "list hunks"
and "get impact" would let a UI render rows before the evidence arrived, and a row on screen with
an empty third column is exactly the blank this feature exists to remove.
"""

import asyncio

from fastapi import APIRouter

from tempest.compose import compose as compose_mod
from tempest.prove import ProveConfig, run_prove
from tempest_api.errors import error_responses
from tempest_api.localprove import resolve_local_repo
from tempest_api.schemas import ComposeRequest, ComposeView, HunkRow

router = APIRouter(tags=["compose"])

#: The branch name every composer selection is materialized under. One per repository is enough:
#: a selection is a scratch tree that only ever answers the request that built it, and keeping
#: them would leave a worktree per keystroke.
_SELECTION = "composer"


def _build(body: ComposeRequest) -> ComposeView:
    repo, base_sha, head_sha = resolve_local_repo(body.repo_path, body.base, body.head)
    hunks = compose_mod.hunks_for(repo, base_sha, head_sha)
    wanted = set(body.accepted) if body.accepted is not None else {h.id for h in hunks}
    accepted = tuple(h for h in hunks if h.id in wanted)

    selection = compose_mod.apply_selection(repo, base_sha, accepted, _SELECTION)
    proved = run_prove(
        ProveConfig(repo=repo, base=base_sha, head=selection.head, max_inputs=body.max_inputs)
    )

    # Attribution reads the HEAD REVISION the user is composing from — not the working tree and
    # not the selection's tree. A row names the change the user is deciding about, even when this
    # selection did not include it, and a hunk's line numbers only mean anything against head.
    sources = compose_mod.sources_at(repo, head_sha, tuple(h.path for h in hunks))

    impacts = compose_mod.impact(hunks, proved.bundle.targets, sources)
    rejected = {h.id for h in selection.rejected_by_git}
    return ComposeView(
        hunks=[
            HunkRow(
                id=i.hunk.id,
                path=i.hunk.path,
                summary=i.hunk.summary,
                patch=i.hunk.patch,
                accepted=i.hunk.id in wanted and i.hunk.id not in rejected,
                verdict=i.verdict,
                qualnames=list(i.qualnames),
                divergence_count=i.divergence_count,
                changed_line_coverage=i.changed_line_coverage,
                reason=i.reason,
            )
            for i in impacts
        ],
        selection_head=selection.head,
        rejected_ids=sorted(rejected),
        reproved_paths=sorted({t.file_path for t in proved.bundle.targets}),
        carried_paths=[],
        bundle_id=(
            f"{proved.bundle.manifest.base_sha[:12]}..{proved.bundle.manifest.head_sha[:12]}"
        ),
    )


@router.post(
    "/v1/local/compose",
    operation_id="composeChange",
    responses=error_responses(400, 422),
)
async def compose_change(body: ComposeRequest) -> ComposeView:
    """Split a change into hunks, prove the accepted subset, and return both together."""
    return await asyncio.to_thread(_build, body)
