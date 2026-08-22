"""C3: the merged-app cold-launch samples bench merges, and the states in which it must NOT.

Same property as the editor leg: refusal. A budget that reads "met" because a file was missing,
stale, or an anecdote is worse than no budget at all (L22), so every degenerate input below
must produce silence — which `perf_suite` renders as NOT-YET-MEASURED.

States enumerated before the tests (trap 43): file absent · malformed JSON · not an object ·
no `samples` key · `samples` not an object · series not a list · fewer than three launches ·
non-numeric entries diluting below three · a file from ANOTHER COMMIT (provenance is checked,
not merely recorded) · a good file. Plus the instrument parser's own arms, and the `--help`
wiring pin (a gate module without a `__main__` guard exits 0 silently under `python -m`).
"""

import json
import subprocess
import sys
from pathlib import Path

from tempest.dev.bench import _merged_measurements
from tempest.dev.bench_merged import parse_instrument

EMPTY: tuple[dict[str, float], dict[str, list[float]], None] = ({}, {}, None)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(tmp_path: Path, doc: object) -> Path:
    path = tmp_path / "merged-metrics.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _good_doc(commit: str) -> dict[str, object]:
    return {
        "commit": commit,
        "measured_at": "2026-08-22T07:00:00+00:00",
        "app": "/Applications/Tempest AI.app/Contents/MacOS/tempest-desktop",
        "samples": {"merged_cold_launch_ms": [673.0, 662.0, 611.0]},
    }


class TestTheInstrumentParser:
    def test_the_real_line_parses(self) -> None:
        assert parse_instrument("[tempest-perf] merged_cold_launch_ms=662") == 662.0

    def test_a_trailing_newline_parses(self) -> None:
        assert parse_instrument("[tempest-perf] merged_cold_launch_ms=611\n") == 611.0

    def test_other_stderr_lines_are_not_samples(self) -> None:
        assert parse_instrument("[tempest-platform] boundary: listening on /tmp/x.sock") is None

    def test_a_mangled_value_is_not_a_sample(self) -> None:
        assert parse_instrument("[tempest-perf] merged_cold_launch_ms=fast") is None

    def test_the_line_must_stand_alone(self) -> None:
        """A prefix-matched line inside other output must not smuggle a number in."""
        assert parse_instrument("x [tempest-perf] merged_cold_launch_ms=1") is None


class TestRefusalStates:
    def test_an_absent_file_measures_nothing(self, tmp_path: Path) -> None:
        assert _merged_measurements(tmp_path / "nope.json") == EMPTY

    def test_malformed_json_measures_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "merged-metrics.json"
        path.write_text("{not json", encoding="utf-8")
        assert _merged_measurements(path) == EMPTY

    def test_a_non_object_measures_nothing(self, tmp_path: Path) -> None:
        assert _merged_measurements(_write(tmp_path, [1, 2, 3])) == EMPTY

    def test_missing_samples_measures_nothing(self, tmp_path: Path) -> None:
        assert _merged_measurements(_write(tmp_path, {"commit": _head()})) == EMPTY

    def test_samples_that_are_not_an_object_measure_nothing(self, tmp_path: Path) -> None:
        doc = _good_doc(_head())
        doc["samples"] = [673.0]
        assert _merged_measurements(_write(tmp_path, doc)) == EMPTY

    def test_a_series_that_is_not_a_list_measures_nothing(self, tmp_path: Path) -> None:
        doc = _good_doc(_head())
        doc["samples"] = {"merged_cold_launch_ms": 673.0}
        assert _merged_measurements(_write(tmp_path, doc)) == EMPTY

    def test_two_launches_are_an_anecdote(self, tmp_path: Path) -> None:
        doc = _good_doc(_head())
        doc["samples"] = {"merged_cold_launch_ms": [673.0, 662.0]}
        assert _merged_measurements(_write(tmp_path, doc)) == EMPTY

    def test_non_numeric_entries_do_not_count_toward_three(self, tmp_path: Path) -> None:
        doc = _good_doc(_head())
        doc["samples"] = {"merged_cold_launch_ms": [673.0, 662.0, "fast"]}
        assert _merged_measurements(_write(tmp_path, doc)) == EMPTY

    def test_a_file_from_another_commit_is_rejected(self, tmp_path: Path) -> None:
        """Provenance is checked: a stale install's numbers must not answer for this tree."""
        assert _merged_measurements(_write(tmp_path, _good_doc("0" * 40))) == EMPTY


class TestTheGoodPath:
    def test_the_metric_is_the_best_launch_in_seconds(self, tmp_path: Path) -> None:
        metrics, samples, provenance = _merged_measurements(_write(tmp_path, _good_doc(_head())))
        assert metrics == {"merged_cold_launch_s": 0.611}
        assert samples == {"merged_cold_launch_ms": [673.0, 662.0, 611.0]}
        assert provenance is not None
        assert provenance["counts"] == {"merged_cold_launch_ms": 3}


def test_the_module_runs_under_python_dash_m() -> None:
    """The __main__ guard pin: without it the module exits 0 SILENTLY under `python -m`."""
    result = subprocess.run(
        [sys.executable, "-m", "tempest.dev.bench_merged", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "merged" in result.stdout


def test_a_missing_app_is_a_refusal_with_a_named_repair(tmp_path: Path) -> None:
    """No binary → exit 2 and the repair named — never a written file, never a zero."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tempest.dev.bench_merged",
            "--app",
            str(tmp_path / "no-such-app"),
            "--out",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "install the bundle" in result.stderr
    assert not (tmp_path / "out.json").exists()
