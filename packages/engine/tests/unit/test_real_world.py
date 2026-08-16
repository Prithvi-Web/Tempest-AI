"""The real-world proof-rate table (HANDOFF-WORLD-CLASS 2.2) — the rendering and the math.

The measurement itself needs network clones and hours of execution; what MUST be pinned is
that the table never lies: rates computed from the actual verdict counts, zero-target repos
render without division blowups, and the UNPROVEN reason distribution names real targets
(the distribution IS the engine roadmap).
"""

from tempest.bundle.bundle import TargetRecord
from tempest.dev.real_world import RepoResult, render_real_world_table
from tempest.model import Lang, ReasonCode, TargetClassification, Verdict


def _record(
    module: str,
    verdict: Verdict,
    reason: ReasonCode | None = None,
    detail: str | None = None,
) -> TargetRecord:
    return TargetRecord(
        file_path=f"{module.replace('.', '/')}.py",
        module=module,
        qualname="fn",
        lang=Lang.PYTHON,
        classification=TargetClassification.PURE_CANDIDATE,
        verdict=verdict,
        reason_code=reason,
        reason_detail=detail,
        inputs_run=10,
        equivalent_inputs=10 if verdict is Verdict.EQUIVALENT_UNDER_BUDGET else 0,
        unprovable_inputs=0,
        changed_line_coverage=100.0,
        divergences=(),
    )


def _result(name: str, records: list[TargetRecord]) -> RepoResult:
    return RepoResult(
        name=name,
        url=f"https://github.com/example/{name}",
        base_ref="v1",
        head_ref="v2",
        base_sha="a" * 40,
        head_sha="b" * 40,
        sandbox_tier="T2",
        records=tuple(records),
    )


class TestRenderRealWorldTable:
    def test_rates_come_from_the_actual_counts(self) -> None:
        out = render_real_world_table(
            [
                _result(
                    "alpha",
                    [
                        _record("a.one", Verdict.DIVERGENT),
                        _record("a.two", Verdict.EQUIVALENT_UNDER_BUDGET),
                        _record(
                            "a.three",
                            Verdict.UNPROVEN,
                            ReasonCode.TARGET_UNREACHABLE,
                            "instance method",
                        ),
                        _record(
                            "a.four",
                            Verdict.UNPROVEN,
                            ReasonCode.NONDETERMINISTIC_BASE,
                            "time-dependent",
                        ),
                    ],
                )
            ]
        )
        assert "| alpha |" in out
        assert "2/4" in out and "50%" in out
        # Reason distribution names the code, not just the count (L1: evidence).
        assert "TARGET_UNREACHABLE" in out and "a.three" in out
        assert "NONDETERMINISTIC_BASE" in out and "a.four" in out
        assert "aaaaaaaaaaaa" in out and "bbbbbbbbbbbb" in out  # exact SHAs recorded

    def test_overall_row_sums_every_repo(self) -> None:
        out = render_real_world_table(
            [
                _result("alpha", [_record("a.one", Verdict.DIVERGENT)]),
                _result(
                    "beta",
                    [
                        _record("b.one", Verdict.EQUIVALENT_UNDER_BUDGET),
                        _record("b.two", Verdict.UNPROVEN, ReasonCode.TARGET_UNREACHABLE, "method"),
                    ],
                ),
            ]
        )
        assert "2/3" in out and "67%" in out

    def test_zero_targets_render_honestly_without_blowups(self) -> None:
        out = render_real_world_table([_result("quiet", [])])
        assert "0/0" in out
        assert "n/a" in out

    def test_the_forbidden_word_never_appears(self) -> None:
        out = render_real_world_table(
            [_result("alpha", [_record("a.one", Verdict.EQUIVALENT_UNDER_BUDGET)])]
        )
        assert "SAFE" not in out.upper().replace("UNSAFE", "")
