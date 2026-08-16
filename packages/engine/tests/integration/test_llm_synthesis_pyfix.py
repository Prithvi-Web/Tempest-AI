"""THE SYNTHESIS GATE (HANDOFF-WORLD-CLASS 2.1): on the pyfix instance-method targets,
proof rate must go from 0% keyless (honest UNPROVEN + remediation) to measured with a key
— c01/c02 seeded method changes land DIVERGENT through AI-written adapters, the c03 no-op
stays clean, and every claim rides real sandboxed execution. The "model" is a local
Messages-API peer; the adapters it serves are real code the engine validates on BASE."""

import importlib.util
import sys
from pathlib import Path

import pytest

from tempest.model import ReasonCode, TargetClassification, Verdict
from tempest.prove import ProveConfig, run_prove

from ..helpers_fake_anthropic import FakeAnthropic, fake_anthropic_server

_FIXTURE_SCRIPT = (
    Path(__file__).resolve().parents[4] / "corpus" / "fixtures" / "pyfix" / "make_fixture.py"
)

PLANTED_KEY = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC"

ADAPTERS = {
    "Discounter": (
        "```python\nfrom c01 import Discounter\n\n\n"
        "def adapter(price: float) -> float:\n"
        "    return Discounter(0.25).apply(price)\n```"
    ),
    "Wallet": (
        "```python\nfrom c02 import Wallet\n\n\n"
        "def adapter(amount: int) -> int:\n"
        "    return Wallet(100).withdraw(amount)\n```"
    ),
    "Tally": (
        "```python\nfrom c03 import Tally\n\n\n"
        "def adapter(xs: list[int]) -> int:\n"
        "    return Tally(7).bump(xs)\n```"
    ),
}


def _load_fixture_module():  # type: ignore[no-untyped-def]  # returns a module
    spec = importlib.util.spec_from_file_location("pyfix_fixture_llm", _FIXTURE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pyfix_fixture_llm"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    fixture = _load_fixture_module()
    return Path(fixture.build(tmp_path_factory.mktemp("pyfix-llm") / "repo"))


def _instance_targets(result):  # type: ignore[no-untyped-def]  # bundle targets
    return {t.module: t for t in result.bundle.targets if t.module in ("c01", "c02", "c03")}


class TestKeylessHonesty:
    def test_proof_rate_is_zero_and_the_remediation_names_the_fix(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0))
        targets = _instance_targets(result)
        assert len(targets) == 3
        for t in targets.values():
            assert t.verdict is Verdict.UNPROVEN
            assert t.reason_code is ReasonCode.TARGET_UNREACHABLE
            assert t.reason_detail is not None and "Anthropic API key" in t.reason_detail


class TestSynthesisProofRate:
    def test_method_changes_prove_divergent_and_the_noop_stays_clean(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeAnthropic()
        fake.replies = ADAPTERS
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("TEMPEST_DEV", "1")
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            result = run_prove(
                ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0)
            )
        targets = _instance_targets(result)

        # The measurement: 0/3 keyless → 3/3 exercised with a key; seeded changes caught,
        # zero false alarms through adapters.
        assert targets["c01"].verdict is Verdict.DIVERGENT
        assert targets["c02"].verdict is Verdict.DIVERGENT
        assert targets["c03"].verdict is Verdict.EQUIVALENT_UNDER_BUDGET

        for t in targets.values():
            assert t.classification is TargetClassification.SYNTHESIZED

        # Divergences carry evidence, and the repro rides the adapter inside it (L7).
        divergent = targets["c01"].divergences[0]
        repro = result.bundle.repro_scripts[divergent.repro_filename]
        assert "ADAPTER_SOURCE" in repro
        assert "Discounter(0.25)" in repro

        # Validated adapters are cached in the user's repo for offline reruns (L8).
        cached = list((repo / ".tempest" / "adapters").glob("*.py"))
        assert len(cached) == 3

    def test_declined_adapters_are_stated_plainly_never_downgraded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that returns prose instead of an adapter: every target lands
        UNPROVEN(SYNTHESIS_DECLINED) with the failure named — never TARGET_UNREACHABLE
        with a remediation hint that would suggest the key wasn't tried, and never a
        silently lesser claim. Fresh repo: no adapter cache in play."""
        fixture = _load_fixture_module()
        fresh_repo = Path(fixture.build(tmp_path / "repo"))
        fake = FakeAnthropic()
        fake.reply_text = "I would be happy to help you construct these classes!"
        with fake_anthropic_server(fake) as url:
            monkeypatch.setenv("TEMPEST_DEV", "1")
            monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
            monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", url)
            result = run_prove(
                ProveConfig(repo=fresh_repo, base="base", head="head", max_inputs=20, seed=0)
            )
        targets = _instance_targets(result)
        assert len(targets) == 3
        for t in targets.values():
            assert t.verdict is Verdict.UNPROVEN
            assert t.reason_code is ReasonCode.SYNTHESIS_DECLINED
            assert t.reason_detail is not None and "adapter" in t.reason_detail
        assert not (fresh_repo / ".tempest" / "adapters").exists()

    def test_cached_repo_reruns_fully_offline(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runs after the cache is populated: no server at all, key still set — the same
        verdicts reproduce with zero network (L8)."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", PLANTED_KEY)
        monkeypatch.setenv("TEMPEST_SYNTHESIS_BASE_URL", "http://127.0.0.1:9")
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0))
        targets = _instance_targets(result)
        assert targets["c01"].verdict is Verdict.DIVERGENT
        assert targets["c02"].verdict is Verdict.DIVERGENT
        assert targets["c03"].verdict is Verdict.EQUIVALENT_UNDER_BUDGET
