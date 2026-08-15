/**
 * Desktop E2E (HANDOFF-WORLD-CLASS §1.1): the real webview UI, the real engine.
 *
 * Two processes back every run, both started here: the vite dev server (the exact UI code
 * the app bundles) and the e2e bridge (spawns `tempest-server --stdio` on a fresh data dir
 * and speaks the Rust supervisor's frames — see e2e/bridge.mjs).
 *
 * Sequential by design: the specs build real state in order (an empty store, then a real
 * pyfix prove, then views over its evidence). Parallel workers would race the one engine.
 */
import { defineConfig } from "@playwright/test";

const BRIDGE_PORT = Number(process.env.E2E_BRIDGE_PORT ?? 39755);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:1420",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // Never reuse an existing server: a zombie vite from an interrupted run serves until
      // it dies mid-suite and every later spec cascades with ERR_CONNECTION_REFUSED.
      // strictPort means a squatter on 1420 is a loud startup error instead.
      command: "pnpm dev",
      url: "http://localhost:1420",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "node e2e/bridge.mjs",
      url: `http://127.0.0.1:${BRIDGE_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
