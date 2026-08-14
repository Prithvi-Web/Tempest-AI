"""Stage 3: adapter synthesis is accepted by EXECUTION only — never by reading code."""

from pathlib import Path

from tempest.execute.sandbox import ProcessSandbox
from tempest.harness.synth import SynthesisFailure, synthesize
from tempest.model import ReasonCode

from .test_execute_worker import write_module

SANDBOX = ProcessSandbox()


class TestSynthesize:
    def test_typed_function_synthesizes_and_validates_by_running(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "def f(a: int, b: int) -> int:\n    return a + b\n")
        result = synthesize(root, "m", "f", sandbox=SANDBOX)
        assert not isinstance(result, SynthesisFailure)
        assert result.validated_by_execution is True
        assert result.introspection.params[0].annotation == "int"

    def test_target_raising_on_probe_is_still_a_valid_adapter(self, tmp_path: Path) -> None:
        root = write_module(
            tmp_path, "m", "def f(a: int) -> int:\n    raise ValueError('always')\n"
        )
        result = synthesize(root, "m", "f", sandbox=SANDBOX)
        assert not isinstance(result, SynthesisFailure)

    def test_import_crash_fails_with_attempts_attached(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "raise RuntimeError('cannot import')\n")
        result = synthesize(root, "m", "f", sandbox=SANDBOX)
        assert isinstance(result, SynthesisFailure)
        assert result.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert result.detail

    def test_probe_killing_worker_every_time_is_a_failure(self, tmp_path: Path) -> None:
        src = "import ctypes\n\n\ndef f(a: int) -> int:\n    ctypes.string_at(0)\n    return a\n"
        root = write_module(tmp_path, "m", src)
        result = synthesize(root, "m", "f", sandbox=SANDBOX)
        assert isinstance(result, SynthesisFailure)
        assert result.attempts >= 3

    def test_synthesis_result_carries_cache_key(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "m", "def f(a: int) -> int:\n    return a\n")
        result = synthesize(root, "m", "f", sandbox=SANDBOX)
        assert not isinstance(result, SynthesisFailure)
        assert "m.f" in result.cache_key
        assert len(result.cache_key.split("@")[1]) >= 8  # file-hash component
