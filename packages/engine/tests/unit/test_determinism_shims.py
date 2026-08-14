"""Stage 4 — the moat. In-process tests for the shim layer: record then replay must serve
IDENTICAL values with the real surface absent, every interaction lands in the ordered ledger,
and un-interceptable surfaces refuse loudly (never silently pass)."""

import os
import random
import subprocess
import time
from pathlib import Path

import pytest

from tempest.determinism import _shims as shims


@pytest.fixture(autouse=True)
def clean_install() -> object:
    yield
    shims.uninstall()


def _record_session() -> shims.Session:
    session = shims.Session(mode="record")
    shims.install(session)
    return session


def _replay_session(recorded: shims.Session) -> shims.Session:
    shims.uninstall()
    session = shims.Session(mode="replay", cassette=recorded.cassette_data())
    shims.install(session)
    return session


class TestClock:
    def test_time_is_recorded_then_replayed_identically(self) -> None:
        rec = _record_session()
        t1, t2 = time.time(), time.time()
        assert t2 >= t1
        rep = _replay_session(rec)
        assert time.time() == t1
        assert time.time() == t2
        assert [e.surface for e in rep.ledger] == ["CLOCK", "CLOCK"]

    def test_datetime_now_is_replayed(self) -> None:
        import datetime as dt

        rec = _record_session()
        first = dt.datetime.now()
        rep = _replay_session(rec)
        assert dt.datetime.now() == first
        assert rep.ledger[0].surface == "CLOCK"

    def test_monotonic_is_covered(self) -> None:
        rec = _record_session()
        m = time.monotonic()
        _replay_session(rec)
        assert time.monotonic() == m


class TestRandomness:
    def test_os_urandom_replays_identical_bytes(self) -> None:
        rec = _record_session()
        blob = os.urandom(16)
        rep = _replay_session(rec)
        assert os.urandom(16) == blob
        assert rep.ledger[0].surface == "RANDOM"

    def test_uuid4_is_stable_across_replay(self) -> None:
        import uuid

        rec = _record_session()
        u = uuid.uuid4()
        _replay_session(rec)
        assert uuid.uuid4() == u

    def test_random_module_calls_replay(self) -> None:
        rec = _record_session()
        values = [random.random(), random.randint(1, 100)]
        _replay_session(rec)
        assert [random.random(), random.randint(1, 100)] == values


class TestEnv:
    def test_environment_reads_are_recorded_and_replayed(self) -> None:
        os.environ["TEMPEST_SHIM_TEST"] = "live-value"
        try:
            rec = _record_session()
            v = os.environ.get("TEMPEST_SHIM_TEST")
            assert v == "live-value"
        finally:
            del os.environ["TEMPEST_SHIM_TEST"]
        _replay_session(rec)
        # replay serves the recorded value even though the real env var is gone
        assert os.environ.get("TEMPEST_SHIM_TEST") == "live-value"


class TestFilesystem:
    def test_file_read_replays_content_after_deletion(self, tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("payload-42")
        rec = _record_session()
        with open(target) as fh:
            content = fh.read()
        assert content == "payload-42"
        shims.uninstall()
        target.unlink()
        _replay_session(rec)
        with open(target) as fh:
            assert fh.read() == "payload-42"

    def test_writes_are_captured_as_effects_and_swallowed_in_replay(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        rec = _record_session()
        with open(target, "w") as fh:
            fh.write("written")
        shims.uninstall()
        assert target.read_text() == "written"  # record mode writes for real
        target.unlink()
        rep = _replay_session(rec)
        with open(target, "w") as fh:
            fh.write("written")
        shims.uninstall()
        assert not target.exists()  # replay swallows writes
        assert any(e.surface == "FS" and "write" in e.call for e in rep.ledger)

    def test_listdir_replays(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.txt").write_text("y")
        rec = _record_session()
        listing = os.listdir(tmp_path)
        shims.uninstall()
        (tmp_path / "c.txt").write_text("z")
        _replay_session(rec)
        assert os.listdir(tmp_path) == listing


class TestProcess:
    def test_subprocess_run_is_recorded_and_replayed_without_spawning(self) -> None:
        rec = _record_session()
        result = subprocess.run(["/bin/echo", "hi"], capture_output=True, text=True)
        assert result.stdout == "hi\n"
        rep = _replay_session(rec)
        replayed = subprocess.run(["/bin/echo", "hi"], capture_output=True, text=True)
        assert replayed.stdout == "hi\n"
        assert replayed.returncode == 0
        assert any(e.surface == "PROC" for e in rep.ledger)


class TestHonesty:
    def test_cassette_miss_raises_with_the_requested_call(self) -> None:
        rec = _record_session()
        time.time()
        _replay_session(rec)
        time.time()
        with pytest.raises(shims.CassetteMiss) as exc:
            time.time()  # second call was never recorded
        assert "CLOCK" in str(exc.value)

    def test_raw_socket_is_uninterceptable_and_refuses(self) -> None:
        import socket

        _record_session()
        with pytest.raises(shims.UninterceptableEffect) as exc:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        assert "socket" in str(exc.value)

    def test_ledger_preserves_global_order_across_surfaces(self) -> None:
        rec = _record_session()
        time.time()
        os.urandom(4)
        time.time()
        assert [e.surface for e in rec.ledger] == ["CLOCK", "RANDOM", "CLOCK"]
        assert [e.ordinal for e in rec.ledger] == [0, 0, 1]

    def test_uninstall_restores_the_real_world(self) -> None:
        rec = _record_session()
        time.time()
        shims.uninstall()
        real1, real2 = time.time(), time.time()
        assert real2 > real1 or real2 == pytest.approx(real1)
        assert len(rec.ledger) == 1
