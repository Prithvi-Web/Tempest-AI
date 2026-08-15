"""Remaining API surfaces pinned directly: target/divergence endpoints (including the repro
download's filename sanitization), both search backends against real rows (FTS5 and the
ILIKE fallback — SQLite executes ILIKE, so the Postgres query shape runs for real), the
unknown-log-level filter miss, the non-SQLite app startup path (no store preparation, no
connection attempted), the dialect-aware JSON column type, hand-corrupted bundle zips
(zip-slip, missing manifest, unreadable manifest), and the devseed module entrypoint as a
real subprocess."""

import asyncio
import dataclasses
import io
import json
import sqlite3
import subprocess
import sys
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.ext.asyncio import AsyncSession

from tempest.model import DivergenceClass, Severity
from tempest_api.app import create_app
from tempest_api.db.models import Divergence, Target
from tempest_api.db.session import create_engine_and_factory
from tempest_api.db.types import JSONPayload
from tempest_api.errors import ApiError
from tempest_api.ingest import parse_bundle_zip
from tempest_api.routers.divergences import get_divergence, get_divergence_repro
from tempest_api.routers.search import (
    _fts_match_expression,
    _search_fts,
    _search_like,
    search_divergences,
)
from tempest_api.routers.targets import get_target


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    engine, factory = create_engine_and_factory()
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _searchable_bundle(api: Any, *, phrase: str, repro_filename: str = "clamp_0.py") -> Any:
    divergence = dataclasses.replace(
        api.make_divergence(0), detail=phrase, repro_filename=repro_filename
    )
    return api.make_bundle(targets=(api.make_target((divergence,)),))


class TestTargetsAndDivergences:
    def test_target_detail_and_404(self, api: Any) -> None:
        api.ingest(api.make_bundle())

        async def scenario() -> None:
            async with _session() as session:
                target_id = await session.scalar(
                    sa.select(Target.id).where(Target.qualname == "clamp")
                )
                assert target_id is not None
                detail = await get_target(target_id, session)
                assert detail.qualname == "clamp"
                assert len(detail.divergences) == 1
                assert detail.divergences[0].minimized_args == "(0,)"
                with pytest.raises(ApiError) as excinfo:
                    await get_target(999_999, session)
                assert excinfo.value.status_code == 404
                assert excinfo.value.code.value == "NOT_FOUND"

        asyncio.run(scenario())

    def test_divergence_detail_repro_download_and_404(self, api: Any) -> None:
        bundle = _searchable_bundle(
            api, phrase="sanitized names too", repro_filename="odd name!.py"
        )
        run_id = api.ingest(bundle)

        async def scenario() -> None:
            async with _session() as session:
                divergence_id = await session.scalar(sa.select(Divergence.id))
                assert divergence_id is not None
                detail = await get_divergence(divergence_id, session)
                assert detail.run_id == run_id
                assert detail.repro_filename == "odd name!.py"

                response = await get_divergence_repro(divergence_id, session)
                assert bytes(response.body).decode() == bundle.repro_scripts["odd name!.py"]
                disposition = response.headers["content-disposition"]
                assert 'filename="odd_name_.py"' in disposition, (
                    "header-unsafe characters must be sanitized, the script untouched"
                )

                for missing_call in (get_divergence, get_divergence_repro):
                    with pytest.raises(ApiError) as excinfo:
                        await missing_call(999_999, session)
                    assert excinfo.value.status_code == 404

        asyncio.run(scenario())


class TestSearchBackends:
    def test_fts_backend_and_router_dispatch(self, api: Any) -> None:
        run_id = api.ingest(_searchable_bundle(api, phrase="the accumulator frobnicates"))

        async def scenario() -> None:
            async with _session() as session:
                results = await search_divergences("frobnicates", session, limit=10)
                assert [h.run_id for h in results.hits] == [run_id]
                hit = results.hits[0]
                assert hit.qualname == "clamp"
                assert hit.divergence_class is DivergenceClass.RETURN_VALUE
                assert hit.severity is Severity.NORMAL
                assert "frobnicates" in hit.snippet

                empty = await search_divergences("!!! ---", session, limit=10)
                assert empty.hits == [], "operator junk tokenizes to nothing and hits nothing"

                direct = await _search_fts(session, _fts_match_expression("accumulator"), 10)
                assert [h.divergence_id for h in direct] == [hit.divergence_id]

        asyncio.run(scenario())

    def test_ilike_backend_matches_all_three_columns_case_insensitively(self, api: Any) -> None:
        """The Postgres fallback, executed for real: SQLite implements ILIKE, so the exact
        query shape runs against the same rows the FTS test uses."""
        divergence = dataclasses.replace(
            api.make_divergence(0),
            detail="detail speaks of WIDGETS",
            base_summary="base saw a gadget",
            head_summary="head saw a doodad",
        )
        run_id = api.ingest(api.make_bundle(targets=(api.make_target((divergence,)),)))

        async def scenario() -> None:
            async with _session() as session:
                for needle in ("widgets", "GADGET", "doodad"):
                    hits = await _search_like(session, needle, 10)
                    assert [h.run_id for h in hits] == [run_id], f"ILIKE must match {needle!r}"
                    assert hits[0].snippet.startswith("detail speaks")
                assert await _search_like(session, "zebra", 10) == []

        asyncio.run(scenario())


def test_unknown_log_level_is_a_filter_miss_not_a_500(
    api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    from tempest.obslog import get_logger

    get_logger("cov-test").info("a record that a bogus filter must not surface")
    assert api.get_json("/v1/logs", params={"level": "NOT_A_LEVEL"}) == []
    messages = [r["message"] for r in api.get_json("/v1/logs", params={"level": "INFO"})]
    assert any("bogus filter" in m for m in messages), "the record itself is really there"


def test_non_sqlite_database_skips_local_store_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Postgres URL takes the Alembic path (ADR-0009): startup must not run the SQLite
    store preparation — proven by the fact that no connection is ever attempted against this
    unreachable server (preparation would have to connect and would fail startup)."""
    monkeypatch.setenv(
        "TEMPEST_DATABASE_URL", "postgresql+asyncpg://tempest:nope@127.0.0.1:9/absent"
    )
    with TestClient(create_app()) as client:
        assert client.app.state.db_engine.dialect.name == "postgresql"  # type: ignore[attr-defined]


def test_json_payload_renders_jsonb_only_on_postgres() -> None:
    assert isinstance(JSONPayload().load_dialect_impl(PGDialect()), JSONB)
    sqlite_impl = JSONPayload().load_dialect_impl(SQLiteDialect())
    assert isinstance(sqlite_impl, sa.JSON) and not isinstance(sqlite_impl, JSONB)


def _zip_with(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buf.getvalue()


class TestCorruptBundleZips:
    def test_zip_slip_member_is_rejected(self) -> None:
        data = _zip_with({"manifest.json": "{}", "../escape.txt": "outside the extraction dir"})
        with pytest.raises(ApiError) as excinfo:
            parse_bundle_zip(data)
        assert excinfo.value.status_code == 400
        assert excinfo.value.code.value == "BUNDLE_INVALID"
        assert "unsafe path" in excinfo.value.message

    def test_zip_without_manifest_is_rejected(self) -> None:
        data = _zip_with({"targets.json": "[]"})
        with pytest.raises(ApiError) as excinfo:
            parse_bundle_zip(data)
        assert "no manifest.json" in excinfo.value.message

    def test_unreadable_manifest_is_rejected(self) -> None:
        data = _zip_with({"manifest.json": json.dumps({"schema_version": "not-an-int"})})
        with pytest.raises(ApiError) as excinfo:
            parse_bundle_zip(data)
        assert "manifest.json is unreadable" in excinfo.value.message


def test_devseed_module_entrypoint_builds_a_store(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tempest_api.devseed",
            "--data-dir",
            str(tmp_path / "seed"),
            "--runs",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    seeded = json.loads(result.stdout.strip().splitlines()[-1])
    assert seeded["runs"] == 2
    with sqlite3.connect(tmp_path / "seed" / "tempest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM divergences WHERE id = ?", (seeded["big_divergence_id"],)
            ).fetchone()[0]
            == 1
        )
