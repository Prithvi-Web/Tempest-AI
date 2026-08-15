/**
 * FTS search over the divergences 02-prove-flow produced. The index covers the divergence's
 * EVIDENCE text (detail + base/head summaries — see routers/search.py), so the test learns
 * its query term from a real divergence's detail, then verifies the hit navigates back to
 * that class of evidence. Junk gets the honest no-match state.
 */
import { expect, test } from "./fixtures";

test("search finds a real divergence by its evidence text and navigates to it", async ({
  page,
}) => {
  await page.goto("/");
  // Walk to a real divergence and learn a searchable word from its indexed detail text.
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await page
    .locator("tbody tr", { has: page.locator(".chip.DIVERGENT") })
    .first()
    .click();
  await expect(page).toHaveURL(/view=target&id=\d+/);
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/view=divergence&id=\d+/);
  const detail = ((await page.locator("main > p.dim").first().textContent()) ?? "").trim();
  const module = detail.match(/[A-Za-z]{4,}/)?.[0] ?? "";
  expect(module).not.toBe("");

  await page.getByRole("link", { name: "runs" }).click();
  await page.getByLabel("search divergences").fill(module);
  // Scope to the search-results table (its header has the "evidence" column) — the runs
  // table below also has .rowlink rows and would race an unscoped locator.
  const results = page.locator("table", { has: page.locator('th:text-is("evidence")') });
  const hits = results.locator("tbody tr.rowlink");
  await expect.poll(async () => hits.count(), { timeout: 15_000 }).toBeGreaterThan(0);
  await hits.first().click();
  await expect(page).toHaveURL(/view=divergence&id=\d+/);
});

test("a query matching nothing states so plainly", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("search divergences").fill("zzqx-no-such-divergence");
  await expect(page.getByText(/No divergences match/)).toBeVisible({ timeout: 15_000 });
});
