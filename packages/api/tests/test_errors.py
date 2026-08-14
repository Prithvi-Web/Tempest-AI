"""Every non-2xx body is the stable envelope `{error: {code, message, details?}}` —
including framework-raised 404/422 (master spec §8)."""

import pytest


class TestErrorEnvelope:
    @pytest.mark.parametrize(
        "path",
        [
            "/v1/runs/999999",
            "/v1/targets/999999",
            "/v1/divergences/999999",
            "/v1/divergences/999999/repro.py",
        ],
    )
    def test_missing_resources_are_enveloped_404s(self, api, path: str) -> None:
        resp = api.client.get(path)
        assert resp.status_code == 404
        error = resp.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["message"]

    def test_unknown_route_is_an_enveloped_404(self, api) -> None:
        resp = api.client.get("/v1/nope")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_malformed_cursor_is_a_400_validation_error(self, api) -> None:
        resp = api.client.get("/v1/runs", params={"cursor": "not-a-cursor"})
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "cursor" in error["message"]

    def test_bad_sha_in_create_run_is_an_enveloped_422(self, api) -> None:
        resp = api.client.post(
            "/v1/runs", json={"repo": "r", "base_sha": "not-a-sha", "head_sha": "b" * 40}
        )
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"]["errors"]  # pydantic's per-field reasons travel in details

    def test_missing_multipart_file_is_an_enveloped_422(self, api) -> None:
        run_id = api.create_run_id(repo="r", base_sha="a" * 40, head_sha="b" * 40)
        resp = api.client.post(f"/v1/runs/{run_id}/bundle")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
