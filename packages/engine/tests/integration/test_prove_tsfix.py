"""THE TYPESCRIPT GATE (wave 1, ADR-0028): Tempest is bilingual — real node execution,
real verdicts, the same honesty vocabulary.

On the tsfix fixture through full `run_prove`, keyless and offline: seeded changes land
DIVERGENT with self-contained .mjs repros; the no-op refactor and the shim-dependent
formatting churn land EQUIVALENT (zero false divergences — the JS determinism shims ARE
the difference between those two outcomes); the unexported helper and the fetch-touching
function land UNPROVEN with their exact reasons. Skipped only where node or the sidecar's
node_modules are genuinely absent (the same convention as the analysis tests).
"""

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from tempest.model import Lang, ReasonCode, Verdict
from tempest.prove import ProveConfig, run_prove
from tempest.targets.ts_sidecar import default_sidecar_dir

_FIXTURE_SCRIPT = (
    Path(__file__).resolve().parents[4] / "corpus" / "fixtures" / "tsfix" / "make_fixture.py"
)

pytestmark = [
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed"),
    pytest.mark.skipif(
        not (default_sidecar_dir() / "node_modules" / "ts-morph").exists(),
        reason="ts-sidecar node_modules missing (run pnpm install)",
    ),
]


def _load_fixture_module():  # type: ignore[no-untyped-def]  # returns a module
    spec = importlib.util.spec_from_file_location("tsfix_fixture", _FIXTURE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tsfix_fixture"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def result():  # type: ignore[no-untyped-def]  # ProveResult
    import os

    os.environ["TEMPEST_DEV"] = "1"
    fixture = _load_fixture_module()
    with tempfile.TemporaryDirectory() as td:
        repo = Path(fixture.build(Path(td) / "repo"))
        yield run_prove(ProveConfig(repo=repo, base="base", head="head", max_inputs=12, seed=0))


def _targets(result):  # type: ignore[no-untyped-def]
    return {t.qualname: t for t in result.bundle.targets if t.lang is Lang.TYPESCRIPT}


class TestTsGate:
    def test_seeded_number_change_is_divergent_with_a_repro(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _targets(result)["clampTs"]
        assert t.verdict is Verdict.DIVERGENT, (t.reason_code, t.reason_detail)
        assert t.inputs_run > 0
        d = t.divergences[0]
        repro = result.bundle.repro_scripts[d.repro_filename]
        assert d.repro_filename.endswith(".mjs")
        assert "clampTs" in repro and "tempest observed" in repro

    def test_seeded_string_change_is_divergent(self, result) -> None:  # type: ignore[no-untyped-def]
        assert _targets(result)["greetTs"].verdict is Verdict.DIVERGENT

    def test_noop_refactor_is_equivalent(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _targets(result)["totalTs"]
        assert t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET, (t.reason_code, t.reason_detail)
        assert t.changed_line_coverage > 0.0

    def test_async_seeded_change_is_divergent(self, result) -> None:  # type: ignore[no-untyped-def]
        assert _targets(result)["combineTs"].verdict is Verdict.DIVERGENT

    def test_time_and_random_are_pinned_by_the_shims(self, result) -> None:  # type: ignore[no-untyped-def]
        """Date.now + Math.random inside the target, formatting-only churn: without the
        JS shims this is NONDETERMINISTIC_BASE; with them it must be EQUIVALENT."""
        t = _targets(result)["stampTag"]
        assert t.verdict is Verdict.EQUIVALENT_UNDER_BUDGET, (t.reason_code, t.reason_detail)

    def test_unexported_function_is_honestly_unreachable(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _targets(result)["hiddenHelper"]
        assert t.verdict is Verdict.UNPROVEN
        assert t.reason_code is ReasonCode.TARGET_UNREACHABLE
        assert t.reason_detail is not None and "export" in t.reason_detail.lower()

    def test_fetch_touching_function_awaits_wave_two(self, result) -> None:  # type: ignore[no-untyped-def]
        t = _targets(result)["fetchTitle"]
        assert t.verdict is Verdict.UNPROVEN
        assert t.reason_code is ReasonCode.RECORD_REPLAY_UNAVAILABLE
        assert t.reason_detail is not None and "NOT exercised" in t.reason_detail

    def test_zero_false_divergences_on_ts_noops(self, result) -> None:  # type: ignore[no-untyped-def]
        for name in ("totalTs", "stampTag"):
            assert not _targets(result)[name].divergences, name
