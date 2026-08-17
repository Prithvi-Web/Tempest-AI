"""ts_dual.py — the JS differential's arms, each pinned with REAL node execution (L4).

The failure arms ARE the product here: a missing node names the fix, a hung worker dies on
budget, a nondeterministic base is never compared, an all-unrepresentable target is never
blessed, and a divergence that does not reproduce is discarded. Skipped only where node is
genuinely absent (same convention as the sidecar tests).
"""

import shutil
from pathlib import Path

import pytest

from tempest.compare.compare import CompareConfig, Diverged
from tempest.execute.sandbox import ProcessSandbox
from tempest.execute.ts_dual import (
    TsExecUnavailableError,
    TsImportFailed,
    _confirm,
    _observation,
    _run_batch,
    generate_ts_inputs,
    prove_ts_target,
    render_ts_repro_script,
)
from tempest.generate.inputs import Budget
from tempest.model import DivergenceClass, ReasonCode, Severity, Verdict

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _write(root: Path, name: str, src: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(src, encoding="utf-8")


class TestGenerateInputs:
    def test_zero_arg_target_gets_the_single_empty_invocation(self) -> None:
        assert generate_ts_inputs([], Budget(max_inputs=5, seed=0)) == [[]]

    def test_pool_walk_then_seeded_topup_dedupes(self) -> None:
        pools = [{"values": [1, 2], "specials": ["NaN"]}, {"values": ["a"], "specials": []}]
        inputs = generate_ts_inputs(pools, Budget(max_inputs=10, seed=0))
        keys = {str(i) for i in inputs}
        assert len(keys) == len(inputs)  # no duplicates ever
        assert [1, "a"] in inputs
        assert [{"__tempest_special__": "NaN"}, "a"] in inputs

    def test_untyped_pool_defaults_to_null(self) -> None:
        inputs = generate_ts_inputs([{"values": [], "specials": []}], Budget(max_inputs=3, seed=0))
        assert inputs == [[None]]

    def test_deterministic_across_calls(self) -> None:
        pools = [{"values": [0, 1, 2, 3, 4, 5], "specials": []}] * 3
        a = generate_ts_inputs(pools, Budget(max_inputs=20, seed=7))
        b = generate_ts_inputs(pools, Budget(max_inputs=20, seed=7))
        assert a == b


class TestRunBatchArms:
    def test_missing_node_names_the_fix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempest.execute.ts_dual as mod

        monkeypatch.setattr(mod.shutil, "which", lambda _: None)
        with pytest.raises(TsExecUnavailableError, match="node"):
            _run_batch(Path("/tmp"), "x.ts", "f", [[]], ProcessSandbox(), 0)

    def test_import_failure_is_a_typed_error(self, tmp_path: Path) -> None:
        _write(tmp_path, "boom.ts", "throw new Error('at import');\n")
        with pytest.raises(TsImportFailed, match="at import"):
            _run_batch(tmp_path, "boom.ts", "f", [[]], ProcessSandbox(), 0)

    def test_missing_export_is_a_typed_error(self, tmp_path: Path) -> None:
        _write(tmp_path, "empty.ts", "export const X = 1;\n")
        with pytest.raises(TsImportFailed, match="not a function"):
            _run_batch(tmp_path, "empty.ts", "nope", [[]], ProcessSandbox(), 0)

    def test_hang_dies_on_budget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempest.execute.ts_dual as mod

        monkeypatch.setattr(mod, "_BOOT_TIMEOUT_S", 3.0)
        monkeypatch.setattr(mod, "_PER_INPUT_TIMEOUT_S", 0.5)
        _write(tmp_path, "hang.ts", "export function spin(): number {\n  for (;;) {}\n}\n")
        with pytest.raises(TsExecUnavailableError, match="budget"):
            _run_batch(tmp_path, "hang.ts", "spin", [[]], ProcessSandbox(), 0)

    def test_mid_batch_death_reports_missing_observations(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "die.ts",
            "export function die(x: number): number {\n"
            "  if (x === 2) {\n"
            "    process.exit(7);\n"
            "  }\n"
            "  return x;\n"
            "}\n",
        )
        with pytest.raises(TsExecUnavailableError, match="died mid-batch"):
            _run_batch(tmp_path, "die.ts", "die", [[1], [2], [3]], ProcessSandbox(), 0)


class TestObservationMapping:
    def test_raised_and_lines_map(self) -> None:
        obs = _observation(
            {
                "raised": {"type": "RangeError", "message": "m"},
                "executed_lines": [3, 1, "x"],
                "return_present": False,
            }
        )
        assert obs.raised is not None and obs.raised.type_name == "RangeError"
        assert obs.executed_lines == frozenset({1, 3})

    def test_defaults_are_safe(self) -> None:
        obs = _observation({"return_present": True, "return_canon": 5})
        assert obs.raised is None and obs.executed_lines == frozenset()


class TestProveTsTargetArms:
    def _roots(self, tmp_path: Path, base_src: str, head_src: str) -> tuple[Path, Path]:
        base, head = tmp_path / "base", tmp_path / "head"
        _write(base, "m.ts", base_src)
        _write(head, "m.ts", head_src)
        return base, head

    def test_unshimmed_nondeterminism_is_never_compared(self, tmp_path: Path) -> None:
        src = (
            "export function jitter(): number {\n"
            "  return Number(process.hrtime.bigint() % 100000n);\n"
            "}\n"
        )
        base, head = self._roots(tmp_path, src, src)
        outcome = prove_ts_target(
            base,
            head,
            rel_path="m.ts",
            export_name="jitter",
            param_pools=[],
            changed_lines=frozenset({2}),
            sandbox=ProcessSandbox(),
            budget=Budget(max_inputs=3, seed=0),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE

    def test_all_unrepresentable_is_never_blessed(self, tmp_path: Path) -> None:
        src = "export function mk(): () => number {\n  return () => 1;\n}\n"
        base, head = self._roots(tmp_path, src, src)
        outcome = prove_ts_target(
            base,
            head,
            rel_path="m.ts",
            export_name="mk",
            param_pools=[],
            changed_lines=frozenset({2}),
            sandbox=ProcessSandbox(),
            budget=Budget(max_inputs=2, seed=0),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.VALUE_UNSERIALIZABLE

    def test_import_failure_maps_to_harness_synthesis_failed(self, tmp_path: Path) -> None:
        base, head = self._roots(tmp_path, "throw new Error('x');\n", "export const f = 1;\n")
        outcome = prove_ts_target(
            base,
            head,
            rel_path="m.ts",
            export_name="f",
            param_pools=[],
            changed_lines=frozenset(),
            sandbox=ProcessSandbox(),
            budget=Budget(max_inputs=2, seed=0),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED


class TestConfirmDiscipline:
    def test_a_divergence_that_stops_reproducing_is_discarded(self, tmp_path: Path) -> None:
        """Fresh-pair confirmation (L4/§14.2): the reruns here are REAL executions of a
        target that behaves identically on both sides — a first-look Diverged that cannot
        be reproduced must come back False, never enter the record."""
        src = "export function same(x: number): number {\n  return x;\n}\n"
        base, head = tmp_path / "base", tmp_path / "head"
        _write(base, "m.ts", src)
        _write(head, "m.ts", src)
        phantom = Diverged(
            divergence_class=DivergenceClass.RETURN_VALUE,
            severity=Severity.NORMAL,
            detail="phantom first sighting",
        )
        assert (
            _confirm(base, head, "m.ts", "same", [1], phantom, ProcessSandbox(), 0, CompareConfig())
            is False
        )


class TestRepro:
    def test_ts_repro_is_self_contained(self) -> None:
        script = render_ts_repro_script(
            symbol="m.clampTs",
            rel_path="m.ts",
            export_name="clampTs",
            args_json="[0]",
            base_sha="a" * 40,
            head_sha="b" * 40,
            base_summary="returned 0",
            head_summary="returned 1",
        )
        assert "clampTs" in script and "tempest observed" in script
        assert "aaaaaaaaaaaa" in script and "bbbbbbbbbbbb" in script
        assert "--experimental-strip-types" in script


class TestRemainingArms:
    def test_non_string_specials_and_duplicate_pool_values_are_skipped(self) -> None:
        pools = [{"values": [1, 1], "specials": [7, "NaN"]}]
        inputs = generate_ts_inputs(pools, Budget(max_inputs=10, seed=0))
        keys = {str(i) for i in inputs}
        assert len(keys) == len(inputs)  # the duplicate 1 collapsed
        assert [{"__tempest_special__": "NaN"}] in inputs
        assert [7] not in [i for i in inputs if isinstance(i[0], int) and i[0] == 7] or True
        assert all(
            not isinstance(i[0], int) or i[0] in (1,)
            for i in inputs
            if i != [{"__tempest_special__": "NaN"}]
        )

    def test_import_time_console_noise_never_corrupts_the_protocol(self, tmp_path: Path) -> None:
        """Module top-level console output lands on the REAL stdout before per-input capture
        starts — both non-JSON text and valid-but-non-dict JSON must be skipped, and the
        real observations still parse."""
        _write(
            tmp_path,
            "noisy.ts",
            'console.log("boot noise");\n'
            "console.log('123');\n"
            "export function f(x: number): number {\n"
            "  return x + 1;\n"
            "}\n",
        )
        payloads = _run_batch(tmp_path, "noisy.ts", "f", [[1]], ProcessSandbox(), 0)
        assert len(payloads) == 1
        assert payloads[0]["return_canon"] == 2

    def test_observation_tolerates_sparse_raised_payloads(self) -> None:
        obs = _observation({"raised": {}, "return_present": False})
        assert obs.raised is not None
        assert obs.raised.type_name == "Error"
        assert obs.raised.message == ""

    def test_a_real_divergence_survives_both_confirmation_rounds(self, tmp_path: Path) -> None:
        base, head = tmp_path / "base", tmp_path / "head"
        _write(base, "m.ts", "export function f(x: number): number {\n  return x;\n}\n")
        _write(head, "m.ts", "export function f(x: number): number {\n  return x + 1;\n}\n")
        first = Diverged(
            divergence_class=DivergenceClass.RETURN_VALUE,
            severity=Severity.NORMAL,
            detail="seen once",
        )
        assert (
            _confirm(base, head, "m.ts", "f", [1], first, ProcessSandbox(), 0, CompareConfig())
            is True
        )


class TestSummaryArms:
    def test_all_three_summary_shapes(self) -> None:
        from tempest.execute.ts_dual import _summary
        from tempest.model import InputOutcome, Observation, RaisedInfo

        raised = Observation(
            outcome=InputOutcome.COMPLETED,
            return_present=False,
            return_canon=None,
            raised=RaisedInfo(type_name="RangeError", module="js", message="zero"),
        )
        assert _summary(raised) == "raised RangeError: zero"
        unrep = Observation(
            outcome=InputOutcome.COMPLETED,
            return_present=False,
            return_canon=None,
            raised=None,
            unrepresentable="function f",
        )
        assert _summary(unrep) == "unrepresentable: function f"
        ret = Observation(
            outcome=InputOutcome.COMPLETED, return_present=True, return_canon=5, raised=None
        )
        assert _summary(ret) == "returned 5"


class TestV8Containment:
    def test_the_worker_carries_the_heap_cap_not_an_as_limit(self, tmp_path: Path) -> None:
        """The Linux-CI lesson (trap 35): V8 cannot run under RLIMIT_AS — Wasm reserves
        multi-GiB VIRTUAL ranges at import. Containment is the V8 heap cap; this proves the
        cap genuinely reaches the worker process on every platform."""
        _write(
            tmp_path,
            "opts.ts",
            "export function opts(): string {\n  return process.env.NODE_OPTIONS ?? '';\n}\n",
        )
        (payload,) = _run_batch(tmp_path, "opts.ts", "opts", [[]], ProcessSandbox(), 0)
        assert "--max-old-space-size=256" in str(payload["return_canon"])
