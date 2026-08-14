"""FTS over divergences + portable `.tempest` import/export (Phase 11).

Search is index-backed (SQLite FTS5, kept in sync by triggers — pruned runs leave the index),
and a run's bundle can be exported byte-identical to what was ingested (L7) and imported on
another machine, idempotently by content digest.
"""

import dataclasses
import hashlib
import sqlite3
from pathlib import Path

import pytest


def _searchable_bundle(api, *, phrase: str, repo: str = "searchable", head: str = "f" * 40):
    divergence = dataclasses.replace(api.make_divergence(0), detail=phrase)
    target = api.make_target((divergence,))
    return api.make_bundle(targets=(target,), repo=repo, head_sha=head)


def _hits(api, query: str):
    return api.get_json("/v1/search/divergences", params={"q": query})["hits"]


class TestDivergenceSearch:
    def test_search_finds_divergences_by_text(self, api) -> None:
        bundle = _searchable_bundle(api, phrase="the accumulator frobnicates on negative input")
        run_id = api.ingest(bundle)

        hits = _hits(api, "frobnicates")
        assert len(hits) == 1
        hit = hits[0]
        assert hit["run_id"] == run_id
        assert hit["qualname"] == "clamp"
        assert "frobnicates" in hit["snippet"]

        assert _hits(api, "zebra") == []

    def test_search_matches_summaries_too(self, api) -> None:
        divergence = dataclasses.replace(
            api.make_divergence(0), base_summary="returned the sentinel VALUE_XYZZY"
        )
        bundle = api.make_bundle(targets=(api.make_target((divergence,)),), repo="summaries")
        api.ingest(bundle)
        assert len(_hits(api, "XYZZY")) == 1

    def test_search_survives_fts_operator_junk(self, api) -> None:
        api.ingest(_searchable_bundle(api, phrase="plain text here"))
        for junk in ('"unbalanced', "AND OR NOT", "a*b(c)", '"" -- ;'):
            resp = api.client.get("/v1/search/divergences", params={"q": junk})
            assert resp.status_code == 200, f"query {junk!r} must not break search: {resp.text}"

    def test_pruned_runs_leave_the_index(self, api, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        old = _searchable_bundle(api, phrase="ephemeral xylophone regression", repo="old-repo")
        api.ingest(old)
        assert len(_hits(api, "xylophone")) == 1

        monkeypatch.setenv("TEMPEST_BUNDLE_BUDGET_BYTES", "1")
        newer = _searchable_bundle(api, phrase="fresh content", repo="new-repo", head="e" * 40)
        api.ingest(newer)

        assert _hits(api, "xylophone") == [], "pruned run's divergences must leave the index"
        assert len(_hits(api, "fresh")) == 1


class TestBundleExport:
    def test_export_returns_byte_identical_zip(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        bundle = api.make_bundle()
        data = api.zip_bytes(bundle)
        run_id = api.create_run_for(bundle)
        assert api.upload_zip(run_id, data).status_code == 200

        resp = api.client.get(f"/v1/runs/{run_id}/bundle")
        assert resp.status_code == 200
        assert resp.content == data, "export must be byte-identical to what was ingested (L7)"
        assert resp.headers["content-type"] == "application/zip"
        assert ".tempest.zip" in resp.headers["content-disposition"]

    def test_export_without_bundle_is_404(self, api) -> None:
        run_id = api.create_run_id(repo="pending", base_sha="a" * 40, head_sha="b" * 40)
        resp = api.client.get(f"/v1/runs/{run_id}/bundle")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestBundleImport:
    def test_import_round_trips_a_bundle(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        bundle = api.make_bundle()
        data = api.zip_bytes(bundle)

        resp = api.client.post(
            "/v1/runs/import",
            files={"file": ("run.tempest.zip", data, "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        run_id = resp.json()["id"]
        assert api.fetch_bundle(run_id) == bundle, "imported run must reconstruct the bundle"

    def test_import_is_idempotent_by_digest(
        self, api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path / "data"))
        data = api.zip_bytes(api.make_bundle())
        first = api.client.post(
            "/v1/runs/import", files={"file": ("a.tempest.zip", data, "application/zip")}
        )
        second = api.client.post(
            "/v1/runs/import", files={"file": ("b.tempest.zip", data, "application/zip")}
        )
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["id"] == second.json()["id"], "same bytes → same run"
        with sqlite3.connect(api.db_path) as conn:
            digest = hashlib.sha256(data).hexdigest()
            count = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE bundle_digest = ?", (digest,)
            ).fetchone()[0]
        assert count == 1

    def test_import_rejects_garbage(self, api) -> None:
        resp = api.client.post(
            "/v1/runs/import", files={"file": ("x.tempest.zip", b"not a zip", "application/zip")}
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "BUNDLE_INVALID"
