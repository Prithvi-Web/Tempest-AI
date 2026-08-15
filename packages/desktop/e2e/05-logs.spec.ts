/**
 * The LOGS view over the engine's real obslog: records exist after the proves the earlier
 * specs ran, and the minimum-level filter genuinely filters (or states emptiness honestly).
 */
import { expect, test } from "./fixtures";

test("log records from the real proves render, and the level filter filters", async ({
  page,
}) => {
  await page.goto("/?view=logs");
  await expect(page.getByRole("heading", { name: "LOGS" })).toBeVisible();

  // The earlier proves wrote real records; ALL LEVELS must show them.
  const rows = page.locator("tbody tr");
  await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBeGreaterThan(0);

  // Raise the floor to ERROR: every remaining row is ERROR/CRITICAL — or the view says
  // plainly that nothing is at that level. Either way, nothing below the floor leaks through.
  await page.getByLabel("minimum level").selectOption("ERROR");
  await expect
    .poll(async () => {
      const empty = await page.getByText(/No log records at ERROR or above/).count();
      if (empty > 0) return true;
      const levels = await page.locator("tbody tr td:nth-child(2)").allTextContents();
      return levels.length > 0 && levels.every((l) => l === "ERROR" || l === "CRITICAL");
    }, { timeout: 15_000 })
    .toBe(true);
});
