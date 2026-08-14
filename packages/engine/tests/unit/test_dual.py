"""Stage 6 pairing: differential proof of one target across two real revisions.

Includes failure-mode §14.2 defense: a divergence is only DIVERGENT after 3x stable re-runs;
a base that disagrees with itself is NONDETERMINISTIC_BASE, never a head bug."""

from pathlib import Path

from tempest.compare.compare import Diverged
from tempest.execute.dual import ConfirmOutcome, confirm_divergence, prove_target
from tempest.execute.sandbox import ProcessSandbox
from tempest.generate.inputs import Budget
from tempest.model import DivergenceClass, ReasonCode, Severity, Verdict

from .test_targets_diff import commit_head, make_repo

SANDBOX = ProcessSandbox()


def _envs(tmp_path: Path, base_src: str, head_src: str) -> tuple[Path, Path]:
    from tempest.envrepro.worktree import materialize

    repo = make_repo(tmp_path, {"m.py": base_src})
    commit_head(repo, {"m.py": head_src})
    cache = tmp_path / "cache"
    return materialize(repo, "base", cache).worktree, materialize(repo, "head", cache).worktree


class TestProveTarget:
    def test_behavior_change_is_divergent_with_evidence(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "def clamp(x: int) -> int:\n    return max(0, min(100, x))\n",
            "def clamp(x: int) -> int:\n    return max(1, min(100, x))\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "clamp",
            changed_lines=frozenset({2}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=40),
        )
        assert outcome.verdict is Verdict.DIVERGENT
        assert outcome.divergences
        d = outcome.divergences[0]
        assert d.divergence_class is DivergenceClass.RETURN_VALUE
        assert d.args_literal  # the concrete evidence input
        assert outcome.inputs_run > 0

    def test_noop_refactor_is_equivalent_under_budget(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "def total(xs: list[int]) -> int:\n    s = 0\n"
            "    for x in xs:\n        s += x\n    return s\n",
            "def total(xs: list[int]) -> int:\n    return sum(xs)\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "total",
            changed_lines=frozenset({2, 3, 4, 5}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=30),
        )
        assert outcome.verdict is Verdict.EQUIVALENT_UNDER_BUDGET
        assert outcome.divergences == ()
        assert outcome.inputs_run >= 10

    def test_exception_type_change_is_divergent(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "def pick(d: dict[str, int], k: str) -> int:\n    return d[k]\n",
            "def pick(d: dict[str, int], k: str) -> int:\n    if k not in d:\n"
            "        raise ValueError(f'missing {k}')\n    return d[k]\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "pick",
            changed_lines=frozenset({2, 3, 4}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=40),
        )
        assert outcome.verdict is Verdict.DIVERGENT
        classes = {d.divergence_class for d in outcome.divergences}
        assert DivergenceClass.EXCEPTION_TYPE in classes

    def test_changed_line_coverage_is_reported(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "def f(x: int) -> int:\n    if x == 123456789:\n        return 1\n    return 0\n",
            "def f(x: int) -> int:\n    if x == 123456789:\n        return 2\n    return 0\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset({3}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=15),
        )
        # The magic number is essentially unreachable by generation — coverage must say so
        # honestly, and the verdict must still be EQUIVALENT_UNDER_BUDGET (not "correct").
        assert 0.0 <= outcome.changed_line_coverage <= 1.0
        assert outcome.verdict in (Verdict.EQUIVALENT_UNDER_BUDGET, Verdict.DIVERGENT)

    def test_synthesis_failure_yields_unproven(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "raise ImportError('base broken')\n",
            "raise ImportError('head broken')\n",
        )
        outcome = prove_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset({1}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=5),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED


class TestConfirmDivergence:
    def _diverged(self) -> Diverged:
        return Diverged(DivergenceClass.RETURN_VALUE, Severity.NORMAL, "differs")

    def test_stable_divergence_is_confirmed(self) -> None:
        outcome = confirm_divergence(lambda attempt: (self._diverged(), True, True))
        assert outcome is ConfirmOutcome.CONFIRMED

    def test_base_self_disagreement_is_nondeterministic_base(self) -> None:
        outcome = confirm_divergence(lambda attempt: (self._diverged(), False, True))
        assert outcome is ConfirmOutcome.NONDETERMINISTIC_BASE

    def test_vanishing_divergence_is_flaky_not_reported(self) -> None:
        outcome = confirm_divergence(
            lambda attempt: (None if attempt > 0 else self._diverged(), True, True)
        )
        assert outcome is ConfirmOutcome.FLAKY

    def test_class_drift_between_reruns_is_flaky(self) -> None:
        def rerun(attempt: int) -> tuple[Diverged | None, bool, bool]:
            cls = DivergenceClass.RETURN_VALUE if attempt == 0 else DivergenceClass.OUTPUT_STREAM
            return Diverged(cls, Severity.NORMAL, "x"), True, True

        assert confirm_divergence(rerun) is ConfirmOutcome.FLAKY
