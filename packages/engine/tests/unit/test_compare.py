"""Observation comparison → DivergenceClass (master spec stage 7).

Precedence and honesty rules under test:
- hang/crash asymmetry outranks value comparison; identical crashes are NOT divergence
- raised-vs-returned and exception type/message classes
- return values via canonical equality; -0.0 vs 0.0 is a LOW-severity RETURN_VALUE finding
- float tolerance is opt-in and silences only float-magnitude diffs
- output streams compared normalized
- effect ledgers: first divergent index reported (Phase 2 fills recording; comparison is generic)
- unrepresentable values are UNPROVABLE for that input — never silently equal
- timing is never compared
"""

from dataclasses import dataclass

from tempest.compare.compare import CompareConfig, Diverged, Equal, Unprovable, compare
from tempest.model import (
    DivergenceClass,
    EffectEntry,
    InputOutcome,
    Observation,
    RaisedInfo,
    Severity,
    Timing,
)


def obs(
    *,
    returned: object = None,
    has_return: bool = True,
    raised: RaisedInfo | None = None,
    stdout: str = "",
    stderr: str = "",
    effects: tuple[EffectEntry, ...] = (),
    outcome: InputOutcome = InputOutcome.COMPLETED,
    exit_status: int = 0,
    unrepresentable: str | None = None,
    cassette_miss: str | None = None,
    uninterceptable: str | None = None,
    wall_ns: int = 1000,
) -> Observation:
    return Observation(
        outcome=outcome,
        return_present=has_return and raised is None,
        return_canon=None if raised is not None or not has_return else _canon(returned),
        raised=raised,
        effects=effects,
        stdout=stdout,
        stderr=stderr,
        exit_status=exit_status,
        timing=Timing(wall_ns=wall_ns, cpu_ns=wall_ns // 2),
        unrepresentable=unrepresentable,
        cassette_miss=cassette_miss,
        uninterceptable=uninterceptable,
    )


def raw_obs(return_canon: object) -> Observation:
    """An Observation carrying a hand-built canonical tree, as rebuilt from a stored bundle."""
    return Observation(
        outcome=InputOutcome.COMPLETED,
        return_present=True,
        return_canon=return_canon,
        raised=None,
        exit_status=0,
        timing=Timing(wall_ns=1000, cpu_ns=500),
    )


def _canon(v: object) -> object:
    from tempest.compare.canonical import canonicalize

    return canonicalize(v)


@dataclass
class Point:
    x: int
    y: int


@dataclass
class OtherPoint:
    x: int
    y: int


CFG = CompareConfig()


class TestOutcomePrecedence:
    def test_identical_returns_are_equal(self) -> None:
        assert compare(obs(returned=42), obs(returned=42), CFG) == Equal()

    def test_hang_on_one_side_is_HANG(self) -> None:
        result = compare(obs(returned=1), obs(outcome=InputOutcome.HUNG, has_return=False), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.HANG
        assert result.severity is Severity.HEADLINE

    def test_crash_on_one_side_is_CRASH(self) -> None:
        result = compare(
            obs(returned=1),
            obs(outcome=InputOutcome.CRASHED, has_return=False, exit_status=-11),
            CFG,
        )
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.CRASH
        assert result.severity is Severity.HEADLINE

    def test_identical_crashes_are_equal_behavior(self) -> None:
        a = obs(outcome=InputOutcome.CRASHED, has_return=False, exit_status=-11)
        b = obs(outcome=InputOutcome.CRASHED, has_return=False, exit_status=-11)
        assert compare(a, b, CFG) == Equal()

    def test_timing_difference_alone_is_never_divergence(self) -> None:
        assert (
            compare(obs(returned=1, wall_ns=10), obs(returned=1, wall_ns=10_000_000), CFG)
            == Equal()
        )


class TestExceptions:
    def test_raised_vs_returned_is_EXCEPTION_TYPE(self) -> None:
        r = RaisedInfo(type_name="ValueError", module="builtins", message="bad")
        result = compare(obs(returned=1), obs(raised=r), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EXCEPTION_TYPE

    def test_different_exception_types_are_EXCEPTION_TYPE(self) -> None:
        a = RaisedInfo(type_name="ValueError", module="builtins", message="x")
        b = RaisedInfo(type_name="KeyError", module="builtins", message="x")
        result = compare(obs(raised=a), obs(raised=b), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EXCEPTION_TYPE

    def test_same_type_different_message_is_EXCEPTION_MESSAGE(self) -> None:
        a = RaisedInfo(type_name="ValueError", module="builtins", message="expected 5")
        b = RaisedInfo(type_name="ValueError", module="builtins", message="expected 6")
        result = compare(obs(raised=a), obs(raised=b), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EXCEPTION_MESSAGE

    def test_messages_differing_only_in_memory_address_are_equal(self) -> None:
        a = RaisedInfo("TypeError", "builtins", "<Foo object at 0x7f00> is not callable")
        b = RaisedInfo("TypeError", "builtins", "<Foo object at 0x105a> is not callable")
        assert compare(obs(raised=a), obs(raised=b), CFG) == Equal()


class TestReturnValues:
    def test_different_returns_are_RETURN_VALUE(self) -> None:
        result = compare(obs(returned={"a": 1}), obs(returned={"a": 2}), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.RETURN_VALUE
        assert result.severity is Severity.NORMAL

    def test_negative_zero_is_LOW_severity_RETURN_VALUE(self) -> None:
        result = compare(obs(returned=0.0), obs(returned=-0.0), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.RETURN_VALUE
        assert result.severity is Severity.LOW

    def test_nan_equals_nan(self) -> None:
        assert compare(obs(returned=float("nan")), obs(returned=float("nan")), CFG) == Equal()

    def test_float_tolerance_is_opt_in(self) -> None:
        exact = compare(obs(returned=0.1 + 0.2), obs(returned=0.3), CFG)
        assert isinstance(exact, Diverged)
        tolerant = compare(
            obs(returned=0.1 + 0.2),
            obs(returned=0.3),
            CompareConfig(float_rel_tol=1e-9),
        )
        assert tolerant == Equal()

    def test_tolerance_does_not_mask_non_float_diffs(self) -> None:
        result = compare(obs(returned="a"), obs(returned="b"), CompareConfig(float_rel_tol=1e-9))
        assert isinstance(result, Diverged)


class TestStreams:
    def test_stdout_difference_is_OUTPUT_STREAM(self) -> None:
        result = compare(obs(returned=1, stdout="hi\n"), obs(returned=1, stdout="ho\n"), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.OUTPUT_STREAM

    def test_stream_diffs_only_in_tmp_paths_are_equal(self) -> None:
        a = obs(returned=1, stderr="wrote /tmp/tmpaaa/x")
        b = obs(returned=1, stderr="wrote /tmp/tmpbbb/x")
        assert compare(a, b, CFG) == Equal()


class TestEffects:
    def test_effect_sequence_difference_reports_first_divergent_index(self) -> None:
        e = lambda call, ordinal: EffectEntry(  # noqa: E731
            surface="NET", call=call, ordinal=ordinal, args_fingerprint="fp"
        )
        base = (e("GET /v1", 0), e("GET /v2", 1))
        head = (e("GET /v1", 0), e("GET /v3", 1))
        result = compare(obs(returned=1, effects=base), obs(returned=1, effects=head), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EFFECT_SEQUENCE
        assert result.first_divergent_effect == 1

    def test_extra_head_effect_diverges(self) -> None:
        e = EffectEntry(surface="FS", call="open r", ordinal=0, args_fingerprint="fp")
        result = compare(obs(returned=1, effects=()), obs(returned=1, effects=(e,)), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EFFECT_SEQUENCE
        assert result.first_divergent_effect == 0


class TestUnprovable:
    def test_unrepresentable_value_is_unprovable_not_equal(self) -> None:
        result = compare(
            obs(has_return=False, unrepresentable="no fingerprint for FooHandle"),
            obs(returned=1),
            CFG,
        )
        assert isinstance(result, Unprovable)
        assert "FooHandle" in result.reason

    def test_head_unrepresentable_is_unprovable_too(self) -> None:
        result = compare(obs(returned=1), obs(has_return=False, unrepresentable="FooHandle"), CFG)
        assert isinstance(result, Unprovable)
        assert result.reason.startswith("head")


class TestReplayPrecedence:
    """Replay-era fields outrank everything: honesty before value comparison."""

    def test_uninterceptable_base_is_unprovable(self) -> None:
        result = compare(
            obs(has_return=False, uninterceptable="socket.connect"), obs(returned=1), CFG
        )
        assert isinstance(result, Unprovable)
        assert "socket.connect" in result.reason

    def test_uninterceptable_head_is_unprovable(self) -> None:
        result = compare(
            obs(returned=1), obs(has_return=False, uninterceptable="socket.connect"), CFG
        )
        assert isinstance(result, Unprovable)
        assert result.reason.startswith("head")

    def test_head_only_cassette_miss_is_a_new_interaction_divergence(self) -> None:
        result = compare(obs(returned=1), obs(has_return=False, cassette_miss="GET /new"), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.CASSETTE_MISS
        assert "GET /new" in result.detail

    def test_base_cassette_miss_is_unprovable_replay_instability(self) -> None:
        result = compare(obs(has_return=False, cassette_miss="GET /a"), obs(returned=1), CFG)
        assert isinstance(result, Unprovable)
        assert "unstable" in result.reason

    def test_cassette_miss_on_both_sides_is_unprovable_not_divergent(self) -> None:
        result = compare(
            obs(has_return=False, cassette_miss="GET /a"),
            obs(has_return=False, cassette_miss="GET /a"),
            CFG,
        )
        assert isinstance(result, Unprovable)


class TestOutcomeBranches:
    def test_both_crashed_with_different_exits_is_CRASH(self) -> None:
        a = obs(outcome=InputOutcome.CRASHED, has_return=False, exit_status=-11)
        b = obs(outcome=InputOutcome.CRASHED, has_return=False, exit_status=-9)
        result = compare(a, b, CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.CRASH
        assert "differently" in result.detail

    def test_both_hung_is_equal_behavior(self) -> None:
        a = obs(outcome=InputOutcome.HUNG, has_return=False)
        b = obs(outcome=InputOutcome.HUNG, has_return=False)
        assert compare(a, b, CFG) == Equal()

    def test_stderr_difference_is_OUTPUT_STREAM(self) -> None:
        result = compare(
            obs(returned=1, stderr="warn A\n"), obs(returned=1, stderr="warn B\n"), CFG
        )
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.OUTPUT_STREAM
        assert "stderr" in result.detail

    def test_effect_argument_difference_is_EFFECT_ARGUMENTS(self) -> None:
        base = (EffectEntry(surface="NET", call="GET /v1", ordinal=0, args_fingerprint="aaaa"),)
        head = (EffectEntry(surface="NET", call="GET /v1", ordinal=0, args_fingerprint="bbbb"),)
        result = compare(obs(returned=1, effects=base), obs(returned=1, effects=head), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.EFFECT_ARGUMENTS
        assert result.first_divergent_effect == 0


class TestCanonicalTreeEquality:
    def test_equal_lists_are_equal(self) -> None:
        assert compare(obs(returned=[1, 2.5]), obs(returned=[1, 2.5]), CFG) == Equal()

    def test_list_length_difference_diverges(self) -> None:
        result = compare(obs(returned=[1]), obs(returned=[1, 1]), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.RETURN_VALUE

    def test_list_signed_zero_only_difference_is_LOW(self) -> None:
        result = compare(obs(returned=[0.0, 3]), obs(returned=[-0.0, 3]), CFG)
        assert isinstance(result, Diverged)
        assert result.severity is Severity.LOW

    def test_list_content_difference_is_NORMAL(self) -> None:
        result = compare(obs(returned=[1, "x"]), obs(returned=[1, "y"]), CFG)
        assert isinstance(result, Diverged)
        assert result.severity is Severity.NORMAL

    def test_mismatched_canonical_tags_diverge(self) -> None:
        result = compare(obs(returned=2.0), obs(returned=b"\x00"), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.RETURN_VALUE

    def test_container_vs_scalar_diverges(self) -> None:
        result = compare(obs(returned={"a": 1}), obs(returned=7), CFG)
        assert isinstance(result, Diverged)

    def test_bool_never_equals_int(self) -> None:
        result = compare(obs(returned=True), obs(returned=1), CFG)
        assert isinstance(result, Diverged)
        assert compare(obs(returned=True), obs(returned=True), CFG) == Equal()

    def test_dataclass_objects_compare_structurally(self) -> None:
        assert compare(obs(returned=Point(1, 2)), obs(returned=Point(1, 2)), CFG) == Equal()
        result = compare(obs(returned=Point(1, 2)), obs(returned=Point(1, 3)), CFG)
        assert isinstance(result, Diverged)

    def test_objects_of_different_types_diverge(self) -> None:
        result = compare(obs(returned=Point(1, 2)), obs(returned=OtherPoint(1, 2)), CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.RETURN_VALUE

    def test_bytes_returns_compare_by_payload(self) -> None:
        assert compare(obs(returned=b"a"), obs(returned=b"a"), CFG) == Equal()
        result = compare(obs(returned=b"a"), obs(returned=b"b"), CFG)
        assert isinstance(result, Diverged)

    def test_dict_key_difference_diverges(self) -> None:
        result = compare(obs(returned={"a": 1}), obs(returned={"b": 1}), CFG)
        assert isinstance(result, Diverged)

    def test_dict_extra_key_diverges(self) -> None:
        result = compare(obs(returned={"a": 1}), obs(returned={"a": 1, "b": 2}), CFG)
        assert isinstance(result, Diverged)

    def test_dict_second_value_difference_diverges(self) -> None:
        result = compare(obs(returned={"a": 1, "b": 2}), obs(returned={"a": 1, "b": 3}), CFG)
        assert isinstance(result, Diverged)
        assert result.severity is Severity.NORMAL

    def test_dict_signed_zero_value_is_LOW(self) -> None:
        result = compare(obs(returned={"a": 0.0}), obs(returned={"a": -0.0}), CFG)
        assert isinstance(result, Diverged)
        assert result.severity is Severity.LOW

    def test_nan_vs_number_diverges(self) -> None:
        result = compare(obs(returned=float("nan")), obs(returned=1.0), CFG)
        assert isinstance(result, Diverged)

    def test_tolerance_treats_signed_zero_as_equal(self) -> None:
        cfg = CompareConfig(float_rel_tol=1e-9)
        assert compare(obs(returned=0.0), obs(returned=-0.0), cfg) == Equal()


class TestForeignPayloads:
    """Observations are rebuilt from stored bundles; compare must stay total over canonical
    trees today's canonicalize() would not emit (foreign platforms, future schema versions)."""

    def test_unknown_matching_tags_fall_back_to_raw_equality(self) -> None:
        assert (
            compare(raw_obs({"__t": "custom", "v": 1}), raw_obs({"__t": "custom", "v": 1}), CFG)
            == Equal()
        )
        result = compare(
            raw_obs({"__t": "custom", "v": 1}), raw_obs({"__t": "custom", "v": 2}), CFG
        )
        assert isinstance(result, Diverged)

    def test_negative_nan_spelling_still_equals_nan(self) -> None:
        a = raw_obs({"__t": "float", "v": "-nan"})
        b = raw_obs({"__t": "float", "v": "nan"})
        assert compare(a, b, CFG) == Equal()

    def test_malformed_pair_entries_fall_back_to_raw_equality(self) -> None:
        assert (
            compare(
                raw_obs({"__t": "dict", "v": ["odd"]}), raw_obs({"__t": "dict", "v": ["odd"]}), CFG
            )
            == Equal()
        )
        result = compare(
            raw_obs({"__t": "dict", "v": ["odd"]}), raw_obs({"__t": "dict", "v": ["even"]}), CFG
        )
        assert isinstance(result, Diverged)
