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
    # Narrative requests carry "Divergence class:" — routed BEFORE the class-name keys
    # (which also appear in narrative prompts). ADR-0029 rides the same fake peer.
    "Divergence class:": "The rounding was removed, so prices keep their full precision.",
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
    "Ledger": (
        "```python\nfrom c08 import Ledger\n\n\n"
        "def adapter(xs: list[int]) -> int:\n"
        "    return Ledger(7).score(xs)\n```"
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


#: c01-c03 are constructible from their annotated `__init__`; c08's is unannotated and is not.
_DETERMINISTIC = ("c01", "c02", "c03")
_NEEDS_A_MODEL = "c08"


def _instance_targets(result):  # type: ignore[no-untyped-def]  # bundle targets
    wanted = (*_DETERMINISTIC, _NEEDS_A_MODEL)
    return {t.module: t for t in result.bundle.targets if t.module in wanted}


class TestKeylessHonesty:
    """REWRITTEN BY PHASE 19a (ADR-0048). This class asserted that **all three** instance
    targets were UNPROVEN without a key, and that was the honest answer while the deterministic
    rung understood only dataclasses. It is no longer true, and the reason it stopped being true
    is the entire point of the phase: `Discounter(rate: float)`, `Wallet(balance: int)` and
    `Tally(start: int)` are mechanically constructible, so they are now proven for free.

    The property the old test really guarded — *a target the engine cannot construct is honestly
    UNPROVEN and names what would change the answer* — is not weakened. It moved to `c08`, whose
    `__init__` takes an unannotated parameter, and it is asserted below with the same force.
    """

    def test_constructible_receivers_are_now_proven_with_no_key_at_all(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measurement Phase 19a bought: 0 of 3 keyless → 3 of 3 keyless."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0))
        targets = _instance_targets(result)

        assert targets["c01"].verdict is Verdict.DIVERGENT
        assert targets["c02"].verdict is Verdict.DIVERGENT
        assert targets["c03"].verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        for module in _DETERMINISTIC:
            assert targets[module].classification is TargetClassification.TYPE_SYNTHESIZED, (
                "provenance must say the constructor was DERIVED, not written by a model"
            )

    def test_a_receiver_the_engine_cannot_build_is_unproven_and_names_the_fix(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`Ledger.__init__(self, seed)` — unannotated, so there is nothing to derive a value
        from. Honest silence plus a remediation, never a guess and never a lesser claim."""
        monkeypatch.setenv("TEMPEST_DEV", "1")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0))
        t = _instance_targets(result)[_NEEDS_A_MODEL]
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

        # The measurement, restated after Phase 19a: the VERDICTS are unchanged, and what moved
        # is who earned them. c01-c03 are now the deterministic rung's (no key, no network);
        # c08 is the only one that still needs a model, and it is the one that keeps ADR-0024
        # exercised end to end.
        assert targets["c01"].verdict is Verdict.DIVERGENT
        assert targets["c02"].verdict is Verdict.DIVERGENT
        assert targets["c03"].verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        assert targets[_NEEDS_A_MODEL].verdict is Verdict.DIVERGENT

        for module in _DETERMINISTIC:
            assert targets[module].classification is TargetClassification.TYPE_SYNTHESIZED, (
                "a key must NOT change who constructs a mechanically constructible receiver — "
                "the cheap, offline, deterministic rung runs first and wins"
            )
        assert targets[_NEEDS_A_MODEL].classification is TargetClassification.SYNTHESIZED

        # ADR-0029: with a key, every divergence carries the labeled narrative — and it
        # is generated FROM evidence, after verdicts (the verdict set is identical to the
        # keyless expectations above).
        for module in ("c01", "c02"):
            for d in targets[module].divergences:
                assert d.ai_narrative == (
                    "The rounding was removed, so prices keep their full precision."
                )

        # Divergences carry evidence, and the repro rides the adapter inside it (L7) — for
        # BOTH rungs, because a repro that omitted the constructor would not be self-contained.
        model_written = targets[_NEEDS_A_MODEL].divergences[0]
        repro = result.bundle.repro_scripts[model_written.repro_filename]
        assert "ADAPTER_SOURCE" in repro
        assert "Ledger(7)" in repro, "the constructor the MODEL chose is part of the evidence"

        derived = targets["c01"].divergences[0]
        repro = result.bundle.repro_scripts[derived.repro_filename]
        assert "ADAPTER_SOURCE" in repro
        assert "Discounter(" in repro, "and so is the one the ENGINE derived"

        # Validated adapters are cached in the user's repo for offline reruns (L8). Only the
        # model-written one is cached: the deterministic rung re-derives its answer from the AST
        # in microseconds and has no network call to save.
        cached = list((repo / ".tempest" / "adapters").glob("*.py"))
        assert len(cached) == 1

    def test_declined_adapters_are_stated_plainly_never_downgraded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that returns prose instead of an adapter: the target that NEEDS a model lands
        UNPROVEN(SYNTHESIS_DECLINED) with the failure named — never TARGET_UNREACHABLE with a
        remediation hint that would suggest the key wasn't tried, and never a silently lesser
        claim. Fresh repo: no adapter cache in play.

        After Phase 19a this is a statement about `c08` alone. c01-c03 never consult the model,
        so a model that declines cannot take their verdicts away — which is itself worth
        asserting: a deterministic proof must not be hostage to an unrelated network reply."""
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
        assert len(targets) == 4

        declined = targets[_NEEDS_A_MODEL]
        assert declined.verdict is Verdict.UNPROVEN
        assert declined.reason_code is ReasonCode.SYNTHESIS_DECLINED
        assert declined.reason_detail is not None and "adapter" in declined.reason_detail

        # The deterministic rung is unaffected by what the model said.
        assert targets["c01"].verdict is Verdict.DIVERGENT
        assert targets["c02"].verdict is Verdict.DIVERGENT
        assert targets["c03"].verdict is Verdict.EQUIVALENT_UNDER_BUDGET
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
