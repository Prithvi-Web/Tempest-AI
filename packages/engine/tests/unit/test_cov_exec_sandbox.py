"""Sandbox backend edges exercised for real (Law L4):

- `_set_child_limits` runs in a REAL child interpreter (preexec_fn code executes between
  fork and exec where no tracer can live, so a dedicated child applies and verifies the
  rlimits with subprocess coverage collecting it).
- Docker-present selection runs against a FAKE `docker` binary that answers `docker info`
  through real subprocess execution — the selection logic is real even where Docker is not.
- Seatbelt discovery/failure paths run against controlled PATH + real files.
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tempest.execute.sandbox import DockerSandbox, SeatbeltSandbox, select_sandbox

REPO_ROOT = Path(__file__).resolve().parents[4]


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestChildLimits:
    def test_limits_apply_inside_a_real_child(self) -> None:
        code = (
            "import resource\n"
            "from tempest.execute.sandbox import _set_child_limits\n"
            "_set_child_limits()\n"
            "assert resource.getrlimit(resource.RLIMIT_CPU) == (120, 120)\n"
            "assert resource.getrlimit(resource.RLIMIT_CORE)[0] == 0\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,  # child coverage data lands where the session combines it
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr

    def test_v8_limits_keep_cpu_but_never_cap_the_address_space(self) -> None:
        """Trap 35: the V8 variant must keep the CPU/core ceilings while leaving RLIMIT_AS
        untouched — Wasm reserves multi-GiB virtual ranges and dies under any AS cap."""
        code = (
            "import resource\n"
            "before = resource.getrlimit(resource.RLIMIT_AS)\n"
            "from tempest.execute.sandbox import _set_child_limits_v8\n"
            "_set_child_limits_v8()\n"
            "assert resource.getrlimit(resource.RLIMIT_CPU) == (120, 120)\n"
            "assert resource.getrlimit(resource.RLIMIT_CORE)[0] == 0\n"
            "assert resource.getrlimit(resource.RLIMIT_AS) == before\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr


class TestSeatbeltDiscovery:
    def test_missing_configured_binary_falls_back_to_path_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _executable(tmp_path / "bin" / "sandbox-exec", "#!/bin/sh\nexit 0\n")
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        sandbox = SeatbeltSandbox(sandbox_exec=str(tmp_path / "definitely-missing"))
        assert sandbox._binary() == str(fake)
        assert shutil.which("sandbox-exec") == str(fake)

    def test_configured_binary_is_used_when_it_exists(self, tmp_path: Path) -> None:
        fake = _executable(tmp_path / "sb" / "sandbox-exec", "#!/bin/sh\nexit 0\n")
        assert SeatbeltSandbox(sandbox_exec=str(fake))._binary() == str(fake)

    def test_popen_refuses_when_the_binary_vanished(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        sandbox = SeatbeltSandbox(sandbox_exec=str(tmp_path / "definitely-missing"))
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        with pytest.raises(RuntimeError, match="vanished between selection and launch"):
            sandbox.popen([sys.executable, "x.py"], cwd=tmp_path, env={}, scratch=scratch)

    def test_read_roots_without_a_uv_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() now holds no ~/.local/share/uv
        roots = SeatbeltSandbox()._read_roots(Path(sys.executable))
        assert Path(sys.executable) in roots
        assert tmp_path / ".local" / "share" / "uv" not in roots


def _fake_docker(tmp_path: Path, *, info_exit: int) -> Path:
    return _executable(
        tmp_path / "bin" / "docker",
        f'#!/bin/sh\nif [ "$1" = "info" ]; then exit {info_exit}; fi\nexit 0\n',
    )


class TestDockerSelection:
    def test_docker_that_answers_info_selects_t1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_docker(tmp_path, info_exit=0)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        selection = select_sandbox(docker_binary="docker")
        assert selection.tier == "T1"
        assert selection.kind == "docker"
        assert selection.assurance == "full"
        assert isinstance(selection.sandbox, DockerSandbox)
        assert selection.reason is None

    def test_docker_whose_daemon_is_down_is_not_selected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_docker(tmp_path, info_exit=1)  # binary present, `docker info` fails for real
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        assert DockerSandbox(docker_binary="docker").available() is False
        selection = select_sandbox(docker_binary="docker", allow_seatbelt=False)
        assert selection.tier == "none"
        assert selection.sandbox is None
        assert selection.reason is not None and "Law L6" in selection.reason

    def test_seatbelt_rung_is_probed_when_docker_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The T2 rung must execute on EVERY platform when Docker is missing (trap 22): CI's
        ubuntu runners ship a live Docker daemon, so the real-ladder doctor test lands on T1
        there and — without this test — the rung ran only on macOS, leaving the Linux
        coverage denominator at 99.95% while every test passed."""
        empty = tmp_path / "emptybin"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        # probed for real on both platforms: /usr/bin/sandbox-exec on macOS, the sys.platform
        # short-circuit elsewhere — no skipif, the assertion is platform-aware instead
        assert SeatbeltSandbox().available() is (sys.platform == "darwin")
        selection = select_sandbox(docker_binary=str(tmp_path / "definitely-missing-docker"))
        if sys.platform == "darwin":
            assert selection.tier == "T2"
            assert selection.kind == "seatbelt"
            assert selection.assurance == "full"
            assert isinstance(selection.sandbox, SeatbeltSandbox)
            assert selection.reason is None
        else:
            assert selection.tier == "none"
            assert selection.sandbox is None
            assert selection.reason is not None and "Law L6" in selection.reason

    def test_translate_job_without_sys_path_maps_only_path_fields(self, tmp_path: Path) -> None:
        workdir = tmp_path / "repo"
        scratch = tmp_path / "scratch"
        workdir.mkdir()
        scratch.mkdir()
        job: dict[str, object] = {"scratch": str(scratch / "inner"), "mode": "invoke"}
        translated = DockerSandbox().translate_job(job, workdir=workdir, scratch=scratch)
        assert translated["scratch"] == "/scratch/inner"
        assert translated["mode"] == "invoke"
        assert "sys_path" not in translated
