"""Run lifecycle: create (202 + idempotency), cursor pagination, filters, event ledger."""

import sqlalchemy as sa


def _sha(n: int) -> str:
    return f"{n:040x}"


class TestCreateRun:
    def test_create_run_is_pending_202(self, api) -> None:
        run_id = api.create_run_id(repo="pyfix", base_sha=_sha(1), head_sha=_sha(2))
        run = api.get_json(f"/v1/runs/{run_id}")
        assert run["status"] == "PENDING"
        assert run["verdict"] is None
        assert run["targets"] == []
        assert run["target_count"] == 0
        assert run["repo"] == "pyfix"

    def test_idempotency_key_replays_the_same_response(self, api) -> None:
        first = api.create_run(
            repo="pyfix", base_sha=_sha(1), head_sha=_sha(2), idempotency_key="k-1"
        )
        second = api.create_run(
            repo="pyfix", base_sha=_sha(1), head_sha=_sha(2), idempotency_key="k-1"
        )
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()

    def test_idempotency_key_reuse_with_different_body_conflicts(self, api) -> None:
        api.create_run_id(repo="pyfix", base_sha=_sha(1), head_sha=_sha(2), idempotency_key="k-1")
        resp = api.create_run(
            repo="pyfix", base_sha=_sha(1), head_sha=_sha(9), idempotency_key="k-1"
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    def test_runs_without_keys_are_always_distinct(self, api) -> None:
        a = api.create_run_id(repo="pyfix", base_sha=_sha(1), head_sha=_sha(2))
        b = api.create_run_id(repo="pyfix", base_sha=_sha(1), head_sha=_sha(2))
        assert a != b


class TestListRuns:
    def test_pagination_walks_every_run_exactly_once(self, api) -> None:
        ids = [
            api.create_run_id(repo="pag", base_sha=_sha(i), head_sha=_sha(100 + i))
            for i in range(7)
        ]
        seen: list[int] = []
        page_sizes: list[int] = []
        cursor: str | None = None
        while True:
            params: dict[str, object] = {"limit": 3}
            if cursor is not None:
                params["cursor"] = cursor
            page = api.get_json("/v1/runs", params=params)
            seen.extend(r["id"] for r in page["items"])
            page_sizes.append(len(page["items"]))
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert page_sizes == [3, 3, 1]
        assert seen == sorted(ids, reverse=True)  # newest first, each id exactly once

    def test_filters_by_status_and_verdict(self, api) -> None:
        complete_id = api.ingest(api.make_bundle())
        pending_id = api.create_run_id(repo="other", base_sha=_sha(11), head_sha=_sha(12))

        by_status = api.get_json("/v1/runs", params={"status": "PENDING"})
        assert [r["id"] for r in by_status["items"]] == [pending_id]

        by_verdict = api.get_json("/v1/runs", params={"verdict": "DIVERGENT"})
        assert [r["id"] for r in by_verdict["items"]] == [complete_id]
        assert by_verdict["items"][0]["divergence_count"] == 1

        assert api.get_json("/v1/runs", params={"verdict": "ERROR"})["items"] == []


class TestRunEvents:
    def test_ledger_records_created_then_ingested(self, api) -> None:
        # No read endpoint until the SSE phase — the database file is the observable surface.
        run_id = api.ingest(api.make_bundle())
        engine = sa.create_engine(f"sqlite:///{api.db_path}")
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT seq, event_type FROM run_events WHERE run_id = :run_id ORDER BY seq"
                ),
                {"run_id": run_id},
            ).all()
        engine.dispose()
        assert [tuple(r) for r in rows] == [(1, "run.created"), (2, "bundle.ingested")]
