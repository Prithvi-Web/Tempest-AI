"""EGRESS GATE, two legs.

**L10 (runtime):** `python -m tempest.dev.egress_check --expect-zero`. Every network-reaching
payload in the escape corpus is run inside the T2 sandbox and must be blocked; the sandbox's
`(deny network*)` rule stops the connection at the socket syscall, so no packet is ever
emitted. The count of successful outbound connections must be exactly zero, or the build
fails. The output is a sales artifact (§10).

**L32 (static, C3):** `python -m tempest.dev.egress_check --platform-tree --deny-all
--airplane-mode-full-function`. The adopted platform ships a full telemetry stack — HyperDX
RUM, Langfuse tracing, OpenTelemetry, GTM analytics, a Sandpack bundler, a PWA service worker.
L32 says the desktop product reaches the network only where the user asked it to, and that the
whole authed shell must render with the network unplugged. This leg is the static audit over
the vendored tree plus OUR seam files: every egress surface is off by default, the local-mode
config cannot silently enable one, and the sidecar cannot even *express* an outbound call.

Seven mechanical checks, each anchored to file:line evidence:

1. **The local-mode startup config carries no telemetry keys.** `local-api.mjs`'s
   `STARTUP_CONFIG` is the entire answer to `GET /api/config`; the client reads
   `startupConfig.rum` (`client/src/lib/rum/useRum.ts`, `shouldInitializeRum`),
   `analyticsGtmId`, `turnstile`, `bundlerURL` and `staticBundlerURL` from it. A key present
   at all is a switch someone can flip to `true` in one edit, so none may appear.
2. **The sidecar's import allowlist.** `boundary.mjs`, `boundary-validate.mjs` and
   `local-api.mjs` may import only `node:net`, `node:fs`, `node:process` and relative `./`
   modules. No `node:http`, no `node:https`, no bare package — the sidecar has no vocabulary
   in which to write an outbound request. The same files carry no `connect(`, `fetch(`,
   `createConnection`, `WebSocket`, `XMLHttpRequest` or `sendBeacon` token.
3. **No TCP listener.** `boundary.mjs` binds exactly one thing, and its `.listen()` argument
   is the `socketPath` read from `TEMPEST_PLATFORM_SOCKET` — never a numeric port.
4. **Langfuse and OTel are off by default, and no seam turns them on.** The upstream gates
   still read as audited: `api/src/langfuse/config.ts` requires BOTH `LANGFUSE_PUBLIC_KEY`
   and `LANGFUSE_SECRET_KEY`, `api/src/telemetry/config.ts` gates on
   `isTruthy(env.OTEL_TRACING_ENABLED)`. Those two anchors are a drift tripwire: if upstream
   restructures either, this gate FAILS and forces a re-audit rather than assuming the old
   finding still holds. Separately, no seam file and no line of the sidecar spawn
   (`desktop/src-tauri/src/platform.rs`) mentions `LANGFUSE_*`, `OTEL_TRACING_ENABLED`,
   `RUM_ENABLED`, `ANALYTICS_GTM_ID`, `RUM_PROXY_TARGET_URL` or `SANDPACK_BUNDLER_URL`.
5. **The service worker is neutralized.** The seam build config strips `vite-plugin-pwa` and
   THROWS if the plugin is absent (a silent no-op there could ship an update layer), and the
   `tempest://` protocol serves `/registerSW.js` as a no-op and 404s `/sw.js`.
6. **The client's hard-coded CDN constants are a closed ledger of two.** `TAILWIND_CDN`
   (`utils/artifacts.ts`) and `MARKED_CDN` (`utils/markdown.ts`) are upstream's artifact-iframe
   resources — unreachable in local mode until artifacts land at C9, and recorded here as
   known-C9 items. A THIRD such constant anywhere in `client/src/utils` fails: the ledger is
   closed, so a new CDN cannot arrive unnoticed. The RUM inline bootstrap
   (`client/src/lib/rum/bootstrap.js`) — the one script that runs before anything else on the
   page — carries no `fetch`, `sendBeacon`, `XMLHttpRequest`, `WebSocket` or `EventSource`.
7. **Airplane-mode full function.** `handleLocalApi` answers the whole boot surface that
   renders the authed shell — `GET /api/config`, `POST /api/auth/refresh`, `GET /api/user`,
   `GET /api/roles/USER`, `GET /api/health`, `GET /api/convos` — and `STARTUP_CONFIG` sets
   every `*LoginEnabled` key and `registrationEnabled` to `false`, so zero auth prompts and
   zero remote round-trips stand between launch and a usable window.

Scope, stated honestly. This leg is a LINT: it reads source text and proves properties of the
tree, not of a running process. The runtime proofs live elsewhere and are not duplicated here:
the L10 leg above is the syscall-level egress proof, the Linux-netns packet capture is the CI
leg, and the socket-only binding of a live sidecar is probed by `orphan_check` and the C2
desktop tests. What a lint buys that a runtime probe cannot is coverage of the paths a test run
never takes — the config key nobody set today, the import nobody added yet. Check 6 covers
`client/src/utils` and the RUM bootstrap, not every module in the vendored client; the general
"no new network call" rule across the whole client is the per-phase UI-integration review, and
naming that gap here keeps it a documented scope rather than a silent one.
"""

import argparse
import re
import sys
from pathlib import Path

from tempest.dev.escape_suite import PAYLOADS, run_matrix

# ── surfaces this leg audits, repository-relative ────────────────────────────────────────────
_LOCAL_API = "packages/platform/server/tempest/local-api.mjs"
_BOUNDARY = "packages/platform/server/tempest/boundary.mjs"
_BOUNDARY_VALIDATE = "packages/platform/server/tempest/boundary-validate.mjs"
_LANGFUSE_CONFIG = "packages/platform/api/src/langfuse/config.ts"
_TELEMETRY_CONFIG = "packages/platform/api/src/telemetry/config.ts"
_SEAM_VITE = "packages/platform/client/tempest/vite.config.mjs"
_RUM_BOOTSTRAP = "packages/platform/client/src/lib/rum/bootstrap.js"
_CLIENT_UTILS = "packages/platform/client/src/utils"
_PLATFORM_WEB_RS = "packages/desktop/src-tauri/src/platform_web.rs"
_PLATFORM_RS = "packages/desktop/src-tauri/src/platform.rs"

_SIDECAR_MODULES = (_BOUNDARY, _BOUNDARY_VALIDATE, _LOCAL_API)

#: Telemetry/egress switches the client reads straight off `GET /api/config`.
_FORBIDDEN_STARTUP_KEYS = ("analyticsGtmId", "rum", "turnstile", "bundlerURL", "staticBundlerURL")

#: The sidecar's whole import vocabulary. Relative `./` specifiers are allowed separately.
_ALLOWED_IMPORTS = frozenset({"node:net", "node:fs", "node:process"})

#: Tokens through which any JavaScript reaches the network.
_OUTBOUND_TOKENS = (
    r"\bcreateConnection\b",
    r"\bconnect\s*\(",
    r"\bfetch\s*\(",
    r"\bXMLHttpRequest\b",
    r"\bWebSocket\b",
    r"\bsendBeacon\b",
    r"\bEventSource\b",
    r"\bimportScripts\s*\(",
)

#: Environment names that would switch a telemetry exporter on. No seam may write one. Written
#: as patterns so the failure quotes the identifier it actually found (`LANGFUSE_PUBLIC_KEY`),
#: not the family it belongs to — evidence a reader can grep for.
_TELEMETRY_ENV = (
    r"\bLANGFUSE_\w+",
    r"\bOTEL_TRACING_ENABLED\b",
    r"\bRUM_ENABLED\b",
    r"\bANALYTICS_GTM_ID\b",
    r"\bRUM_PROXY_TARGET_URL\b",
    r"\bSANDPACK_BUNDLER_URL\b",
)

#: The boot surface that renders the authed shell with the network unplugged.
_REQUIRED_ROUTES = (
    "GET /api/config",
    "POST /api/auth/refresh",
    "GET /api/user",
    "GET /api/roles/USER",
    "GET /api/health",
    "GET /api/convos",
)

#: The closed ledger of check 6: (path relative to `client/src/utils`, constant name).
_KNOWN_CDN_CONSTANTS = frozenset({("artifacts.ts", "TAILWIND_CDN"), ("markdown.ts", "MARKED_CDN")})

#: Every way a module can be named: static `import … from "x"`, bare `import "x"`, dynamic
#: `import("x")`, and `require("x")` — a sidecar that reached the network through the one form
#: this gate forgot would be the whole failure.
_MODULE_SPECIFIER = re.compile(
    r"(?:^[ \t]*import\s+(?:[^'\"]*?\sfrom\s+)?"
    r"|\bimport\s*\(\s*"
    r"|\brequire\s*\(\s*)"
    r"['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_LISTEN_CALL = re.compile(r"\.listen\s*\(\s*([^,)\s]+)")
_CDN_CONSTANT = re.compile(
    r"^[ \t]*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]*)?=\s*['\"`](https://[^'\"`\n]*)",
    re.MULTILINE,
)
_LOGIN_KEY = re.compile(r"\b(\w*LoginEnabled)\s*:\s*(\w+)")
_CLIENT_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/parity.py`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _line_of(body: str, index: int) -> int:
    return body.count("\n", 0, index) + 1


def _outbound_tokens(body: str) -> list[tuple[int, str]]:
    """(line, matched text) for every way this source could reach the network."""
    found: list[tuple[int, str]] = []
    for pattern in _OUTBOUND_TOKENS:
        hit = re.search(pattern, body)
        if hit is not None:
            found.append((_line_of(body, hit.start()), hit.group(0)))
    return found


def _is_test_file(path: Path) -> bool:
    name = path.name
    return (
        "__tests__" in path.parts
        or ".spec." in name
        or ".test." in name
        or name.endswith(".fakeData.ts")
    )


def _read(root: Path, relative: str, problems: list[str]) -> str | None:
    """Read an audited surface, recording a problem (never a skip) when it is not there."""
    path = root / relative
    if not path.is_file():
        problems.append(
            f"{relative}: missing — L32 names this surface; a file the gate cannot read "
            "is not a file it can clear (a vacuous pass is the failure this gate exists to "
            "prevent)"
        )
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _object_literal(body: str, name: str) -> tuple[str, int] | None:
    """Return (`const <name> = {...}` literal text, its 1-based line), or None if absent.

    Brace-counting, which is enough for the hand-written seam objects this gate reads and
    would not be enough for arbitrary JavaScript — a brace inside a string literal would
    confuse it. Stated so the limitation is chosen rather than assumed.
    """
    marker = re.search(rf"\bconst\s+{re.escape(name)}\s*=", body)
    if marker is None:
        return None
    start = body.find("{", marker.end())
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(body)):
        character = body[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return body[start : index + 1], _line_of(body, marker.start())
    return None


def _seam_files(root: Path) -> list[Path]:
    """Every file under `packages/platform/<pkg>/tempest/**` — OUR integration code."""
    out: list[Path] = []
    platform = root / "packages" / "platform"
    if not platform.is_dir():
        return out
    for package in sorted(platform.iterdir()):
        seam = package / "tempest"
        if not seam.is_dir():
            continue
        out.extend(sorted(path for path in seam.rglob("*") if path.is_file()))
    return out


# ── check 1: the local-mode startup config carries no telemetry keys ─────────────────────────
def _check_startup_config_is_telemetry_free(body: str, problems: list[str]) -> None:
    found = _object_literal(body, "STARTUP_CONFIG")
    if found is None:
        problems.append(
            f"{_LOCAL_API}: no STARTUP_CONFIG object literal — this is the entire answer to "
            "GET /api/config and the gate must be able to read it"
        )
        return
    literal, line = found
    for key in _FORBIDDEN_STARTUP_KEYS:
        match = re.search(rf"\b{re.escape(key)}\s*:", literal)
        if match is not None:
            at = line + literal.count("\n", 0, match.start())
            problems.append(
                f"{_LOCAL_API}:{at}: "
                f"STARTUP_CONFIG carries `{key}` — the client reads that key straight off "
                "GET /api/config to decide whether to reach the network; local mode must not "
                "mention it at all, so no one can flip it on in a single edit (L32)"
            )


# ── check 2: the sidecar's import allowlist and outbound vocabulary ──────────────────────────
def _check_sidecar_imports(relative: str, body: str, problems: list[str]) -> None:
    for match in _MODULE_SPECIFIER.finditer(body):
        specifier = match.group(1)
        if specifier.startswith("./") or specifier.startswith("../"):
            continue
        if specifier in _ALLOWED_IMPORTS:
            continue
        problems.append(
            f"{relative}:{_line_of(body, match.start())}: imports `{specifier}` — the sidecar's "
            f"allowlist is {sorted(_ALLOWED_IMPORTS)} plus relative modules, so that it has no "
            "vocabulary in which to express an outbound request (L32)"
        )
    for where, token in _outbound_tokens(body):
        problems.append(
            f"{relative}:{where}: carries the outbound token `{token}` — the platform sidecar "
            "makes no network call of any kind (L32)"
        )


# ── check 3: no TCP listener ─────────────────────────────────────────────────────────────────
def _check_no_tcp_listener(body: str, problems: list[str]) -> None:
    if "process.env.TEMPEST_PLATFORM_SOCKET" not in body:
        problems.append(
            f"{_BOUNDARY}: does not read TEMPEST_PLATFORM_SOCKET — the socket path is the only "
            "thing the boundary is allowed to bind, and it must come from the host (L32)"
        )
    listens = list(_LISTEN_CALL.finditer(body))
    if not listens:
        problems.append(
            f"{_BOUNDARY}: no .listen() call found — the boundary binds its Unix socket here, "
            "and a gate that cannot see the bind cannot vouch for it"
        )
    for match in listens:
        target = match.group(1)
        if target != "socketPath":
            problems.append(
                f"{_BOUNDARY}:{_line_of(body, match.start())}: listens on `{target}` — the only "
                "permitted listen target is `socketPath` (the Unix domain socket named by "
                "TEMPEST_PLATFORM_SOCKET); a port number here would open a TCP surface (L32)"
            )


# ── check 4: Langfuse/OTel off by default, and no seam turns them on ─────────────────────────
def _check_upstream_telemetry_gates(
    langfuse: str | None, telemetry: str | None, problems: list[str]
) -> None:
    if langfuse is not None:
        for anchor in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "publicKey && secretKey"):
            if anchor not in langfuse:
                problems.append(
                    f"{_LANGFUSE_CONFIG}: the audited off-by-default shape is gone — `{anchor}` "
                    "no longer appears. Central Langfuse export required BOTH keys; upstream "
                    "has restructured, so the C3 finding is stale and must be re-audited (L32)"
                )
    if telemetry is not None and "isTruthy(env.OTEL_TRACING_ENABLED)" not in telemetry:
        problems.append(
            f"{_TELEMETRY_CONFIG}: the audited off-by-default shape is gone — OTel tracing was "
            "gated on `isTruthy(env.OTEL_TRACING_ENABLED)` and no longer is; re-audit before "
            "this gate can vouch for it (L32)"
        )


def _check_no_seam_sets_telemetry_env(root: Path, problems: list[str]) -> int:
    """Scan every seam file plus the sidecar spawn. The spawn goes through `_read` so that an
    absent `platform.rs` is a recorded problem rather than a scan that quietly found nothing."""
    scanned = 0
    sources: list[tuple[str, str]] = []
    for path in _seam_files(root):
        sources.append(
            (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="replace"))
        )
    spawn = _read(root, _PLATFORM_RS, problems)
    if spawn is not None:
        sources.append((_PLATFORM_RS, spawn))
    for relative, body in sources:
        scanned += 1
        for pattern in _TELEMETRY_ENV:
            match = re.search(pattern, body)
            if match is not None:
                problems.append(
                    f"{relative}:{_line_of(body, match.start())}: names the telemetry switch "
                    f"`{match.group(0)}` — no seam and no sidecar spawn may set one; off by "
                    "default means nothing of ours turns it on (L32)"
                )
    return scanned


# ── check 5: the service worker is neutralized ───────────────────────────────────────────────
def _check_service_worker_neutralized(
    seam_vite: str | None, platform_web: str | None, problems: list[str]
) -> None:
    if seam_vite is not None:
        if "vite-plugin-pwa" not in seam_vite:
            problems.append(
                f"{_SEAM_VITE}: does not filter `vite-plugin-pwa` — the seam build is what "
                "strips the PWA service worker out of the shell bundle (L32)"
            )
        if "throw new Error(" not in seam_vite:
            problems.append(
                f"{_SEAM_VITE}: the PWA-plugin-absent `throw` is gone — without it an upstream "
                "config reshuffle makes this override a silent no-op and ships an update layer "
                "the native shell must never have (L32)"
            )
    if platform_web is None:
        return
    if "/registerSW.js" not in platform_web or "service worker disabled" not in platform_web:
        problems.append(
            f"{_PLATFORM_WEB_RS}: does not serve /registerSW.js as a no-op — the built client "
            "still calls it, and anything but a no-op body registers a worker (L32)"
        )
    lines = platform_web.splitlines()
    route_line = next((i for i, line in enumerate(lines) if '"/sw.js"' in line), None)
    if route_line is None:
        problems.append(
            f"{_PLATFORM_WEB_RS}: has no /sw.js route — the protocol must 404 it rather than "
            "fall through to the static dist/ handler (L32)"
        )
    # The arm, not the rest of the function: a three-line window ends before the fallthrough
    # `not_found` at the bottom, which would otherwise vouch for any arm at all.
    elif "not_found" not in "\n".join(lines[route_line : route_line + 3]):
        problems.append(
            f"{_PLATFORM_WEB_RS}:{route_line + 1}: /sw.js does not answer not_found — a served "
            "service worker is an update channel (L32)"
        )


# ── check 6: the client's CDN ledger, and a beacon-free RUM bootstrap ────────────────────────
def _check_cdn_ledger(root: Path, problems: list[str]) -> int:
    utils = root / _CLIENT_UTILS
    if not utils.is_dir():
        problems.append(
            f"{_CLIENT_UTILS}: missing — the hard-coded CDN ledger is kept over this directory "
            "and cannot be checked against a tree that has none"
        )
        return 0
    scanned = 0
    seen: set[tuple[str, str]] = set()
    for path in sorted(utils.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _CLIENT_SOURCE_SUFFIXES:
            continue
        if _is_test_file(path.relative_to(utils)):
            continue
        scanned += 1
        body = path.read_text(encoding="utf-8", errors="replace")
        relative_to_utils = path.relative_to(utils).as_posix()
        for match in _CDN_CONSTANT.finditer(body):
            name, url = match.group(1), match.group(2)
            entry = (relative_to_utils, name)
            seen.add(entry)
            if entry not in _KNOWN_CDN_CONSTANTS:
                problems.append(
                    f"{_CLIENT_UTILS}/{relative_to_utils}:{_line_of(body, match.start())}: "
                    f"hard-coded CDN constant `{name}` = {url} — the ledger is closed at "
                    "TAILWIND_CDN and MARKED_CDN (upstream's artifact-iframe resources, "
                    "unreachable in local mode until C9). A new one must be audited and "
                    "recorded, never absorbed silently (L32)"
                )
    for missing in sorted(_KNOWN_CDN_CONSTANTS - seen):
        problems.append(
            f"{_CLIENT_UTILS}/{missing[0]}: the recorded C9 item `{missing[1]}` is gone — the "
            "ledger describes a tree that no longer exists, so the C9 artifact hand-off is "
            "working from a stale audit (L32)"
        )
    return scanned


def _check_rum_bootstrap_is_beacon_free(body: str, problems: list[str]) -> None:
    for where, token in _outbound_tokens(body):
        problems.append(
            f"{_RUM_BOOTSTRAP}:{where}: the inline RUM bootstrap carries `{token}` — it runs "
            "before anything else on the page and may only queue events in memory, never emit "
            "them (L32)"
        )


# ── check 7: airplane-mode full function ─────────────────────────────────────────────────────
def _check_airplane_mode_full_function(body: str, problems: list[str]) -> None:
    for route in _REQUIRED_ROUTES:
        if f'case "{route}":' not in body:
            problems.append(
                f'{_LOCAL_API}: no `case "{route}":` — that route is part of the boot surface '
                "the client must have answered to render the authed shell; without it local "
                "mode is not fully functional with the network unplugged (L32)"
            )
    found = _object_literal(body, "STARTUP_CONFIG")
    if found is None:
        return
    literal, line = found
    login_keys = list(_LOGIN_KEY.finditer(literal))
    if not any(match.group(1) == "emailLoginEnabled" for match in login_keys):
        problems.append(
            f"{_LOCAL_API}:{line}: STARTUP_CONFIG does not state `emailLoginEnabled` — the login "
            "surfaces must be explicitly off, not merely unmentioned (L32)"
        )
    for match in login_keys:
        if match.group(2) != "false":
            at = line + literal.count("\n", 0, match.start())
            problems.append(
                f"{_LOCAL_API}:{at}: "
                f"`{match.group(1)}: {match.group(2)}` — every login surface is false in local "
                "mode; a true one puts a remote auth round-trip between launch and the shell "
                "(L32)"
            )
    registration = re.search(r"\bregistrationEnabled\s*:\s*(\w+)", literal)
    if registration is None or registration.group(1) != "false":
        problems.append(
            f"{_LOCAL_API}:{line}: STARTUP_CONFIG must state `registrationEnabled: false` — "
            "there is no registry to register against in local mode (L32)"
        )


# ── the legs ─────────────────────────────────────────────────────────────────────────────────
def _run_platform_leg(root: Path) -> int:
    platform = root / "packages" / "platform"
    if not platform.is_dir():
        print("egress_check: 1 problem(s) — FAIL")
        print(
            f"EGRESS-GATE {platform}: missing — --platform-tree asserts a vendored tree and "
            "there is none to audit",
            file=sys.stderr,
        )
        return 1

    problems: list[str] = []
    scanned = 0

    local_api = _read(root, _LOCAL_API, problems)
    if local_api is not None:
        scanned += 1
        _check_startup_config_is_telemetry_free(local_api, problems)
        _check_airplane_mode_full_function(local_api, problems)

    for relative in _SIDECAR_MODULES:
        body = local_api if relative == _LOCAL_API else _read(root, relative, problems)
        if body is None:
            continue
        if relative != _LOCAL_API:
            scanned += 1
        _check_sidecar_imports(relative, body, problems)
        if relative == _BOUNDARY:
            _check_no_tcp_listener(body, problems)

    langfuse = _read(root, _LANGFUSE_CONFIG, problems)
    telemetry = _read(root, _TELEMETRY_CONFIG, problems)
    scanned += sum(1 for body in (langfuse, telemetry) if body is not None)
    _check_upstream_telemetry_gates(langfuse, telemetry, problems)
    scanned += _check_no_seam_sets_telemetry_env(root, problems)

    seam_vite = _read(root, _SEAM_VITE, problems)
    platform_web = _read(root, _PLATFORM_WEB_RS, problems)
    scanned += sum(1 for body in (seam_vite, platform_web) if body is not None)
    _check_service_worker_neutralized(seam_vite, platform_web, problems)

    scanned += _check_cdn_ledger(root, problems)
    bootstrap = _read(root, _RUM_BOOTSTRAP, problems)
    if bootstrap is not None:
        scanned += 1
        _check_rum_bootstrap_is_beacon_free(bootstrap, problems)

    if problems:
        print(f"egress_check: {len(problems)} problem(s) — FAIL")
        for problem in problems:
            print(f"EGRESS-GATE {problem}", file=sys.stderr)
        return 1
    print(
        f"egress_check: {scanned} platform surfaces audited — every telemetry and egress "
        "surface off by default, the sidecar unable to express an outbound call, and the boot "
        "surface fully answered with the network unplugged (L32 holds)"
    )
    return 0


def _run_l10_leg(tier: str) -> int:
    if sys.platform != "darwin" and tier == "T2":
        raise SystemExit("T2 (Seatbelt) is macOS-only — run the Linux netns egress leg in CI")
    if tier == "T2" and not Path("/usr/bin/sandbox-exec").exists():
        raise SystemExit("sandbox-exec not found — cannot verify egress on T2 here")

    network_payloads = {p.name for p in PAYLOADS if p.category == "network"}
    outcomes = [o for o in run_matrix(tier) if o.payload.name in network_payloads]

    print(f"\ntempest egress check · tier {tier} · {len(outcomes)} network vectors")
    print("-" * 56)
    escaped = 0
    for o in outcomes:
        blocked = o.contained
        if not blocked:
            escaped += 1
        print(f"  {o.payload.name:26} {'BLOCKED' if blocked else '**EGRESS**'}  {o.detail}")
    print("-" * 56)
    print(f"outbound connections that succeeded: {escaped} (required: 0)")
    print("netns packet-capture leg: PENDING(CI, Linux) — docs/PLAN-DESKTOP.md Phase 10")

    if escaped:
        print("\nL10 VIOLATED — traffic escaped the sandbox. This blocks the release.")
        return 1
    print("\negress check: zero outbound connections from sandboxed runner code (L10).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-zero", action="store_true", help="L10 runtime leg")
    parser.add_argument("--tier", default="T2", choices=("T2", "T3"))
    parser.add_argument("--platform-tree", action="store_true", help="L32 static leg")
    parser.add_argument("--deny-all", action="store_true", help="L32 static leg")
    parser.add_argument("--airplane-mode-full-function", action="store_true", help="L32 static leg")
    parser.add_argument(
        "--root", default=None, help="repository root to check (default: this repository)"
    )
    args = parser.parse_args(argv)

    platform_flags = (args.platform_tree, args.deny_all, args.airplane_mode_full_function)
    if any(platform_flags):
        if not all(platform_flags):
            parser.error(
                "--platform-tree, --deny-all and --airplane-mode-full-function name one gate "
                "and are passed together"
            )
        if args.expect_zero:
            parser.error(
                "--expect-zero is the L10 runtime leg and --platform-tree the L32 static leg; "
                "run them as separate commands so each reports its own result"
            )
        return _run_platform_leg(Path(args.root) if args.root else _repo_root())

    if not args.expect_zero:
        parser.error(
            "pick a leg: --expect-zero (L10 runtime egress) or --platform-tree --deny-all "
            "--airplane-mode-full-function (L32 static platform-tree audit)"
        )
    return _run_l10_leg(args.tier)


if __name__ == "__main__":
    raise SystemExit(main())
