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
const STARTUP_CONFIG = Object.freeze({
  appTitle: "Tempest",
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
  interface: {},
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
    case "GET /api/roles/user":
      // zod fills unspecified permission groups from its own defaults.
      return json(200, { name: "USER", permissions: {} });
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
    default:
      return json(404, {
        error: "not part of local mode yet",
        detail:
          "this endpoint joins the local surface at its convergence phase " +
          "(C4 models, C5 agents, C6 conversations)",
        path,
      });
  }
}
