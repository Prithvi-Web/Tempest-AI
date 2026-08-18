/**
 * The demo's second entry point (ADR-0032): the empty-state button disappears once history
 * exists, so the New proof form carries it permanently. This spec runs LATE in the suite —
 * the store already holds real runs from earlier specs — which is exactly the state it pins.
 */
import { expect, test } from "./fixtures";

test("the demo is reachable from New proof even with existing history", async ({ page }) => {
  test.slow(); // a real differential prove runs inside this test
  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });
  // History exists (earlier specs proved for real), so the empty-state button is gone…
  await expect(page.getByText("No runs yet.")).toHaveCount(0);

  // …but the New proof form still offers the demo.
  await page.locator(".sidebar").getByRole("link", { name: "New proof" }).click();
  await page.getByRole("button", { name: "Try a demo proof" }).click();
  await expect(page).toHaveURL(/view=run&id=\d+/);
  await expect(page.locator(".statusline .chip").first()).toHaveText("DIVERGENT", {
    timeout: 90_000,
  });
});
