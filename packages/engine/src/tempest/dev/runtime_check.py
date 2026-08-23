"""C5 gate: `python -m tempest.dev.runtime_check --single-orchestrator --single-tool-registry`

Law L29: two agent runtimes is a bug, not an architecture. This gate makes both halves of
that sentence mechanical, and every check is proven to FAIL on a violating tree by its unit
pins (a gate that cannot fail is decoration).

--single-orchestrator
1. `tempest/agent/orchestrator.py` holds the ONE turn loop: exactly one function returns
   `AgentRun`, exactly one `ProvenChange(...)` construction site, exactly one `run_prove(`
   call — the L16 forge property held as a standing gate, by AST, so a fixture tree can be
   judged without importing it.
2. The conversational surface cannot proof-claim: `tempest_api/chatturn.py` references
   neither `ProvenChange` nor `run_prove` — a chat turn authors no repo change, so there is
   nothing L28 could even be asked about.
3. The vendored agent runtime is DORMANT on the desktop path: the two anchor files still
   carry their engines (`initialize.js` constructing `AgentClient`, `client.js` calling
   `createRun(`) — an anchor that vanishes forces a re-audit, never a silent pass — and no
   seam file (`packages/platform/*/tempest/**`) reaches them: no `@librechat/agents`, no
   `controllers/agents/client`, no `createRun(`, and the local seam serves no model wire
   itself (`chat/completions` absent from `local-api.mjs`).
4. The desktop chat family is host-claimed: `platform_web.rs` routes through
   `agent_chat::handle_chat` before anything can reach the Node sidecar.

--single-tool-registry
5. The committed manifest (`packages/shared-schema/agent-tools.json`) and the Python
   dispatch table (`tempest/agent/tools.py` `HANDLERS`) name the same tools, in both
   directions, by AST — the drift gate covers dispatch even when the unit suite is not
   running.
6. Both model-facing artifacts name exactly the canonical set.
7. Every policy holds the Rust invariants' reflection: `writes` ∈ {none, shadow_worktree}
   (a user-tree write stays unrepresentable), and a networked or destructive tool is never
   auto-approved.
8. The generated webview artifact (`agentTools.ts`) names exactly the manifest's tools.
9. No second listing source: no seam file imports LibreChat's `manifest.json` tool map or
   `toolConstructors` — what clients can list is what the one registry declares.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "__pycache__", "target"}


def _repo_root(start: Path) -> Path:
    """Walk up to the checkout root, matching dev/parity.py."""
    for candidate in [start, *start.parents]:
        if (candidate / "packages" / "desktop").is_dir():
            return candidate
    raise SystemExit("runtime_check: no repository root above " + str(start))


def _seam_files(root: Path) -> list[Path]:
    out: list[Path] = []
    platform = root / "packages" / "platform"
    if not platform.is_dir():
        return out
    for pkg in sorted(platform.iterdir()):
        seam = pkg / "tempest"
        if not seam.is_dir():
            continue
        stack = [seam]
        while stack:
            current = stack.pop()
            for entry in sorted(current.iterdir()):
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in _SKIP_DIRS:
                        stack.append(entry)
                elif entry.suffix in {".mjs", ".js", ".ts", ".tsx", ".cjs", ".mts"}:
                    out.append(entry)
    return out


def _ast_or_none(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None


def _call_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return names


def _returns_agent_run(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.returns is not None:
            annotation = ast.unparse(node.returns)
            if "AgentRun" in annotation and "SubagentRun" not in annotation:
                out.append(node.name)
    return out


def _check_orchestrator(root: Path, fail: list[str]) -> None:
    orchestrator = root / "packages/engine/src/tempest/agent/orchestrator.py"
    tree = _ast_or_none(orchestrator)
    if tree is None:
        fail.append(f"{orchestrator}: missing or unparseable — the one runtime has no home")
        return
    producers = _returns_agent_run(tree)
    if producers != ["run_task"]:
        fail.append(
            f"{orchestrator}: functions returning AgentRun must be exactly ['run_task'], "
            f"found {producers} — a second producer is a second runtime"
        )
    calls = _call_names(tree)
    constructions = calls.count("ProvenChange")
    if constructions != 1:
        fail.append(
            f"{orchestrator}: ProvenChange constructed {constructions}x — one construction "
            "site is the L16 property"
        )
    proofs = calls.count("run_prove")
    if proofs != 1:
        fail.append(
            f"{orchestrator}: run_prove called {proofs}x — the loop terminates on ONE proof path"
        )

    chatturn = root / "packages/api/src/tempest_api/chatturn.py"
    chat_tree = _ast_or_none(chatturn)
    if chat_tree is None:
        fail.append(f"{chatturn}: missing or unparseable — the chat surface has no home")
        return
    chat_names = {node.id for node in ast.walk(chat_tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(chat_tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in ("ProvenChange", "run_prove"):
        if forbidden in chat_names:
            fail.append(
                f"{chatturn}: references {forbidden} — the conversational surface may never "
                "touch the proof vocabulary (L28 has nothing to gate there BECAUSE of this)"
            )


_PLATFORM_ANCHORS: tuple[tuple[str, str], ...] = (
    # (relative path, the engine signature that must still be there — dormant, not gone)
    ("packages/platform/server/server/services/Endpoints/agents/initialize.js", "AgentClient("),
    ("packages/platform/server/server/controllers/agents/client.js", "createRun("),
)

_SEAM_FORBIDDEN: tuple[str, ...] = (
    "@librechat/agents",
    "controllers/agents/client",
    "createRun(",
)


def _check_platform_dormant(root: Path, fail: list[str]) -> None:
    for rel, signature in _PLATFORM_ANCHORS:
        path = root / rel
        if not path.is_file() or signature not in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            fail.append(
                f"{rel}: anchor '{signature}' not found — the vendored runtime moved; "
                "re-audit the dormancy claim rather than letting it pass silently"
            )
    for seam in _seam_files(root):
        text = seam.read_text(encoding="utf-8", errors="replace")
        for forbidden in _SEAM_FORBIDDEN:
            if forbidden in text:
                fail.append(
                    f"{seam.relative_to(root)}: reaches the vendored agent runtime "
                    f"('{forbidden}') — the desktop path must delegate to the engine, "
                    "never wake the second loop"
                )
    local_api = root / "packages/platform/server/tempest/local-api.mjs"
    if local_api.is_file() and "chat/completions" in local_api.read_text(encoding="utf-8"):
        fail.append(
            f"{local_api.relative_to(root)}: speaks a model wire itself — the seam serves "
            "state, the engine's router serves models (ADR-0076)"
        )
    platform_web = root / "packages/desktop/src-tauri/src/platform_web.rs"
    if platform_web.is_file():
        if "agent_chat::handle_chat" not in platform_web.read_text(encoding="utf-8"):
            fail.append(
                f"{platform_web.relative_to(root)}: the chat family is not host-claimed — "
                "/api/agents/chat would fall through to the Node sidecar"
            )
    else:
        fail.append(f"{platform_web.relative_to(root)}: missing — no host seam")


def _handlers_from_tools_py(path: Path) -> set[str] | None:
    tree = _ast_or_none(path)
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            else:
                targets = [node.target.id] if isinstance(node.target, ast.Name) else []
            if "HANDLERS" in targets and isinstance(node.value, ast.Dict):
                keys: set[str] = set()
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add(key.value)
                return keys
    return None


def _manifest_tools(path: Path) -> list[dict[str, Any]] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tools = doc.get("tools")
    if not isinstance(tools, list):
        return None
    return [t for t in tools if isinstance(t, dict)]


def _names_from_wire_artifact(path: Path, *, nested: str | None) -> set[str] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = doc if isinstance(doc, list) else doc.get("tools")
    if not isinstance(rows, list):
        return None
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        target = row.get(nested) if nested else row
        if isinstance(target, dict) and isinstance(target.get("name"), str):
            names.add(target["name"])
        elif isinstance(row.get("name"), str):
            names.add(row["name"])
    return names


def _check_registry(root: Path, fail: list[str]) -> None:
    manifest_path = root / "packages/shared-schema/agent-tools.json"
    tools = _manifest_tools(manifest_path)
    if tools is None:
        fail.append(f"{manifest_path}: unreadable — no canonical registry, no runtime")
        return
    canonical = {t["name"] for t in tools if isinstance(t.get("name"), str)}

    handlers = _handlers_from_tools_py(root / "packages/engine/src/tempest/agent/tools.py")
    if handlers is None:
        fail.append("tempest/agent/tools.py: HANDLERS table not found — dispatch is untethered")
    elif handlers != canonical:
        fail.append(
            f"manifest vs HANDLERS drift: manifest-only {sorted(canonical - handlers)}, "
            f"handlers-only {sorted(handlers - canonical)} — the registry split in two"
        )

    for rel, nested in (
        ("packages/shared-schema/agent-tools.anthropic.json", None),
        ("packages/shared-schema/agent-tools.openai.json", "function"),
    ):
        names = _names_from_wire_artifact(root / rel, nested=nested)
        if names != canonical:
            fail.append(
                f"{rel}: names {sorted(names or set())} != canonical {sorted(canonical)} — "
                "what the model is told drifted from the enforcement point"
            )

    for tool in tools:
        name = str(tool.get("name"))
        policy = tool.get("policy")
        if not isinstance(policy, dict):
            fail.append(f"tool {name}: no policy object — an ungoverned tool")
            continue
        writes = policy.get("writes")
        if writes not in ("none", "shadow_worktree"):
            fail.append(
                f"tool {name}: writes={writes!r} — the user's working tree must stay "
                "unrepresentable (L19)"
            )
        risky = bool(policy.get("touches_network")) or bool(policy.get("destructive"))
        if risky and policy.get("approval") == "auto":
            fail.append(
                f"tool {name}: networked-or-destructive yet auto-approved — the Rust "
                "invariant's reflection must hold in the committed artifact too"
            )

    ts_path = root / "packages/desktop/src/generated/agentTools.ts"
    try:
        ts_text = ts_path.read_text(encoding="utf-8")
    except OSError:
        fail.append(f"{ts_path}: missing — the approval UI has no registry")
        ts_text = ""
    if ts_text:
        ts_names = set(re.findall(r'name:\s*"([^"]+)"', ts_text))
        if ts_names != canonical:
            fail.append(f"agentTools.ts names {sorted(ts_names)} != canonical {sorted(canonical)}")

    for seam in _seam_files(root):
        text = seam.read_text(encoding="utf-8", errors="replace")
        for forbidden in ("manifestToolMap", "toolConstructors", "clients/tools/manifest"):
            if forbidden in text:
                fail.append(
                    f"{seam.relative_to(root)}: lists tools from '{forbidden}' — a second "
                    "registry visible to clients"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single-orchestrator", action="store_true", required=True)
    parser.add_argument("--single-tool-registry", action="store_true", required=True)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else _repo_root(Path.cwd())
    fail: list[str] = []
    _check_orchestrator(root, fail)
    _check_platform_dormant(root, fail)
    _check_registry(root, fail)

    if fail:
        print(f"runtime_check: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"RUNTIME-GATE {problem}", file=sys.stderr)
        return 1
    print(
        "runtime_check: one orchestrator (run_task, one ProvenChange site, one proof path), "
        "one tool registry across four artifacts, vendored runtime dormant behind its "
        "anchors — L29 holds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
