"""Stage 8: minimization must shrink while reproducing the SAME DivergenceClass (§14.3),
and emit a standalone repro script."""

from typing import cast

from hypothesis import given, settings
from hypothesis import strategies as st

from tempest.compare.canonical import parse_input_literal
from tempest.compare.compare import Diverged
from tempest.minimize.ddmin import _shrink_value, minimize_input
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


class TestShrinkBranches:
    """Each value-type shrinker, exercised through the public minimizer (§14.3 invariant)."""

    def test_input_that_never_diverges_returns_none(self) -> None:
        def rerun(args_literal: str, kwargs_literal: str) -> Diverged | None:
            return None

        assert minimize_input(rerun, "(5,)", "{}") is None

    def test_bool_shrinks_true_to_false(self) -> None:
        rerun = _rerun_factory(lambda args: isinstance(args[0], bool))
        result = minimize_input(rerun, "(True,)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal) == (False,)

    def test_float_shrinks_toward_small_magnitude(self) -> None:
        rerun = _rerun_factory(lambda args: abs(args[0]) >= 1.0)
        result = minimize_input(rerun, "(1937.75,)", "{}")
        assert result is not None
        final = cast("tuple[float, ...]", parse_input_literal(result.args_literal))[0]
        assert final == 1.0  # halving then rounding bottoms out at the smallest diverging float

    def test_nan_and_inf_skip_rounding_and_duplicate_candidates(self) -> None:
        rerun_nan = _rerun_factory(lambda args: args[0] != args[0])
        result_nan = minimize_input(rerun_nan, "(nan,)", "{}")
        assert result_nan is not None
        final_nan = cast("tuple[float, ...]", parse_input_literal(result_nan.args_literal))[0]
        assert final_nan != final_nan
        rerun_inf = _rerun_factory(lambda args: args[0] == float("inf"))
        result_inf = minimize_input(rerun_inf, "(inf,)", "{}")
        assert result_inf is not None
        assert parse_input_literal(result_inf.args_literal) == (float("inf"),)
        # inf/2 == inf reproduces the current input; that candidate must be skipped
        # without spending an attempt: only the original run plus the 0.0 probe count.
        assert result_inf.attempts_used == 2

    def test_int_one_shrinks_no_further(self) -> None:
        rerun = _rerun_factory(lambda args: args[0] == 1)
        result = minimize_input(rerun, "(1,)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal) == (1,)

    def test_bytes_shrink_to_minimal_length(self) -> None:
        rerun = _rerun_factory(lambda args: isinstance(args[0], bytes) and len(args[0]) >= 2)
        result = minimize_input(rerun, "(b'abcdef',)", "{}")
        assert result is not None
        shrunk = cast("tuple[bytes, ...]", parse_input_literal(result.args_literal))[0]
        assert isinstance(shrunk, bytes)
        assert len(shrunk) == 2

    def test_single_element_tuple_shrinks_its_element(self) -> None:
        rerun = _rerun_factory(lambda args: isinstance(args[0], tuple) and len(args[0]) == 1)
        result = minimize_input(rerun, "((99,),)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal) == ((0,),)

    def test_dict_drops_keys_and_shrinks_values(self) -> None:
        rerun = _rerun_factory(lambda args: isinstance(args[0], dict) and args[0].get("a", 0) >= 3)
        result = minimize_input(rerun, "({'a': 9, 'b': 'zzz'},)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal) == ({"a": 3},)

    def test_sets_shrink_by_dropping_members(self) -> None:
        rerun = _rerun_factory(lambda args: 3 in args[0])
        result = minimize_input(rerun, "({1, 2, 3},)", "{}")
        assert result is not None
        assert parse_input_literal(result.args_literal) == ({3},)

    def test_frozenset_candidates_keep_their_type(self) -> None:
        # frozenset reprs do not survive the input-literal transport today, so the shrinker
        # is exercised directly: every candidate must stay a frozenset.
        candidates = list(_shrink_value(frozenset({3, 7})))
        assert (frozenset(), "set[2]→empty") == candidates[0]
        assert all(isinstance(value, frozenset) for value, _ in candidates)
        assert frozenset({7}) in {value for value, _ in candidates}

    def test_kwargs_are_dropped_and_shrunk(self) -> None:
        def rerun(args_literal: str, kwargs_literal: str) -> Diverged | None:
            kwargs = cast("dict[str, object]", parse_input_literal(kwargs_literal))
            if kwargs.get("keep") == 5:
                return Diverged(DivergenceClass.RETURN_VALUE, Severity.NORMAL, "differs")
            return None

        result = minimize_input(rerun, "()", "{'junk': 'abc', 'keep': 5}")
        assert result is not None
        assert parse_input_literal(result.kwargs_literal) == {"keep": 5}
        assert any("junk" in note for note in result.shrink_path)

    def test_depth_guard_stops_recursive_shrinking(self) -> None:
        assert list(_shrink_value(7, depth=5)) == []
        rerun = _rerun_factory(lambda args: "5" in repr(args))
        result = minimize_input(rerun, "([[[[[[5]]]]]],)", "{}")
        assert result is not None
        assert "5" in result.args_literal  # the divergence-carrying leaf survives


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
