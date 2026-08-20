"""F16, the server half — Tempest as a verification oracle any coding agent can call.

    python -m tempest.mcp

**Why this half matters more than the client half.** As an MCP *client* Tempest gets ecosystem
parity. As an MCP *server* it becomes the thing every other coding agent asks before claiming a
task is done — including the ones it competes with. Every agent alive today can say "tests pass"
and hope; none of them can say what changed behaviourally, because none of them execute two
revisions and compare. This exposes that.

**Four tools, and the list is short on purpose.**

* `prove` — the oracle. Two revisions in, a verdict and its evidence out.
* `explain_behavior` — F4's behavioural spec: what a function DOES, from execution, with an
  observation id behind every sentence.
* `minimize_repro` — the smallest input that still shows a divergence, from a stored bundle.
* `check_intent_contract` — how a bundle's divergences classify against a stated intent.

`mutation_score` is named in the spec and is **not here**, because F9 (Phase 24) has not been
built. Declaring a tool that always refuses would spend a caller's turn to tell them so.

**Nothing here authors a verdict** (L17). Every value a tool returns is an engine output or a
transformation of one, and the model on the other end of the wire is a caller, not a source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tempest.agent import contracts as contracts_mod
from tempest.bundle.bundle import read_bundle, run_verdict
from tempest.index import specs as specs_mod
from tempest.index.build import build_index
from tempest.index.store import index_for
from tempest.mcp.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    TOOL_REFUSED,
    Request,
    RpcError,
    serve,
)
from tempest.prove import ProveConfig, run_prove

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "tempest"

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "prove",
        "description": (
            "Run a differential proof between two revisions of a repository and return the "
            "verdict with its evidence. This is the only way to learn whether a change altered "
            "behaviour: it executes both revisions on generated inputs and compares canonically. "
            "A DIVERGENT verdict means behaviour changed and names the smallest input that shows "
            "it. UNPROVEN means nothing could be established — it is not a pass."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["repo", "base", "head"],
            "properties": {
                "repo": {"type": "string", "description": "path to the git repository"},
                "base": {"type": "string", "description": "the revision to compare against"},
                "head": {"type": "string", "description": "the revision under test"},
                "max_inputs": {"type": "integer", "description": "input budget per target"},
            },
        },
    },
    {
        "name": "explain_behavior",
        "description": (
            "Describe what a function actually does, derived from executing it — not from "
            "reading its source. Every claim cites the observation that supports it. A function "
            "whose name promises one thing and whose body does another is described by its body."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["repo", "qualname"],
            "properties": {
                "repo": {"type": "string"},
                "qualname": {"type": "string", "description": "e.g. `total` or `Money.cents`"},
                "max_inputs": {"type": "integer"},
            },
        },
    },
    {
        "name": "minimize_repro",
        "description": (
            "The smallest input that still shows a divergence, from a bundle a previous `prove` "
            "wrote, together with what each revision did with it."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["bundle_dir"],
            "properties": {
                "bundle_dir": {"type": "string"},
                "qualname": {"type": "string", "description": "narrow to one symbol"},
            },
        },
    },
    {
        "name": "check_intent_contract",
        "description": (
            "Classify a bundle's divergences against a stated intent: INTENDED, UNINTENDED, or "
            "UNCLASSIFIED. Unclassified divergences are the ones nobody predicted, and are the "
            "most important to look at."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["bundle_dir"],
            "properties": {
                "bundle_dir": {"type": "string"},
                "repo": {"type": "string"},
                "task_id": {"type": "string"},
            },
        },
    },
)


def handle(request: Request) -> dict[str, Any]:
    """One request, one result. Raises `RpcError` for anything a caller can act on."""
    if request.method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": _version()},
        }
    if request.method == "tools/list":
        return {"tools": list(TOOLS)}
    if request.method == "tools/call":
        return _call(request.params)
    if request.method == "ping":
        return {}
    raise RpcError(METHOD_NOT_FOUND, f"unknown method {request.method!r}")


def _version() -> str:
    import tempest

    return getattr(tempest, "__version__", "0")


def _text(payload: object) -> dict[str, Any]:
    """MCP tool results are content blocks. One JSON block, because a caller parsing prose is a
    caller guessing."""
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


def _call(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments")
    if not isinstance(name, str) or not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "tools/call needs a `name` and an `arguments` object")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise RpcError(
            METHOD_NOT_FOUND,
            f"unknown tool {name!r}; this server offers {', '.join(sorted(_HANDLERS))}",
        )
    return _text(handler(args))


def _need(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError(INVALID_PARAMS, f"{key!r} is required and must be a non-empty string")
    return value


def _prove(args: dict[str, Any]) -> dict[str, Any]:
    repo = Path(_need(args, "repo"))
    budget = args.get("max_inputs")
    result = run_prove(
        ProveConfig(
            repo=repo,
            base=_need(args, "base"),
            head=_need(args, "head"),
            max_inputs=int(budget) if isinstance(budget, int) and budget > 0 else 30,
        )
    )
    return {
        "verdict": run_verdict(result.bundle.targets).value,
        "bundle_dir": str(result.bundle_dir),
        "sandbox_tier": result.sandbox_tier,
        "targets": [
            {
                "qualname": t.qualname,
                "file": t.file_path,
                "verdict": t.verdict.value,
                "reason": t.reason_detail or "",
                "inputs_run": t.inputs_run,
                "divergences": [
                    {
                        "class": d.divergence_class.value,
                        "detail": d.detail,
                        "minimized_args": d.minimized_args,
                        "minimized_kwargs": d.minimized_kwargs,
                        "base": d.base_summary,
                        "head": d.head_summary,
                    }
                    for d in t.divergences
                ],
            }
            for t in result.bundle.targets
        ],
    }


def _explain_behavior(args: dict[str, Any]) -> dict[str, Any]:
    repo = Path(_need(args, "repo"))
    qualname = _need(args, "qualname")
    budget = args.get("max_inputs")
    with index_for(repo) as conn:
        build_index(
            conn,
            repo,
            observe=True,
            only=frozenset({qualname}),
            max_inputs=int(budget) if isinstance(budget, int) and budget > 0 else 24,
        )
        spec = specs_mod.synthesize(conn, qualname)
        backed, detail = specs_mod.every_claim_is_backed(conn, spec)
    if not backed:  # pragma: no cover - the type refuses an unbacked claim at construction
        raise RpcError(TOOL_REFUSED, f"refusing to return unbacked claims: {detail}")
    return {
        "qualname": spec.qualname,
        "span": spec.span,
        "signature": spec.signature,
        "inputs_observed": spec.inputs_observed,
        "unobserved": spec.unobserved,
        "claims": [{"text": c.text, "observations": list(c.observations)} for c in spec.claims],
        "markdown": spec.render(),
    }


def _minimize_repro(args: dict[str, Any]) -> dict[str, Any]:
    bundle = read_bundle(Path(_need(args, "bundle_dir")))
    wanted = args.get("qualname")
    rows = [
        {
            "qualname": t.qualname,
            "class": d.divergence_class.value,
            "minimized_args": d.minimized_args,
            "minimized_kwargs": d.minimized_kwargs,
            "base": d.base_summary,
            "head": d.head_summary,
            "repro_script": bundle.repro_scripts.get(d.repro_filename or "", ""),
        }
        for t in bundle.targets
        for d in t.divergences
        if not isinstance(wanted, str) or t.qualname == wanted
    ]
    if not rows:
        raise RpcError(
            TOOL_REFUSED,
            "that bundle records no divergence to minimize"
            + (f" for {wanted!r}" if isinstance(wanted, str) else ""),
        )
    return {"divergences": rows}


def _check_intent_contract(args: dict[str, Any]) -> dict[str, Any]:
    bundle = read_bundle(Path(_need(args, "bundle_dir")))
    repo = args.get("repo")
    task_id = args.get("task_id")
    contract = (
        contracts_mod.load(Path(repo), str(task_id))
        if isinstance(repo, str) and isinstance(task_id, str)
        else None
    )
    return {
        "contract": None
        if contract is None
        else {
            "intent": contract.intent,
            "may_change": list(contract.may_change),
            "must_not_change": list(contract.must_not_change),
        },
        "divergences": [
            {
                "qualname": t.qualname,
                "classification": (
                    contract.classify(t.qualname)
                    if contract is not None
                    else contracts_mod.UNCLASSIFIED
                ),
                "detail": d.detail,
            }
            for t in bundle.targets
            for d in t.divergences
        ],
    }


_HANDLERS: dict[str, Any] = {
    "prove": _prove,
    "explain_behavior": _explain_behavior,
    "minimize_repro": _minimize_repro,
    "check_intent_contract": _check_intent_contract,
}


def main() -> int:
    """Serve until the client closes the stream.

    There is deliberately no `if __name__ == "__main__"` guard here: `python -m tempest.mcp`
    goes through `mcp/__main__.py`, which is the documented entry point and the one a client
    spawns. A second way in would be a second thing to keep working, reachable only by running
    this file by path — and unreachable code in a server is where a divergence hides.
    """
    serve(handle)
    return 0
