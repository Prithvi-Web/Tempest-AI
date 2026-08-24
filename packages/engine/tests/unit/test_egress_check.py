"""C3 gate pins: `egress_check --platform-tree --deny-all --airplane-mode-full-function` (L32).

Every check is proven to FAIL on a violating tree: a gate that cannot fail is decoration. The
fixture builds a minimal tree that PASSES, and each pin then breaks exactly one property and
asserts both the exit code and that the `EGRESS-GATE` line names the thing that broke — an
egress gate whose failure output does not say WHICH surface opened is a gate someone will
disable rather than debug.

The precision arms matter as much as the biting ones. A telemetry key in some unrelated object,
a CDN constant in a test file, a relative import: none of those are egress, and a gate that
cries wolf on them is a gate that gets a `# noqa` in six months.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tempest.dev import egress_check

_ARGS = ["--platform-tree", "--deny-all", "--airplane-mode-full-function"]

_LOCAL_API = "packages/platform/server/tempest/local-api.mjs"
_BOUNDARY = "packages/platform/server/tempest/boundary.mjs"
_BOUNDARY_VALIDATE = "packages/platform/server/tempest/boundary-validate.mjs"
_LANGFUSE = "packages/platform/api/src/langfuse/config.ts"
_TELEMETRY = "packages/platform/api/src/telemetry/config.ts"
_SEAM_VITE = "packages/platform/client/tempest/vite.config.mjs"
_ARTIFACTS = "packages/platform/client/src/utils/artifacts.ts"
_MARKDOWN = "packages/platform/client/src/utils/markdown.ts"
_BOOTSTRAP = "packages/platform/client/src/lib/rum/bootstrap.js"
_PLATFORM_WEB_RS = "packages/desktop/src-tauri/src/platform_web.rs"
_PLATFORM_RS = "packages/desktop/src-tauri/src/platform.rs"

_SOURCES = {
    _LOCAL_API: """\
const STARTUP_CONFIG = Object.freeze({
  appTitle: "Tempest AI",
  socialLogins: [],
  emailLoginEnabled: false,
  googleLoginEnabled: false,
  socialLoginEnabled: false,
  registrationEnabled: false,
});

const json = (status, value) => ({ status, body: JSON.stringify(value) });

export function handleLocalApi(method, path) {
  const route = method.toUpperCase() + " " + path.split("?")[0];
  switch (route) {
    case "GET /api/config":
      return json(200, STARTUP_CONFIG);
    case "POST /api/auth/refresh":
      return json(200, { token: "local" });
    case "GET /api/user":
      return json(200, { id: "local" });
    case "GET /api/roles/USER":
      return json(200, { name: "USER" });
    case "GET /api/health":
      return json(200, "OK");
    case "GET /api/convos":
      return json(200, { conversations: [], nextCursor: null });
    default:
      return json(404, { error: "not part of local mode yet" });
  }
}
""",
    _BOUNDARY: """\
import { createServer } from "node:net";
import { unlinkSync } from "node:fs";
import process from "node:process";

import { checkRequest } from "./boundary-validate.mjs";
import { handleLocalApi } from "./local-api.mjs";

const socketPath = process.env.TEMPEST_PLATFORM_SOCKET;
const server = createServer((c) => c.on("data", (d) => handleLocalApi("GET", "/api/health", d)));
server.listen(socketPath, () => process.stderr.write("boundary: listening\\n"));
export { checkRequest, unlinkSync };
""",
    _BOUNDARY_VALIDATE: """\
import { PLATFORM_METHODS } from "./generated/platform-schema.mjs";

export const checkRequest = (value) =>
  PLATFORM_METHODS.includes(value?.method) ? { ok: true } : { ok: false, why: "method" };
""",
    _LANGFUSE: """\
export function applyCentralEnvConfig(langfuse: { publicKey?: string }): void {
  const publicKey = process.env.LANGFUSE_PUBLIC_KEY;
  const secretKey = process.env.LANGFUSE_SECRET_KEY;
  if (publicKey && secretKey) {
    langfuse.publicKey = publicKey;
  }
}
""",
    _TELEMETRY: """\
function isTruthy(value?: string): boolean {
  return value?.trim().toLowerCase() === 'true';
}

export function getTelemetryConfig(env: NodeJS.ProcessEnv = process.env) {
  const enabled = isTruthy(env.OTEL_TRACING_ENABLED) && !isTruthy(env.OTEL_SDK_DISABLED);
  return { enabled };
}
""",
    _SEAM_VITE: """\
import vendored from '../vite.config.ts';

export default async (env) => {
  const base = typeof vendored === 'function' ? await vendored(env) : vendored;
  const plugins = (base.plugins ?? []).flat(Infinity).filter(Boolean);
  const isServiceWorker = (p) => String(p?.name ?? '').startsWith('vite-plugin-pwa');
  if (!plugins.some(isServiceWorker)) {
    throw new Error('no vite-plugin-pwa plugins found — re-audit the neutralization');
  }
  base.plugins = plugins.filter((p) => !isServiceWorker(p));
  return base;
};
""",
    _ARTIFACTS: """\
const TAILWIND_CDN = 'https://cdn.tailwindcss.com/3.4.17#tailwind.js';

export const sharedOptions = { externalResources: [TAILWIND_CDN] };
""",
    _MARKDOWN: """\
const MARKED_CDN = 'https://cdn.jsdelivr.net/npm/marked@15.0.12/marked.min.js';

export const scriptTag = '<script src="' + MARKED_CDN + '"></script>';
""",
    _BOOTSTRAP: """\
export function installRumBootstrap(targetWindow) {
  targetWindow.__lcRumQueue = [];
  targetWindow.__lcRumPush = (type) => targetWindow.__lcRumQueue.push({ type });
}
""",
    _PLATFORM_WEB_RS: """\
pub fn serve(path: &str) -> Response {
    if path == "/registerSW.js" {
        return response(
            200,
            "text/javascript",
            b"// service worker disabled: a native shell has no browser-update layer".to_vec(),
        );
    }
    if path == "/sw.js" || path.starts_with("/workbox-") {
        return not_found(path);
    }
    not_found(path)
}
""",
    _PLATFORM_RS: """\
pub fn spawn_config(node: PathBuf, boundary_script: PathBuf, socket: PathBuf) -> SpawnConfig {
    SpawnConfig {
        program: node,
        args: vec![boundary_script.to_string_lossy().into_owned()],
        env_provider: None,
        transport: Transport::Unix { socket },
        rpc_prefix: "platform",
    }
}
""",
}


#: The engine half of the miniature world. Check 8's model-host ledger is kept over the
#: ENGINE tree, so a fixture with no engine is a fixture the check cannot vouch for — the same
#: lesson `gate_audit`'s synthetic world learned when it gained a declared path and its
#: fixture did not. Both recorded sites are present, so the ledger resolves in both
#: directions here exactly as it does in the real repository.
_ENGINE_SOURCES: dict[str, str] = {
    "packages/engine/src/tempest/models/catalog.py": (
        'HUGGINGFACE_HOST = "huggingface.co"\n'
        "def url(repo: str) -> str:\n"
        '    return f"https://{HUGGINGFACE_HOST}/{repo}"\n'
    ),
    "packages/engine/src/tempest/models/download.py": (
        '_ALLOWED_REDIRECT_SUFFIXES = ("hf.co", "huggingface.co")\n'
    ),
    "packages/engine/src/tempest/prove.py": "def prove() -> None:\n    return None\n",
}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal platform tree that PASSES, for tests to then break one property at a time."""
    for relative, body in {**_SOURCES, **_ENGINE_SOURCES}.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def _run(root: Path) -> int:
    return egress_check.main([*_ARGS, "--root", str(root)])


def _edit(tree: Path, relative: str, old: str, new: str) -> None:
    """Break exactly one property, refusing to no-op if the anchor text has drifted."""
    path = tree / relative
    body = path.read_text()
    assert old in body, f"{relative}: fixture no longer contains {old!r}"
    path.write_text(body.replace(old, new, 1))


def _fails(root: Path, capsys: pytest.CaptureFixture[str], *needles: str) -> None:
    assert _run(root) == 1
    captured = capsys.readouterr()
    assert "— FAIL" in captured.out
    for needle in needles:
        assert needle in captured.err, captured.err


class TestPassing:
    def test_a_clean_platform_tree_passes(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(tree) == 0
        assert "L32 holds" in capsys.readouterr().out

    def test_the_real_repository_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert egress_check.main(_ARGS) == 0
        assert "L32 holds" in capsys.readouterr().out

    def test_repo_root_marker_walk_finds_the_repository(self) -> None:
        assert (egress_check._repo_root() / "packages" / "desktop").is_dir()

    def test_a_root_with_no_platform_tree_fails_rather_than_passing_vacuously(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fails(tmp_path, capsys, "--platform-tree asserts a vendored tree")

    @pytest.mark.parametrize(
        "relative", [_LOCAL_API, _BOUNDARY, _LANGFUSE, _SEAM_VITE, _PLATFORM_WEB_RS, _PLATFORM_RS]
    )
    def test_a_missing_audited_surface_fails_rather_than_being_skipped(
        self, tree: Path, capsys: pytest.CaptureFixture[str], relative: str
    ) -> None:
        (tree / relative).unlink()
        _fails(tree, capsys, f"{relative}: missing")


class TestCommandLine:
    def test_the_gate_runs_main_under_python_dash_m(self) -> None:
        """A gate module without its `__main__` guard imports cleanly, prints nothing and exits
        0 under `python -m` — which reads exactly like a pass. Caught live at C2 on the orphan
        gate; pinned here so this one cannot repeat it."""
        result = subprocess.run(
            [sys.executable, "-m", "tempest.dev.egress_check", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "--airplane-mode-full-function" in result.stdout, (
            "argparse help must render — silence here means the __main__ guard is gone and "
            "`python -m` would exit 0 having checked nothing"
        )

    @pytest.mark.parametrize(
        "argv",
        [
            [],
            ["--platform-tree"],
            ["--deny-all"],
            ["--airplane-mode-full-function"],
            ["--platform-tree", "--deny-all"],
            [*_ARGS, "--expect-zero"],
        ],
    )
    def test_an_incomplete_or_mixed_leg_is_refused_not_half_run(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit) as raised:
            egress_check.main(argv)
        assert raised.value.code == 2

    def test_the_l10_leg_still_takes_its_own_flags(self) -> None:
        parsed = subprocess.run(
            [sys.executable, "-m", "tempest.dev.egress_check", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "--expect-zero" in parsed.stdout
        assert "--tier" in parsed.stdout


class TestCheck1StartupConfigIsTelemetryFree:
    @pytest.mark.parametrize(
        "key", ["analyticsGtmId", "rum", "turnstile", "bundlerURL", "staticBundlerURL"]
    )
    def test_a_telemetry_key_in_the_startup_config_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], key: str
    ) -> None:
        _edit(tree, _LOCAL_API, '  appTitle: "Tempest AI",', f'  appTitle: "T",\n  {key}: null,')
        _fails(tree, capsys, f"STARTUP_CONFIG carries `{key}`")

    def test_an_off_switch_is_still_a_switch(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`rum: { enabled: false }` reads safe and is one word away from unsafe. The key must
        not be mentioned at all, so flipping it takes an audit rather than an edit."""
        _edit(tree, _LOCAL_API, "  socialLogins: [],", "  rum: { enabled: false },")
        _fails(tree, capsys, "STARTUP_CONFIG carries `rum`")

    def test_a_telemetry_key_outside_the_startup_config_is_not_the_boot_answer(
        self, tree: Path
    ) -> None:
        """The check is scoped to what `GET /api/config` actually returns; an unrelated local
        object naming `turnstile` is not a switch the client can read."""
        _edit(
            tree,
            _LOCAL_API,
            "const json =",
            "const NOTES = { turnstile: 'upstream only' };\nconst json =",
        )
        assert _run(tree) == 0

    def test_a_startup_config_the_gate_cannot_read_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _LOCAL_API, "const STARTUP_CONFIG =", "const BOOT_CONFIG =")
        _fails(tree, capsys, "no STARTUP_CONFIG object literal")


class TestCheck2SidecarImports:
    @pytest.mark.parametrize(
        "line",
        [
            'import https from "node:https";',
            'import { get } from "node:http";',
            'import { Resolver } from "node:dns";',
            'import fetch from "node-fetch";',
            'const dgram = require("node:dgram");',
        ],
    )
    def test_an_import_outside_the_allowlist_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], line: str
    ) -> None:
        _edit(tree, _BOUNDARY, 'import process from "node:process";', line)
        _fails(tree, capsys, "the sidecar's")

    def test_a_relative_seam_import_is_our_own_code_and_passes(self, tree: Path) -> None:
        _edit(
            tree,
            _BOUNDARY,
            'import process from "node:process";',
            'import process from "node:process";\nimport { x } from "../shared/x.mjs";',
        )
        assert _run(tree) == 0

    @pytest.mark.parametrize("relative", [_BOUNDARY, _BOUNDARY_VALIDATE, _LOCAL_API])
    def test_an_outbound_token_in_any_sidecar_module_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], relative: str
    ) -> None:
        path = tree / relative
        path.write_text(path.read_text() + "\nexport const ping = () => fetch('/x');\n")
        _fails(tree, capsys, f"{relative}:", "outbound token")


class TestCheck3NoTcpListener:
    @pytest.mark.parametrize("target", ["3080", "process.env.PORT", "8080"])
    def test_listening_on_anything_but_the_unix_socket_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], target: str
    ) -> None:
        _edit(tree, _BOUNDARY, "server.listen(socketPath,", f"server.listen({target},")
        _fails(tree, capsys, f"listens on `{target}`")

    def test_a_socket_path_not_taken_from_the_host_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(
            tree,
            _BOUNDARY,
            "const socketPath = process.env.TEMPEST_PLATFORM_SOCKET;",
            'const socketPath = "/tmp/platform.sock";',
        )
        _fails(tree, capsys, "does not read TEMPEST_PLATFORM_SOCKET")

    def test_a_boundary_with_no_bind_at_all_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _BOUNDARY, "server.listen(socketPath, () =>", "const unused = (() =>")
        _fails(tree, capsys, "no .listen() call found")


class TestCheck4TelemetryOffByDefault:
    @pytest.mark.parametrize(
        "anchor", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "publicKey && secretKey"]
    )
    def test_langfuse_drifting_off_its_double_key_requirement_forces_a_re_audit(
        self, tree: Path, capsys: pytest.CaptureFixture[str], anchor: str
    ) -> None:
        _edit(tree, _LANGFUSE, anchor, "SOMETHING_ELSE")
        _fails(tree, capsys, f"`{anchor}` no longer appears")

    def test_otel_drifting_off_its_truthy_gate_forces_a_re_audit(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _TELEMETRY, "isTruthy(env.OTEL_TRACING_ENABLED)", "true")
        _fails(tree, capsys, "the audited off-by-default shape is gone")

    @pytest.mark.parametrize(
        "name",
        [
            "LANGFUSE_PUBLIC_KEY",
            "OTEL_TRACING_ENABLED",
            "RUM_ENABLED",
            "ANALYTICS_GTM_ID",
            "RUM_PROXY_TARGET_URL",
            "SANDPACK_BUNDLER_URL",
        ],
    )
    def test_a_seam_naming_a_telemetry_switch_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], name: str
    ) -> None:
        path = tree / _LOCAL_API
        path.write_text(path.read_text() + f"\nprocess.env.{name} = 'true';\n")
        _fails(tree, capsys, f"names the telemetry switch `{name}`")

    def test_the_sidecar_spawn_naming_a_telemetry_switch_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(
            tree,
            _PLATFORM_RS,
            "        env_provider: None,",
            '        env_provider: Some(vec![("OTEL_TRACING_ENABLED", "true")]),',
        )
        _fails(tree, capsys, _PLATFORM_RS, "names the telemetry switch `OTEL_TRACING_ENABLED`")


class TestCheck5ServiceWorkerNeutralized:
    def test_dropping_the_pwa_filter_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _SEAM_VITE, "vite-plugin-pwa", "vite-plugin-something")
        _edit(tree, _SEAM_VITE, "vite-plugin-pwa", "vite-plugin-something")
        _fails(tree, capsys, "does not filter `vite-plugin-pwa`")

    def test_dropping_the_drift_throw_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without the throw, an upstream reshuffle turns the override into a silent no-op and
        ships the service worker — the exact failure the throw exists to make loud."""
        _edit(tree, _SEAM_VITE, "throw new Error(", "console.warn(")
        _fails(tree, capsys, "the PWA-plugin-absent `throw` is gone")

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("// service worker disabled: a native shell", "// registers the real worker"),
            ('"/registerSW.js"', '"/register-sw.js"'),
        ],
    )
    def test_a_register_sw_that_is_not_a_no_op_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], old: str, new: str
    ) -> None:
        _edit(tree, _PLATFORM_WEB_RS, old, new)
        _fails(tree, capsys, "does not serve /registerSW.js as a no-op")

    def test_a_sw_js_that_is_not_404ed_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(
            tree,
            _PLATFORM_WEB_RS,
            'if path == "/sw.js" || path.starts_with("/workbox-") {\n'
            "        return not_found(path);",
            'if path == "/sw.js" {\n        return serve_static(path);',
        )
        # The fallthrough `not_found(path)` at the bottom of the function must NOT vouch for
        # this arm — that is the bug a whole-file substring check would have.
        _fails(tree, capsys, "/sw.js does not answer not_found")

    def test_dropping_the_sw_js_route_entirely_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _PLATFORM_WEB_RS, '"/sw.js"', '"/service-worker.js"')
        _fails(tree, capsys, "has no /sw.js route")


class TestCheck6CdnLedger:
    def test_a_third_hard_coded_cdn_constant_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "packages/platform/client/src/utils/charts.ts").write_text(
            "const CHART_CDN = 'https://cdn.example.com/chart.js';\nexport default CHART_CDN;\n"
        )
        _fails(tree, capsys, "hard-coded CDN constant `CHART_CDN`")

    def test_a_third_constant_hiding_in_a_subdirectory_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        nested = tree / "packages/platform/client/src/utils/diagram"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "mermaid.ts").write_text(
            "export const MERMAID_CDN = 'https://cdn.jsdelivr.net/npm/mermaid/mermaid.js';\n"
        )
        _fails(tree, capsys, "hard-coded CDN constant `MERMAID_CDN`")

    @pytest.mark.parametrize(
        ("relative", "name"), [(_ARTIFACTS, "TAILWIND_CDN"), (_MARKDOWN, "MARKED_CDN")]
    )
    def test_a_recorded_c9_item_vanishing_fails_because_the_ledger_went_stale(
        self, tree: Path, capsys: pytest.CaptureFixture[str], relative: str, name: str
    ) -> None:
        _edit(tree, relative, f"const {name} =", f"const {name}_RENAMED_UPSTREAM =")
        _fails(tree, capsys, f"the recorded C9 item `{name}` is gone")

    def test_a_constant_in_a_test_file_is_not_a_runtime_cdn_reference(self, tree: Path) -> None:
        tests = tree / "packages/platform/client/src/utils/__tests__"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "artifacts.test.ts").write_text(
            "const TAILWIND_CDN = 'https://cdn.tailwindcss.com/3.4.17#tailwind.js';\n"
        )
        (tree / "packages/platform/client/src/utils/files.spec.ts").write_text(
            "const OTHER_CDN = 'https://cdn.example.com/x.js';\n"
        )
        assert _run(tree) == 0

    def test_an_https_url_that_is_not_a_constant_declaration_is_not_a_cdn_pin(
        self, tree: Path
    ) -> None:
        """Doc links and comparisons are prose, not fetches — the ledger tracks declarations."""
        (tree / "packages/platform/client/src/utils/tilde.ts").write_text(
            "// Based on: https://zod.dev/api?id=emails\n"
            "export const same = (url, v) => url === `https://${v}`;\n"
        )
        assert _run(tree) == 0

    @pytest.mark.parametrize(
        "line",
        [
            "  const r = await fetch('https://rum.example.com/v1/traces');",
            "  navigator.sendBeacon('/rum', '{}');",
            "  const socket = new WebSocket('wss://rum.example.com');",
            "  const es = new EventSource('/rum/stream');",
        ],
    )
    def test_an_emitter_in_the_inline_rum_bootstrap_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], line: str
    ) -> None:
        _edit(tree, _BOOTSTRAP, "  targetWindow.__lcRumQueue = [];", line)
        _fails(tree, capsys, "the inline RUM bootstrap carries")


class TestCheck7AirplaneModeFullFunction:
    @pytest.mark.parametrize(
        "route",
        [
            "GET /api/config",
            "POST /api/auth/refresh",
            "GET /api/user",
            "GET /api/roles/USER",
            "GET /api/health",
            "GET /api/convos",
        ],
    )
    def test_a_missing_boot_route_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], route: str
    ) -> None:
        _edit(tree, _LOCAL_API, f'case "{route}":', 'case "GET /api/unused":')
        _fails(tree, capsys, f'no `case "{route}":`')

    @pytest.mark.parametrize(
        "key", ["emailLoginEnabled", "googleLoginEnabled", "socialLoginEnabled"]
    )
    def test_any_login_surface_left_on_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str], key: str
    ) -> None:
        _edit(tree, _LOCAL_API, f"  {key}: false,", f"  {key}: true,")
        _fails(tree, capsys, f"`{key}: true`")

    def test_registration_left_on_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _LOCAL_API, "  registrationEnabled: false,", "  registrationEnabled: true,")
        _fails(tree, capsys, "must state `registrationEnabled: false`")

    def test_registration_merely_unmentioned_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _edit(tree, _LOCAL_API, "  registrationEnabled: false,\n", "")
        _fails(tree, capsys, "must state `registrationEnabled: false`")

    def test_login_surfaces_merely_unmentioned_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Silence is not "off": the client fills unmentioned config from its own defaults, so
        the seam states every login surface explicitly."""
        _edit(tree, _LOCAL_API, "  emailLoginEnabled: false,\n", "")
        _fails(tree, capsys, "does not state `emailLoginEnabled`")


class TestCheck8ModelHostLedger:
    """The one outbound connection Tempest makes on the user's behalf that is not a provider
    they configured (ADR-0080 §7). It gets the CDN ledger's treatment — closed, and checked in
    BOTH directions — because the failure that matters is not a new host appearing loudly, it
    is an audit going stale while the capability quietly stays.
    """

    _CATALOG = "packages/engine/src/tempest/models/catalog.py"

    def test_an_unrecorded_file_that_names_the_host_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rogue = tree / "packages/engine/src/tempest/sneaky.py"
        rogue.write_text('URL = "https://huggingface.co/some/model"\n')
        _fails(tree, capsys, "names the model host", "second egress surface")

    def test_a_subdomain_of_the_host_is_still_the_host(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`cdn-lfs.huggingface.co` is where the bytes actually come from, so a check that
        only matched the bare domain would miss the reach that matters most."""
        rogue = tree / "packages/engine/src/tempest/sneaky.py"
        rogue.write_text('URL = "https://cdn-lfs.huggingface.co/x"\n')
        _fails(tree, capsys, "names the model host")

    def test_the_short_form_counts_too(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rogue = tree / "packages/engine/src/tempest/sneaky.py"
        rogue.write_text('URL = "https://hf.co/x"\n')
        _fails(tree, capsys, "names the model host")

    def test_a_recorded_constant_that_vanishes_fails_even_though_the_reach_remains(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The direction a grep cannot do, and the one that matters. The file still reaches
        the host; only the anchor the audit was written against is gone. Passing here would
        mean the ledger describes a tree that no longer exists."""
        _edit(tree, self._CATALOG, 'HUGGINGFACE_HOST = "huggingface.co"', 'X = "y"')
        _edit(
            tree,
            self._CATALOG,
            'f"https://{HUGGINGFACE_HOST}/{repo}"',
            'f"https://huggingface.co/{repo}"',
        )
        _fails(tree, capsys, "the recorded constant `HUGGINGFACE_HOST` is gone")

    def test_a_recorded_site_that_disappears_entirely_fails(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / self._CATALOG).unlink()
        _fails(tree, capsys, "the ledger describes a tree that no longer exists")

    def test_an_engine_tree_that_is_not_there_cannot_be_vouched_for(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A check that silently passes on a tree it could not find is worse than no check:
        it reports a property nobody measured."""
        for relative, body in _SOURCES.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        _fails(tmp_path, capsys, "the model-host ledger is kept over this tree")

    def test_the_gate_module_itself_may_name_the_host(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """It has to: the matcher is written in its own source, exactly as `gate_audit` names
        its tripwire strings in its own. Exempted by NAME rather than by exempting `dev/`,
        because a BENCH that started reaching the network should still fail this gate."""
        gate = tree / "packages/engine/src/tempest/dev/egress_check.py"
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text('PATTERN = "huggingface.co|hf.co"\n')
        assert _run(tree) == 0
        assert "L32 holds" in capsys.readouterr().out

    def test_a_bench_that_reaches_the_host_is_NOT_exempt(
        self, tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The hole the blanket exemption would have opened."""
        bench = tree / "packages/engine/src/tempest/dev/model_bench.py"
        bench.parent.mkdir(parents=True, exist_ok=True)
        bench.write_text('URL = "https://huggingface.co/x"\n')
        _fails(tree, capsys, "names the model host")
