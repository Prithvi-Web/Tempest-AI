/**
 * Screenshot pass for the owner's per-phase review (HANDOFF-WORLD-CLASS §3.3): every view,
 * light and dark, over REAL data (a live pyfix prove — nothing staged). Skipped in normal
 * runs; enable with SCREENSHOTS=1:
 *
 *   SCREENSHOTS=1 pnpm test:e2e --grep "screenshot"
 *
 * Output: docs/ui/<view>-<scheme>.png (repo-committed so the review survives the session).
 */
import path from "node:path";

import { expect, test } from "./fixtures";
import { closeSettings, openModelsFromRail, openProofEngineSettings } from "./settings-home";

const OUT = path.resolve(import.meta.dirname, "..", "..", "..", "docs", "ui");

test("screenshot every view in light and dark", async ({ page, bridge }) => {
  test.skip(!process.env.SCREENSHOTS, "screenshot pass runs only with SCREENSHOTS=1");
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1180, height: 800 });

  // Real evidence first: one live prove so populated views show the product, not lorem.
  const { fixture } = await bridge.info();
  await page.goto("/tempest/prove");
  await page.locator("#repo").fill(fixture.repo);
  await page.locator("#base").fill(fixture.base);
  await page.locator("#head").fill(fixture.head);
  await page.getByRole("button", { name: "Prove it" }).click();
  await expect(page).toHaveURL(/\/tempest\/runs\/\d+/, { timeout: 30_000 });
  await expect(page.locator(".statusline .chip").first()).toHaveText("DIVERGENT", {
    timeout: 240_000,
  });
  const runUrl = page.url();

  // Walk into a divergence for the evidence views.
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/\/tempest\/targets\/\d+/);
  const targetUrl = page.url();
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/\/tempest\/divergences\/\d+/);
  const divergenceUrl = page.url();

  // The engine key with the planted fixture (trap 19), through the app's ONE settings home
  // (ADR-0082) — the same door a person uses, on the rail.
  await page.goto("/");
  const settings = await openModelsFromRail(page);
  await settings
    .getByRole("textbox", { name: "Anthropic API key for the proof engine" })
    .fill("sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC");
  await settings.getByRole("button", { name: "Save key" }).click();
  await expect(settings.getByText("Key configured")).toBeVisible();
  await closeSettings(page);

  const shots: Array<[string, string]> = [
    ["runs", "/tempest"],
    ["prove", "/tempest/prove"],
    ["run-detail", runUrl],
    ["target", targetUrl],
    ["divergence", divergenceUrl],
    ["watch", "/tempest/watch"],
    ["logs", "/tempest/logs"],
    // The editor over REAL code from the same pyfix fixture the run above proved. Added because
    // the view shipped unstyled and this pass — the one place a human sees every surface in both
    // schemes — was not looking at it.
    [
      "editor",
      `/tempest/editor?repo=${encodeURIComponent(fixture.repo)}&file=${encodeURIComponent("b01.py")}`,
    ],
  ];
  for (const scheme of ["light", "dark"] as const) {
    // Polarity is the app's own html.dark switch (from localStorage), not the OS query:
    // land on any page of the origin first so storage is reachable, then every later
    // navigation's mode script picks the scheme up before first paint.
    await page.goto("/tempest/runs");
    await page.evaluate((s) => localStorage.setItem("color-theme", s), scheme);
    for (const [name, url] of shots) {
      await page.goto(url);
      await page.waitForTimeout(400); // let queries settle + the view-in transition finish
      await page.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`) });
    }

    // The settings home is a DIALOG now (ADR-0082), not a route, so it cannot ride the loop
    // above — and it is the one surface this pass most needs to keep looking at, because it is
    // where the proof engine's settings and the chat app's settings meet. Both new tabs.
    await page.goto("/");
    await openModelsFromRail(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `settings-models-${scheme}.png`) });
    await closeSettings(page);

    await openProofEngineSettings(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, `settings-engine-${scheme}.png`) });
    await closeSettings(page);
  }
});
