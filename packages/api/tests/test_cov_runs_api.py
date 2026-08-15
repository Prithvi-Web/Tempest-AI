"""Run-endpoint behavior pinned by DIRECT calls on the real temp database.

The HTTP suite (test_runs_api, test_search_and_portability) already speaks to these endpoints
end to end; these tests call the same coroutines directly with a real AsyncSession on the same
SQLite file, pinning the handler-internal branches: idempotency replay/conflict including the
flush-time race (staged by a genuinely committed competing row, not a mock), the cursor walk
and its malformed-cursor rejection, status/verdict filters, import idempotency and rejection,
export error paths, upload 404, and cancel 404/409. Opaque-cursor codec errors are pinned here
too. No mocked layer anywhere (L4): every assertion follows real SQL against real constraints.
"""

import asyncio
import base64
import io
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tempest.model import Verdict
from tempest_api.db.local_store import install_sqlite_pragmas
from tempest_api.db.models import Repo, Run, RunEvent
from tempest_api.db.session import create_engine_and_factory
from tempest_api.errors import ApiError
from tempest_api.routers.runs import (
    cancel_run,
    create_run,
    export_run_bundle,
    get_or_create_repo,
    get_run,
    import_run_bundle,
    list_run_events,
    list_runs,
    upload_run_bundle,
)
from tempest_api.schemas import RunCreate, RunStatus, decode_cursor, encode_cursor


def _sha(n: int) -> str:
    return f"{n:040x}"


@asynccontextmanager
async def _session(*, foreign_keys: bool = False) -> AsyncIterator[AsyncSession]:
    """A real AsyncSession on the same file the app serves (TEMPEST_DATABASE_URL)."""
    engine, factory = create_engine_and_factory()
    if foreign_keys:
        install_sqlite_pragmas(engine)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _plant_competing_run(
    db_path: Path, *, repo: str, base_sha: str, head_sha: str, key: str
) -> int:
    """Commit a competing run through a SEPARATE connection — the real 'another request won
    the race' state, exactly what a concurrent create leaves behind."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with Session(engine) as s:
            planted_repo = s.scalar(sa.select(Repo).where(Repo.name == repo))
            if planted_repo is None:
                planted_repo = Repo(name=repo)
                s.add(planted_repo)
                s.flush()
            run = Run(
                repo_id=planted_repo.id,
                base_sha=base_sha,
                head_sha=head_sha,
                status=RunStatus.PENDING,
                idempotency_key=key,
            )
            s.add(run)
            s.commit()
            return run.id
    finally:
        engine.dispose()


class TestCreateRunIdempotency:
    def test_no_key_then_key_then_replay_then_conflict(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                body = RunCreate(repo="direct", base_sha=_sha(1), head_sha=_sha(2))
                keyless = await create_run(body, session)
                fresh = await create_run(body, session, idempotency_key="dk-1")
                assert fresh.run_id != keyless.run_id
                replay = await create_run(body, session, idempotency_key="dk-1")
                assert replay.run_id == fresh.run_id, "same key + same body replays the run_id"
                other = RunCreate(repo="direct", base_sha=_sha(1), head_sha=_sha(9))
                with pytest.raises(ApiError) as excinfo:
                    await create_run(other, session, idempotency_key="dk-1")
                assert excinfo.value.status_code == 409
                assert excinfo.value.code.value == "IDEMPOTENCY_CONFLICT"
                assert excinfo.value.details == {"existing_run_id": fresh.run_id}

        asyncio.run(scenario())

    def test_flush_time_race_replays_the_winner(self, api: Any) -> None:
        """A competing request lands the same key (and the same repo row) between the lookup
        and the flush: both IntegrityError recoveries — repo re-select and run replay — fire."""

        async def scenario() -> None:
            async with _session() as session:
                body = RunCreate(repo="race-repo", base_sha=_sha(3), head_sha=_sha(4))

                def sabotage(sync_session: Session, _ctx: object, _instances: object) -> None:
                    _plant_competing_run(
                        api.db_path,
                        repo="race-repo",
                        base_sha=_sha(3),
                        head_sha=_sha(4),
                        key="race-key",
                    )

                event.listen(session.sync_session, "before_flush", sabotage, once=True)
                result = await create_run(body, session, idempotency_key="race-key")
                winner = await session.scalar(
                    sa.select(Run).where(Run.idempotency_key == "race-key")
                )
                assert winner is not None and result.run_id == winner.id
                count = await session.scalar(
                    sa.select(sa.func.count(Run.id)).where(Run.idempotency_key == "race-key")
                )
                assert count == 1, "the loser must not have written a second run"

        asyncio.run(scenario())

    def test_flush_time_race_with_different_body_conflicts(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                body = RunCreate(repo="loser-repo", base_sha=_sha(5), head_sha=_sha(6))

                def sabotage(sync_session: Session, _ctx: object, _instances: object) -> None:
                    _plant_competing_run(
                        api.db_path,
                        repo="winner-repo",
                        base_sha=_sha(5),
                        head_sha=_sha(7),
                        key="fought-key",
                    )

                event.listen(session.sync_session, "before_flush", sabotage, once=True)
                with pytest.raises(ApiError) as excinfo:
                    await create_run(body, session, idempotency_key="fought-key")
                assert excinfo.value.status_code == 409
                assert excinfo.value.code.value == "IDEMPOTENCY_CONFLICT"

        asyncio.run(scenario())

    def test_keyless_integrity_error_is_reraised(self, api: Any) -> None:
        """An IntegrityError that is NOT an idempotency race (here: a genuine FK violation
        joining the same flush) must propagate, never be swallowed as a replay."""

        async def scenario() -> None:
            async with _session(foreign_keys=True) as session:
                flushes = {"n": 0}

                def poison(sync_session: Session, _ctx: object, _instances: object) -> None:
                    flushes["n"] += 1
                    if flushes["n"] == 2:  # after the repo flush, into the run's own flush
                        sync_session.add(
                            RunEvent(run_id=987_654, seq=1, event_type="poison", payload={})
                        )

                event.listen(session.sync_session, "before_flush", poison)
                body = RunCreate(repo="poisoned", base_sha=_sha(8), head_sha=_sha(9))
                with pytest.raises(IntegrityError):
                    await create_run(body, session, idempotency_key=None)
                event.remove(session.sync_session, "before_flush", poison)
                assert await session.scalar(sa.select(sa.func.count(Run.id))) == 0

        asyncio.run(scenario())


class TestGetOrCreateRepo:
    def test_existing_repo_is_returned_not_duplicated(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                first = await get_or_create_repo(session, "one-repo")
                await session.commit()
                again = await get_or_create_repo(session, "one-repo")
                assert again.id == first.id
                count = await session.scalar(
                    sa.select(sa.func.count(Repo.id)).where(Repo.name == "one-repo")
                )
                assert count == 1

        asyncio.run(scenario())

    def test_non_race_integrity_error_is_reraised(self, api: Any) -> None:
        """The flush fails for a reason that is NOT 'someone inserted this repo first' (a FK
        violation riding the same flush); the re-select finds nothing and the error propagates."""

        async def scenario() -> None:
            async with _session(foreign_keys=True) as session:

                def poison(sync_session: Session, _ctx: object, _instances: object) -> None:
                    sync_session.add(
                        RunEvent(run_id=987_654, seq=1, event_type="poison", payload={})
                    )

                event.listen(session.sync_session, "before_flush", poison, once=True)
                with pytest.raises(IntegrityError):
                    await get_or_create_repo(session, "never-created")
                assert (
                    await session.scalar(sa.select(Repo).where(Repo.name == "never-created"))
                ) is None

        asyncio.run(scenario())


class TestListRuns:
    def test_cursor_walk_filters_and_malformed_cursor(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                ids = []
                for i in range(5):
                    body = RunCreate(repo="walk", base_sha=_sha(i), head_sha=_sha(100 + i))
                    ids.append((await create_run(body, session)).run_id)

                seen: list[int] = []
                sizes: list[int] = []
                cursor: str | None = None
                while True:
                    page = await list_runs(session, cursor=cursor, limit=2)
                    seen.extend(r.id for r in page.items)
                    sizes.append(len(page.items))
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                assert sizes == [2, 2, 1]
                assert seen == sorted(ids, reverse=True), "newest first, each exactly once"

                with pytest.raises(ApiError) as excinfo:
                    await list_runs(session, cursor="not-a-cursor!", limit=2)
                assert excinfo.value.status_code == 400
                assert excinfo.value.code.value == "VALIDATION_ERROR"

                pending = await list_runs(session, status=RunStatus.PENDING, limit=100)
                assert {r.id for r in pending.items} == set(ids)
                assert (await list_runs(session, status=RunStatus.COMPLETE, limit=5)).items == []
                assert (await list_runs(session, verdict=Verdict.ERROR, limit=5)).items == []

        asyncio.run(scenario())

    def test_verdict_filter_matches_ingested_run(self, api: Any) -> None:
        divergent_id = api.ingest(api.make_bundle())

        async def scenario() -> None:
            async with _session() as session:
                page = await list_runs(session, verdict=Verdict.DIVERGENT, limit=5)
                assert [r.id for r in page.items] == [divergent_id]
                assert page.items[0].divergence_count == 1

        asyncio.run(scenario())


class TestRunDetailAndEvents:
    def test_get_run_found_and_missing(self, api: Any) -> None:
        run_id = api.ingest(api.make_bundle())

        async def scenario() -> None:
            async with _session() as session:
                detail = await get_run(run_id, session)
                assert detail.id == run_id
                assert detail.verdict is Verdict.DIVERGENT
                assert [t.qualname for t in detail.targets] == ["clamp", "closure.inner"]
                with pytest.raises(ApiError) as excinfo:
                    await get_run(999_999, session)
                assert excinfo.value.status_code == 404

        asyncio.run(scenario())

    def test_events_ledger_and_missing_run(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                body = RunCreate(repo="ledgered", base_sha=_sha(11), head_sha=_sha(12))
                run_id = (await create_run(body, session)).run_id
                events = await list_run_events(run_id, session)
                assert [e.stage for e in events] == ["created"]
                assert "ledgered" in events[0].message
                with pytest.raises(ApiError) as excinfo:
                    await list_run_events(999_999, session)
                assert excinfo.value.status_code == 404

        asyncio.run(scenario())


def _upload(data: bytes, filename: str | None = "run.tempest.zip") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data"


class TestImportRunBundle:
    def test_import_is_idempotent_by_digest(self, api: Any, data_dir: Path) -> None:
        bundle = api.make_bundle()
        data = api.zip_bytes(bundle)

        async def scenario() -> None:
            async with _session() as session:
                first = await import_run_bundle(_upload(data, filename=None), session)
                assert first.repo == bundle.manifest.repo
                assert first.verdict is Verdict.DIVERGENT
                assert len(first.targets) == 2
                second = await import_run_bundle(_upload(data), session)
                assert second.id == first.id, "same bytes → the run that already holds them"

        asyncio.run(scenario())

    def test_import_rejects_garbage_before_any_row(self, api: Any, data_dir: Path) -> None:
        async def scenario() -> None:
            async with _session() as session:
                with pytest.raises(ApiError) as excinfo:
                    await import_run_bundle(_upload(b"not a zip"), session)
                assert excinfo.value.status_code == 400
                assert excinfo.value.code.value == "BUNDLE_INVALID"
                assert await session.scalar(sa.select(sa.func.count(Run.id))) == 0

        asyncio.run(scenario())


class TestExportRunBundle:
    def test_export_error_paths_and_byte_identity(self, api: Any, data_dir: Path) -> None:
        bundle = api.make_bundle()
        data = api.zip_bytes(bundle)

        async def scenario() -> None:
            async with _session() as session:
                with pytest.raises(ApiError) as excinfo:
                    await export_run_bundle(999_999, session)
                assert excinfo.value.status_code == 404

                pending = (
                    await create_run(
                        RunCreate(repo="no-bundle", base_sha=_sha(21), head_sha=_sha(22)),
                        session,
                    )
                ).run_id
                with pytest.raises(ApiError) as excinfo:
                    await export_run_bundle(pending, session)
                assert excinfo.value.status_code == 404
                assert "no stored bundle" in excinfo.value.message

                run_id = (
                    await create_run(
                        RunCreate(
                            repo=bundle.manifest.repo,
                            base_sha=bundle.manifest.base_sha,
                            head_sha=bundle.manifest.head_sha,
                        ),
                        session,
                    )
                ).run_id
                await upload_run_bundle(run_id, _upload(data), session)
                response = await export_run_bundle(run_id, session)
                assert response.body == data, "export is byte-identical to the ingest (L7)"
                assert response.media_type == "application/zip"
                assert f"run-{run_id}.tempest.zip" in response.headers["content-disposition"]

                run = await session.get(Run, run_id)
                assert run is not None
                run.bundle_digest = "0" * 64  # the blob for this digest does not exist
                await session.commit()
                with pytest.raises(ApiError) as excinfo:
                    await export_run_bundle(run_id, session)
                assert excinfo.value.status_code == 404
                assert "missing from the store" in excinfo.value.message

        asyncio.run(scenario())


class TestUploadAndCancel:
    def test_upload_to_missing_run_is_404(self, api: Any, data_dir: Path) -> None:
        data = api.zip_bytes(api.make_bundle())

        async def scenario() -> None:
            async with _session() as session:
                with pytest.raises(ApiError) as excinfo:
                    await upload_run_bundle(999_999, _upload(data), session)
                assert excinfo.value.status_code == 404
                assert "create it" in excinfo.value.message

        asyncio.run(scenario())

    def test_cancel_missing_run_404_and_idle_run_409(self, api: Any) -> None:
        async def scenario() -> None:
            async with _session() as session:
                with pytest.raises(ApiError) as excinfo:
                    await cancel_run(999_999, session)
                assert excinfo.value.status_code == 404

                idle = (
                    await create_run(
                        RunCreate(repo="idle", base_sha=_sha(31), head_sha=_sha(32)), session
                    )
                ).run_id
                with pytest.raises(ApiError) as excinfo:
                    await cancel_run(idle, session)
                assert excinfo.value.status_code == 409
                assert excinfo.value.code.value == "RUN_NOT_ACTIVE"

        asyncio.run(scenario())


class TestCursorCodec:
    def test_round_trip_and_malformed_cursors(self) -> None:
        assert decode_cursor(encode_cursor(42)) == 42
        with pytest.raises(ValueError, match="malformed cursor"):
            decode_cursor("a")  # not decodable base64
        with pytest.raises(ValueError, match="malformed cursor"):
            decode_cursor(base64.urlsafe_b64encode(b"nope").decode())  # missing v1: prefix
        with pytest.raises(ValueError, match="malformed cursor"):
            decode_cursor(base64.urlsafe_b64encode(b"v1:xyz").decode())  # non-integer id
