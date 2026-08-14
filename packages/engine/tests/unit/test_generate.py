"""Stage 5: type-derived + corpus-mined + mutation-based input generation.

Everything generated must be transportable (repr → ast.literal_eval round-trip) and deterministic
under a fixed seed (Law L3 applies to Tempest itself)."""

import ast
from pathlib import Path

from tempest.execute.runner import ParamInfo, TargetIntrospection
from tempest.generate.inputs import Budget, generate_inputs
from tempest.generate.mining import mine_literals
from tempest.generate.mutate import mutate_input
from tempest.generate.strategies import parse_annotation, values_for


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

    def test_mining_caps_volume(self, tmp_path: Path) -> None:
        body = "\n".join(f"V{i} = {i}" for i in range(5000))
        (tmp_path / "big.py").write_text(body + "\n")
        assert len(mine_literals(tmp_path)) <= 500


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
