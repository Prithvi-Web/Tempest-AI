"""Bench seeder: a real local store at bench scale (Phase 11).

`python -m tempest_api.devseed --data-dir <dir> --runs 10000` builds `<dir>/tempest.db` through
the production open path (WAL + stamp + FTS, `db.local_store`) and bulk-inserts `--runs`
completed runs plus one divergence carrying a ~5 MB observation payload. Prints a JSON line
with the ids the bench needs. Dev tooling — never shipped in the app manifest."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from tempest.model import DivergenceClass, Lang, Severity, TargetClassification, Verdict
from tempest_api.db.local_store import install_sqlite_pragmas, prepare_local_store
from tempest_api.db.models import Divergence, Repo, Run, Target, utcnow
from tempest_api.db.session import create_engine_and_factory
from tempest_api.schemas.enums import RunStatus

_FIVE_MB_SENTENCE = "observed payload diverges at byte offset %d under seeded input. "


def _five_mb_text() -> str:
    chunk = "".join(_FIVE_MB_SENTENCE % i for i in range(64))
    return chunk * (5 * 1024 * 1024 // len(chunk) + 1)


def _seed(conn: sa.Connection, runs: int) -> dict[str, Any]:
    conn.execute(sa.insert(Repo), [{"name": "bench-repo", "created_at": utcnow()}])
    repo_id = conn.execute(sa.select(Repo.id)).scalar_one()
    conn.execute(
        sa.insert(Run),
        [
            {
                "repo_id": repo_id,
                "base_sha": "a" * 40,
                "head_sha": f"{i:040x}",
                "status": RunStatus.COMPLETE,
                "verdict": Verdict.EQUIVALENT_UNDER_BUDGET,
                "created_at": utcnow(),
            }
            for i in range(runs)
        ],
    )
    last_run_id = conn.execute(sa.select(sa.func.max(Run.id))).scalar_one()
    target_pk = conn.execute(
        sa.insert(Target).values(
            run_id=last_run_id,
            position=0,
            file_path="bench.py",
            module="bench",
            qualname="payload",
            lang=Lang.PYTHON,
            classification=TargetClassification.PURE_CANDIDATE,
            verdict=Verdict.DIVERGENT,
            inputs_run=1,
            equivalent_inputs=0,
            unprovable_inputs=0,
            changed_line_coverage=1.0,
        )
    ).inserted_primary_key
    assert target_pk is not None
    divergence_pk = conn.execute(
        sa.insert(Divergence).values(
            target_id=target_pk[0],
            position=0,
            divergence_class=DivergenceClass.RETURN_VALUE,
            severity=Severity.NORMAL,
            detail=_five_mb_text(),
            args_literal="()",
            kwargs_literal="{}",
            minimized_args="()",
            minimized_kwargs="{}",
            shrink_path=[],
            base_summary="returned base payload",
            head_summary="returned head payload",
            repro_filename="bench_payload.py",
            repro_script="print('bench')\n",
        )
    ).inserted_primary_key
    assert divergence_pk is not None
    return {"runs": runs, "big_divergence_id": divergence_pk[0], "big_run_id": last_run_id}


async def _amain(data_dir: Path, runs: int) -> dict[str, Any]:
    data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{data_dir / 'tempest.db'}"
    engine, _ = create_engine_and_factory(url)
    try:
        install_sqlite_pragmas(engine)
        await prepare_local_store(engine)
        async with engine.begin() as conn:
            return await conn.run_sync(_seed, runs)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=10_000)
    args = parser.parse_args(argv)
    result = asyncio.run(_amain(args.data_dir.expanduser().resolve(), args.runs))
    json.dump(result, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
