"""F16's gate — the MCP server driven over a REAL stdio pipe by a real JSON-RPC client.

    python -m tempest.dev.mcp_check

**What this proves, and what it does not.** F16's stated gate is a recorded demo of Claude Code
refusing to mark a refactor complete when Tempest answers DIVERGENT. That demo needs a second
product and a person to watch it, and it is an owner action. What a keyless run CAN prove is
everything underneath it: that the server speaks the protocol, that its advertised tool list and
its implemented tool set are the same set in both directions, that `prove` really executes and
really returns DIVERGENT for a behaviour change and EQUIVALENT_UNDER_BUDGET for a no-op refactor,
that a malformed request produces an error object rather than a dead connection, and that
**nothing but JSON-RPC ever reaches stdout** — the failure that silently corrupts every client.

The server runs as a genuine subprocess over genuine pipes. Nothing here is mocked (L4).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

_BASE = "def total(xs):\n    return sum(xs)\n"
#: A real behaviour change — what an agent must be told about.
_DIVERGENT = "def total(xs):\n    return sum(xs) + 1\n"
#: A no-op refactor — what an agent must NOT be told is a change.
_REFACTOR = "def total(xs):\n    result = sum(xs)\n    return result\n"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


class _Client:
    """The smallest honest MCP client: one request, one response, over real pipes."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._next = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next += 1
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": self._next, "method": method, "params": params or {}}
            )
            + "\n"
        )
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("the server closed the stream without answering")
        return json.loads(line)  # type: ignore[no-any-return]

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def raw(self, text: str) -> dict[str, Any]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())  # type: ignore[no-any-return]


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-mcp",
            "GIT_AUTHOR_EMAIL": "mcp@tempest",
            "GIT_COMMITTER_NAME": "tempest-mcp",
            "GIT_COMMITTER_EMAIL": "mcp@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )
    return done.stdout.strip()


def _repo(root: Path, head_source: str) -> tuple[Path, str, str]:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text(_BASE, encoding="utf-8")
    (repo / ".tempest-first-party").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text(head_source, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _is_rpc(line: str) -> bool:
    """Is this line a JSON-RPC message, or something that has corrupted the stream?

    The check that made this real: the first version asserted `True` with a note saying a stray
    print "would have failed a read above". It would have failed the NEXT read — which is a
    different claim, and one a gate should not make on its own behalf. So the leftover stream is
    drained and every line in it is checked. A library that prints a deprecation warning on
    import, or a tool that debugs to stdout, lands here.
    """
    try:
        payload = json.loads(line)
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("jsonrpc") == "2.0"


def _content(response: dict[str, Any]) -> dict[str, Any]:
    blocks = response["result"]["content"]
    return json.loads(blocks[0]["text"])  # type: ignore[no-any-return]


def run() -> list[Check]:
    import os

    from tempest.mcp import server as server_mod

    checks: list[Check] = []
    with TemporaryDirectory(prefix="tempest-mcp-") as tmp:
        root = Path(tmp)
        proc = subprocess.Popen(
            [sys.executable, "-m", "tempest.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "TEMPEST_DEV": "1", "TEMPEST_NO_POWER_PAUSE": "1"},
        )
        client = _Client(proc)
        try:
            handshake = client.call("initialize", {"protocolVersion": server_mod.PROTOCOL_VERSION})
            checks.append(
                Check(
                    "the handshake answers with a protocol version and a server name",
                    handshake.get("result", {}).get("protocolVersion")
                    == server_mod.PROTOCOL_VERSION
                    and handshake["result"]["serverInfo"]["name"] == server_mod.SERVER_NAME,
                    json.dumps(handshake.get("result", {}).get("serverInfo", {})),
                )
            )
            client.notify("notifications/initialized")

            listed = {t["name"] for t in client.call("tools/list")["result"]["tools"]}
            implemented = set(server_mod._HANDLERS)
            checks.append(
                Check(
                    "the advertised tools and the implemented tools are the same set",
                    listed == implemented,
                    f"advertised-only {sorted(listed - implemented)}, "
                    f"implemented-only {sorted(implemented - listed)}",
                )
            )
            checks.append(
                Check(
                    "every advertised tool describes what it is for",
                    all(
                        len(t["description"]) > 80 and t["inputSchema"]["type"] == "object"
                        for t in client.call("tools/list")["result"]["tools"]
                    ),
                    "a tool a model cannot understand is a tool it will misuse",
                )
            )

            repo, base, head = _repo(root, _DIVERGENT)
            proved = _content(
                client.call(
                    "tools/call",
                    {
                        "name": "prove",
                        "arguments": {"repo": str(repo), "base": base, "head": head},
                    },
                )
            )
            checks.append(
                Check(
                    "a real behaviour change comes back DIVERGENT, with the input that shows it",
                    proved["verdict"] == "DIVERGENT"
                    and any(t["divergences"] for t in proved["targets"]),
                    f"{proved['verdict']} over {len(proved['targets'])} target(s)",
                )
            )
            checks.append(
                Check(
                    "the verdict carries a bundle a caller can go and read",
                    bool(proved["bundle_dir"]) and Path(proved["bundle_dir"]).is_dir(),
                    proved["bundle_dir"],
                )
            )

            minimized = _content(
                client.call(
                    "tools/call",
                    {
                        "name": "minimize_repro",
                        "arguments": {"bundle_dir": proved["bundle_dir"], "qualname": "total"},
                    },
                )
            )
            checks.append(
                Check(
                    "the smallest failing input is available to the caller",
                    bool(minimized["divergences"])
                    and bool(minimized["divergences"][0]["minimized_args"]),
                    str(minimized["divergences"][0]["minimized_args"])[:40],
                )
            )

            classified = _content(
                client.call(
                    "tools/call",
                    {
                        "name": "check_intent_contract",
                        "arguments": {"bundle_dir": proved["bundle_dir"]},
                    },
                )
            )
            checks.append(
                Check(
                    "with no contract on file every divergence is UNCLASSIFIED, not approved",
                    all(d["classification"] == "UNCLASSIFIED" for d in classified["divergences"]),
                    f"{len(classified['divergences'])} divergence(s)",
                )
            )

            explained = _content(
                client.call(
                    "tools/call",
                    {
                        "name": "explain_behavior",
                        "arguments": {"repo": str(repo), "qualname": "total", "max_inputs": 12},
                    },
                )
            )
            checks.append(
                Check(
                    "every behavioural claim cites an observation",
                    bool(explained["claims"])
                    and all(c["observations"] for c in explained["claims"]),
                    f"{len(explained['claims'])} claim(s)",
                )
            )

            refactor_repo, r_base, r_head = _repo(root / "second", _REFACTOR)
            refactored = _content(
                client.call(
                    "tools/call",
                    {
                        "name": "prove",
                        "arguments": {
                            "repo": str(refactor_repo),
                            "base": r_base,
                            "head": r_head,
                        },
                    },
                )
            )
            checks.append(
                Check(
                    "a genuine no-op refactor is NOT reported as a behaviour change",
                    refactored["verdict"] == "EQUIVALENT_UNDER_BUDGET",
                    refactored["verdict"],
                )
            )

            unknown = client.call("tools/call", {"name": "no_such_tool", "arguments": {}})
            checks.append(
                Check(
                    "an unknown tool is an error object, not a dead connection",
                    "error" in unknown and "no_such_tool" in unknown["error"]["message"],
                    unknown.get("error", {}).get("message", "")[:60],
                )
            )
            malformed = client.raw("{not json at all")
            checks.append(
                Check(
                    "a malformed message is an error object, and the server keeps serving",
                    "error" in malformed and client.call("ping").get("result") == {},
                    malformed.get("error", {}).get("message", "")[:40],
                )
            )
            exploded = client.call(
                "tools/call",
                {"name": "minimize_repro", "arguments": {"bundle_dir": "/nowhere/at/all"}},
            )
            checks.append(
                Check(
                    "an UNEXPECTED failure inside a tool is an error object, and the loop lives",
                    "error" in exploded and client.call("ping").get("result") == {},
                    exploded.get("error", {}).get("message", "")[:50],
                )
            )

            missing = client.call("tools/call", {"name": "prove", "arguments": {"repo": "x"}})
            checks.append(
                Check(
                    "a call with missing arguments says which one",
                    "error" in missing and "base" in missing["error"]["message"],
                    missing.get("error", {}).get("message", "")[:50],
                )
            )
        finally:
            assert proc.stdin is not None
            proc.stdin.close()
            leftover = proc.stdout.read() if proc.stdout else ""
            proc.wait(timeout=30)
            stderr = (proc.stderr.read() if proc.stderr else "") or ""

        stray = [line for line in leftover.splitlines() if line.strip() and not _is_rpc(line)]

        checks.append(
            Check(
                "the server exits cleanly when its input ends",
                proc.returncode == 0,
                f"exit {proc.returncode}",
            )
        )
        checks.append(
            Check(
                "nothing but JSON-RPC ever reached stdout",
                not stray,
                f"{len(stray)} stray line(s) on the protocol stream"
                + (f": {stray[0][:40]!r}" if stray else ""),
            )
        )
        checks.append(
            Check(
                "diagnostics went to stderr or nowhere, never into the protocol",
                "jsonrpc" not in stderr,
                f"{len(stderr)} byte(s) on stderr",
            )
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", action="store_true", default=True)
    parser.parse_args(argv)

    checks = run()
    print(f"{'invariant':<66} status")
    for check in checks:
        print(f"{check.name:<66} {'PASS' if check.ok else 'FAIL'}  {check.detail[:50]}")
    failed = [c for c in checks if not c.ok]
    print("")
    print(f"mcp_check: {len(checks) - len(failed)}/{len(checks)} invariants held")
    print("")
    print(
        "NOT proved here: F16's recorded demo of another agent refusing to finish on DIVERGENT.\n"
        "That needs a second product and a person to watch it, and is an owner action."
    )
    for check in failed:
        print(f"MCP-CHECK {check.name}: {check.detail}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
