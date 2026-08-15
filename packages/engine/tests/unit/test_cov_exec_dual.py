"""Stage-6 pairing edges driven by REAL cross-process nondeterminism (Law L4):

flaky heads that stop diverging the moment a fresh pair re-checks them, bases that disagree
with themselves, record/replay instability through raw-fd side channels the shims honestly
cannot intercept, and the confirmation cap. Every scenario executes real worker pairs — the
on-disk marker/counter files below ARE the nondeterminism, not a simulation of it.
"""

from pathlib import Path

from tempest.compare.compare import Unprovable, UnprovableKind
from tempest.execute import runner
from tempest.execute.dual import (
    _UnprovableTally,
    observation_summary,
    prove_impure_target,
    prove_target,
)
from tempest.execute.sandbox import ProcessSandbox
from tempest.generate.inputs import Budget
from tempest.model import ReasonCode, Verdict

SANDBOX = ProcessSandbox()


def _roots(tmp_path: Path, base_src: str, head_src: str) -> tuple[Path, Path]:
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()
    (base / "m.py").write_text(base_src)
    (head / "m.py").write_text(head_src)
    return base, head


def _flaky_head_src(tmp_path: Path) -> str:
    """Diverges only in the first few processes that import it (synthesis probes the head in
    1-3 workers before the initial batch, so the threshold outlasts them): the on-disk
    counter is real cross-process state, and every confirmation's fresh pair lands past the
    threshold — the divergence vanishes or drifts, exactly what FLAKY discard is for."""
    counter = _RAW_FD_COUNTER.format(path=str(tmp_path / "head-count.txt"))
    return counter + "\n\ndef f(x: int) -> int:\n    return 1 if _N < 4 else 0\n"


_RAW_FD_COUNTER = (
    "import os\n"
    "_P = {path!r}\n"
    "\n"
    "\n"
    "def _bump() -> int:\n"
    "    try:\n"
    "        fd = os.open(_P, os.O_RDONLY)\n"
    "        n = int(os.read(fd, 32) or b'0')\n"
    "        os.close(fd)\n"
    "    except OSError:\n"
    "        n = 0\n"
    "    fd = os.open(_P, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)\n"
    "    os.write(fd, str(n + 1).encode())\n"
    "    os.close(fd)\n"
    "    return n\n"
    "\n"
    "\n"
    "_N = _bump()\n"  # bumps once per PROCESS via raw fds no determinism layer intercepts
)


class TestUnprovableTally:
    def test_zero_inputs_is_synthesis_failure_wording(self) -> None:
        code, detail = _UnprovableTally().unexercised_reason(0)
        assert code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert "nothing is being blessed" in detail

    def test_uninterceptable_dominates_when_no_unserializable(self) -> None:
        tally = _UnprovableTally()
        tally.add(Unprovable(reason="raw socket", kind=UnprovableKind.UNINTERCEPTABLE))
        code, detail = tally.unexercised_reason(1)
        assert code is ReasonCode.UNINTERCEPTABLE_EFFECT
        assert "raw socket" in detail

    def test_only_flaky_inputs_fall_through_to_nondeterministic_base(self) -> None:
        tally = _UnprovableTally()
        tally.flaky = 3
        code, detail = tally.unexercised_reason(3)
        assert code is ReasonCode.NONDETERMINISTIC_BASE
        assert "3 unconfirmable-flaky" in detail
        assert tally.total == 3


class TestObservationSummary:
    def test_hung_crashed_and_unrepresentable_summaries(self) -> None:
        assert observation_summary(runner._hung_observation(1.0)) == "hung (per-input timeout)"
        assert observation_summary(runner._crashed_observation(-9)) == "crashed (exit -9)"
        unrep = runner._completed_observation(
            {
                "return_present": False,
                "return_canon": None,
                "stdout": "",
                "stderr": "",
                "wall_ns": 1,
                "cpu_ns": 1,
                "unrepresentable": "function value",
            }
        )
        assert observation_summary(unrep) == "returned an unrepresentable value (function value)"


class TestProveTargetEdges:
    def test_zero_generated_inputs_is_unproven_not_blessed(self, tmp_path: Path) -> None:
        src = "def f(x: int) -> int:\n    return x\n"
        base, head = _roots(tmp_path, src, src)
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=0),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert outcome.inputs_run == 0

    def test_flaky_divergences_are_discarded_and_never_reported(self, tmp_path: Path) -> None:
        base, head = _roots(
            tmp_path, "def f(x: int) -> int:\n    return 0\n", _flaky_head_src(tmp_path)
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=4),
        )
        # Every initial divergence vanished under fresh pairs: nothing may be reported as a
        # head bug, and nothing was proven equivalent either.
        assert outcome.divergences == ()
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE
        assert outcome.reason_detail is not None
        assert "unconfirmable-flaky" in outcome.reason_detail
        assert outcome.unprovable_inputs == outcome.inputs_run > 0

    def test_base_disagreeing_with_itself_is_nondeterministic_base(self, tmp_path: Path) -> None:
        counter = _RAW_FD_COUNTER.format(path=str(tmp_path / "count.txt"))
        base_src = (
            counter.replace("_N = _bump()\n", "")
            + "\n\ndef f(x: int) -> int:\n    return _bump()\n"
        )
        base, head = _roots(tmp_path, base_src, "def f(x: int) -> int:\n    return -1\n")
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE
        assert outcome.reason_detail is not None
        assert "disagrees with itself" in outcome.reason_detail

    def test_same_args_same_class_divergences_deduplicate(self, tmp_path: Path) -> None:
        # Keyword-only signature: every generated input shares the args literal "()", so a
        # second stable divergence of the same class must dedupe, not confirm again.
        base, head = _roots(
            tmp_path,
            "def f(*, k: int) -> int:\n    return k\n",
            "def f(*, k: int) -> int:\n    return k + 1\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=6),
        )
        assert outcome.verdict is Verdict.DIVERGENT
        assert outcome.inputs_run >= 2
        assert len(outcome.divergences) == 1
        assert outcome.divergences[0].args_literal == "()"


class TestProveImpureTargetEdges:
    def test_synthesis_failure_is_unproven(self, tmp_path: Path) -> None:
        base, head = _roots(
            tmp_path, "raise ImportError('base broken')\n", "raise ImportError('head broken')\n"
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED

    def test_replay_that_cannot_reproduce_its_recording_is_unproven(self, tmp_path: Path) -> None:
        counter = _RAW_FD_COUNTER.format(path=str(tmp_path / "count.txt"))
        base_src = counter + "\n\ndef f(x: int) -> int:\n    return _N\n"
        base, head = _roots(tmp_path, base_src, "def f(x: int) -> int:\n    return 0\n")
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE
        assert outcome.reason_detail is not None
        assert "does not reproduce its own recording" in outcome.reason_detail

    def test_base_record_replay_self_disagreement_during_confirmation(self, tmp_path: Path) -> None:
        counter = _RAW_FD_COUNTER.format(path=str(tmp_path / "count.txt"))
        # Stable for the first record/replay pair (processes 1 and 2), unstable afterwards —
        # exactly the shape only the confirmation re-check can catch.
        base_src = counter + "\n\ndef f(x: int) -> int:\n    return 0 if _N < 2 else _N\n"
        base, head = _roots(tmp_path, base_src, "def f(x: int) -> int:\n    return 7\n")
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE
        assert outcome.reason_detail is not None
        assert "disagrees with itself" in outcome.reason_detail

    def test_head_reaching_an_uninterceptable_surface_is_unproven(self, tmp_path: Path) -> None:
        base, head = _roots(
            tmp_path,
            "def f(x: int) -> int:\n    return 0\n",
            "import socket\n\n\ndef f(x: int) -> int:\n    socket.socket()\n    return 0\n",
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.UNINTERCEPTABLE_EFFECT
        assert outcome.reason_detail is not None
        assert "on head" in outcome.reason_detail

    def test_flaky_impure_divergences_are_discarded(self, tmp_path: Path) -> None:
        base, head = _roots(
            tmp_path, "def f(x: int) -> int:\n    return 0\n", _flaky_head_src(tmp_path)
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=3),
        )
        assert outcome.divergences == ()
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.NONDETERMINISTIC_BASE
        assert outcome.reason_detail is not None
        assert "unconfirmable-flaky" in outcome.reason_detail

    def test_confirmation_cap_stops_at_eight_reported_divergences(self, tmp_path: Path) -> None:
        base, head = _roots(
            tmp_path,
            "def f(x: int, y: int) -> int:\n    return 0\n",
            "def f(x: int, y: int) -> int:\n    return 1\n",
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset(),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=12),
        )
        assert outcome.verdict is Verdict.DIVERGENT
        assert outcome.inputs_run > 8, "the cap needs more divergences than it reports"
        assert len(outcome.divergences) == 8  # _MAX_CONFIRMATIONS: the rest are capped
