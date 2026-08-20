"""THE PRODUCER HALF: `make bench` must actually WRITE the conditions block it promises.

Every other test of this feature calls `machine_conditions()` and `conditions_block()` directly,
which pins the two functions and pins nothing about whether anything calls them. A review found
that deleting the single line `"conditions": conditions_block(...)` from `bench.main`'s payload
turned the whole feature into a no-op — `perf_suite` would print `PENDING(conditions)` for ever,
qualification would never engage, and the entire unit suite stayed green. That is trap 43 in its
purest form: the lines all ran, and the STATE "nobody wires them up" was not considered.

**Real execution, no mocking (L4).** This runs the actual `tempest.dev.bench` entry point against
the actual stdio sidecar with a one-run seeded store — about 7 seconds — because the thing under
test is the wiring, and a test that stubbed the measurement would be pinning a fiction of exactly
the shape it exists to catch.

States enumerated before the tests (trap 43): the block is present · it names its source and
sample · it declares WHICH metrics it covers · the covered set matches what this process actually
measures · the editor metrics are deliberately absent from that set · the payload still parses as
the JSON the two gates read.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tempest.dev import bench
from tempest.dev import perf_suite as ps


@pytest.fixture(scope="module")
def bench_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """One real bench run for the whole module — module-scoped on purpose.

    Each assertion below is about a different property of the SAME artifact, and spawning a
    sidecar per assertion bought nothing but forty seconds of `make verify`.
    """
    tmp_path = tmp_path_factory.mktemp("bench-conditions")
    return tmp_path, _run_bench(tmp_path)


def _run_bench(tmp_path: Path) -> dict[str, Any]:
    out = tmp_path / "bench.json"
    exit_code = bench.main(
        [
            "--runs",
            "1",
            "--out",
            str(out),
            # A path that cannot exist, so the editor metrics are genuinely absent rather than
            # picked up from whatever this machine happens to have lying in bench/.
            "--editor-metrics",
            str(tmp_path / "no-such-editor-metrics.json"),
        ]
    )
    assert exit_code == 0, "the bench itself must succeed before anything here means anything"
    doc: Any = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def test_a_real_bench_run_writes_a_conditions_block(
    bench_run: tuple[Path, dict[str, Any]],
) -> None:
    """Delete the line from `main`'s payload and this is the only test in the repo that notices."""
    _, doc = bench_run
    assert "conditions" in doc, "the feature is a no-op unless main writes this"
    conditions = doc["conditions"]
    assert isinstance(conditions, dict)


def test_the_block_carries_a_usable_load_sample_on_this_platform(
    bench_run: tuple[Path, dict[str, Any]],
) -> None:
    """darwin and linux both implement `os.getloadavg`, so a run here must produce a number —
    not the `unavailable` fallback, which would silently disable qualification everywhere."""
    _, doc = bench_run
    conditions = doc["conditions"]
    assert conditions["source"] == "os.getloadavg"
    assert isinstance(conditions["load_avg_1m_background"], float)
    assert isinstance(conditions["cpu_count"], int)
    assert conditions["judged_on"] == "load_avg_1m_background"


def test_the_block_declares_what_it_covers_and_the_gate_agrees(
    bench_run: tuple[Path, dict[str, Any]],
) -> None:
    """The producer's `covers` list and the consumer's reading of it must be the same set.

    This is the boundary the whole scoping fix rests on: `perf_suite` refuses to qualify any
    metric absent from this list, so a producer that wrote the wrong names would silently disable
    qualification while every note still claimed it was on.
    """
    _, doc = bench_run
    conditions = doc["conditions"]
    assert set(conditions["covers"]) == set(bench.MEASURED_IN_PROCESS)
    assert ps.covered_metrics(conditions) == frozenset(bench.MEASURED_IN_PROCESS)


def test_the_covered_set_is_exactly_what_this_process_measured(
    bench_run: tuple[Path, dict[str, Any]],
) -> None:
    """Not a hand-maintained list: every metric the run actually produced is covered, and the
    editor metrics — which come from a different process on a different day — are not."""
    _, doc = bench_run
    covered = set(doc["conditions"]["covers"])
    assert covered == set(doc["metrics"]), "a metric measured here but uncovered is a silent gap"
    assert covered.isdisjoint({"open_file_ms", "keystroke_ms", "completion_ms"})


def test_the_written_file_is_what_both_gates_actually_read(
    bench_run: tuple[Path, dict[str, Any]],
) -> None:
    """The payload is consumed by two separate commands; a shape only one of them tolerates is
    a defect neither one's own tests would find."""
    tmp_path, doc = bench_run
    out = tmp_path / "bench.json"
    # perf_suite: parses, evaluates, and reaches a verdict rather than crashing on the new key.
    assert ps.main(["--enforce-budgets", "--bench", str(out)]) in (0, 1)
    # bench_guard runs in CI and must be entirely unaffected by the added key.
    from tempest.dev import bench_guard

    without = dict(doc)
    without.pop("conditions")
    (tmp_path / "without.json").write_text(json.dumps(without), encoding="utf-8")
    with_key = bench_guard.main(["--bench", str(out)])
    without_key = bench_guard.main(["--bench", str(tmp_path / "without.json")])
    assert with_key == without_key, "the new key must be invisible to the CI gate"
