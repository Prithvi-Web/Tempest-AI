"""Stage 5: type-derived + corpus-mined + mutation-based input generation.

Everything generated must be transportable (repr → ast.literal_eval round-trip) and deterministic
under a fixed seed (Law L3 applies to Tempest itself)."""

import ast
import random
import typing
from pathlib import Path

from hypothesis import strategies as st

from tempest.execute.runner import ParamInfo, TargetIntrospection
from tempest.generate.inputs import Budget, generate_inputs
from tempest.generate.mining import mine_literals
from tempest.generate.mutate import _mutate_value, mutate_input
from tempest.generate.strategies import (
    _edge_cases_for,
    _hypothesis_examples,
    parse_annotation,
    values_for,
)


def intro(*params: tuple[str, str | None, str | None]) -> TargetIntrospection:
    return TargetIntrospection(
        params=tuple(
            ParamInfo(name=n, kind="POSITIONAL_OR_KEYWORD", annotation=a, default_literal=d)
            for n, a, d in params
        )
    )


class TestParseAnnotation:
    def test_builtin_scalars(self) -> None:
        assert parse_annotation("int") is int
        assert parse_annotation("str") is str
        assert parse_annotation("float") is float
        assert parse_annotation("bool") is bool

    def test_generics(self) -> None:
        assert parse_annotation("list[int]") == list[int]
        assert parse_annotation("dict[str, int]") == dict[str, int]

    def test_optional_union(self) -> None:
        assert parse_annotation("int | None") == (int | None)

    def test_malicious_annotation_is_rejected_not_executed(self) -> None:
        assert parse_annotation("__import__('os').system('true')") is None
        assert parse_annotation("open('/etc/passwd')") is None

    def test_unknown_names_are_none(self) -> None:
        assert parse_annotation("SomeCustomThing") is None

    def test_unparseable_annotation_text_is_none(self) -> None:
        assert parse_annotation("list[int") is None

    def test_valid_shape_that_fails_to_evaluate_is_none(self) -> None:
        assert parse_annotation("int[str]") is None  # AST-valid, but int is not subscriptable


class TestValuesFor:
    def test_int_pool_hits_boundaries(self) -> None:
        values = values_for(int, seed=1, mined=[])
        assert 0 in values and -1 in values
        assert any(abs(v) > 2**30 for v in values if isinstance(v, int))

    def test_float_pool_includes_signed_zero_and_nan(self) -> None:
        values = values_for(float, seed=1, mined=[])
        reprs = {repr(v) for v in values}
        assert "-0.0" in reprs and "nan" in reprs

    def test_str_pool_includes_empty_and_unicode(self) -> None:
        values = values_for(str, seed=1, mined=[])
        assert "" in values
        assert any(any(ord(c) > 127 for c in v) for v in values if isinstance(v, str))

    def test_mined_values_are_included(self) -> None:
        values = values_for(str, seed=1, mined=["session-42", 17])
        assert "session-42" in values

    def test_deterministic_under_seed(self) -> None:
        assert values_for(int, seed=7, mined=[]) == values_for(int, seed=7, mined=[])

    def test_every_value_round_trips_as_literal(self) -> None:
        from tempest.compare.canonical import parse_input_literal

        for typ in (int, str, float, bool, list[int], dict[str, int], int | None):
            for v in values_for(typ, seed=3, mined=[]):
                assert parse_input_literal(repr(v)) == v or (v != v)  # NaN compares unequal


class TestValuesForEdges:
    def test_non_literal_mined_values_are_filtered_out(self) -> None:
        marker = object()  # repr does not round-trip as a literal
        values = values_for(None, seed=2, mined=[marker, 11])
        assert marker not in values
        assert 11 in values

    def test_mined_values_for_generic_annotations_pass_through(self) -> None:
        values = values_for(list[int], seed=2, mined=[[7, 8, 9]])
        assert [7, 8, 9] in values

    def test_union_edge_cases_include_both_sides(self) -> None:
        union_edges = _edge_cases_for(int | None)
        assert None in union_edges
        assert 0 in union_edges
        assert _edge_cases_for(typing.Optional) == []  # bare Optional carries no args

    def test_container_edge_cases_cover_each_origin(self) -> None:
        assert _edge_cases_for(tuple[int, str]) == [(0, 1)]
        assert _edge_cases_for(set[int]) == [set(), {0}]
        assert _edge_cases_for(frozenset[int]) == [frozenset(), frozenset({0})]

    def test_empty_set_survives_the_type_pool(self) -> None:
        assert set() in values_for(set[int], seed=4, mined=[])

    def test_failing_hypothesis_strategy_yields_no_examples(self) -> None:
        def boom() -> object:
            raise ValueError("no examples")

        assert _hypothesis_examples(st.builds(boom), 5) == []


class TestGenerateInputs:
    def test_inputs_cover_all_required_params(self) -> None:
        candidates = generate_inputs(
            intro(("a", "int", None), ("b", "str", None)), mined=[], budget=Budget(max_inputs=50)
        )
        assert candidates
        for c in candidates:
            args = ast.literal_eval(c.args_literal)
            assert len(args) == 2

    def test_defaulted_params_are_sometimes_omitted(self) -> None:
        candidates = generate_inputs(
            intro(("a", "int", None), ("b", "str", "'x'")), mined=[], budget=Budget(max_inputs=60)
        )
        arities = {len(ast.literal_eval(c.args_literal)) for c in candidates}
        assert arities == {1, 2}

    def test_untyped_params_get_mixed_pool(self) -> None:
        candidates = generate_inputs(
            intro(("a", None, None)), mined=[], budget=Budget(max_inputs=80)
        )
        types = {type(ast.literal_eval(c.args_literal)[0]) for c in candidates}
        assert len(types) >= 3

    def test_budget_caps_input_count(self) -> None:
        candidates = generate_inputs(
            intro(("a", "int", None)), mined=[], budget=Budget(max_inputs=10)
        )
        assert len(candidates) <= 10

    def test_deterministic_under_seed(self) -> None:
        a = generate_inputs(
            intro(("a", "int", None)), mined=[], budget=Budget(max_inputs=20, seed=5)
        )
        b = generate_inputs(
            intro(("a", "int", None)), mined=[], budget=Budget(max_inputs=20, seed=5)
        )
        assert a == b

    def test_keyword_only_params_populate_kwargs(self) -> None:
        introspection = TargetIntrospection(
            params=(
                ParamInfo(
                    name="a", kind="POSITIONAL_OR_KEYWORD", annotation="int", default_literal=None
                ),
                ParamInfo(
                    name="flag", kind="KEYWORD_ONLY", annotation="bool", default_literal=None
                ),
                ParamInfo(name="opt", kind="KEYWORD_ONLY", annotation="int", default_literal="7"),
            )
        )
        candidates = generate_inputs(introspection, mined=[], budget=Budget(max_inputs=40))
        assert candidates
        kwarg_sets = [set(ast.literal_eval(c.kwargs_literal)) for c in candidates]
        assert all("flag" in ks for ks in kwarg_sets)  # required keyword-only: always supplied
        assert {"opt" in ks for ks in kwarg_sets} == {True, False}  # defaulted: sometimes omitted


class TestMining:
    def test_literals_are_harvested_from_repo_sources(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text("THRESHOLD = 86400\n\n\ndef f(x):\n    return x\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_mod.py").write_text(
            "def test_f():\n    assert f('alpha-key') == 'alpha-key'\n"
        )
        mined = mine_literals(tmp_path)
        assert 86400 in mined
        assert "alpha-key" in mined

    def test_a_root_that_lives_under_a_skip_named_directory_is_still_mined(
        self, tmp_path: Path
    ) -> None:
        """Field recall bug, 2026-08-18 (trap 38): the engine's own worktrees live at
        `<repo>/.tempest/cache/worktrees/<sha>/`, and the skip check tested the FULL path's
        parts — so mining skipped every file of the very worktree it was asked to mine, and
        corpus mining was silently dead in every real prove. Only components BELOW the
        mining root may be skipped; the root's own location is not the root's business."""
        worktree = tmp_path / ".tempest" / "cache" / "worktrees" / "abc123def456"
        worktree.mkdir(parents=True)
        (worktree / "shipping.py").write_text("FREE_FROM = 5\nFLAT = 500\n")
        mined = mine_literals(worktree)
        assert 5 in mined
        assert 500 in mined

    def test_skip_directories_below_the_root_are_still_skipped(self, tmp_path: Path) -> None:
        root = tmp_path / ".venv" / "checkout"  # a skip-NAMED ancestor must not matter…
        (root / ".venv").mkdir(parents=True)  # …while a skip dir INSIDE the root must
        (root / "app.py").write_text("REAL = 777\n")
        (root / ".venv" / "vendored.py").write_text("NOISE = 999\n")
        mined = mine_literals(root)
        assert 777 in mined
        assert 999 not in mined

    def test_mining_caps_volume(self, tmp_path: Path) -> None:
        body = "\n".join(f"V{i} = {i}" for i in range(5000))
        (tmp_path / "big.py").write_text(body + "\n")
        assert len(mine_literals(tmp_path)) <= 500

    def test_syntax_error_files_are_skipped_not_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("def broken(:\n")
        (tmp_path / "ok.py").write_text("GOOD = 424242\n")
        assert 424242 in mine_literals(tmp_path)

    def test_uninformative_literals_are_excluded(self, tmp_path: Path) -> None:
        src = "A = True\nB = None\nC = ...\nD = ''\nE = " + repr("x" * 250) + "\nF = 31337\n"
        (tmp_path / "mod.py").write_text(src)
        mined = mine_literals(tmp_path)
        assert 31337 in mined
        assert not any(v is True or v is None or v is Ellipsis for v in mined)
        assert "" not in mined
        assert not any(isinstance(v, str) and len(v) > 200 for v in mined)


class TestMutation:
    def test_mutant_is_a_valid_literal_and_usually_different(self) -> None:
        seen_different = False
        for seed in range(10):
            mutant = mutate_input("(3, 'abc')", "{}", seed=seed)
            args = ast.literal_eval(mutant[0])
            assert isinstance(args, tuple)
            if mutant != ("(3, 'abc')", "{}"):
                seen_different = True
        assert seen_different

    def test_mutation_is_deterministic_per_seed(self) -> None:
        assert mutate_input("(3, 'abc')", "{}", seed=4) == mutate_input("(3, 'abc')", "{}", seed=4)


class TestMutationBranches:
    def test_unparseable_input_is_returned_unchanged(self) -> None:
        assert mutate_input("(unclosed", "{}", seed=0) == ("(unclosed", "{}")

    def test_kwargs_only_inputs_mutate_a_kwarg(self) -> None:
        seen_change = False
        for seed in range(8):
            args_literal, kwargs_literal = mutate_input("()", "{'a': 3}", seed=seed)
            assert args_literal == "()"
            mutated = ast.literal_eval(kwargs_literal)
            assert set(mutated) == {"a"}
            if mutated != {"a": 3}:
                seen_change = True
        assert seen_change

    def test_bytes_values_mutate_to_other_bytes(self) -> None:
        outs = {ast.literal_eval(mutate_input("(b'ab',)", "{}", seed=s)[0])[0] for s in range(10)}
        assert outs <= {b"", b"ab\x00", b"a"}
        assert b"ab" not in outs

    def test_empty_containers_get_seeded(self) -> None:
        assert ast.literal_eval(mutate_input("([],)", "{}", seed=1)[0])[0] == [0]
        assert ast.literal_eval(mutate_input("({},)", "{}", seed=1)[0])[0] == {"k": 0}

    def test_nonempty_dicts_drop_or_mutate_an_entry(self) -> None:
        seen_drop = seen_change = False
        for seed in range(20):
            out = ast.literal_eval(mutate_input("({'a': 1, 'b': 2},)", "{}", seed=seed)[0])[0]
            if set(out) != {"a", "b"}:
                seen_drop = True
            elif out != {"a": 1, "b": 2}:
                seen_change = True
        assert seen_drop and seen_change

    def test_sets_shrink_or_reseed(self) -> None:
        for seed in range(8):
            out = ast.literal_eval(mutate_input("({1, 2, 3},)", "{}", seed=seed)[0])[0]
            assert isinstance(out, set)
            assert out == {0} or out <= {1, 2, 3}

    def test_tuples_mutate_via_their_list_form(self) -> None:
        outs = {ast.literal_eval(mutate_input("((1, 2),)", "{}", seed=s)[0])[0] for s in range(8)}
        assert all(isinstance(o, tuple) for o in outs)
        assert any(o != (1, 2) for o in outs)

    def test_unknown_values_pass_through(self) -> None:
        assert mutate_input("(None,)", "{}", seed=3) == ("(None,)", "{}")

    def test_depth_guard_returns_the_value_unchanged(self) -> None:
        assert _mutate_value(41, random.Random(0), depth=5) == 41
