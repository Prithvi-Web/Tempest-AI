"""The TS sidecar bridge, exercised against the REAL sidecar — every test here spawns
`node --experimental-strip-types src/index.ts` (Law L4: no mocked execution). Skips cleanly
when node or the sidecar's node_modules are absent."""

import shutil
from pathlib import Path

import pytest

from tempest.targets.ts_sidecar import (
    TsChangedFile,
    TsSidecarClient,
    TsSidecarRpcError,
    TsSidecarUnavailableError,
    default_sidecar_dir,
    select_ts_targets,
    ts_value_pools,
)

pytestmark = [
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed"),
    pytest.mark.skipif(
        not (default_sidecar_dir() / "node_modules" / "ts-morph").exists(),
        reason="ts-sidecar dependencies not installed — run `pnpm install`",
    ),
]

_FIXTURE = (
    "export function add(a: number, b: number): number {\n"  # 1
    "  return a + b;\n"  # 2
    "}\n"  # 3
    "function hidden(x: number): number {\n"  # 4
    "  return x - 1;\n"  # 5
    "}\n"  # 6
    "export function roll(sides: number): number {\n"  # 7
    "  return Math.floor(Math.random() * sides) + 1;\n"  # 8
    "}\n"  # 9
    "export async function later(x: number): Promise<number> {\n"  # 10
    "  return x;\n"  # 11
    "}\n"  # 12
)


def _write_fixture(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.ts").write_text(_FIXTURE, encoding="utf-8")


class TestSelectTsTargets:
    def test_classifies_a_real_project_end_to_end(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        targets = select_ts_targets(
            tmp_path, [TsChangedFile(path="src/mod.ts", changed_lines=(2, 5, 8, 11))]
        )
        by_symbol = {str(t["symbol"]): t for t in targets}
        assert set(by_symbol) == {"add", "hidden", "roll", "later"}

        assert by_symbol["add"]["classification"] == "PURE_CANDIDATE"
        assert by_symbol["add"]["exported"] is True
        assert by_symbol["add"]["span"] == [1, 3]

        assert by_symbol["hidden"]["classification"] == "UNREACHABLE"
        assert "not exported; cannot be imported in isolation" in str(
            by_symbol["hidden"]["reasonDetail"]
        )

        assert by_symbol["roll"]["classification"] == "IMPURE_RECORDABLE"

        assert by_symbol["later"]["classification"] == "UNREACHABLE"
        assert by_symbol["later"]["isAsync"] is True


class TestTsValuePools:
    def test_number_and_string_edge_pools(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        pools = ts_value_pools(tmp_path, "src/mod.ts", "add")
        assert pools["symbol"] == "add"
        parameters = pools["parameters"]
        assert isinstance(parameters, list) and len(parameters) == 2
        first = parameters[0]
        assert first["name"] == "a"
        assert first["typed"] is True
        assert 0 in first["values"] and 2147483647 in first["values"]
        assert first["specials"] == ["NaN", "Infinity", "-Infinity"]

    def test_unknown_symbol_is_an_rpc_error(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        with pytest.raises(TsSidecarRpcError, match="symbol not found"):
            ts_value_pools(tmp_path, "src/mod.ts", "nope")


class TestClientLifecycle:
    def test_ping_and_reuse_on_one_process(self, tmp_path: Path) -> None:
        _write_fixture(tmp_path)
        with TsSidecarClient() as client:
            pong = client.request("ping")
            assert isinstance(pong, dict) and pong["pong"] is True
            result = client.request(
                "selectTargets",
                {
                    "projectRoot": str(tmp_path),
                    "changedFiles": [{"path": "src/mod.ts", "changedLines": [2]}],
                },
            )
            assert isinstance(result, dict)
            targets = result["targets"]
            assert isinstance(targets, list) and len(targets) == 1

    def test_missing_node_binary_is_unavailable_not_a_crash(self, tmp_path: Path) -> None:
        client = TsSidecarClient(node_executable=str(tmp_path / "no-such-node"))
        with pytest.raises(TsSidecarUnavailableError, match="could not launch"):
            client.request("ping")

    def test_missing_sidecar_dir_is_actionable(self, tmp_path: Path) -> None:
        client = TsSidecarClient(sidecar_dir=tmp_path / "nowhere")
        with pytest.raises(TsSidecarUnavailableError, match="TEMPEST_TS_SIDECAR_DIR"):
            client.request("ping")
