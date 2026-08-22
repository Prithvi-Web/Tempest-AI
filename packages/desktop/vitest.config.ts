/// <reference types="vitest/config" />
/**
 * Desktop unit layer (HANDOFF-WORLD-CLASS §1.1, re-targeted per ADR-0077): vitest over the
 * absorbed surface's LOGIC modules — the SEAM copies in packages/platform/client/tempest/views,
 * imported across the package boundary exactly the way the seam itself imports the desktop's
 * generated bindings.
 *
 * Coverage gate scope, stated: the modules measured here are the ones whose behavior is
 * decidable without a live engine — the enum vocabulary, the route table, and the editor's
 * decision modules (completion validity, hover outcomes, risk wording, divergence lookup).
 * routes.ts replaces router.ts in the list: react-router owns navigation now, and the URL
 * grammar that remains ours is the path-builder module.
 *
 * hooks.ts, TempestViews.tsx, and the views are deliberately excluded from THIS gate because
 * their behavior is pinned end-to-end by the Playwright suite against the real engine
 * (22 specs, console-clean) — measuring their unit coverage would demand mocking the sidecar,
 * which Law L4 forbids as a substitute for the real thing.
 *
 * The include is scoped to tests/ alone: the OLD suite under src/ lives on until the legacy
 * webview's deletion commit (ADR-0077 removes both at the close of C3), and running both
 * would double-count every case; the coverage duty transferred here with the relocation.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { coverageConfigDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Absolute, because the coverage matcher resolves include patterns against this package's
// root and a `../` glob matches nothing there — the seam lives one package over.
const SEAM = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "platform",
  "client",
  "tempest",
  "views",
);

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      // The measured modules live outside this package's root (the seam) — that is the point
      // of the relocation, and allowExternal is what lets the gate see them.
      allowExternal: true,
      // With allowExternal the matcher sees ABSOLUTE paths, and the default exclude
      // `**/[.]**` (meant to hide .git/.cache internals) then matches ANY checkout that
      // lives under a dot-directory — a `.claude/worktrees` checkout measured 0 files and
      // reported nothing. The explicit eight-file include above already owns the scope, so
      // dropping that one pattern widens nothing.
      exclude: coverageConfigDefaults.exclude.filter((p) => p !== "**/[.]**"),
      include: [
        `${SEAM}/vocabulary.tsx`,
        `${SEAM}/routes.ts`,
        `${SEAM}/editor/completionPolicy.ts`,
        `${SEAM}/editor/documentSource.ts`,
        `${SEAM}/editor/modelSource.ts`,
        `${SEAM}/editor/risk.ts`,
        `${SEAM}/editor/divergenceLookup.ts`,
        `${SEAM}/editor/hoverSource.ts`,
      ],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
