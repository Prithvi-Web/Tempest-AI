/**
 * The flagship flow: a REAL prove of the pyfix fixture through the UI — form → run created →
 * live polling → DIVERGENT verdict with evidence rows. Plus the honest failure paths:
 * a nonexistent repo is rejected with the engine's reason, and a running prove cancels
 * cleanly into CANCELLED (L11).
 *
 * Sequential file order matters: later specs (divergence/search) read the run this file
 * creates. Nothing here is seeded — every row the UI shows was computed by the engine.
 */
import { expect, test } from "./fixtures";

test("a nonexistent repository is rejected with the engine's reason", async ({ page }) => {
  await page.goto("/tempest/prove");
  await page.locator("#repo").fill("/nonexistent/e2e-no-such-repo");
  await page.getByRole("button", { name: "PROVE IT" }).click();
  await expect(page.getByText("could not start")).toBeVisible();
  // Still on the form (no run was created), and the reason text is non-empty.
  await expect(page).toHaveURL(/\/tempest\/prove/);
  await expect(page.locator(".panel.notproven p")).not.toHaveText("");
});

test("a real pyfix prove reaches DIVERGENT with evidence", async ({ page, bridge }) => {
  test.setTimeout(300_000); // a real differential execution, not a mock — give it room
  const { fixture } = await bridge.info();

  await page.goto("/tempest/prove");
  await page.locator("#repo").fill(fixture.repo);
  await page.locator("#base").fill(fixture.base);
  await page.locator("#head").fill(fixture.head);
  await page.getByRole("button", { name: "PROVE IT" }).click();

  // The form navigates to the created run, which polls while the engine executes.
  await expect(page).toHaveURL(/\/tempest\/runs\/\d+/, { timeout: 30_000 });
  await expect(page.locator(".statusline .chip").first()).toHaveText("DIVERGENT", {
    timeout: 240_000,
  });

  // Evidence, not opinion: the targets table carries divergent rows with red counts.
  await expect(page.getByRole("heading", { name: "targets" })).toBeVisible();
  const divergentChips = page.locator("table .chip.DIVERGENT");
  await expect
    .poll(async () => divergentChips.count(), { timeout: 10_000 })
    .toBeGreaterThan(0);

  // The runs list reflects the finished run: verdict chip + a non-zero divergence count.
  await page.locator(".crumbs").getByRole("link", { name: "Runs" }).click();
  const runRow = page.locator("tbody tr").first();
  await expect(runRow.locator(".chip.DIVERGENT")).toBeVisible();
  await expect(runRow.locator("td.num.red")).not.toHaveText("0");
});

test("a running prove cancels into CANCELLED", async ({ page, bridge }) => {
  test.setTimeout(120_000);
  const { fixture } = await bridge.info();

  await page.goto("/tempest/prove");
  await page.locator("#repo").fill(fixture.repo);
  await page.locator("#base").fill(fixture.base);
  await page.locator("#head").fill(fixture.head);
  await page.locator("#budget").fill("2000"); // enough work to still be RUNNING when we cancel
  await page.getByRole("button", { name: "PROVE IT" }).click();

  await expect(page).toHaveURL(/\/tempest\/runs\/\d+/, { timeout: 30_000 });
  await expect(page.locator(".statusline .chip").first()).toHaveText("RUNNING…");
  await page.getByRole("button", { name: "CANCEL" }).click();

  // L11: cancel stops everything fast; the UI must land on the honest CANCELLED state.
  await expect(page.locator(".statusline .chip").first()).toHaveText("CANCELLED", {
    timeout: 15_000,
  });
  await expect(page.getByRole("button", { name: "CANCEL" })).toHaveCount(0);
});
