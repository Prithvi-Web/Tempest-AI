"""Stage 7 foundation: canonical value encoding.

Requirements under test (master spec stage 7):
- dicts/objects key-sorted; sets order-normalized
- NaN equals NaN; -0.0 vs 0.0 must remain distinguishable (a distinct low-severity class)
- unserializable objects fall back to a structural fingerprint; if that fails, the value is
  explicitly Unrepresentable — never silently equal
- canonical encoding is byte-deterministic: equal values → identical bytes
"""

import math
from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tempest.compare.canonical import Unrepresentable, canonical_bytes, canonicalize


def cb(obj: object) -> bytes:
    return canonical_bytes(canonicalize(obj))


class TestScalars:
    def test_json_scalars_survive_roundtrip_distinctly(self) -> None:
        values = [None, True, False, 0, 1, -7, 10**30, "", "hello", "0", "None"]
        encodings = [cb(v) for v in values]
        assert len(set(encodings)) == len(values), "distinct scalars must encode distinctly"

    def test_bool_is_not_int(self) -> None:
        assert cb(True) != cb(1)
        assert cb(False) != cb(0)

    def test_str_zero_is_not_int_zero(self) -> None:
        assert cb("0") != cb(0)


class TestFloats:
    def test_nan_equals_nan(self) -> None:
        assert cb(float("nan")) == cb(float("nan"))

    def test_negative_zero_distinguished_from_positive_zero(self) -> None:
        assert cb(-0.0) != cb(0.0)

    def test_infinities_are_distinct(self) -> None:
        assert cb(float("inf")) != cb(float("-inf"))

    def test_float_int_equal_value_distinct_encoding(self) -> None:
        assert cb(1.0) != cb(1)

    @given(st.floats(allow_nan=False))
    def test_float_encoding_is_injective_on_reals(self, x: float) -> None:
        assert cb(x) == cb(x)
        if x != 0.0 and not math.isnan(x):
            assert cb(x) != cb(-x)


class TestContainers:
    def test_dict_key_order_is_normalized(self) -> None:
        assert cb({"a": 1, "b": 2}) == cb({"b": 2, "a": 1})

    def test_set_order_is_normalized(self) -> None:
        assert cb({3, 1, 2}) == cb({2, 3, 1})
        assert cb(frozenset({1, 2})) == cb(frozenset({2, 1}))

    def test_set_and_frozenset_distinct(self) -> None:
        assert cb({1}) != cb(frozenset({1}))

    def test_tuple_and_list_distinct(self) -> None:
        assert cb((1, 2)) != cb([1, 2])

    def test_bytes_and_str_distinct(self) -> None:
        assert cb(b"abc") != cb("abc")

    def test_non_string_dict_keys(self) -> None:
        assert cb({1: "a", (2, 3): "b"}) == cb({(2, 3): "b", 1: "a"})

    def test_nested_normalization(self) -> None:
        a = {"outer": [{"x": {1, 2}}, ("t", b"\x00")]}
        b = {"outer": [{"x": {2, 1}}, ("t", b"\x00")]}
        assert cb(a) == cb(b)

    @given(
        st.dictionaries(
            st.text(max_size=5),
            st.one_of(st.integers(), st.text(max_size=5), st.booleans(), st.none()),
            max_size=6,
        )
    )
    def test_dict_encoding_invariant_under_insertion_order(self, d: dict[str, object]) -> None:
        items = list(d.items())
        reordered = dict(reversed(items))
        assert cb(d) == cb(reordered)


@dataclass
class Point:
    x: int
    y: int


class Opaque:
    """No __eq__, not serializable by value — must fingerprint structurally."""

    def __init__(self) -> None:
        self.a = 1
        self._private = 2


class TestObjects:
    def test_dataclass_fingerprint_includes_type_and_fields(self) -> None:
        assert cb(Point(1, 2)) == cb(Point(1, 2))
        assert cb(Point(1, 2)) != cb(Point(1, 3))

    def test_objects_of_different_types_with_same_attrs_differ(self) -> None:
        @dataclass
        class Point2:
            x: int
            y: int

        assert cb(Point(1, 2)) != cb(Point2(1, 2))

    def test_plain_object_fingerprints_public_attrs(self) -> None:
        assert cb(Opaque()) == cb(Opaque())

    def test_private_attrs_excluded_from_fingerprint(self) -> None:
        a, b = Opaque(), Opaque()
        b._private = 999
        assert cb(a) == cb(b)

    def test_public_attr_change_alters_fingerprint(self) -> None:
        a, b = Opaque(), Opaque()
        b.a = 999
        assert cb(a) != cb(b)


class TestUnrepresentable:
    def test_lambda_is_unrepresentable_not_silently_equal(self) -> None:
        with pytest.raises(Unrepresentable):
            canonicalize(lambda: 1)

    def test_cycle_is_unrepresentable(self) -> None:
        lst: list[object] = []
        lst.append(lst)
        with pytest.raises(Unrepresentable):
            canonicalize(lst)

    def test_extreme_depth_is_unrepresentable(self) -> None:
        deep: object = 0
        for _ in range(200):
            deep = [deep]
        with pytest.raises(Unrepresentable):
            canonicalize(deep)


class TestDeterminism:
    @given(
        st.recursive(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.floats(),
                st.text(max_size=8),
                st.binary(max_size=8),
            ),
            lambda children: st.one_of(
                st.lists(children, max_size=4),
                st.dictionaries(st.text(max_size=4), children, max_size=4),
                st.tuples(children),
            ),
            max_leaves=12,
        )
    )
    def test_encoding_is_stable_across_calls(self, value: object) -> None:
        assert cb(value) == cb(value)
