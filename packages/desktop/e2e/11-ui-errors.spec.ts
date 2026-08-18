/**
 * Frontend crash honesty, end to end (HANDOFF-WORLD-CLASS §1.1): a REAL page error travels
 * window handler → typed command → bridge → engine → redaction → obslog → the LOGS view the
 * user actually opens. The deliberate error is declared to the console-clean gate — anything
 * ELSE landing on the console still fails the suite.
 */
import { expect, test } from "./fixtures";

test.use({ allowedConsoleErrors: /tempest-e2e-planted-ui-error|Unhandled/ });

test("a page error is reported, scrubbed, and visible in Logs", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });

  // A real uncaught error, thrown outside Playwright's own call stack. The planted email
  // must be scrubbed by the engine before the record lands (L9).
  await page.evaluate(() => {
    setTimeout(() => {
      throw new Error("tempest-e2e-planted-ui-error for victim@example.com");
    }, 0);
  });

  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  const row = page.getByRole("row", { name: /tempest-e2e-planted-ui-error/ });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row).toContainText("window.error");
  await expect(row).toContainText("[EMAIL]");
  await expect(row).not.toContainText("victim@example.com");
});

test("an unhandled promise rejection is reported too", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });
  await page.evaluate(() => {
    void Promise.reject(new Error("tempest-e2e-planted-ui-error rejection leg"));
  });
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  await expect(
    page.getByRole("row", { name: /rejection leg/ }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("row", { name: /rejection leg/ })).toContainText(
    "unhandledrejection",
  );
});
