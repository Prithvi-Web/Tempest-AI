// Local single-user mode — the C3 auth seam (PLAN-V3 C3; MERGE-CONTRACT "middleware" row).
//
// The plan's words, implemented literally: "local single-user mode short-circuits to an
// implicit local principal through a DISTINCT CODE PATH with its own tests. Never a bypass
// flag." This module IS that code path: when the desktop app runs with no configured server,
// the boundary sidecar answers the client's boot surface here — a fixed local principal, no
// login screen, no network, nothing to bypass because in local mode there is no remote auth
// to begin with. Multi-user auth (OAuth2/LDAP/email) arrives at C10 for TEAM features and
// runs through LibreChat's real AuthService — never through this file.
//
// Scope discipline: everything answered here is the minimum the client needs to BOOT into
// an authed shell. Anything not yet wired answers 404 with an honest JSON body — never a
// hang, never a fake-success (L15.3). The endpoint surface grows phase by phase (C4 models,
// C5 agents, C6 conversations) and each addition lands here deliberately.

const ONE_YEAR_S = 365 * 24 * 60 * 60;

const b64url = (value) =>
  Buffer.from(JSON.stringify(value)).toString("base64url");

/** A syntactically valid, deliberately UNSIGNED JWT. The client only DECODES it (for expiry
 * scheduling); nothing verifies it because in local mode there is no verifier to satisfy —
 * the possession of the local machine IS the principal. */
const mintLocalToken = () =>
  `${b64url({ alg: "none", typ: "JWT" })}.${b64url({
    id: "local",
    exp: Math.floor(Date.now() / 1000) + ONE_YEAR_S,
  })}.`;

const LOCAL_USER = Object.freeze({
  id: "local",
  username: "local",
  email: "local@tempest.localhost",
  name: "Local",
  avatar: "",
  role: "USER",
  provider: "local",
  createdAt: "2026-01-01T00:00:00.000Z",
  updatedAt: "2026-01-01T00:00:00.000Z",
});

/** TStartupConfig, local-mode honest: every remote login surface OFF, no registration, no
 * turnstile, no telemetry config. The client renders an authed shell from exactly this. */
/** The client treats a PRESENT-but-empty `interface` as the whole answer — every
 * `startupConfig?.interface ?? defaults` site keeps `{}` and hides the header and sidebar
 * affordances. These are upstream's own resolved defaults, stated explicitly (the nested
 * permission-seed keys are server-side seeds; nav visibility comes from /api/roles/USER). */
const INTERFACE_CONFIG = Object.freeze({
  modelSelect: true,
  parameters: true,
  presets: true,
  multiConvo: true,
  bookmarks: true,
  memories: true,
  temporaryChat: true,
  autoSubmitFromUrl: true,
  runCode: true,
  webSearch: true,
  fileSearch: true,
  fileCitations: true,
  contextUsage: true,
  contextCost: false,
  feedback: true,
  buildInfo: true,
});

/** Explicit permission booleans: the client reads `permissions[type][perm] === true`
 * directly (no schema-default fill on this path), so an empty object hides every gated
 * section. Single-user honest values — sharing, people-picker, marketplace, shared links
 * and schedules stay off until the phases that back them (C7/C8/C10). */
const USER_ROLE = Object.freeze({
  name: "USER",
  permissions: {
    PROMPTS: { USE: true, CREATE: true, SHARE: false, SHARE_PUBLIC: false },
    BOOKMARKS: { USE: true },
    AGENTS: { USE: true, CREATE: true, SHARE: false, SHARE_PUBLIC: false },
    MEMORIES: { USE: true, CREATE: true, UPDATE: true, READ: true, OPT_OUT: true },
    MULTI_CONVO: { USE: true },
    TEMPORARY_CHAT: { USE: true },
    RUN_CODE: { USE: true },
    WEB_SEARCH: { USE: true },
    PEOPLE_PICKER: { VIEW_USERS: false, VIEW_GROUPS: false, VIEW_ROLES: false },
    MARKETPLACE: { USE: false },
    FILE_SEARCH: { USE: true },
    FILE_CITATIONS: { USE: true },
    MCP_SERVERS: {
      USE: true,
      CREATE: true,
      SHARE: false,
      SHARE_PUBLIC: false,
      CONFIGURE_OBO: false,
    },
    REMOTE_AGENTS: { USE: false, CREATE: false, SHARE: false, SHARE_PUBLIC: false },
    SKILLS: { USE: true, CREATE: true, SHARE: false, SHARE_PUBLIC: false },
    SHARED_LINKS: { CREATE: false, SHARE: false, SHARE_PUBLIC: false },
    SCHEDULES: { USE: false, CREATE: false },
  },
});

const STARTUP_CONFIG = Object.freeze({
  appTitle: "Tempest AI",
  socialLogins: [],
  discordLoginEnabled: false,
  facebookLoginEnabled: false,
  githubLoginEnabled: false,
  googleLoginEnabled: false,
  openidLoginEnabled: false,
  appleLoginEnabled: false,
  samlLoginEnabled: false,
  openidLabel: "",
  openidImageUrl: "",
  openidAutoRedirect: false,
  samlLabel: "",
  samlImageUrl: "",
  serverDomain: "",
  emailLoginEnabled: false,
  registrationEnabled: false,
  socialLoginEnabled: false,
  passwordResetEnabled: false,
  emailEnabled: false,
  showBirthdayIcon: false,
  helpAndFaqURL: "",
  interface: INTERFACE_CONFIG,
});

const json = (status, value) => ({
  status,
  content_type: "application/json",
  body: JSON.stringify(value),
});

/** Route one local-mode API request. Exported for the boundary AND for direct tests. */
export function handleLocalApi(method, path) {
  const route = `${method.toUpperCase()} ${path.split("?")[0]}`;
  switch (route) {
    case "GET /api/config":
      return json(200, STARTUP_CONFIG);
    case "POST /api/auth/refresh":
      return json(200, { token: mintLocalToken(), user: LOCAL_USER });
    case "GET /api/user":
      return json(200, LOCAL_USER);
    case "GET /api/roles/USER":
      // The client requests the UPPERCASE system-role name (SystemRoles.USER), and the
      // chat route refuses to mount until this answers. ADMIN is requested only when the
      // user's role is ADMIN, which the local principal's never is.
      return json(200, USER_ROLE);
    case "GET /api/banner":
      return json(200, null);
    case "GET /api/health":
      return { status: 200, content_type: "text/plain", body: "OK" };
    case "GET /api/endpoints":
      // Honest empty: model endpoints arrive when C4 maps them onto tempest/inference.
      return json(200, {});
    case "GET /api/models":
      return json(200, {});
    case "GET /api/files/config":
      return json(200, { endpoints: {} });
    case "GET /api/user/terms":
      return json(200, { termsAccepted: true });
    case "GET /api/convos":
      // Truthfully empty until C6 wires the conversation store. `nextCursor` must be a
      // literal null: the pinned-conversations query drains cursors in a loop, and any
      // non-null value here would spin it forever.
      return json(200, { conversations: [], nextCursor: null });
    case "GET /api/projects":
      return json(200, { projects: [], nextCursor: null });
    case "GET /api/user/settings/favorites":
    case "GET /api/user/settings/favorites/tools":
      return json(200, []);
    case "GET /api/search/enable":
      // The client tri-states on the bare literal (=== true / === false / error);
      // anything object-shaped would leave search stuck between states.
      return json(200, false);
    case "GET /api/files":
      return json(200, []);
    case "GET /api/files/speech/config/get":
      // Upstream's own "no server speech config" sentinel — the client skips its
      // seed-from-config pass and still marks speech settings initialized.
      return json(200, { message: "not_found" });
    case "GET /api/balance":
      return json(200, { tokenCredits: 0, autoRefillEnabled: false });
    case "GET /api/agents/chat/active":
      // An empty list also stops the 5s active-jobs poll loop.
      return json(200, { activeJobIds: [] });
    default:
      // One line per miss on stderr: the boundary only logs transport failures, and a
      // valid 404 is not one — without this, a starved client query is invisible.
      process.stderr.write(`[local-api] 404 ${route}\n`);
      return json(404, {
        error: "not part of local mode yet",
        detail:
          "this endpoint joins the local surface at its convergence phase " +
          "(C4 models, C5 agents, C6 conversations)",
        path,
      });
  }
}
