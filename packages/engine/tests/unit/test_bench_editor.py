"""Phase 20.1b: the webview measurements bench merges, and the states in which it must NOT.

The property under test is refusal. A budget that reads "met" because a file was missing, empty,
truncated or an anecdote is worse than no budget at all (L22), so every degenerate input below
must produce silence — which `perf_suite` renders as NOT-YET-MEASURED.

States enumerated before the tests (trap 43): file absent · malformed JSON · not an object ·
no `samples` key · `samples` not an object · a series that is not a list · a series of fewer
than five readings · a series with non-numeric entries · one metric present and not the other ·
both present.
"""

import json
import subprocess
from pathlib import Path

from tempest.dev.bench import _editor_measurements

EMPTY: tuple[dict[str, float], dict[str, list[float]], None] = ({}, {}, None)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(tmp_path: Path, doc: object) -> Path:
    path = tmp_path / "editor-metrics.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_an_absent_file_measures_nothing(tmp_path: Path) -> None:
    assert _editor_measurements(tmp_path / "nope.json") == EMPTY


def test_malformed_json_measures_nothing(tmp_path: Path) -> None:
    path = tmp_path / "editor-metrics.json"
    path.write_text("{not json", encoding="utf-8")
    assert _editor_measurements(path) == EMPTY


def test_a_non_object_document_measures_nothing(tmp_path: Path) -> None:
    assert _editor_measurements(_write(tmp_path, [1, 2, 3])) == EMPTY


def test_a_document_without_samples_measures_nothing(tmp_path: Path) -> None:
    assert _editor_measurements(_write(tmp_path, {"commit": "abc"})) == EMPTY


def test_samples_that_are_not_an_object_measure_nothing(tmp_path: Path) -> None:
    assert _editor_measurements(_write(tmp_path, {"samples": "lots"})) == EMPTY


def test_a_series_that_is_not_a_list_is_skipped(tmp_path: Path) -> None:
    assert _editor_measurements(_write(tmp_path, {"samples": {"open_file_ms": 12.0}})) == EMPTY


def test_fewer_than_five_readings_is_an_anecdote_and_is_refused(tmp_path: Path) -> None:
    # A p50 over one reading IS that reading. Arming a 40 ms budget on a single sample would let
    # one lucky open declare the budget met.
    doc = {"samples": {"open_file_ms": [10.0, 11.0, 12.0, 13.0]}}
    assert _editor_measurements(_write(tmp_path, doc)) == EMPTY


def test_exactly_five_readings_is_enough(tmp_path: Path) -> None:
    doc = {"samples": {"open_file_ms": [10.0, 12.0, 11.0, 13.0, 14.0]}}
    metrics, samples, provenance = _editor_measurements(_write(tmp_path, doc))
    assert metrics == {"open_file_ms": 12.0}
    assert samples == {"open_file_ms": [10.0, 12.0, 11.0, 13.0, 14.0]}
    assert provenance is not None
    assert provenance["counts"] == {"open_file_ms": 5}


def test_non_numeric_entries_are_dropped_not_coerced(tmp_path: Path) -> None:
    doc = {"samples": {"keystroke_ms": [1.0, "slow", 2.0, None, 3.0, 4.0, 5.0]}}
    metrics, samples, _ = _editor_measurements(_write(tmp_path, doc))
    assert samples == {"keystroke_ms": [1.0, 2.0, 3.0, 4.0, 5.0]}
    assert metrics == {"keystroke_ms": 3.0}


def test_one_metric_present_does_not_invent_the_other(tmp_path: Path) -> None:
    doc = {"samples": {"keystroke_ms": [1.0, 2.0, 3.0, 4.0, 5.0]}}
    metrics, samples, _ = _editor_measurements(_write(tmp_path, doc))
    assert "open_file_ms" not in metrics
    assert "open_file_ms" not in samples


def test_both_metrics_ride_through_with_provenance(tmp_path: Path) -> None:
    # The commit must be THIS one: a measurement recorded against any other is stale and is
    # discarded (see the staleness tests below). Using a placeholder here would have made this
    # test assert the merge of something the merge now refuses.
    doc = {
        "commit": _head(),
        "measured_at": "2026-08-19T00:00:00Z",
        "samples": {
            "open_file_ms": [30.0, 31.0, 32.0, 33.0, 34.0],
            "keystroke_ms": [4.0, 5.0, 6.0, 7.0, 8.0],
        },
    }
    metrics, samples, provenance = _editor_measurements(_write(tmp_path, doc))
    assert metrics == {"open_file_ms": 32.0, "keystroke_ms": 6.0}
    assert set(samples) == {"open_file_ms", "keystroke_ms"}
    assert provenance == {
        "commit": _head(),
        "measured_at": "2026-08-19T00:00:00Z",
        "counts": {"open_file_ms": 5, "keystroke_ms": 5},
    }


def test_a_measurement_from_another_commit_is_discarded_not_merged(tmp_path: Path) -> None:
    """Recording provenance is not the same as acting on it.

    The first version wrote the commit into bench.json and claimed a stale file "cannot pass as
    this run's work" — while nothing read it back. A measurement of code that no longer exists
    must leave the budgets NOT-YET-MEASURED, not arm them.
    """
    doc = {
        "commit": "0000000000000000000000000000000000000000",
        "samples": {"open_file_ms": [10.0, 11.0, 12.0, 13.0, 14.0]},
    }
    assert _editor_measurements(_write(tmp_path, doc)) == EMPTY


def test_a_measurement_from_this_commit_is_merged(tmp_path: Path) -> None:
    doc = {"commit": _head(), "samples": {"open_file_ms": [10.0, 11.0, 12.0, 13.0, 14.0]}}
    metrics, _, provenance = _editor_measurements(_write(tmp_path, doc))
    assert metrics == {"open_file_ms": 12.0}
    assert provenance is not None and provenance["commit"] == _head()


def test_a_measurement_with_no_commit_recorded_is_still_used(tmp_path: Path) -> None:
    """Absent provenance is not evidence of staleness — only a MISMATCH is."""
    doc = {"samples": {"open_file_ms": [10.0, 11.0, 12.0, 13.0, 14.0]}}
    metrics, _, _ = _editor_measurements(_write(tmp_path, doc))
    assert metrics == {"open_file_ms": 12.0}
