"""THE PHASE 1 GATE (docs/PLAN.md): on the pyfix fixture, Tempest must find 12/12 seeded
behavior changes with minimized repros and report 0 false divergences on the 12 no-ops."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from tempest.bundle.bundle import read_bundle
from tempest.model import Verdict
from tempest.prove import ProveConfig, run_prove

_FIXTURE_SCRIPT = (
    Path(__file__).resolve().parents[4] / "corpus" / "fixtures" / "pyfix" / "make_fixture.py"
)


def _load_fixture_module():  # type: ignore[no-untyped-def]  # returns a module
    spec = importlib.util.spec_from_file_location("pyfix_fixture", _FIXTURE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pyfix_fixture"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pyfix_result(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]  # yields (fixture, result)
    fixture = _load_fixture_module()
    repo = fixture.build(tmp_path_factory.mktemp("pyfix") / "repo")
    os.environ["TEMPEST_DEV"] = "1"
    result = run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=40, seed=0))
    return fixture, result


class TestPhase1Gate:
    def test_all_12_behavior_changes_are_divergent(self, pyfix_result) -> None:  # type: ignore[no-untyped-def]  # untyped fixture tuple
        fixture, result = pyfix_result
        verdict_by_module = {t.module: t.verdict for t in result.bundle.targets}
        missed = [
            m for m in fixture.BEHAVIOR_MODULES if verdict_by_module.get(m) is not Verdict.DIVERGENT
        ]
        assert missed == [], f"behavior changes NOT caught: {missed}"

    def test_zero_false_divergences_on_noop_refactors(self, pyfix_result) -> None:  # type: ignore[no-untyped-def]  # untyped fixture tuple
        fixture, result = pyfix_result
        false_alarms = [
            t.module
            for t in result.bundle.targets
            if t.module in fixture.NOOP_MODULES and t.verdict is Verdict.DIVERGENT
        ]
        assert false_alarms == [], f"false divergences on no-ops: {false_alarms}"
        noop_verdicts = {
            t.module: t.verdict for t in result.bundle.targets if t.module in fixture.NOOP_MODULES
        }
        assert all(v is Verdict.EQUIVALENT_UNDER_BUDGET for v in noop_verdicts.values()), (
            noop_verdicts
        )

    def test_every_divergence_has_minimized_input_and_repro(self, pyfix_result) -> None:  # type: ignore[no-untyped-def]  # untyped fixture tuple
        _, result = pyfix_result
        for t in result.bundle.targets:
            for d in t.divergences:
                assert d.minimized_args is not None
                assert d.repro_filename in result.bundle.repro_scripts
                script = result.bundle.repro_scripts[d.repro_filename]
                compile(script, d.repro_filename, "exec")

    def test_run_verdict_is_divergent_and_bundle_round_trips(self, pyfix_result) -> None:  # type: ignore[no-untyped-def]  # untyped fixture tuple
        _, result = pyfix_result
        assert result.bundle.manifest.verdict is Verdict.DIVERGENT
        assert read_bundle(result.bundle_dir) == result.bundle
        assert result.zip_path.exists()

    def test_first_party_sandbox_was_used_and_declared(self, pyfix_result) -> None:  # type: ignore[no-untyped-def]  # untyped fixture tuple
        _, result = pyfix_result
        assert result.sandbox_kind == "process-first-party"
