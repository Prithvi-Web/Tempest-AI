/** The app boots against a real engine: healthy masthead, honest empty state, navigation. */
import { expect, test } from "./fixtures";

test("the app reaches a healthy engine and shows the empty runs state", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".brand strong")).toHaveText("Tempest");
  // The engine pill settles on version + schema once getHealth answers.
  await expect(page.locator(".sidebar-foot .green")).toContainText(/engine .+ · schema v/, {
    timeout: 15_000,
  });
  // A fresh data dir means an honest empty state, not a spinner and not an error.
  await expect(page.getByText("No runs yet.")).toBeVisible();
});

test("sidebar navigation reaches every destination and returns to runs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New proof" }).click();
  await expect(page.getByRole("heading", { name: "New proof" })).toBeVisible();
  await expect(page).toHaveURL(/view=prove/);
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  await expect(page.getByRole("heading", { name: "Logs" })).toBeVisible();
  await page.locator(".sidebar").getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await page.locator(".sidebar").getByRole("link", { name: "Runs" }).click();
  await expect(page.getByText("No runs yet.")).toBeVisible();
});
