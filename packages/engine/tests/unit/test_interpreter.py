"""Worker interpreter discovery, validated against real executables (Law L4: every probe here
launches an actual child process — fixture interpreters are real scripts on disk, not mocks)."""

import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tempest.execute import interpreter
from tempest.execute.interpreter import WorkerPythonNotFound, find_worker_python


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    """Discovery caches per-process; every scenario starts and ends uncached."""
    interpreter._reset_cache()
    yield
    interpreter._reset_cache()


def fake_interpreter(tmp_path: Path, version_line: str) -> Path:
    """A real executable that answers `--version` the way an interpreter would."""
    script = tmp_path / "fake-python"
    script.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


class TestEnvOverride:
    def test_valid_override_is_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_PYTHON", sys.executable)
        assert find_worker_python() == sys.executable

    def test_nonexistent_override_raises_actionably(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEMPEST_PYTHON", "/nonexistent/bin/python3")
        with pytest.raises(WorkerPythonNotFound) as excinfo:
            find_worker_python()
        message = str(excinfo.value)
        assert "TEMPEST_PYTHON" in message
        assert "does not exist" in message
        assert "3.12" in message  # tells the user what would satisfy the requirement

    def test_unrunnable_override_raises_actionably(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # exists on disk but is not executable as an interpreter — validation must RUN it,
        # not just stat it.
        not_a_python = tmp_path / "not-a-python"
        not_a_python.write_text("just text\n")
        monkeypatch.setenv("TEMPEST_PYTHON", str(not_a_python))
        with pytest.raises(WorkerPythonNotFound) as excinfo:
            find_worker_python()
        assert "not a runnable Python interpreter" in str(excinfo.value)

    def test_too_old_override_raises_with_both_versions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        old = fake_interpreter(tmp_path, "Python 3.8.0")
        monkeypatch.setenv("TEMPEST_PYTHON", str(old))
        with pytest.raises(WorkerPythonNotFound) as excinfo:
            find_worker_python()
        message = str(excinfo.value)
        assert "3.8" in message
        assert "3.12" in message

    def test_bare_command_override_resolves_via_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        good = fake_interpreter(tmp_path, "Python 3.12.4")
        good = good.rename(tmp_path / "python-fixture")
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("TEMPEST_PYTHON", "python-fixture")
        assert find_worker_python() == str(good)


class TestNonFrozen:
    def test_returns_sys_executable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_PYTHON", raising=False)
        assert getattr(sys, "frozen", False) is False  # pytest never runs frozen
        assert find_worker_python() == sys.executable

    def test_result_is_cached_per_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEMPEST_PYTHON", raising=False)
        first = find_worker_python()
        # a bogus override set AFTER first discovery must not disturb the cached answer —
        # workers within one process always get the same interpreter
        monkeypatch.setenv("TEMPEST_PYTHON", "/nonexistent/bin/python3")
        assert find_worker_python() == first == sys.executable


class TestUvManagedCandidates:
    def test_orders_newest_first_and_ignores_old_versions(self, tmp_path: Path) -> None:
        for name, binary in [
            ("cpython-3.12.4-macos-aarch64-none", "python3.12"),
            ("cpython-3.13.2-macos-aarch64-none", "python3.13"),
            ("cpython-3.11.9-macos-aarch64-none", "python3.11"),  # outside the 3.1[2-9] glob
        ]:
            bin_dir = tmp_path / name / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / binary).write_text("#!/bin/sh\n")
        candidates = interpreter._uv_managed_candidates(tmp_path)
        assert [Path(c).name for c in candidates] == ["python3.13", "python3.12"]

    def test_missing_uv_dir_yields_nothing(self, tmp_path: Path) -> None:
        assert interpreter._uv_managed_candidates(tmp_path / "absent") == []


class TestProbeVersion:
    def test_reads_a_real_interpreter(self) -> None:
        version = interpreter._probe_version(sys.executable)
        assert version == (sys.version_info.major, sys.version_info.minor)

    def test_nonzero_exit_is_rejected(self, tmp_path: Path) -> None:
        failing = tmp_path / "failing"
        failing.write_text("#!/bin/sh\nexit 3\n")
        failing.chmod(0o755)
        assert interpreter._probe_version(str(failing)) is None

    def test_gibberish_output_is_rejected(self, tmp_path: Path) -> None:
        chatty = fake_interpreter(tmp_path, "definitely not a version")
        assert interpreter._probe_version(str(chatty)) is None
