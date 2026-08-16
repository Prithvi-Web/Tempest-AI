"""LLM constructor synthesis (HANDOFF-WORLD-CLASS 2.1, ADR-0024) — the unit surface.

Everything here is REAL except the model: a local Messages-API peer serves the adapter
text (helpers_fake_anthropic), and every adapter is accepted only by genuine sandboxed
execution on BASE. The laws under test: no key → the honest UNPROVEN stands untouched
(and no network is attempted); an adapter that fails execution validation is
SYNTHESIS_DECLINED, never silently degraded; a cached adapter needs no network at all
(L8 — offline reproducibility); the model writes ONLY the adapter, verdicts stay with
the differential runner.
"""

from pathlib import Path

import pytest

from tempest.execute.sandbox import ProcessSandbox
from tempest.harness.llm import (
    InstanceAdapter,
    SynthesisDeclined,
    synthesize_instance_adapter,
)

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

CLASS_SOURCE = (
    "class Discounter:\n"
    "    def __init__(self, rate: float) -> None:\n"
    "        self.rate = rate\n"
    "\n"
    "    def apply(self, price: float) -> float:\n"
    "        return round(price * (1 - self.rate), 2)\n"
)

GOOD_ADAPTER = (
    "from c01 import Discounter\n"
    "\n"
    "\n"
    "def adapter(price: float) -> float:\n"
    "    return Discounter(0.25).apply(price)\n"
)

PLANTED_KEY = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC"


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A minimal base/head worktree pair holding the class module, plus a cache dir."""
    base = tmp_path / "base"
    head = tmp_path / "head"
    cache = tmp_path / "cache"
    for root in (base, head):
        root.mkdir()
        (root / "c01.py").write_text(CLASS_SOURCE, encoding="utf-8")
    return base, head, cache


def _synthesize(base: Path, head: Path, cache: Path) -> InstanceAdapter | SynthesisDeclined | None:
    return synthesize_instance_adapter(
        cache_dir=cache,
        base_root=base,
        head_root=head,
        module="c01",
        owner_class="Discounter",
        method="apply",
        head_source=CLASS_SOURCE,
        sandbox=ProcessSandbox(),
    )


class TestHonestPathsWithoutAModel:
    def test_no_key_means_no_attempt_and_no_network(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert _synthesize(base, head, cache) is None
        assert not list(cache.glob("*")) if cache.exists() else True

    def test_kill_switch_outranks_a_configured_key(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
        monkeypatch.setenv("TEMPEST_NO_SYNTHESIS", "1")
        assert _synthesize(base, head, cache) is None


class TestModelBackedSynthesis:
    def test_good_adapter_validates_on_base_and_is_cached(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        fake.reply_text = f"```python\n{GOOD_ADAPTER}```\n"
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            outcome = _synthesize(base, head, cache)
        assert isinstance(outcome, InstanceAdapter)
        assert outcome.qualname == "adapter"
        assert not outcome.from_cache
        # The adapter module exists in BOTH worktrees (the differential needs both sides).
        assert (base / f"{outcome.module}.py").exists()
        assert (head / f"{outcome.module}.py").exists()
        # Validated adapters are cached in the repo for offline reruns (L8).
        assert len(list(cache.glob("*.py"))) == 1
        # The model was asked exactly once, with the class source in the request.
        assert len(fake.requests) == 1
        assert "Discounter" in str(fake.requests[0])

    def test_cached_adapter_needs_no_network(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        fake.reply_text = f"```python\n{GOOD_ADAPTER}```"
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            first = _synthesize(base, head, cache)
        assert isinstance(first, InstanceAdapter)
        # Second run: the base URL points at a dead port — any network attempt fails loudly.
        monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", "http://127.0.0.1:9")
        second = _synthesize(base, head, cache)
        assert isinstance(second, InstanceAdapter)
        assert second.from_cache
        assert len(fake.requests) == 1  # no second model call

    def test_adapter_failing_execution_on_base_is_declined(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        fake.reply_text = (
            "```python\nfrom c01 import Missing\n\n\ndef adapter(price: float) -> float:\n"
            "    return Missing().apply(price)\n```"
        )
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            outcome = _synthesize(base, head, cache)
        assert isinstance(outcome, SynthesisDeclined)
        assert "validation" in outcome.detail or "probe" in outcome.detail
        assert not list(cache.glob("*.py"))  # failed adapters are never cached

    def test_reply_without_an_adapter_function_is_declined(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        # Valid Python, wrong shape: compiles cleanly but defines no `adapter` — this must
        # be caught by the adapter-name check, not the syntax check below.
        fake.reply_text = "```python\nGREETING = 'hello from the model'\n```"
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            outcome = _synthesize(base, head, cache)
        assert isinstance(outcome, SynthesisDeclined)
        assert "defines no module-level `adapter`" in outcome.detail

    def test_unparseable_python_is_declined(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        fake.reply_text = "```python\ndef adapter(:\n```"
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            outcome = _synthesize(base, head, cache)
        assert isinstance(outcome, SynthesisDeclined)
        assert "syntax" in outcome.detail.lower()

    def test_api_failure_is_declined_with_the_error_named(
        self, roots: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base, head, cache = roots
        fake = FakeAnthropic()
        fake.status = 500
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            outcome = _synthesize(base, head, cache)
        assert isinstance(outcome, SynthesisDeclined)
        assert "model call failed" in outcome.detail
