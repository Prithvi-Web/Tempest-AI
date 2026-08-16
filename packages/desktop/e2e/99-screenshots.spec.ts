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

const OUT = path.resolve(import.meta.dirname, "..", "..", "..", "docs", "ui");

test("screenshot every view in light and dark", async ({ page, bridge }) => {
  test.skip(!process.env.SCREENSHOTS, "screenshot pass runs only with SCREENSHOTS=1");
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1180, height: 800 });

  // Real evidence first: one live prove so populated views show the product, not lorem.
  const { fixture } = await bridge.info();
  await page.goto("/?view=prove");
  await page.locator("#repo").fill(fixture.repo);
  await page.locator("#base").fill(fixture.base);
  await page.locator("#head").fill(fixture.head);
  await page.getByRole("button", { name: "Prove it" }).click();
  await expect(page).toHaveURL(/view=run&id=\d+/, { timeout: 30_000 });
  await expect(page.locator(".statusline .chip").first()).toHaveText("DIVERGENT", {
    timeout: 240_000,
  });
  const runUrl = page.url();

  // Walk into a divergence for the evidence views.
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/view=target&id=\d+/);
  const targetUrl = page.url();
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/view=divergence&id=\d+/);
  const divergenceUrl = page.url();

  // Settings with a configured key (the planted fixture — trap 19).
  await page.goto("/?view=settings");
  await page
    .getByRole("textbox", { name: "API key" })
    .fill("sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByText("Key configured")).toBeVisible();

  const shots: Array<[string, string]> = [
    ["runs", "/"],
    ["prove", "/?view=prove"],
    ["run-detail", runUrl],
    ["target", targetUrl],
    ["divergence", divergenceUrl],
    ["logs", "/?view=logs"],
    ["settings", "/?view=settings"],
  ];
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const [name, url] of shots) {
      await page.goto(url);
      await page.waitForTimeout(400); // let queries settle + the view-in transition finish
      await page.screenshot({ path: path.join(OUT, `${name}-${scheme}.png`) });
    }
  }
});
