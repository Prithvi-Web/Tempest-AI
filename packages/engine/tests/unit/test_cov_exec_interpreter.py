"""Frozen-runtime interpreter discovery, validated against REAL executables (Law L4).

`sys.frozen` is the one thing that cannot be true under pytest (PyInstaller sets it at boot),
so it is pinned per test; every candidate the discovery then considers is a real script on
disk answering `--version` through a real subprocess, exactly as production probes them.
"""

import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tempest.execute import interpreter
from tempest.execute.interpreter import WorkerPythonNotFound, find_worker_python


@pytest.fixture(autouse=True)
def _fresh_discovery(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    interpreter._reset_cache()
    monkeypatch.delenv("TEMPEST_PYTHON", raising=False)
    yield
    interpreter._reset_cache()


def _fake_python(directory: Path, name: str, version_line: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / name
    script.write_text(f"#!/bin/sh\necho '{version_line}'\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _frozen(monkeypatch: pytest.MonkeyPatch, *, path_dir: Path, home: Path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PATH", str(path_dir))
    monkeypatch.setenv("HOME", str(home))  # keeps the real uv store out of the probe set


class TestFrozenDiscovery:
    def test_python312_on_path_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bin_dir = tmp_path / "bin"
        good = _fake_python(bin_dir, "python3.12", "Python 3.12.9")
        _frozen(monkeypatch, path_dir=bin_dir, home=tmp_path / "home")
        assert find_worker_python() == str(good)

    def test_python3_is_accepted_when_new_enough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "bin"
        good = _fake_python(bin_dir, "python3", "Python 3.13.1")
        _frozen(monkeypatch, path_dir=bin_dir, home=tmp_path / "home")
        assert find_worker_python() == str(good)

    def test_unusable_path_candidates_fall_through_to_the_uv_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "bin"
        _fake_python(bin_dir, "python3.12", "not a version at all")  # unparsable → skipped
        _fake_python(bin_dir, "python3", "Python 3.10.14")  # too old → skipped
        home = tmp_path / "home"
        uv_bin = home / ".local" / "share" / "uv" / "python" / "cpython-3.12.4-test-none" / "bin"
        managed = _fake_python(uv_bin, "python3.12", "Python 3.12.4")
        _frozen(monkeypatch, path_dir=bin_dir, home=home)
        assert find_worker_python() == str(managed)

    def test_no_candidate_raises_with_install_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "emptybin"
        empty.mkdir()
        _frozen(monkeypatch, path_dir=empty, home=tmp_path / "home")
        with pytest.raises(WorkerPythonNotFound) as excinfo:
            find_worker_python()
        message = str(excinfo.value)
        assert "3.12" in message
        assert "TEMPEST_PYTHON" in message

    def test_home_env_controls_the_uv_store_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The default-store path flows from Path.home(); an empty home yields no candidates.
        monkeypatch.setenv("HOME", str(tmp_path))
        assert interpreter._uv_managed_candidates() == []
        assert os.environ["HOME"] == str(tmp_path)
