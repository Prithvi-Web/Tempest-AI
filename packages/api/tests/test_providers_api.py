"""GET /v1/platform/catalog (PLAN-V3 C4, ADR-0076) — the model world, and its refusals.

Real app, real loopback HTTP where discovery is exercised (L4). Pinned here: the catalog is
the registry (16 rows, anthropic the one built-in, object keys = display names, order = the
registry's order); adopted static metadata is served as-is; a LOCAL runner's models are
discovered live from its own /models; a keyless remote is NEVER probed (a hit counter proves
the absence of the request, not just the absence of models); a keyed metadata-less remote is
probed with its key as a Bearer; and every degenerate /models answer — unreachable, non-JSON,
non-dict, data-not-a-list, rows without ids — narrows to [] rather than failing the catalog.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tempest.inference import providers as registry
from tempest_api.app import create_app

#: The seam directory the desktop host serves at /tempest-assets/ — one badge per registry row.
_BADGE_DIR = (
    Path(__file__).resolve().parents[3] / "packages/platform/client/tempest/assets/providers"
)


class _ModelsPeer:
    """A loopback /models endpoint with a scriptable body and a hit ledger."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self.hits: list[str | None] = []
        peer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                peer.hits.append(self.headers.get("Authorization"))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def client(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TEMPEST_DATA_DIR", str(tmp_path))
    # No provider keys and no overrides leak in from the developer's shell: every test
    # states its own environment or it is not the environment under test.
    for provider in registry.PROVIDERS:
        if provider.env_var:
            monkeypatch.delenv(provider.env_var, raising=False)
        monkeypatch.delenv(provider.base_url_env(), raising=False)
    with TestClient(create_app()) as instance:
        yield instance


def _catalog(client: TestClient) -> dict[str, object]:
    response = client.get("/v1/platform/catalog")
    assert response.status_code == 200
    payload: dict[str, object] = response.json()
    return payload


class TestTheCatalogIsTheRegistry:
    def test_every_registry_row_is_an_endpoint_and_keys_match_models(
        self, client: TestClient
    ) -> None:
        payload = _catalog(client)
        endpoints = payload["endpoints"]
        models = payload["models"]
        assert isinstance(endpoints, dict) and isinstance(models, dict)
        assert len(endpoints) == len(registry.PROVIDERS)
        assert set(endpoints) == set(models)

    def test_anthropic_is_the_one_builtin_and_first(self, client: TestClient) -> None:
        payload = _catalog(client)
        endpoints = payload["endpoints"]
        assert isinstance(endpoints, dict)
        anthropic = endpoints["anthropic"]
        assert anthropic["type"] is None
        assert anthropic["order"] == 0
        assert anthropic["userProvide"] is True
        others = [row for key, row in endpoints.items() if key != "anthropic"]
        assert all(row["type"] == "custom" for row in others)

    def test_object_keys_are_display_names_and_order_is_registry_order(
        self, client: TestClient
    ) -> None:
        payload = _catalog(client)
        endpoints = payload["endpoints"]
        assert isinstance(endpoints, dict)
        by_order = sorted(endpoints.items(), key=lambda item: item[1]["order"])
        expected = ["anthropic" if p.id == "anthropic" else p.label for p in registry.PROVIDERS]
        assert [key for key, _row in by_order] == expected

    def test_local_runners_need_no_key(self, client: TestClient) -> None:
        payload = _catalog(client)
        endpoints = payload["endpoints"]
        assert isinstance(endpoints, dict)
        for provider in registry.PROVIDERS:
            if provider.local:
                assert endpoints[provider.label]["userProvide"] is False

    def test_adopted_static_metadata_is_served(self, client: TestClient) -> None:
        payload = _catalog(client)
        models = payload["models"]
        assert isinstance(models, dict)
        assert models["anthropic"] == list(registry.get("anthropic").models)
        assert models["OpenAI"] == list(registry.get("openai").models)

    def test_provider_rows_carry_the_key_bridge_mapping_and_no_secrets(
        self, client: TestClient
    ) -> None:
        payload = _catalog(client)
        rows = payload["providers"]
        assert isinstance(rows, list)
        assert len(rows) == len(registry.PROVIDERS)
        by_id = {row["id"]: row for row in rows}
        assert by_id["anthropic"]["endpoint_key"] == "anthropic"
        assert by_id["anthropic"]["key_env"] == "ANTHROPIC_API_KEY"
        assert by_id["ollama"]["key_env"] == ""
        assert "value" not in by_id["anthropic"] and "key" not in by_id["anthropic"]


class TestLocalDiscovery:
    def test_a_running_local_runner_lists_its_real_models(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps({"data": [{"id": "llama3.2"}, {"id": "qwen2.5-coder"}]}).encode()
        peer = _ModelsPeer(body)
        try:
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_OLLAMA", peer.base_url)
            payload = _catalog(client)
            models = payload["models"]
            assert isinstance(models, dict)
            assert models["Ollama (local)"] == ["llama3.2", "qwen2.5-coder"]
            # Keyless by construction: the loopback request carried no Authorization.
            assert peer.hits == [None]
        finally:
            peer.close()

    def test_an_offline_runner_lists_nothing_and_nothing_fails(self, client: TestClient) -> None:
        payload = _catalog(client)
        models = payload["models"]
        assert isinstance(models, dict)
        # The registry default ports answer connection-refused instantly on this machine.
        assert models["LM Studio (local)"] == []


class TestKeyedDiscovery:
    def test_a_keyless_remote_is_never_probed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        peer = _ModelsPeer(json.dumps({"data": [{"id": "sneaky"}]}).encode())
        try:
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_GROQ", peer.base_url)
            payload = _catalog(client)
            models = payload["models"]
            assert isinstance(models, dict)
            assert models["Groq"] == []
            assert peer.hits == []  # the absence of the REQUEST, not just of models (L10)
        finally:
            peer.close()

    def test_a_keyed_metadata_less_remote_is_probed_with_its_key(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        peer = _ModelsPeer(json.dumps({"data": [{"id": "llama-3.3-70b"}]}).encode())
        try:
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_GROQ", peer.base_url)
            monkeypatch.setenv("GROQ_API_KEY", "gsk-test-key")
            payload = _catalog(client)
            models = payload["models"]
            assert isinstance(models, dict)
            assert models["Groq"] == ["llama-3.3-70b"]
            assert peer.hits == ["Bearer gsk-test-key"]
        finally:
            peer.close()

    def test_a_keyed_remote_with_adopted_metadata_is_not_probed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        peer = _ModelsPeer(json.dumps({"data": [{"id": "gpt-fetched"}]}).encode())
        try:
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_OPENAI", peer.base_url)
            monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
            payload = _catalog(client)
            models = payload["models"]
            assert isinstance(models, dict)
            assert models["OpenAI"] == list(registry.get("openai").models)
            assert peer.hits == []
        finally:
            peer.close()


class TestProviderIcons:
    """Every selector row's badge exists locally (L32: no remote icon fetch, ever).

    The URL itself is written by the DESKTOP HOST as it bridges the catalog — only its
    protocol serves /tempest-assets/, and an engine-side URL would hand every other consumer
    a broken <img> (the vendored UnknownIcon's iconURL arm has no error handler). So the
    engine pins the ABSENCE of the URL, and the seam pins the badge file the host's
    decoration resolves to, one per registry row. The host's half is pinned in Rust
    (platform_web.rs: the decoration test).
    """

    def test_the_engine_emits_no_icon_url_the_host_decorates(self, client: TestClient) -> None:
        payload = _catalog(client)
        endpoints = payload["endpoints"]
        assert isinstance(endpoints, dict)
        for provider in registry.PROVIDERS:
            key = "anthropic" if provider.id == "anthropic" else provider.label
            assert endpoints[key]["iconURL"] is None

    def test_every_badge_url_resolves_to_a_bundled_seam_file(self) -> None:
        for provider in registry.PROVIDERS:
            badge = _BADGE_DIR / f"{provider.id}.svg"
            assert badge.is_file(), f"missing badge for {provider.id}: {badge}"

    def test_no_badge_reaches_for_the_network(self) -> None:
        # A brand SVG that embeds a remote image or script would be an egress surface inside
        # the model menu; the xmlns identifier is the one URL an SVG legitimately carries.
        for provider in registry.PROVIDERS:
            text = (_BADGE_DIR / f"{provider.id}.svg").read_text(encoding="utf-8")
            stripped = text.replace('xmlns="http://www.w3.org/2000/svg"', "")
            assert "http://" not in stripped and "https://" not in stripped, provider.id
            assert "<script" not in stripped and "<image" not in stripped, provider.id


class TestDegenerateAnswersNarrowToNothing:
    @pytest.mark.parametrize(
        "body",
        [
            b"{not json",
            json.dumps(["not", "a", "dict"]).encode(),
            json.dumps({"data": "not-a-list"}).encode(),
            json.dumps({"data": [{"no_id": True}, {"id": 7}, "bare"]}).encode(),
        ],
    )
    def test_every_malformed_models_answer_is_an_empty_list(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, body: bytes
    ) -> None:
        peer = _ModelsPeer(body)
        try:
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_OLLAMA", peer.base_url)
            payload = _catalog(client)
            models = payload["models"]
            assert isinstance(models, dict)
            assert models["Ollama (local)"] == []
            assert len(peer.hits) == 1  # it DID ask; the answer was unusable
        finally:
            peer.close()
