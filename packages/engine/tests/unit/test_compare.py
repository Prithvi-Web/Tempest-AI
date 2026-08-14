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
    )


def _canon(v: object) -> object:
    from tempest.compare.canonical import canonicalize

    return canonicalize(v)


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
