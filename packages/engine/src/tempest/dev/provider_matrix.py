"""Phase 19.5 gate: `python -m tempest.dev.provider_matrix --min-providers 12`.

The master prompt asks for 12+ providers and for adding one to cost no feature code. This gate
proves both **without a single network call by default**, which is the point: a gate that needs
twelve sets of paid credentials is a gate that never runs, and a gate that never runs is a claim
rather than a fact (trap 37).

What the default run proves, entirely offline:

* the registry holds at least `--min-providers` entries with unique ids;
* every entry is reachable by a wire this codebase actually implements — a row we cannot speak
  to would be a provider count that lies;
* remote entries use https and name the environment variable their key arrives in, and local
  entries are loopback and demand no key at all;
* the request Tempest *would* send is built correctly for each entry, checked against a real
  loopback peer speaking that wire — so the plumbing is exercised, not assumed.

`--live` additionally calls the providers whose keys are actually present, and reports
**"N of M verified live"**. That number is deliberately partial and deliberately honest: claiming
twelve live providers we never called would be exactly the kind of unearned claim this product
exists to refuse (QV10).
"""

import argparse
import json
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from tempest.inference import client as mc
from tempest.inference import providers as mp


@contextmanager
def _loopback_peer(wire: str) -> Iterator[str]:
    """A real server speaking `wire`, so the request path is executed rather than imagined."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # the http.server contract dictates this name
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if wire == mp.WIRE_ANTHROPIC:
                document = {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            else:
                document = {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            body = json.dumps(document).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _check_registry(minimum: int, problems: list[str]) -> None:
    if len(mp.PROVIDERS) < minimum:
        problems.append(f"registry holds {len(mp.PROVIDERS)} providers, need >= {minimum}")
    if len(set(mp.ids())) != len(mp.ids()):
        problems.append("duplicate provider ids in the registry")
    for provider in mp.PROVIDERS:
        if provider.wire not in mp.WIRES:
            problems.append(f"{provider.id}: wire {provider.wire!r} is not implemented")
        if provider.local:
            if provider.needs_key:
                problems.append(f"{provider.id}: local providers must not demand a key")
            if not provider.base_url.startswith("http://127.0.0.1"):
                problems.append(f"{provider.id}: local providers must be loopback")
        else:
            if not provider.base_url.startswith("https://"):
                problems.append(f"{provider.id}: remote providers must use https")
            if not provider.env_var:
                problems.append(f"{provider.id}: remote providers must name a key variable")


def _exercise(provider: mp.Provider, problems: list[str]) -> bool:
    """Send the request this provider would receive, to a local peer of the same wire."""
    try:
        with _loopback_peer(provider.wire) as base:
            env = {provider.base_url_env(): base}
            if provider.needs_key:
                env[provider.env_var] = "gate-key"
            out = mc.complete(
                provider.id,
                [mc.Message("user", "ping")],
                env=env,
                model=provider.default_model or "gate-model",
                timeout=10,
            )
        if out.text != "ok":
            problems.append(f"{provider.id}: response parsing returned {out.text!r}")
            return False
        return True
    except mc.ModelError as err:
        problems.append(f"{provider.id}: {type(err).__name__}: {err}")
        return False


def _live(provider: mp.Provider, model: str | None) -> tuple[bool, str]:
    """Call the real endpoint. Only ever attempted when a key is actually present."""
    try:
        out = mc.complete(
            provider.id,
            [mc.Message("user", "Reply with the single word: ok")],
            env=dict(os.environ),
            model=model or provider.default_model,
            max_tokens=16,
            timeout=30,
        )
    except mc.ModelError as err:
        return False, f"{type(err).__name__}: {err}"[:120]
    return True, f"{out.usage.input_tokens}+{out.usage.output_tokens} tokens"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-providers", type=int, default=16)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also call providers whose keys are present, and report N of M verified live",
    )
    parser.add_argument("--model", default=None, help="model id to use for --live calls")
    args = parser.parse_args(argv)

    problems: list[str] = []
    _check_registry(args.min_providers, problems)

    print(f"provider matrix — {len(mp.PROVIDERS)} configured, wires: {', '.join(mp.WIRES)}")
    print(f"{'id':<16} {'wire':<10} {'key variable':<24} {'local':<6} {'plumbing':<9} live")
    live_ok = live_attempted = 0
    for provider in mp.PROVIDERS:
        wired = _exercise(provider, problems)
        key_present = (not provider.needs_key) or bool(os.environ.get(provider.env_var, "").strip())
        live_note = "-"
        if args.live and key_present:
            live_attempted += 1
            ok, note = _live(provider, args.model)
            live_ok += 1 if ok else 0
            live_note = ("ok " + note) if ok else ("FAIL " + note)
        elif args.live:
            live_note = "no key"
        print(
            f"{provider.id:<16} {provider.wire:<10} {provider.env_var or '(none)':<24} "
            f"{('yes' if provider.local else 'no'):<6} {('ok' if wired else 'FAIL'):<9} {live_note}"
        )

    if args.live:
        # Deliberately partial and deliberately honest (QV10): we report what we called.
        print(
            f"\nlive: {live_ok} of {len(mp.PROVIDERS)} verified live "
            f"({live_attempted} attempted, the rest have no key configured)"
        )

    if problems:
        print(f"provider_matrix: {len(problems)} problem(s) — FAIL")
        for problem in problems:
            print(f"PROVIDER-GATE {problem}", file=sys.stderr)
        return 1
    print(
        f"provider_matrix: {len(mp.PROVIDERS)} providers, every request path exercised against a "
        f"real peer — adding a provider is one row, not one integration"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
