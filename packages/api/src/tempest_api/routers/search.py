"""Full-text search over divergences (Phase 11).

SQLite serves from the FTS5 index (`divergences_fts`, maintained by triggers in
`db.local_store`); Postgres falls back to ILIKE over the same three text columns. User input
is never passed to the FTS engine raw — it is re-tokenized into quoted terms, so operator
syntax cannot error or subvert the query.
"""

import re
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from tempest.model import DivergenceClass, Severity
from tempest_api.db.models import Divergence, Target
from tempest_api.db.session import get_session
from tempest_api.errors import error_responses
from tempest_api.schemas.search import SearchHit, SearchResults

router = APIRouter(tags=["search"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_SNIPPET_CHARS = 160

_FTS_QUERY = sa.text(
    "SELECT d.id AS divergence_id, d.target_id AS target_id, t.run_id AS run_id, "
    "t.module AS module, t.qualname AS qualname, "
    "d.divergence_class AS divergence_class, d.severity AS severity, "
    "snippet(divergences_fts, -1, '', '', '…', 24) AS snippet "
    "FROM divergences_fts "
    "JOIN divergences d ON d.id = divergences_fts.rowid "
    "JOIN targets t ON t.id = d.target_id "
    "WHERE divergences_fts MATCH :match ORDER BY rank LIMIT :limit"
)


def _fts_match_expression(q: str) -> str:
    """Quote every token so FTS5 operators/quotes in user input are literal text, never syntax."""
    return " ".join(f'"{token}"' for token in re.findall(r"\w+", q))


async def _search_fts(session: AsyncSession, match: str, limit: int) -> list[SearchHit]:
    rows = (await session.execute(_FTS_QUERY, {"match": match, "limit": limit})).mappings().all()
    return [
        SearchHit(
            divergence_id=row["divergence_id"],
            target_id=row["target_id"],
            run_id=row["run_id"],
            module=row["module"],
            qualname=row["qualname"],
            divergence_class=DivergenceClass(row["divergence_class"]),
            severity=Severity(row["severity"]),
            snippet=row["snippet"],
        )
        for row in rows
    ]


async def _search_like(session: AsyncSession, q: str, limit: int) -> list[SearchHit]:
    pattern = f"%{q}%"
    rows = (
        await session.execute(
            sa.select(Divergence, Target)
            .join(Target, Target.id == Divergence.target_id)
            .where(
                sa.or_(
                    Divergence.detail.ilike(pattern),
                    Divergence.base_summary.ilike(pattern),
                    Divergence.head_summary.ilike(pattern),
                )
            )
            .order_by(Divergence.id.asc())
            .limit(limit)
        )
    ).all()
    return [
        SearchHit(
            divergence_id=divergence.id,
            target_id=divergence.target_id,
            run_id=target.run_id,
            module=target.module,
            qualname=target.qualname,
            divergence_class=divergence.divergence_class,
            severity=divergence.severity,
            snippet=divergence.detail[:_SNIPPET_CHARS],
        )
        for divergence, target in rows
    ]


@router.get(
    "/v1/search/divergences",
    operation_id="searchDivergences",
    responses=error_responses(422),
)
async def search_divergences(
    q: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SearchResults:
    """Index-backed text search across divergence details and base/head summaries."""
    if session.get_bind().dialect.name == "sqlite":
        match = _fts_match_expression(q)
        hits = [] if not match else await _search_fts(session, match, limit)
    else:
        hits = await _search_like(session, q, limit)
    return SearchResults(query=q, hits=hits)
