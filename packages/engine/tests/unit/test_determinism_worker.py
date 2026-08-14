"""Stage 4 through the REAL sandbox worker: record on base, replay both sides from the
identical cassette. The proof that the moat holds: replayed runs return identical values with
the real world (files, clock, env, loopback server) taken away."""

from pathlib import Path

from tempest.compare.compare import CompareConfig, Diverged, Equal, compare
from tempest.execute.dual import prove_impure_target
from tempest.execute.runner import DeterminismJob, run_batch
from tempest.execute.sandbox import ProcessSandbox
from tempest.generate.inputs import Budget
from tempest.model import DivergenceClass, ReasonCode, Verdict

from .test_dual import _envs
from .test_execute_worker import write_module

SANDBOX = ProcessSandbox()
CFG = CompareConfig()

IMPURE_SRC = (
    "import os\n"
    "import random\n"
    "import time\n"
    "\n"
    "\n"
    "def snapshot(label: str) -> dict[str, object]:\n"
    "    with open('config.txt') as fh:\n"
    "        cfg = fh.read().strip()\n"
    "    return {\n"
    "        'label': label,\n"
    "        't': time.time(),\n"
    "        'r': random.random(),\n"
    "        'cfg': cfg,\n"
    "        'home': os.environ.get('HOME', '?'),\n"
    "    }\n"
)


class TestRecordReplayRoundTrip:
    def test_replay_reproduces_the_recorded_world_even_after_its_gone(self, tmp_path: Path) -> None:
        root = write_module(tmp_path, "wx", IMPURE_SRC)
        (root / "config.txt").write_text("cfg-value-7\n")
        inputs = [("('a',)", "{}"), ("('b',)", "{}")]

        recorded = run_batch(
            root, "wx", "snapshot", inputs, SANDBOX, determinism=DeterminismJob(mode="record")
        )
        assert all(o.return_present for o in recorded)
        assert all(o.cassette for o in recorded)
        assert any(e.surface == "CLOCK" for o in recorded for e in o.effects)
        assert any(e.surface == "FS" for o in recorded for e in o.effects)

        (root / "config.txt").unlink()  # take the world away
        replayed = run_batch(
            root,
            "wx",
            "snapshot",
            inputs,
            SANDBOX,
            determinism=DeterminismJob(
                mode="replay", cassettes={i: o.cassette for i, o in enumerate(recorded)}
            ),
        )
        for rec, rep in zip(recorded, replayed, strict=True):
            assert compare(rec, rep, CFG) == Equal()

    def test_http_via_loopback_records_then_replays_without_any_server(
        self, tmp_path: Path
    ) -> None:
        src = (
            "from urllib.request import urlopen\n"
            "\n"
            "\n"
            "def fetch(base_url: str) -> str:\n"
            "    with urlopen(base_url + '/greet') as resp:\n"
            "        return resp.read().decode()\n"
        )
        root = write_module(tmp_path, "web", src)
        import socket as socket_module

        probe = socket_module.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        inputs = [("('__LOOPBACK__',)", "{}")]
        recorded = run_batch(
            root,
            "web",
            "fetch",
            inputs,
            SANDBOX,
            determinism=DeterminismJob(
                mode="record",
                loopback_routes={"/greet": {"status": 200, "body": "hello from base"}},
                loopback_port=port,
            ),
        )
        (rec,) = recorded
        assert rec.return_present, (rec.raised, rec.uninterceptable)
        replayed = run_batch(
            root,
            "web",
            "fetch",
            inputs,
            SANDBOX,
            determinism=DeterminismJob(
                mode="replay", cassettes={0: rec.cassette}, loopback_port=port
            ),
        )
        assert compare(rec, replayed[0], CFG) == Equal()
        assert any(e.surface == "NET" for e in replayed[0].effects)

    def test_extra_interaction_in_head_is_a_cassette_miss(self, tmp_path: Path) -> None:
        base_src = "import time\n\n\ndef f(x: int) -> float:\n    return time.time() + x\n"
        head_src = (
            "import time\n\n\ndef f(x: int) -> float:\n    return time.time() + time.time() + x\n"
        )
        (tmp_path / "b").mkdir()
        (tmp_path / "h").mkdir()
        base_root = write_module(tmp_path / "b", "m", base_src)
        head_root = write_module(tmp_path / "h", "m", head_src)
        inputs = [("(1,)", "{}")]
        recorded = run_batch(
            base_root, "m", "f", inputs, SANDBOX, determinism=DeterminismJob(mode="record")
        )
        head = run_batch(
            head_root,
            "m",
            "f",
            inputs,
            SANDBOX,
            determinism=DeterminismJob(mode="replay", cassettes={0: recorded[0].cassette}),
        )
        assert head[0].cassette_miss is not None
        result = compare(recorded[0], head[0], CFG)
        assert isinstance(result, Diverged)
        assert result.divergence_class is DivergenceClass.CASSETTE_MISS

    def test_raw_socket_reports_uninterceptable(self, tmp_path: Path) -> None:
        src = (
            "import socket\n\n\ndef f() -> int:\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    s.close()\n    return 1\n"
        )
        root = write_module(tmp_path, "raw", src)
        (obs,) = run_batch(
            root, "raw", "f", [("()", "{}")], SANDBOX, determinism=DeterminismJob(mode="record")
        )
        assert obs.uninterceptable is not None
        assert "socket" in obs.uninterceptable


class TestProveImpureTarget:
    def test_impure_behavior_change_is_divergent(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "import time\n\n\ndef age(x: int) -> int:\n    return int(time.time()) + x\n",
            "import time\n\n\ndef age(x: int) -> int:\n    return int(time.time()) + x + 1\n",
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "age",
            changed_lines=frozenset({5}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=8),
        )
        assert outcome.verdict is Verdict.DIVERGENT
        assert outcome.divergences[0].divergence_class is DivergenceClass.RETURN_VALUE

    def test_impure_noop_refactor_is_equivalent(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "import time\n\n\ndef stamp(x: int) -> dict[str, float]:\n"
            "    t = time.time()\n    return {'t': t, 'x': x * 2.0}\n",
            "import time\n\n\ndef stamp(x: int) -> dict[str, float]:\n"
            "    return {'x': x + x + 0.0, 't': time.time()}\n",
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "stamp",
            changed_lines=frozenset({5, 6}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=8),
        )
        assert outcome.verdict is Verdict.EQUIVALENT_UNDER_BUDGET, outcome
        assert outcome.divergences == ()

    def test_uninterceptable_target_is_unproven_and_names_the_surface(self, tmp_path: Path) -> None:
        base, head = _envs(
            tmp_path,
            "import socket\n\n\ndef f() -> int:\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()\n    return 1\n",
            "import socket\n\n\ndef f() -> int:\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()\n    return 2\n",
        )
        outcome = prove_impure_target(
            base,
            head,
            "m",
            "f",
            changed_lines=frozenset({5}),
            sandbox=SANDBOX,
            budget=Budget(max_inputs=4),
        )
        assert outcome.verdict is Verdict.UNPROVEN
        assert outcome.reason_code is ReasonCode.UNINTERCEPTABLE_EFFECT
        assert outcome.reason_detail is not None and "socket" in outcome.reason_detail
