"""The verdict vocabulary is a law (L2), not a convention — pin it with tests."""

from tempest.model import DivergenceClass, ReasonCode, Verdict


def test_verdict_vocabulary_is_exactly_the_four_lawful_verdicts() -> None:
    assert {v.value for v in Verdict} == {
        "DIVERGENT",
        "EQUIVALENT_UNDER_BUDGET",
        "UNPROVEN",
        "ERROR",
    }


def test_divergence_taxonomy_matches_master_spec_stage_7() -> None:
    assert {d.value for d in DivergenceClass} == {
        "RETURN_VALUE",
        "EXCEPTION_TYPE",
        "EXCEPTION_MESSAGE",
        "EFFECT_SEQUENCE",
        "EFFECT_ARGUMENTS",
        "CASSETTE_MISS",
        "CRASH",
        "HANG",
        "OUTPUT_STREAM",
    }


def test_every_reason_code_is_self_describing_screaming_snake() -> None:
    for code in ReasonCode:
        assert code.value == code.name
        assert code.value.isupper()


def test_enums_serialize_as_plain_strings() -> None:
    assert f"{Verdict.DIVERGENT}" == "DIVERGENT"
    assert Verdict.UNPROVEN == "UNPROVEN"
