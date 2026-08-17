"""THE ENGINE-DEPTH GATE (HANDOFF-WORLD-CLASS 2.5): static/class methods, typed-dataclass
instances, and async functions all reach verdicts KEYLESS — no model, no network, no key.

c04 staticmethod seeded change → DIVERGENT. c05 classmethod no-op → EQUIVALENT. c06 typed
dataclass instance method → DIVERGENT through the deterministic TYPE-driven synthesizer
(classification TYPE_SYNTHESIZED, adapter in the repro). c07 async seeded change →
DIVERGENT with the worker awaiting the coroutine. Real execution end to end (L4).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from tempest.model import TargetClassification, Verdict
from tempest.prove import ProveConfig, run_prove

_FIXTURE_SCRIPT = (
    Path(__file__).resolve().parents[4] / "corpus" / "fixtures" / "pyfix" / "make_fixture.py"
)


def _load_fixture_module():  # type: ignore[no-untyped-def]  # returns a module
    spec = importlib.util.spec_from_file_location("pyfix_fixture_depth", _FIXTURE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pyfix_fixture_depth"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def result():  # type: ignore[no-untyped-def]  # ProveResult
    fixture = _load_fixture_module()
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        repo = Path(fixture.build(Path(td) / "repo"))
        yield run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=20, seed=0))


@pytest.fixture(autouse=True, scope="module")
def _dev_mode():  # type: ignore[no-untyped-def]
    import os

    os.environ["TEMPEST_DEV"] = "1"
    yield


def _depth_targets(result):  # type: ignore[no-untyped-def]
    return {t.module: t for t in result.bundle.targets if t.module in ("c04", "c05", "c06", "c07")}


class TestEngineDepth:
    def test_staticmethod_change_is_divergent(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _depth_targets(result)["c04"]
        assert t.qualname == "Pricing.with_tax"
        assert t.verdict is Verdict.DIVERGENT

    def test_classmethod_noop_is_equivalent(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _depth_targets(result)["c05"]
        assert t.qualname == "Labeler.label"
        assert t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET

    def test_typed_dataclass_method_proves_keyless(self, result) -> None:  # type: ignore[no-untyped-def]
        """The deterministic synthesizer constructs Basket() from its typed fields — no LLM,
        no key, fully offline (L8). Provenance is visible: TYPE_SYNTHESIZED, adapter in the
        repro."""
        t = _depth_targets(result)["c06"]
        assert t.verdict is Verdict.DIVERGENT
        assert t.classification is TargetClassification.TYPE_SYNTHESIZED
        repro = result.bundle.repro_scripts[t.divergences[0].repro_filename]
        assert "ADAPTER_SOURCE" in repro
        assert "Basket(" in repro

    def test_async_change_is_divergent(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _depth_targets(result)["c07"]
        assert t.qualname == "combine"
        assert t.verdict is Verdict.DIVERGENT

    def test_every_depth_target_ran_real_inputs(self, result) -> None:  # type: ignore[no-untyped-def]
        for t in _depth_targets(result).values():
            assert t.inputs_run > 0, t.module
