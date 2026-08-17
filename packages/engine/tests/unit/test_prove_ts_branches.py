"""prove.py's TS dispatch (`_ts_records`) — every branch pinned directly.

These are control-flow pins over real dataclasses: the sidecar/exec failure paths raise
the REAL exception types the callees raise (their own raising behavior is pinned in
test_ts_sidecar / test_ts_dual); nothing here fabricates an execution result (L4) — the
branches under test are precisely the ones that decide NOT to execute, and each must say
why.
"""

from pathlib import Path

import pytest

import tempest.prove as prove_mod
from tempest.envrepro.worktree import MaterializedEnv
from tempest.execute.sandbox import ProcessSandbox
from tempest.model import ReasonCode, Verdict
from tempest.prove import ProveConfig, _ts_records
from tempest.targets.diff import FileDiff
from tempest.targets.ts_sidecar import TsSidecarRpcError, TsSidecarUnavailableError


def _fd(path: str) -> FileDiff:
    return FileDiff(
        path=path,
        status="modified",
        changed_head_lines=frozenset({1, 2}),
        changed_base_lines=frozenset({1}),
    )


def _env(tmp_path: Path, name: str) -> MaterializedEnv:
    wt = tmp_path / name
    wt.mkdir(parents=True, exist_ok=True)
    return MaterializedEnv(
        revision="a" * 40,
        worktree=wt,
        python=Path("/usr/bin/python3"),
        env={},
        deps_fingerprint="x",
    )


def _cfg(tmp_path: Path) -> ProveConfig:
    return ProveConfig(repo=tmp_path, base="base", head="head", max_inputs=4, seed=0)


def _target(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "fn",
        "filePath": "app.ts",
        "span": [1, 3],
        "exported": True,
        "kind": "function",
        "isAsync": False,
        "isGenerator": False,
        "classification": "PURE_CANDIDATE",
    }
    base.update(overrides)
    return base


class TestTsDispatchBranches:
    def test_sidecar_unavailable_marks_every_file_actionably(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kw: object) -> object:
            raise TsSidecarUnavailableError("node is not installed (pin)")

        monkeypatch.setattr(prove_mod, "select_ts_targets", boom)
        records = _ts_records(
            [_fd("a.ts"), _fd("b.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        assert len(records) == 2
        for r in records:
            assert r.verdict is Verdict.UNPROVEN
            assert r.reason_detail is not None and "node is not installed (pin)" in r.reason_detail

    def test_tsx_and_dts_state_why_stripping_cannot_run_them(self, tmp_path: Path) -> None:
        records = _ts_records(
            [_fd("view.tsx"), _fd("types.d.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        assert len(records) == 2
        for r in records:
            assert r.verdict is Verdict.UNPROVEN
            assert r.reason_detail is not None and "NOT exercised" in r.reason_detail

    def test_unreachable_and_impure_pass_through_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prove_mod,
            "select_ts_targets",
            lambda *_a, **_k: [
                _target(classification="UNREACHABLE", reasonDetail="not exported (pin)"),
                _target(symbol="g", classification="IMPURE_RECORDABLE"),
            ],
        )
        records = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        by_symbol = {r.qualname: r for r in records}
        assert by_symbol["fn"].reason_code is ReasonCode.TARGET_UNREACHABLE
        assert by_symbol["fn"].reason_detail == "not exported (pin)"
        assert by_symbol["g"].reason_code is ReasonCode.RECORD_REPLAY_UNAVAILABLE
        assert by_symbol["g"].reason_detail is not None and "wave 2" in by_symbol["g"].reason_detail

    def test_non_runnable_kind_and_missing_span_are_stated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prove_mod,
            "select_ts_targets",
            lambda *_a, **_k: [_target(kind="getAccessor", span=None)],
        )
        (record,) = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        assert record.reason_code is ReasonCode.TARGET_UNREACHABLE
        assert record.reason_detail is not None and "getAccessor" in record.reason_detail

    def test_no_sandbox_and_docker_tier_are_stated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prove_mod, "select_ts_targets", lambda *_a, **_k: [_target()])
        (none_rec,) = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            None,
            "none",
            (),
            _cfg(tmp_path),
            {},
        )
        assert none_rec.reason_code is ReasonCode.SANDBOX_UNAVAILABLE
        (docker_rec,) = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "docker",
            (),
            _cfg(tmp_path),
            {},
        )
        assert docker_rec.reason_code is ReasonCode.SANDBOX_UNAVAILABLE
        assert docker_rec.reason_detail is not None and "node" in docker_rec.reason_detail

    def test_foreign_filepath_is_skipped_defensively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prove_mod,
            "select_ts_targets",
            lambda *_a, **_k: [_target(filePath="not-in-diff.ts")],
        )
        records = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        assert records == []

    def test_exec_unavailable_during_pools_is_actionable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prove_mod, "select_ts_targets", lambda *_a, **_k: [_target()])

        def pools_boom(*_a: object, **_k: object) -> object:
            raise TsSidecarRpcError(1, "pools exploded (pin)")

        monkeypatch.setattr(prove_mod, "ts_value_pools", pools_boom)
        (record,) = _ts_records(
            [_fd("app.ts")],
            _env(tmp_path, "base"),
            _env(tmp_path, "head"),
            ProcessSandbox(),
            "process-first-party",
            (),
            _cfg(tmp_path),
            {},
        )
        assert record.reason_code is ReasonCode.HARNESS_SYNTHESIS_FAILED
        assert record.reason_detail is not None and "pools exploded (pin)" in record.reason_detail
