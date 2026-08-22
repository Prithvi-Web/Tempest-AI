/**
 * Shared E2E plumbing: every test gets the Tauri IPC shim injected before page scripts run,
 * a console-cleanliness gate (zero console errors + zero unhandled rejections is part of the
 * zero-issues bar — HANDOFF-WORLD-CLASS §1.1), and a typed client for the bridge's admin
 * endpoints (engine lifecycle staging + the fixture repo path).
 *
 * Tests that DELIBERATELY break the engine (lifecycle.spec.ts) declare the console noise
 * they expect via `allowedConsoleErrors`; everything unexpected still fails the test.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { test as base, expect } from "@playwright/test";

const BRIDGE_URL = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;
const SHIM = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "shim.js"),
  "utf-8",
);

export interface BridgeInfo {
  ok: boolean;
  sidecarAlive: boolean;
  dataDir: string;
  fixture: { repo: string; base: string; head: string };
}

export class Bridge {
  async info(): Promise<BridgeInfo> {
    const res = await fetch(`${BRIDGE_URL}/health`);
    if (!res.ok) throw new Error(`bridge /health ${res.status}`);
    return (await res.json()) as BridgeInfo;
  }

  async engineDown(): Promise<void> {
    await fetch(`${BRIDGE_URL}/admin/engine-down`, { method: "POST" });
  }

  async engineUp(): Promise<void> {
    await fetch(`${BRIDGE_URL}/admin/engine-up`, { method: "POST" });
  }
}

interface Fixtures {
  bridge: Bridge;
  /** Single pattern (arrays are mangled by test.use's [value, config] tuple parsing). */
  allowedConsoleErrors: RegExp | null;
}

export const test = base.extend<Fixtures>({
  allowedConsoleErrors: [null, { option: true }],
  bridge: async ({}, use) => {
    await use(new Bridge());
  },
  page: async ({ page, allowedConsoleErrors }, use) => {
    const problems: string[] = [];
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      // One known-absent vendored asset, allowed BY URL rather than by pattern: upstream's
      // vite config sets `publicDir: false` on build, so the TTS keep-alive audio is not in
      // dist and the SHIPPED app 404s this exact request too (tauri.conf.json bundles only
      // dist/). Chromium alone turns that into a console line. Any other failed resource —
      // a missing chunk, a broken icon — still fails the suite.
      if (
        message.text().startsWith("Failed to load resource") &&
        message.location().url.endsWith("/assets/silence.mp3")
      ) {
        return;
      }
      problems.push(message.text());
    });
    page.on("pageerror", (error) => problems.push(`pageerror: ${String(error)}`));
    await page.addInitScript({
      content: `window.__E2E_BRIDGE_URL__ = ${JSON.stringify(BRIDGE_URL)};\n${SHIM}`,
    });
    await use(page);
    const unexpected = problems.filter(
      (text) => !(allowedConsoleErrors !== null && allowedConsoleErrors.test(text)),
    );
    expect(unexpected, "console must stay clean during E2E (zero-issues bar)").toEqual([]);
  },
});

export { expect } from "@playwright/test";
