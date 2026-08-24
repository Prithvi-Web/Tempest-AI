"""Tool dispatch for the agent orchestrator (Phase 21) — the enforcement point for boundary D.

**The tools are not declared here.** They are declared once, in Rust, at
`packages/desktop/src-tauri/src/agent_tools.rs`, and `make gen-contracts` emits the committed
`packages/shared-schema/agent-tools.json` that this module *reads*. A second declaration in
Python would be a second truth, and boundary D exists precisely because a model handed a stale
tool schema produces plausible calls that silently do the wrong thing (§9c).

That makes the drift gate cover dispatch as well as shape: `test_agent_tools.py` asserts the
handler set and the manifest's tool set are equal, in both directions. Adding a tool in Rust
therefore breaks the Python suite until someone implements it — which is the design working,
not an inconvenience.

**What this module enforces, and why each rule is here rather than in the model's prompt.**

* **Containment.** Every path argument is resolved and must land inside the worktree it belongs
  to. `..`, absolute paths, and symlinks that escape are refused. A guard's argument is not a
  proof of the guard (trap 45), so the check is on the RESOLVED path, and a file reachable under
  more than one name is refused outright rather than judged by the name it was requested under.
* **Write scope (L19), and READ scope too.** Every tool — reading and writing alike — operates
  on the SHADOW worktree, which is the only root this module is given. The user's checkout is not
  merely un-writable from here; it is unaddressable, because no function takes it as an argument.
  That is also the only correct reading root: a shadow is a full checkout of the baseline plus
  the agent's own edits, so reading the user's tree instead would show the agent a file it did
  not write and hide the one it did.
* **Budgets (L15.4).** Every call is bounded — bytes read, entries listed, matches returned,
  wall-clock for a command, and the number of calls in a turn. An unbounded operation is a law
  violation, not a performance concern.
* **Approval (§8).** A tool whose manifest policy is not `auto` requires an explicit grant. The
  policy is read from the manifest, so it cannot disagree with the schema the model was shown.

Nothing here consults a model, and nothing here computes a verdict.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tempest.agent import terminal
from tempest.execute.sandbox import Sandbox
from tempest.inference.client import ToolCatalog


def _schema_dir() -> Path:
    """Where the committed boundary-D artifacts live — in a checkout AND in the shipped app.

    A source-relative path alone was wrong in the one place it mattered most. Frozen by
    PyInstaller, this module's `__file__` points inside the extraction dir, so
    `parents[4] / "shared-schema"` resolved to somewhere above it that does not exist: in the
    installed app `listAgentTools` answered `FileNotFoundError`, the builder's Tool Library
    was EMPTY, and every tool-bearing agent turn died at `load_manifest()`. The whole C5
    surface was dark in the bundle while the repo, the e2e harness and both coverage gates
    stayed green — because all three run from the source tree.

    This is the failure class ADR-0028 already names in `tempest-server.spec` ("the frozen
    app would fail every TS prove while parity stays green"), and the manifest walked into it
    anyway. `build-server.sh` now loads the manifest THROUGH the frozen binary so the next one
    cannot.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled is not None:  # PyInstaller: shipped beside the engine as data (see the spec)
        return Path(bundled) / "shared-schema"
    # tools.py lives at packages/engine/src/tempest/agent/, so parents[4] is `packages/`.
    return Path(__file__).resolve().parents[4] / "shared-schema"


_SCHEMA_DIR = _schema_dir()
#: The committed boundary-D artifact. Read, never written, and never mirrored.
MANIFEST_PATH = _SCHEMA_DIR / "agent-tools.json"

#: Credential shapes that never leave the disk through a tool, matched on every path SEGMENT of
#: the resolved path and on its suffix. Mirrors `pathguard`'s list; see `ToolError` for why a
#: multi-named file is refused outright rather than matched by name (trap 45 — a hard link is
#: the same file under an innocent name, and no name-based rule can ever see it).
_DENY_SEGMENTS = frozenset({".env", ".ssh", "id_rsa", "id_ed25519", ".netrc", ".aws", ".gnupg"})
_DENY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keychain")


class ToolError(Exception):
    """A refusal the ORCHESTRATOR made. Carries a reason the model is shown verbatim.

    Refusals are values, not crashes: the turn continues with the refusal as the tool result, so
    the model can adapt. A refused call must never look to the model like a call that worked.
    """


@dataclass(frozen=True)
class ToolPolicy:
    """One tool's policy, exactly as the Rust manifest declares it."""

    approval: str
    destructive: bool
    touches_network: bool
    writes: str

    @property
    def needs_grant(self) -> bool:
        return self.approval != "auto"

    @property
    def writes_shadow(self) -> bool:
        return self.writes == "shadow_worktree"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    policy: ToolPolicy
    args_schema: Mapping[str, Any]


def load_manifest(path: Path | None = None) -> dict[str, ToolSpec]:
    """Parse the committed contract. Raises rather than defaulting: an orchestrator that cannot
    read the tool contract must not run with an improvised one."""
    source = MANIFEST_PATH if path is None else path
    doc: Any = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        raise ToolError(f"{source} is not a tool manifest")
    specs: dict[str, ToolSpec] = {}
    for entry in doc["tools"]:
        policy = entry["policy"]
        specs[entry["name"]] = ToolSpec(
            name=entry["name"],
            description=entry["description"],
            policy=ToolPolicy(
                approval=policy["approval"],
                destructive=bool(policy["destructive"]),
                touches_network=bool(policy["touches_network"]),
                writes=policy["writes"],
            ),
            args_schema=entry["args_schema"],
        )
    return specs


#: The model-facing artifacts, one per wire, emitted by the same `make gen-contracts` run that
#: emits the canonical manifest. Committed on purpose (§9c): what the model is told must be
#: visible in review rather than assembled at runtime.
ANTHROPIC_TOOLS_PATH = _SCHEMA_DIR / "agent-tools.anthropic.json"
OPENAI_TOOLS_PATH = _SCHEMA_DIR / "agent-tools.openai.json"


def model_facing_catalog(allowed: frozenset[str] | None = None) -> ToolCatalog:
    """Load both wire shapes and check they describe the SAME tools as the canonical manifest.

    The cross-check is the point. Three files are generated from one Rust declaration, and the
    failure this guards is not a parse error but a *silent* divergence — a model offered a tool
    the orchestrator cannot dispatch, or dispatchable tools the model is never told about. Either
    one is boundary D failing exactly as §9c describes, and neither is a type error.

    `allowed` narrows the catalog to an AGENT's tool selection (C5, LC15): the subset is applied
    AFTER the cross-check so a filtered catalog can never hide a drifted artifact, and a name
    outside the manifest is a loud error — an agent document naming a tool that does not exist
    is data corruption, not a preference.
    """
    anthropic: Any = json.loads(ANTHROPIC_TOOLS_PATH.read_text(encoding="utf-8"))
    openai: Any = json.loads(OPENAI_TOOLS_PATH.read_text(encoding="utf-8"))
    if not isinstance(anthropic, list) or not isinstance(openai, list):
        raise ToolError("the model-facing tool artifacts are not lists")
    canonical = set(load_manifest())
    named_anthropic = {str(entry.get("name")) for entry in anthropic}
    named_openai = {str(entry.get("function", {}).get("name")) for entry in openai}
    if named_anthropic != canonical or named_openai != canonical:
        raise ToolError(
            f"model-facing tools disagree with the manifest: canonical={sorted(canonical)} "
            f"anthropic={sorted(named_anthropic)} openai={sorted(named_openai)} — "
            f"run `make gen-contracts`"
        )
    if allowed is not None:
        unknown = allowed - canonical
        if unknown:
            raise ToolError(
                f"allowed tools {sorted(unknown)} are not in the manifest — the agent's tool "
                f"selection names something boundary D does not declare"
            )
        anthropic = [entry for entry in anthropic if str(entry.get("name")) in allowed]
        openai = [
            entry for entry in openai if str(entry.get("function", {}).get("name")) in allowed
        ]
    return ToolCatalog(anthropic=anthropic, openai=openai)


@dataclass(frozen=True)
class Budgets:
    """Every bound in one place, so "is this operation bounded?" has one answer (L15.4)."""

    max_read_bytes: int = 256 * 1024
    max_dir_entries: int = 500
    max_search_matches: int = 200
    max_command_seconds: int = 120
    max_calls_per_turn: int = 60
    #: Directory walks are bounded in DEPTH as well as count: a wide tree can exhaust the entry
    #: budget before reaching anything useful, which reads to the model as an empty repository.
    max_walk_depth: int = 3


@dataclass
class ToolResult:
    """What the model is shown. `ok=False` carries the refusal reason verbatim."""

    ok: bool
    content: str
    #: Set when a result was cut short by a budget, so the model is never silently given a
    #: partial answer it will treat as complete.
    truncated: bool = False


#: The one tool whose "approval" is a QUESTION rather than a grant (C5 HITL).
ASK_USER = "ask_user"


@dataclass(frozen=True)
class ApprovalRequest:
    """One approval-gated call, parked for a human (C5 HITL, LC18)."""

    tool: str
    arguments: dict[str, Any]
    call_id: str
    #: "tool_approval" for a grant question; "ask_user_question" for `ask_user`, whose
    #: decision carries an ANSWER instead.
    kind: str


@dataclass(frozen=True)
class ApprovalDecision:
    """What the human said. `scope="session"` grants the rest of THIS task — the
    prompt-once-per-project semantic; an always-prompt tool is re-asked regardless of scope.
    `response_text` carries the answer to an `ask_user` question."""

    approved: bool
    scope: str = "once"  # "once" | "session"
    response_text: str | None = None
    reason: str = ""


@dataclass
class Dispatcher:
    """Executes tool calls against ONE root — the task's shadow worktree — under one budget set.

    There is deliberately no second root. An earlier draft gave read tools the user's checkout
    and writes the shadow, which is wrong twice over: the agent would not see its own edits, and
    it would see whatever the user had uncommitted. A shadow is a full checkout of the baseline
    (`shadow.create`), so one root serves both, and L19 becomes a property of the type signature
    rather than a rule someone has to remember.
    """

    root: Path
    budgets: Budgets = field(default_factory=Budgets)
    #: Tool names the user has granted for this project (§8). A tool whose policy is not `auto`
    #: and whose name is absent is refused — never silently auto-approved.
    grants: frozenset[str] = frozenset()
    #: The isolation tier commands run at (F14, L19). `None` means the ladder offered nothing and
    #: `run_command` refuses — a refusal, never a degraded run.
    sandbox: Sandbox | None = None
    sandbox_tier: str = "none"
    #: Why there is no tier, quoted back to the model so the refusal is actionable.
    sandbox_reason: str = ""
    manifest: dict[str, ToolSpec] = field(default_factory=load_manifest)
    #: An AGENT's tool selection (C5, LC15). `None` means the full manifest; a set narrows
    #: dispatch to exactly those names — defense in depth beside the filtered catalog, so a
    #: model that hallucinates an unoffered tool still meets a refusal, never a handler.
    allowed: frozenset[str] | None = None
    calls_made: int = 0

    # -- approval (C5 HITL) --------------------------------------------------------------

    def approval_needed(self, name: str) -> bool:
        """True when dispatching `name` now would hit the approval gate.

        **The agent's selection is checked FIRST, and that ordering is load-bearing.** The
        `allowed` narrowing is enforced inside `call()` below, but `_dispatch_with_approval`
        consults this predicate to decide whether to park — and its `ask_user_question` arm
        returns the human's answer WITHOUT ever reaching `call()`. So while this read
        `manifest`-only, an agent whose selection excluded `ask_user` could still park the
        turn, put a question in front of the user, and have the answer injected into its
        transcript: the one tool that bypasses the dispatcher was the one tool the selection
        did not bind. The docstring on `allowed` promised the opposite, which is why it took
        a test to find — a guard's ARGUMENT is not a proof of the guard (trap 45).

        A tool outside the selection has nothing to approve: dispatch refuses it outright,
        so answering False here routes it to `call()`'s refusal, which names the agent's
        real toolset and is a sentence the model can act on. This also stops the user being
        asked to approve a call that was always going to be refused after they clicked.
        """
        if self.allowed is not None and name not in self.allowed:
            return False
        spec = self.manifest.get(name)
        return spec is not None and spec.policy.needs_grant and name not in self.grants

    def always_prompts(self, name: str) -> bool:
        """A tool declared `always_prompt` is re-asked every call; a session grant may
        never silence it — the declaration outranks the human's generosity, because the
        declaration was reviewed and the generosity is one tired click."""
        spec = self.manifest.get(name)
        return spec is not None and spec.policy.approval == "always_prompt"

    def grant(self, name: str) -> None:
        self.grants = self.grants | {name}

    def revoke(self, name: str) -> None:
        self.grants = self.grants - {name}

    # -- containment ---------------------------------------------------------------------

    def _resolve(self, raw: str) -> Path:
        """Resolve `raw` under the shadow root, refusing anything that escapes or is a credential.

        The denylist is applied to the RESOLVED path, and a file with more than one link is
        refused outright — a hard link is the same bytes under a different name, and no
        name-based rule can see it (trap 45).
        """
        if raw.startswith("/") or raw.startswith("~"):
            raise ToolError(f"path must be repository-relative, got {raw!r}")
        candidate = (self.root / raw).resolve()
        root_resolved = self.root.resolve()
        if not candidate.is_relative_to(root_resolved):
            raise ToolError(f"path escapes the worktree: {raw!r}")
        parts = {p.lower() for p in candidate.parts}
        if parts & _DENY_SEGMENTS:
            raise ToolError(f"refused: {raw!r} is a credential path")
        if candidate.name.lower().endswith(_DENY_SUFFIXES):
            raise ToolError(f"refused: {raw!r} is a credential file")
        if candidate.is_file() and candidate.stat().st_nlink > 1:
            raise ToolError(
                f"refused: {raw!r} has more than one name on disk, so what it IS cannot be "
                f"judged by what it was called"
            )
        return candidate

    # -- dispatch ------------------------------------------------------------------------

    def call(self, name: str, args: Mapping[str, Any]) -> ToolResult:
        """Run one tool call. Never raises for a refusal — refusals come back as results.

        **The counter is incremented exactly once, first, before anything that can refuse.** An
        earlier version incremented before dispatch AND again in the `except`, so a refusal
        raised *inside* a handler (a path escape, a missing file) consumed two units of a budget
        it should have consumed one of. Every test still passed, because they exercised the
        budget with early refusals, which took the other path. A mutation run found it.
        """
        self.calls_made += 1
        try:
            if self.calls_made > self.budgets.max_calls_per_turn:
                raise ToolError(
                    f"turn call budget exhausted ({self.budgets.max_calls_per_turn}) — "
                    f"an unbounded agent loop is a law violation, not a slow turn (L15.4)"
                )
            spec = self.manifest.get(name)
            if spec is None:
                raise ToolError(
                    f"unknown tool {name!r}; this orchestrator offers "
                    f"{', '.join(sorted(self.manifest))}"
                )
            if self.allowed is not None and name not in self.allowed:
                raise ToolError(
                    f"{name} is not part of this agent's toolset; it offers "
                    f"{', '.join(sorted(self.allowed)) or 'nothing'}"
                )
            if spec.policy.needs_grant and name not in self.grants:
                raise ToolError(
                    f"{name} requires approval ({spec.policy.approval}) and none was granted"
                )
            return HANDLERS[name](self, args)
        except ToolError as exc:
            return ToolResult(ok=False, content=str(exc))

    # -- the tools -----------------------------------------------------------------------

    def _read_file(self, args: Mapping[str, Any]) -> ToolResult:
        path = self._resolve(str(args["path"]))
        if not path.is_file():
            raise ToolError(f"not a file: {args['path']!r}")
        cap = self.budgets.max_read_bytes
        requested = args.get("max_bytes")
        if isinstance(requested, int) and not isinstance(requested, bool) and requested >= 0:
            cap = min(cap, requested)
        raw = path.read_bytes()
        body = raw[:cap].decode("utf-8", errors="replace")
        return ToolResult(ok=True, content=body, truncated=len(raw) > cap)

    def _list_dir(self, args: Mapping[str, Any]) -> ToolResult:
        path = self._resolve(str(args.get("path") or "."))
        if not path.is_dir():
            raise ToolError(f"not a directory: {args.get('path')!r}")
        recursive = bool(args.get("recursive"))
        entries: list[str] = []
        truncated = False
        for child in self._walk(path, recursive):
            if len(entries) >= self.budgets.max_dir_entries:
                truncated = True
                break
            rel = child.relative_to(path).as_posix()
            entries.append(f"{rel}/" if child.is_dir() else rel)
        return ToolResult(ok=True, content="\n".join(sorted(entries)), truncated=truncated)

    def _walk(self, root: Path, recursive: bool) -> list[Path]:
        if not recursive:
            return sorted(root.iterdir())
        found: list[Path] = []
        for current, dirnames, filenames in os.walk(root):
            here = Path(current)
            depth = len(here.relative_to(root).parts)
            if depth >= self.budgets.max_walk_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in sorted(dirnames) if d not in {".git", "node_modules"}]
            found.extend(here / n for n in sorted(filenames))
            found.extend(here / d for d in dirnames)
            if len(found) > self.budgets.max_dir_entries:
                break
        return found

    def _search_text(self, args: Mapping[str, Any]) -> ToolResult:
        pattern = str(args["pattern"])
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid pattern {pattern!r}: {exc}") from exc
        root = self._resolve(str(args.get("path") or "."))
        cap = self.budgets.max_search_matches
        requested = args.get("max_results")
        if isinstance(requested, int) and not isinstance(requested, bool) and requested >= 0:
            cap = min(cap, requested)
        hits: list[str] = []
        truncated = False
        for file in self._walk(root, recursive=True) if root.is_dir() else [root]:
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # a binary or unreadable file is not a match, and not an error
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    if len(hits) >= cap:
                        truncated = True
                        break
                    rel = file.relative_to(self.root.resolve()).as_posix()
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
            if truncated:
                break
        return ToolResult(ok=True, content="\n".join(hits), truncated=truncated)

    def _write_file(self, args: Mapping[str, Any]) -> ToolResult:
        # The shadow root, like every other tool here — there is no other root to reach.
        path = self._resolve(str(args["path"]))
        contents = str(args["contents"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return ToolResult(ok=True, content=f"wrote {len(contents)} bytes to {args['path']}")

    def _run_command(self, args: Mapping[str, Any]) -> ToolResult:
        """Run a command at the SAME isolation tier a differential runner would use (L19, F14).

        Phase 21 shipped this as a bare `subprocess.run(argv, cwd=shadow)` — the user's own uid,
        environment, network and whole filesystem, bounded by nothing but a working directory —
        under a manifest declaring `writes: shadow_worktree` and `touches_network: false`. Neither
        was true, so the tool was REFUSED rather than left running (trap 53). This is what makes
        refusing unnecessary.

        **No tier, no command.** When the ladder offers nothing the call is refused with the
        reason the selection gave. A degraded tier that ran anyway would be failure mode 3, and
        "the refusal is inconvenient" is not an argument.

        **The repository may be read-only**, and under T1 Docker it is. A command that writes into
        the worktree fails, and that is the design rather than a limitation to apologise for: an
        agent's writes belong in `write_file`, where they are staged, journalled and proved. A
        side effect the proof never sees is a change reaching the user without evidence, which is
        the one thing L16 exists to prevent.
        """
        argv_raw = args.get("argv")
        if not isinstance(argv_raw, Sequence) or isinstance(argv_raw, str) or not argv_raw:
            raise ToolError("argv must be a non-empty list of already-split arguments")
        if self.sandbox is None:
            raise ToolError(
                f"running commands needs an isolation tier and this machine has none: "
                f"{self.sandbox_reason or 'no OS-native sandbox is available'}. L19 requires an "
                f"agent command to execute at the same tier as a differential runner, and running "
                f"it unsandboxed would hand this tool the whole machine. Read, search and write "
                f"files instead; the proof runs when your turn ends either way."
            )
        argv = [str(a) for a in argv_raw]
        timeout = self.budgets.max_command_seconds
        requested = args.get("timeout_seconds")
        if isinstance(requested, int) and not isinstance(requested, bool) and requested > 0:
            timeout = min(timeout, requested)
        result = terminal.run(
            argv,
            root=self.root,
            sandbox=self.sandbox,
            timeout=timeout,
            max_bytes=self.budgets.max_read_bytes,
        )
        return ToolResult(
            ok=True, content=result.render(tier=self.sandbox_tier), truncated=result.truncated
        )

    def _prove(self, args: Mapping[str, Any]) -> ToolResult:
        """Dispatch exists so the manifest and the handler set cannot disagree; the ACTUAL proof
        is run by the orchestrator at the end of the turn, because a verdict is the turn's
        terminating condition and not a step the model may take or skip (F1, L16)."""
        raise ToolError(
            "`prove` is not callable as a step: the orchestrator proves the shadow worktree "
            "when the turn ends, and the verdict it computes is what terminates the turn. You "
            "may explain a verdict; you may never author one, and you may never ask for the "
            "proof to be skipped (L16)."
        )

    def _ask_user(self, args: Mapping[str, Any]) -> ToolResult:
        """Dispatch exists so the manifest and the handler set cannot disagree; the ACTUAL
        round-trip runs in the orchestrator's approval flow (C5 HITL), which turns the call
        into an `ApprovalRequest(kind="ask_user_question")` and hands back the human's answer
        as this tool's result. Reaching THIS handler means no approver is attached — a
        surface with nobody to ask — and inventing an answer would be the model talking to
        itself wearing the user's voice."""
        raise ToolError(
            "`ask_user` needs a human on the other end and this surface has none attached; "
            "state your assumption in narration and continue, or stop and say what is missing"
        )


HANDLERS: dict[str, Callable[[Dispatcher, Mapping[str, Any]], ToolResult]] = {
    "read_file": Dispatcher._read_file,
    "list_dir": Dispatcher._list_dir,
    "search_text": Dispatcher._search_text,
    "write_file": Dispatcher._write_file,
    "run_command": Dispatcher._run_command,
    "prove": Dispatcher._prove,
    "ask_user": Dispatcher._ask_user,
}
