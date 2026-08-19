/// <reference types="vitest/config" />
/**
 * Desktop unit layer (HANDOFF-WORLD-CLASS §1.1): vitest over the webview's LOGIC modules.
 *
 * Coverage gate scope, stated: the modules measured here are the ones whose behavior is
 * decidable without a live engine — the enum vocabulary, the router, and dev validation.
 * completionPolicy.ts joins them in Phase 20.3: deciding whether a completion is still VALID is
 * a correctness question with no engine in it, and the race it exists to survive (an answer
 * arriving after the document moved) is exactly what an E2E suite is worst at pinning.
 *
 * hooks.ts, App.tsx, and the views are deliberately excluded from THIS gate because their
 * behavior is pinned end-to-end by the Playwright suite against the real engine (26 specs,
 * console-clean) — measuring their unit coverage would demand mocking the sidecar, which
 * Law L4 forbids as a substitute for the real thing.
 */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: [
        "src/vocabulary.tsx",
        "src/router.ts",
        "src/editor/completionPolicy.ts",
        "src/editor/documentSource.ts",
        "src/editor/modelSource.ts",
      ],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
