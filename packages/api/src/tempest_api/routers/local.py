"""Local prove endpoint: the desktop app points its bundled API at a repo on this machine —
no zip upload hop. The verdict still comes only from the engine's bundle (Law L2); this route
merely validates, creates the PENDING run, and hands it to the background prove thread."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tempest.prove import ProveConfig
from tempest_api.db.models import Run
from tempest_api.db.session import database_url, get_session
from tempest_api.demorepo import build_demo_repo
from tempest_api.errors import error_responses
from tempest_api.ledger import append_run_event
from tempest_api.localprove import (
    data_dir,
    local_run_out_dir,
    resolve_local_repo,
    spawn_prove_thread,
)
from tempest_api.routers.runs import get_or_create_repo
from tempest_api.schemas import LocalProveRequest, RunCreated, RunStatus

router = APIRouter(tags=["local"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/v1/local/prove",
    status_code=202,
    operation_id="startLocalProve",
    responses=error_responses(400, 422),
)
async def start_local_prove(body: LocalProveRequest, session: SessionDep) -> RunCreated:
    """Validate repo + refs (400 REPO_NOT_FOUND / REF_NOT_FOUND), create the run, start the
    prove thread, and answer 202 — the UI polls `getRun` and `listRunEvents` from here."""
    repo_dir, base_sha, head_sha = await asyncio.to_thread(
        resolve_local_repo, body.repo_path, body.base, body.head
    )
    repo = await get_or_create_repo(session, repo_dir.name)
    run = Run(repo_id=repo.id, base_sha=base_sha, head_sha=head_sha, status=RunStatus.PENDING)
    session.add(run)
    await session.flush()
    await append_run_event(
        session,
        run.id,
        "local.started",
        stage="started",
        message=(
            f"local prove started for {repo_dir.name}: {body.base} ({base_sha[:12]}) "
            f"vs {body.head} ({head_sha[:12]}), budget {body.max_inputs} inputs"
        ),
        extra={"repo_path": str(repo_dir), "base_sha": base_sha, "head_sha": head_sha},
    )
    await session.commit()
    cfg = ProveConfig(
        repo=repo_dir,
        base=base_sha,
        head=head_sha,
        max_inputs=body.max_inputs,
        out=local_run_out_dir(run.id),
    )
    spawn_prove_thread(run.id, cfg, database_url())
    return RunCreated(run_id=run.id)


# Small on purpose: two tiny pure functions saturate quickly, and the demo's job is the
# first divergence in well under 90 s — depth belongs to the user's own repos.
_DEMO_MAX_INPUTS = 40


@router.post(
    "/v1/local/demo",
    status_code=202,
    operation_id="startDemoProve",
)
async def start_demo_prove(session: SessionDep) -> RunCreated:
    """Write a fresh demo repository and prove it — the Phase 18 activation path. The run it
    answers with is an ORDINARY run; only its repo (and this docstring) know it is a demo."""
    repo_dir, base_sha, head_sha = await asyncio.to_thread(build_demo_repo, data_dir() / "demo")
    repo = await get_or_create_repo(session, "tempest-demo")
    run = Run(repo_id=repo.id, base_sha=base_sha, head_sha=head_sha, status=RunStatus.PENDING)
    session.add(run)
    await session.flush()
    await append_run_event(
        session,
        run.id,
        "local.started",
        stage="started",
        message=(
            f"demo prove started: a fresh demo repository at {repo_dir.name}, "
            f"base ({base_sha[:12]}) vs head ({head_sha[:12]}), "
            f"budget {_DEMO_MAX_INPUTS} inputs — everything that follows is real evidence"
        ),
        extra={"repo_path": str(repo_dir), "base_sha": base_sha, "head_sha": head_sha},
    )
    await session.commit()
    cfg = ProveConfig(
        repo=repo_dir,
        base=base_sha,
        head=head_sha,
        max_inputs=_DEMO_MAX_INPUTS,
        out=local_run_out_dir(run.id),
    )
    spawn_prove_thread(run.id, cfg, database_url())
    return RunCreated(run_id=run.id)
