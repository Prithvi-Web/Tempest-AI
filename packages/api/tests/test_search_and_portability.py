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

from tempest.model import Severity


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


def _by_symbol(api, symbol: str, **params):
    return api.get_json("/v1/symbols/divergences", params={"symbol": symbol, **params})


class TestDivergencesBySymbol:
    """The lookup the editor's risk badge needs, and the one text search cannot be.

    Every test here also asserts what FREE-TEXT search answers for the same query. That pairing
    is the regression: the badge was wired to `/v1/search/divergences`, whose FTS index covers
    `detail`, `base_summary` and `head_summary` and not `qualname`, so a symbol Tempest had
    watched diverge came back with zero hits and rendered as "unmeasured". A test that only
    asserted the new endpoint works would pass again the day someone re-points the caller.
    """

    def test_a_symbol_is_found_by_name_where_text_search_finds_nothing(self, api) -> None:
        # The detail string is what the comparator really writes: value-shaped, and containing
        # no occurrence of the symbol's name anywhere.
        divergence = dataclasses.replace(api.make_divergence(0), detail="return values differ")
        target = api.make_target((divergence,), module="billing", qualname="calculateTotal")
        run_id = api.ingest(api.make_bundle(targets=(target,), repo="by-symbol"))

        assert _hits(api, "calculateTotal") == [], (
            "text search cannot see a qualname — this is the defect, pinned"
        )

        found = _by_symbol(api, "calculateTotal")
        assert found["symbol"] == "calculateTotal"
        assert len(found["hits"]) == 1
        hit = found["hits"][0]
        assert hit["run_id"] == run_id
        assert hit["qualname"] == "calculateTotal"
        assert hit["module"] == "billing"
        assert hit["detail"] == "return values differ"

    def test_severity_crosses_the_wire_in_the_engine_vocabulary(self, api) -> None:
        # The editor compared against {"HIGH","CRITICAL"}, which this enum has never contained,
        # so its "high risk" arm was unreachable. HEADLINE is what a head-only crash records.
        divergence = dataclasses.replace(api.make_divergence(0), severity=Severity.HEADLINE)
        target = api.make_target((divergence,), qualname="crasher")
        api.ingest(api.make_bundle(targets=(target,), repo="sev", head_sha="c" * 40))
        hit = _by_symbol(api, "crasher")["hits"][0]
        assert hit["severity"] == "HEADLINE"
        assert hit["severity"] not in {"HIGH", "CRITICAL"}

    def test_a_method_is_found_by_its_final_segment_and_reports_its_whole_qualname(
        self, api
    ) -> None:
        # An editor sees `post`; the engine recorded `Ledger.post`. Both halves matter: the
        # match has to happen, and the answer has to say WHICH symbol it matched so a badge
        # cannot silently attribute one class's history to another.
        target = api.make_target((api.make_divergence(0),), module="ledger", qualname="Ledger.post")
        api.ingest(api.make_bundle(targets=(target,), repo="methods", head_sha="d" * 40))
        hits = _by_symbol(api, "post")["hits"]
        assert len(hits) == 1
        assert hits[0]["qualname"] == "Ledger.post"
        assert _by_symbol(api, "Ledger.post")["hits"][0]["qualname"] == "Ledger.post"

    def test_a_name_that_merely_ends_in_the_symbol_is_not_a_match(self, api) -> None:
        target = api.make_target((api.make_divergence(0),), qualname="repost")
        api.ingest(api.make_bundle(targets=(target,), repo="suffix", head_sha="e" * 40))
        assert _by_symbol(api, "post")["hits"] == [], "the boundary is a dot, not a substring"

    def test_the_suffix_match_is_case_sensitive_on_every_backend(self, api) -> None:
        # SQLite's LIKE folds ASCII case and Postgres's does not, so the first version answered
        # differently per backend AND disagreed with the exact-match arm beside it: `Ledger.post`
        # matched a recorded `ledger.POST` and the badge reported another symbol's history as
        # this one's. Identifiers are case-sensitive in both languages Tempest proves.
        target = api.make_target((api.make_divergence(0),), module="m", qualname="Ledger.POST")
        api.ingest(api.make_bundle(targets=(target,), repo="case", head_sha="7" * 40))
        assert _by_symbol(api, "post")["hits"] == [], "post must not match .POST"
        assert len(_by_symbol(api, "POST")["hits"]) == 1

    def test_like_metacharacters_in_a_symbol_are_literal(self, api) -> None:
        # `_` is a LIKE wildcard AND a legal identifier character. Unescaped, `a_b` matches
        # `axb`, and the badge reports another symbol's divergences as this one's.
        target = api.make_target((api.make_divergence(0),), qualname="Cls.axb")
        api.ingest(api.make_bundle(targets=(target,), repo="wildcards", head_sha="1" * 40))
        assert _by_symbol(api, "a_b")["hits"] == []
        assert len(_by_symbol(api, "axb")["hits"]) == 1

    def test_an_empty_symbol_answers_nothing_rather_than_everything(self, api) -> None:
        # `LIKE '%.'` matches every dotted qualname there is. An empty query is not a query.
        target = api.make_target((api.make_divergence(0),), qualname="Cls.method")
        api.ingest(api.make_bundle(targets=(target,), repo="empty", head_sha="2" * 40))
        assert _by_symbol(api, "")["hits"] == []

    def test_an_unrecorded_symbol_is_empty_not_an_error(self, api) -> None:
        api.ingest(api.make_bundle(repo="absent", head_sha="3" * 40))
        assert _by_symbol(api, "neverProved")["hits"] == []

    def test_the_limit_binds_and_is_validated(self, api) -> None:
        divergences = tuple(api.make_divergence(n) for n in range(4))
        target = api.make_target(divergences, qualname="busy")
        api.ingest(api.make_bundle(targets=(target,), repo="limits", head_sha="4" * 40))
        assert len(_by_symbol(api, "busy")["hits"]) == 4
        assert len(_by_symbol(api, "busy", limit=2)["hits"]) == 2
        assert (
            api.client.get(
                "/v1/symbols/divergences", params={"symbol": "busy", "limit": 0}
            ).status_code
            == 422
        )


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
