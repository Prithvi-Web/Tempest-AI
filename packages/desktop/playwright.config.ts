/**
 * Desktop E2E (HANDOFF-WORLD-CLASS §1.1, re-targeted per ADR-0077): the real PLATFORM
 * surface, the real engine.
 *
 * Two processes back every run, both started here: the platform harness (the BUILT client
 * dist served with the `tempest://` protocol handler's exact semantics — see
 * e2e/platform-server.mjs) and the e2e bridge (spawns `tempest-server --stdio` on a fresh
 * data dir and speaks the Rust supervisor's frames — see e2e/bridge.mjs).
 *
 * Sequential by design: the specs build real state in order (an empty store, then a real
 * pyfix prove, then views over its evidence). Parallel workers would race the one engine.
 */
import { defineConfig } from "@playwright/test";

const BRIDGE_PORT = Number(process.env.E2E_BRIDGE_PORT ?? 39755);
const PLATFORM_PORT = Number(process.env.E2E_PLATFORM_PORT ?? 4180);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PLATFORM_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // Never reuse an existing server: a zombie server from an interrupted run serves until
      // it dies mid-suite and every later spec cascades with ERR_CONNECTION_REFUSED.
      command: "node e2e/platform-server.mjs",
      url: `http://localhost:${PLATFORM_PORT}/api/health`,
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
