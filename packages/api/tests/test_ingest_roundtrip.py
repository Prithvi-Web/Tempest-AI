"""Phase 4 gate: CLI bundle → ingest → reconstruct through the public API → no data loss.

The reconstruction uses only endpoint responses (GET run/target/divergence + repro download) and
must equal the original `RunBundle` dataclass exactly — every field of every record survives.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tempest.bundle.bundle import (
    DivergenceRecord,
    RunBundle,
    RunManifest,
    TargetRecord,
    run_verdict,
)
from tempest.model import (
    BUNDLE_SCHEMA_VERSION,
    DivergenceClass,
    Lang,
    ReasonCode,
    Severity,
    TargetClassification,
    Verdict,
)


def _unicode_divergence(index: int) -> DivergenceRecord:
    """Quote-, newline- and non-ASCII-heavy fields — transport fidelity, not just happy ASCII."""
    return DivergenceRecord(
        divergence_class=DivergenceClass.EXCEPTION_MESSAGE,
        severity=Severity.HEADLINE,
        detail="message differs: \"héllo\n∆\" vs 'wörld'",
        args_literal="('π≈3.14159', nan)",
        kwargs_literal="{'k': -0.0}",
        minimized_args="('π',)",
        minimized_kwargs="{}",
        shrink_path=("args[0]: 'π≈3.14159'→'π'", "kwargs: dropped 'k'"),
        base_summary="raised ValueError('héllo')",
        head_summary="raised ValueError('wörld')",
        repro_filename=f"clamp_{index}.py",
    )


class TestFixedRoundTrip:
    def test_round_trip_no_data_loss(self, api) -> None:
        bundle = api.make_bundle(
            targets=(
                api.make_target((api.make_divergence(0), _unicode_divergence(1))),
                api.make_unproven_target(),
            ),
        )
        run_id = api.ingest(bundle)
        assert api.fetch_bundle(run_id) == bundle

    def test_run_detail_reports_ingested_state(self, api) -> None:
        run_id = api.ingest(api.make_bundle())
        run = api.get_json(f"/v1/runs/{run_id}")
        assert run["status"] == "COMPLETE"
        assert run["verdict"] == "DIVERGENT"
        assert run["target_count"] == 2
        assert run["divergence_count"] == 1
        assert run["schema_version"] == BUNDLE_SCHEMA_VERSION
        assert [t["qualname"] for t in run["targets"]] == ["clamp", "closure.inner"]
        unproven = run["targets"][1]
        assert unproven["verdict"] == "UNPROVEN"
        assert unproven["reason_code"] == "TARGET_UNREACHABLE"

    def test_repro_download_is_python_media_type_with_filename(self, api) -> None:
        run_id = api.ingest(api.make_bundle())
        run = api.get_json(f"/v1/runs/{run_id}")
        target = api.get_json(f"/v1/targets/{run['targets'][0]['id']}")
        divergence_id = target["divergences"][0]["id"]
        resp = api.client.get(f"/v1/divergences/{divergence_id}/repro.py")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/x-python")
        assert 'filename="clamp_0.py"' in resp.headers["content-disposition"]
        assert resp.text == "#!/usr/bin/env python3\nprint('repro clamp_0.py')\n"


# NUL is excluded (Postgres TEXT rejects it — ADR-0009 risk note) and surrogates are excluded
# (not UTF-8-encodable, so neither JSON nor the zip could carry them).
_CHARS = st.characters(min_codepoint=1, exclude_categories=("Cs",))
_TEXT = st.text(alphabet=_CHARS, max_size=40)
# File bodies additionally exclude "\r": the engine bundle reader uses read_text() whose
# universal-newline mode folds bare CR — a fidelity limit of the file transport, not the API.
_SCRIPT_TEXT = st.text(
    alphabet=st.characters(min_codepoint=1, exclude_categories=("Cs",), exclude_characters="\r"),
    max_size=120,
)
_REPO = st.text(alphabet=_CHARS, min_size=1, max_size=60)
_SHA = st.text(alphabet="0123456789abcdef", min_size=40, max_size=40)
_COUNT = st.integers(0, 2**31 - 1)


@st.composite
def bundles(draw: st.DrawFn) -> RunBundle:
    repro_scripts: dict[str, str] = {}
    targets: list[TargetRecord] = []
    script_index = 0
    for _ in range(draw(st.integers(0, 3))):
        divergences: list[DivergenceRecord] = []
        for _ in range(draw(st.integers(0, 2))):
            filename = f"repro_{script_index}.py"
            script_index += 1
            repro_scripts[filename] = draw(_SCRIPT_TEXT)
            divergences.append(
                DivergenceRecord(
                    divergence_class=draw(st.sampled_from(DivergenceClass)),
                    severity=draw(st.sampled_from(Severity)),
                    detail=draw(_TEXT),
                    args_literal=draw(_TEXT),
                    kwargs_literal=draw(_TEXT),
                    minimized_args=draw(_TEXT),
                    minimized_kwargs=draw(_TEXT),
                    shrink_path=tuple(draw(st.lists(_TEXT, max_size=3))),
                    base_summary=draw(_TEXT),
                    head_summary=draw(_TEXT),
                    repro_filename=filename,
                )
            )
        if divergences:
            verdict = Verdict.DIVERGENT
            reason_code = None
        else:
            verdict = draw(
                st.sampled_from([Verdict.EQUIVALENT_UNDER_BUDGET, Verdict.UNPROVEN, Verdict.ERROR])
            )
            reason_code = draw(st.sampled_from(ReasonCode)) if verdict is Verdict.UNPROVEN else None
        targets.append(
            TargetRecord(
                file_path=draw(_TEXT),
                module=draw(_TEXT),
                qualname=draw(_TEXT),
                lang=draw(st.sampled_from(Lang)),
                classification=draw(st.sampled_from(TargetClassification)),
                verdict=verdict,
                reason_code=reason_code,
                reason_detail=draw(st.none() | _TEXT),
                inputs_run=draw(_COUNT),
                equivalent_inputs=draw(_COUNT),
                unprovable_inputs=draw(_COUNT),
                changed_line_coverage=draw(st.floats(0, 1, allow_nan=False)),
                divergences=tuple(divergences),
            )
        )
    manifest = RunManifest(
        schema_version=BUNDLE_SCHEMA_VERSION,
        engine_version=draw(_TEXT),
        repo=draw(_REPO),
        base_sha=draw(_SHA),
        head_sha=draw(_SHA),
        created_at=draw(_TEXT),
        verdict=run_verdict(tuple(targets)),
        base_deps=draw(_TEXT),
        head_deps=draw(_TEXT),
        budget_max_inputs=draw(_COUNT),
    )
    return RunBundle(manifest=manifest, targets=tuple(targets), repro_scripts=repro_scripts)


class TestRoundTripProperty:
    # One app+database serves every example; each example ingests into its own fresh run, so
    # examples stay independent — the sanctioned use of this suppression.
    @settings(
        max_examples=25,
        deadline=None,
        derandomize=True,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(bundle=bundles())
    def test_any_valid_bundle_round_trips_without_loss(self, api, bundle: RunBundle) -> None:
        run_id = api.ingest(bundle)
        assert api.fetch_bundle(run_id) == bundle
