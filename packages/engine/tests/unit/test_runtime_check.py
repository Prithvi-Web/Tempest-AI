"""Every runtime_check check is proven to FAIL on a violating tree — a gate that cannot
fail is decoration. The fixture is the minimal PASSING world; each test breaks exactly one
property and asserts exit 1 with the violation named."""

import json
from pathlib import Path

from tempest.dev import runtime_check

_ORCHESTRATOR = """
class AgentRun:
    pass


def run_task(spec: object) -> AgentRun:
    change = ProvenChange(bundle_id="b")
    proof = run_prove(spec)
    return AgentRun()
"""

_CHATTURN = """
def start_turn(payload: dict) -> dict:
    return {"streamId": "x"}
"""

_TOOLS_PY = """
HANDLERS: dict[str, object] = {
    "read_file": None,
    "write_file": None,
}
"""

_MANIFEST = {
    "protocol_version": 1,
    "tools": [
        {
            "name": "read_file",
            "policy": {
                "approval": "auto",
                "touches_network": False,
                "destructive": False,
                "writes": "none",
            },
        },
        {
            "name": "write_file",
            "policy": {
                "approval": "auto",
                "touches_network": False,
                "destructive": False,
                "writes": "shadow_worktree",
            },
        },
    ],
}


def _passing_tree(root: Path) -> None:
    (root / "packages/desktop").mkdir(parents=True)
    engine = root / "packages/engine/src/tempest/agent"
    engine.mkdir(parents=True)
    (engine / "orchestrator.py").write_text(_ORCHESTRATOR)
    (engine / "tools.py").write_text(_TOOLS_PY)
    api = root / "packages/api/src/tempest_api"
    api.mkdir(parents=True)
    (api / "chatturn.py").write_text(_CHATTURN)

    schema = root / "packages/shared-schema"
    schema.mkdir(parents=True)
    (schema / "agent-tools.json").write_text(json.dumps(_MANIFEST))
    (schema / "agent-tools.anthropic.json").write_text(
        json.dumps([{"name": "read_file"}, {"name": "write_file"}])
    )
    (schema / "agent-tools.openai.json").write_text(
        json.dumps(
            [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "write_file"}},
            ]
        )
    )
    generated = root / "packages/desktop/src/generated"
    generated.mkdir(parents=True)
    (generated / "agentTools.ts").write_text(
        'export const AGENT_TOOLS = [{ name: "read_file" }, { name: "write_file" }];\n'
    )

    anchors = root / "packages/platform/server/server"
    (anchors / "services/Endpoints/agents").mkdir(parents=True)
    (anchors / "services/Endpoints/agents/initialize.js").write_text("new AgentClient({})\n")
    (anchors / "controllers/agents").mkdir(parents=True)
    (anchors / "controllers/agents/client.js").write_text("const run = createRun({});\n")

    seam = root / "packages/platform/server/tempest"
    seam.mkdir(parents=True)
    (seam / "local-api.mjs").write_text("export function handleLocalApi() {}\n")

    tauri = root / "packages/desktop/src-tauri/src"
    tauri.mkdir(parents=True)
    (tauri / "platform_web.rs").write_text(
        "pub fn handle() { crate::agent_chat::handle_chat(); }\n"
    )


def _run(root: Path) -> int:
    return runtime_check.main(
        ["--single-orchestrator", "--single-tool-registry", "--root", str(root)]
    )


class TestPassing:
    def test_the_fixture_world_passes(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        assert _run(tmp_path) == 0

    def test_the_real_repository_passes(self) -> None:
        assert runtime_check.main(["--single-orchestrator", "--single-tool-registry"]) == 0


class TestOrchestratorPins:
    def test_a_second_agent_run_producer_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        orchestrator = tmp_path / "packages/engine/src/tempest/agent/orchestrator.py"
        orchestrator.write_text(
            orchestrator.read_text() + "\n\ndef run_task_two(spec: object) -> AgentRun:\n"
            "    return AgentRun()\n"
        )
        assert _run(tmp_path) == 1

    def test_a_second_proven_change_construction_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        orchestrator = tmp_path / "packages/engine/src/tempest/agent/orchestrator.py"
        orchestrator.write_text(
            orchestrator.read_text() + '\n\nEXTRA = ProvenChange(bundle_id="two")\n'
        )
        assert _run(tmp_path) == 1

    def test_a_chat_surface_touching_the_proof_vocabulary_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        chatturn = tmp_path / "packages/api/src/tempest_api/chatturn.py"
        chatturn.write_text(chatturn.read_text() + "\n\nCLAIM = ProvenChange\n")
        assert _run(tmp_path) == 1


class TestDormancyPins:
    def test_a_vanished_platform_anchor_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/platform/server/server/controllers/agents/client.js").write_text(
            "// the engine moved somewhere new\n"
        )
        assert _run(tmp_path) == 1

    def test_a_seam_waking_the_vendored_runtime_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        seam = tmp_path / "packages/platform/server/tempest/wake.mjs"
        seam.write_text('import { createRun } from "@librechat/agents";\n')
        assert _run(tmp_path) == 1

    def test_a_seam_speaking_a_model_wire_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        local = tmp_path / "packages/platform/server/tempest/local-api.mjs"
        local.write_text(local.read_text() + '\nfetch("http://x/v1/chat/completions");\n')
        assert _run(tmp_path) == 1

    def test_an_unclaimed_chat_family_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/desktop/src-tauri/src/platform_web.rs").write_text(
            "pub fn handle() {}\n"
        )
        assert _run(tmp_path) == 1


class TestRegistryPins:
    def test_a_manifest_tool_without_a_handler_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        manifest = json.loads((tmp_path / "packages/shared-schema/agent-tools.json").read_text())
        manifest["tools"].append(
            {
                "name": "seventh_tool",
                "policy": {
                    "approval": "auto",
                    "touches_network": False,
                    "destructive": False,
                    "writes": "none",
                },
            }
        )
        (tmp_path / "packages/shared-schema/agent-tools.json").write_text(json.dumps(manifest))
        assert _run(tmp_path) == 1

    def test_a_user_tree_write_scope_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        manifest = json.loads((tmp_path / "packages/shared-schema/agent-tools.json").read_text())
        manifest["tools"][1]["policy"]["writes"] = "user_tree"
        (tmp_path / "packages/shared-schema/agent-tools.json").write_text(json.dumps(manifest))
        assert _run(tmp_path) == 1

    def test_an_auto_approved_networked_tool_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        manifest = json.loads((tmp_path / "packages/shared-schema/agent-tools.json").read_text())
        manifest["tools"][0]["policy"]["touches_network"] = True
        (tmp_path / "packages/shared-schema/agent-tools.json").write_text(json.dumps(manifest))
        assert _run(tmp_path) == 1

    def test_a_drifted_wire_artifact_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/shared-schema/agent-tools.anthropic.json").write_text(
            json.dumps([{"name": "read_file"}])
        )
        assert _run(tmp_path) == 1

    def test_a_drifted_webview_artifact_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/desktop/src/generated/agentTools.ts").write_text(
            'export const AGENT_TOOLS = [{ name: "read_file" }];\n'
        )
        assert _run(tmp_path) == 1

    def test_a_second_listing_source_in_a_seam_fails(self, tmp_path: Path) -> None:
        _passing_tree(tmp_path)
        (tmp_path / "packages/platform/server/tempest/second.mjs").write_text(
            'import { manifestToolMap } from "../../app/clients/tools/manifest";\n'
        )
        assert _run(tmp_path) == 1
