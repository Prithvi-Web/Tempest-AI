"""The "Test key" ping (HANDOFF-WORLD-CLASS §3.2): one live, clearly-labeled request.

Real SDK, real HTTP, local Messages-API peer (L4 — nothing monkeypatched). The laws under
test: the ping travels the SAME sanctioned egress surface as synthesis (no second client, no
second base-URL knob); it asks for the smallest possible completion; it NEVER stores anything;
and with no key configured it makes no network call at all and says exactly what to do.
"""

import pytest

from tempest.harness.llm import KeyCheck, verify_key

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server


class TestKeyless:
    def test_no_key_is_reported_without_touching_the_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # An unroutable base URL: if the ping tried to call out, this test would hang/fail.
        monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", "http://127.0.0.1:1")
        result = verify_key()
        assert result == KeyCheck(
            ok=False,
            detail="no API key is configured — add one above, then test it.",
            model=None,
        )


class TestLivePing:
    def test_the_router_level_override_works_without_the_synthesis_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The alias-absent arm: only the unified client's own per-provider override set —
        the ping still lands on the peer through the one wire (19.5b)."""
        fake = FakeAnthropic()
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
            monkeypatch.delenv("TEMPEST_SYNTHESIS_BASE_URL", raising=False)
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_ANTHROPIC", url)
            result = verify_key()
        assert result.ok is True
        assert len(fake.requests) == 1

    def test_a_working_key_reports_the_model_that_answered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "ok"
        with fake_anthropic_server(fake) as base_url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", base_url)
            result = verify_key()
        assert result.ok is True
        assert result.model == "claude-sonnet-5"
        assert "answered" in result.detail

    def test_the_ping_is_the_smallest_possible_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "ok"
        with fake_anthropic_server(fake) as base_url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", base_url)
            verify_key()
        assert len(fake.requests) == 1
        sent = fake.requests[0]
        assert sent["max_tokens"] == 1
        # No source, no repo, no user content beyond a single literal probe token.
        assert sent["messages"] == [{"role": "user", "content": "ping"}]
        assert "system" not in sent

    def test_a_rejected_key_is_reported_honestly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeAnthropic()
        fake.status = 401
        with fake_anthropic_server(fake) as base_url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", base_url)
            result = verify_key()
        assert result.ok is False
        assert result.model is None
        assert "401" in result.detail or "Authentication" in result.detail

    def test_an_unreachable_endpoint_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
        monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", "http://127.0.0.1:1")
        result = verify_key()
        assert result.ok is False
        assert result.detail  # actionable text, never an empty string

    def test_the_configured_model_is_the_one_pinged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "ok"
        with fake_anthropic_server(fake) as base_url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "planted-for-tests")
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", base_url)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_MODEL", "claude-haiku-4-5-20251001")
            verify_key()
        assert fake.requests[0]["model"] == "claude-haiku-4-5-20251001"
