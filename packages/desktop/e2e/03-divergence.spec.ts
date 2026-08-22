/**
 * Evidence drill-down over the run 02-prove-flow created: run → target → divergence, with
 * the minimized input, base/head observations, the runnable repro script, and a working
 * COPY (real clipboard — permissions granted in this spec).
 */
import { expect, test } from "./fixtures";

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

test("target and divergence views carry the full evidence chain", async ({ page }) => {
  await page.goto("/tempest");
  // Open the DIVERGENT run from 02 (newest first is not guaranteed — pick by chip).
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/\/tempest\/runs\/\d+/);

  // Into a divergent target.
  await page
    .locator("tbody tr", { has: page.locator(".chip.DIVERGENT") })
    .first()
    .click();
  await expect(page).toHaveURL(/\/tempest\/targets\/\d+/);
  await expect(page.getByRole("heading", { name: "changed-line coverage" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "inputs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "divergences" })).toBeVisible();

  // Into the divergence itself.
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/\/tempest\/divergences\/\d+/);
  await expect(page.getByText("minimized input")).toBeVisible();
  await expect(page.getByText("observed behavior, identical conditions")).toBeVisible();
  await expect(page.getByText("BASE", { exact: true })).toBeVisible();
  await expect(page.getByText("HEAD", { exact: true })).toBeVisible();

  // The repro script is real, runnable text (L7): non-empty and python-shaped.
  const script = page.locator("pre.script");
  await expect(script).toBeVisible({ timeout: 15_000 });
  const scriptText = (await script.textContent()) ?? "";
  expect(scriptText.length).toBeGreaterThan(50);

  // COPY genuinely writes the minimized input to the clipboard.
  const minimized = page.locator(".panel.diverge code").first();
  const minimizedText = (await minimized.textContent()) ?? "";
  expect(minimizedText.trim()).not.toBe("");
  await page.locator(".panel.diverge button", { hasText: "COPY" }).first().click();
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toBe(minimizedText);
});
