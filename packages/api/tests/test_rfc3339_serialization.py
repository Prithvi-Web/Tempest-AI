"""API datetimes must honor the contract they publish (Boundary B, CLAUDE.md §9b).

The OpenAPI/domain schema declares `format: date-time` — RFC 3339, offset REQUIRED. Rows
store naive-UTC datetimes (ADR-0009 `utcnow`), and serializing them bare produces
`2026-08-15T05:31:36.201161` (no offset) — off-contract, caught live by the desktop's
dev-mode schema validation (the run view stalled on it). Every wire datetime therefore
serializes through the shared RFC 3339 UTC serializer, and the published schema keeps
`format: date-time` byte-identical.
"""

from datetime import UTC, datetime, timedelta, timezone

from tempest_api.schemas import RunEventOut, RunSummary

_RFC3339_SUFFIX = "Z"


def _summary(created_at: datetime) -> RunSummary:
    return RunSummary(
        id=1,
        repo="pyfix",
        base_sha="a" * 40,
        head_sha="b" * 40,
        status="COMPLETE",
        verdict="DIVERGENT",
        created_at=created_at,
        target_count=1,
        divergence_count=0,
    )


class TestWireFormat:
    def test_naive_utc_rows_serialize_with_an_explicit_offset(self) -> None:
        naive = datetime(2026, 8, 15, 5, 31, 36, 201161)  # exactly what utcnow() stores
        payload = _summary(naive).model_dump(mode="json")
        assert payload["created_at"] == "2026-08-15T05:31:36.201161Z"

    def test_aware_datetimes_normalize_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        aware = datetime(2026, 8, 15, 1, 31, 36, tzinfo=eastern)
        payload = _summary(aware).model_dump(mode="json")
        assert payload["created_at"] == "2026-08-15T05:31:36Z"

    def test_run_event_ts_serializes_with_an_explicit_offset(self) -> None:
        event = RunEventOut(
            ts=datetime(2026, 8, 15, 5, 31, 58, 613315),
            stage="complete",
            level="info",
            message="run complete",
        )
        assert event.model_dump(mode="json")["ts"] == "2026-08-15T05:31:58.613315Z"

    def test_already_utc_aware_values_stay_utc(self) -> None:
        aware = datetime(2026, 8, 15, 5, 31, 36, tzinfo=UTC)
        payload = _summary(aware).model_dump(mode="json")
        assert payload["created_at"] == "2026-08-15T05:31:36Z"


class TestPublishedSchema:
    def test_serialization_schema_still_declares_date_time(self) -> None:
        for model, field in ((RunSummary, "created_at"), (RunEventOut, "ts")):
            schema = model.model_json_schema(mode="serialization")
            prop = schema["properties"][field]
            assert prop == {
                "format": "date-time",
                "title": prop["title"],
                "type": "string",
            }, f"{model.__name__}.{field} must keep the exact date-time contract"
