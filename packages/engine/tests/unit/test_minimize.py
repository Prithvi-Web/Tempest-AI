"""Stage 8: minimization must shrink while reproducing the SAME DivergenceClass (§14.3),
and emit a standalone repro script."""

from hypothesis import given, settings
from hypothesis import strategies as st

from tempest.compare.canonical import parse_input_literal
from tempest.compare.compare import Diverged
from tempest.minimize.ddmin import minimize_input
from tempest.minimize.repro import render_repro_script
from tempest.model import DivergenceClass, Severity


def _rerun_factory(predicate):  # type: ignore[no-untyped-def]  # test helper takes a plain lambda
    """A divergence oracle driven by a real predicate over the parsed input."""

    def rerun(args_literal: str, kwargs_literal: str) -> Diverged | None:
        args = parse_input_literal(args_literal)
        if predicate(args):
            return Diverged(DivergenceClass.RETURN_VALUE, Severity.NORMAL, "differs")
        return None

    return rerun


class TestMinimizeInput:
    def test_shrinks_string_to_minimal_diverging_case(self) -> None:
        rerun = _rerun_factory(lambda args: len(args[0]) > 3)
        result = minimize_input(rerun, "('abcdefghijklmnop',)", "{}")
        assert result is not None
        args = parse_input_literal(result.args_literal)
        assert len(args[0]) == 4  # smallest length still > 3

    def test_shrinks_integers_toward_zero(self) -> None:
        rerun = _rerun_factory(lambda args: args[0] >= 10)
        result = minimize_input(rerun, "(987654,)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal)[0] == 10

    def test_shrinks_lists_by_dropping_elements(self) -> None:
        rerun = _rerun_factory(lambda args: sum(args[0]) > 5)
        result = minimize_input(rerun, "([1, 2, 3, 4, 5],)", "{}")
        assert result is not None
        shrunk = parse_input_literal(result.args_literal)[0]
        assert sum(shrunk) > 5
        assert len(shrunk) < 5

    def test_never_returns_a_non_diverging_input(self) -> None:
        rerun = _rerun_factory(lambda args: args[0] == 42)
        result = minimize_input(rerun, "(42,)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal)[0] == 42

    def test_shrink_path_is_recorded(self) -> None:
        rerun = _rerun_factory(lambda args: len(args[0]) > 3)
        result = minimize_input(rerun, "('abcdefgh',)", "{}")
        assert result is not None
        assert len(result.shrink_path) >= 1

    @settings(max_examples=20, deadline=None)
    @given(st.integers(min_value=5, max_value=10**6))
    def test_property_minimized_input_always_still_diverges(self, threshold: int) -> None:
        rerun = _rerun_factory(lambda args: isinstance(args[0], int) and args[0] >= threshold)
        result = minimize_input(rerun, f"({threshold * 3},)", "{}")
        assert result is not None
        final = parse_input_literal(result.args_literal)[0]
        assert final >= threshold  # still diverges — the invariant that may never break


class TestReproScript:
    def test_script_is_standalone_and_names_the_evidence(self) -> None:
        script = render_repro_script(
            symbol="m.clamp",
            module="m",
            qualname="clamp",
            args_literal="(-7,)",
            kwargs_literal="{}",
            divergence_class=DivergenceClass.RETURN_VALUE,
            base_sha="a" * 40,
            head_sha="b" * 40,
            base_summary="returned 0",
            head_summary="returned 1",
        )
        assert "python" in script.splitlines()[0]
        assert "(-7,)" in script
        assert "a" * 12 in script and "b" * 12 in script
        assert "RETURN_VALUE" in script
        compile(script, "repro.py", "exec")  # must be valid Python
