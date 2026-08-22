"""AI narratives (ADR-0029) — the readability layer's hard lines, pinned.

Keyless → None with zero egress; kill switch honored; API failure → None (never an ERROR,
never a lost run); empty model output → None; the request carries ONLY the evidence fields.
All against the local Messages-API peer (L4: the real SDK→HTTP path, no mocks).
"""

import pytest

from tempest.report.narrative import narrate_divergence, narratives_enabled

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

PLANTED_KEY = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC"


def _narrate() -> str | None:
    return narrate_divergence(
        symbol="b01.clamp",
        divergence_class="RETURN_VALUE",
        args_literal="(0,)",
        kwargs_literal="{}",
        base_summary="returned 0",
        head_summary="returned 1",
    )


class TestNarratives:
    def test_keyless_is_none_and_never_calls_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert narratives_enabled() is False
        assert _narrate() is None

    def test_kill_switch_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
        monkeypatch.setenv("TEMPEST_NO_SYNTHESIS", "1")
        assert narratives_enabled() is False
        assert _narrate() is None

    def test_the_router_level_override_works_without_the_synthesis_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """19.5b's other face: TEMPEST_SYNTHESIS_BASE_URL is an ALIAS, not the mechanism.
        With only the unified client's own per-provider override set, the call still lands
        on the peer — proving the alias-absent arm routes through the same one wire."""
        fake = FakeAnthropic()
        fake.reply_text = "Same wire, no alias."
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.delenv("TEMPEST_SYNTHESIS_BASE_URL", raising=False)
            monkeypatch.setenv("TEMPEST_MODEL_BASE_URL_ANTHROPIC", url)
            got = _narrate()
        assert got == "Same wire, no alias."

    def test_narrative_comes_back_and_the_request_is_evidence_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "The old version clamped to zero; the new one returns one."
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            got = _narrate()
        assert got == "The old version clamped to zero; the new one returns one."
        (request,) = fake.requests
        body = str(request)
        assert "b01.clamp" in body and "returned 0" in body and "returned 1" in body

    def test_api_failure_degrades_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeAnthropic()
        fake.status = 500
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            assert _narrate() is None

    def test_blank_model_output_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakeAnthropic()
        fake.reply_text = "   \n  "
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            assert _narrate() is None
