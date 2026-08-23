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

/** The greeting reads better with the person's actual account name than with "Local" —
 * process.env is already inside the seam's import allowlist, and the name never leaves the
 * machine (it only rides the local principal the webview renders). */
const localName = (() => {
  const raw = (process.env.USER || process.env.LOGNAME || "").trim();
  if (!raw) return "there";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
})();

const LOCAL_USER = Object.freeze({
  id: "local",
  username: "local",
  email: "local@tempest.localhost",
  name: localName,
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
  // Any string suppresses the vendored footer's upstream wordmark + version line; MIT
  // does not license the trademark, so that line must never render (C1 brand-strip's
  // text-surface counterpart). Empty = no footer at all.
  customFooter: "",
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
  if (method.toUpperCase() === "GET" && path.startsWith("/api/share/link/")) {
    // Not shared — the honest local answer until C7's sharing lands (TSharedLinkGetResponse).
    return json(200, { shareId: null, success: false });
  }
  if (method.toUpperCase() === "GET" && path.startsWith("/api/agents/tools/calls")) {
    // No tool calls exist for a plain chat turn; the chat surface polls this per
    // conversation, and the empty list is the truthful shape until the C5 agent-run
    // re-target starts filling it.
    return json(200, []);
  }
  if (method.toUpperCase() === "GET" && path.startsWith("/api/files/agent/")) {
    // The builder lists an agent's attached files on select; none exist until C8's file
    // surfaces land, and the honest empty keeps the console clean.
    return json(200, []);
  }
  if (
    method.toUpperCase() === "GET" &&
    /^\/api\/permissions\/[^/]+\/[^/]+\/effective$/.test(path.split("?")[0])
  ) {
    // Local single-user mode: the one principal OWNS every resource it can name — the
    // builder's edit gate reads these bits (VIEW|EDIT|DELETE|SHARE = 15). The real ACL
    // arrives with C10's sharing; answering less here would lock the owner out of their
    // own agents ("Agent Not Available"), which the first builder boot did.
    return json(200, { permissionBits: 15 });
  }
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
    case "GET /api/mcp/servers":
      // Record<serverName, server>; {} renders the empty MCP picker and keeps
      // /api/mcp/tools from ever firing.
      return json(200, {});
    case "GET /api/permissions/mcpServer/effective/all":
      return json(200, {});
    case "GET /api/prompts/groups":
      // Cursor pagination: has_more:false + after:null is what stops the nav scroller.
      // pageNumber/pageSize/pages are required by the response type, unread when empty.
      return json(200, {
        promptGroups: [],
        pageNumber: "1",
        pageSize: 10,
        pages: 1,
        has_more: false,
        after: null,
      });
    case "GET /api/prompts/all":
      // Must be a bare array: the consumer's select() maps over it directly.
      return json(200, []);
    case "GET /api/presets":
    case "GET /api/tags":
    case "GET /api/categories":
    case "GET /api/agents/tools":
    // The builder queries OpenAPI actions on mount; none exist in local mode until C8,
    // and the honest empty keeps the console clean (the host forwards this family here).
    case "GET /api/agents/actions":
    case "GET /api/api-keys":
      return json(200, []);
    case "GET /api/agents/tools/web_search/auth":
      // Honest: no search provider is configured. The toggle's visibility is decided
      // upstream (agent capabilities); this only makes a click route to the key dialog
      // instead of silently enabling.
      return json(200, { authenticated: false, authTypes: [] });
    case "GET /api/endpoints/token-config":
      return json(200, {});
    case "GET /api/memories":
      return json(200, {
        memories: [],
        totalTokens: 0,
        tokenLimit: null,
        usagePercentage: null,
      });
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
