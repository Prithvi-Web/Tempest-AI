/** The app boots against a real engine: healthy masthead, honest empty state, navigation.
 *
 * Platform surface (ADR-0077): "/" is the CHAT landing now — the proof surface lives at
 * /tempest, mounted inside the client's authed shell (the local principal auto-authenticates
 * through /api/auth/refresh; no login step exists to perform). */
import { expect, test } from "./fixtures";
import { closeSettings, settingsPanel } from "./settings-home";

test("the app reaches a healthy engine and shows the empty runs state", async ({ page }) => {
  await page.goto("/tempest");
  await expect(page.locator(".brand strong")).toHaveText("Tempest");
  // The engine pill settles on version + schema once getHealth answers.
  await expect(page.locator(".sidebar-foot .green")).toContainText(/engine .+ · schema v/, {
    timeout: 15_000,
  });
  // A fresh data dir means an honest empty state, not a spinner and not an error.
  await expect(page.getByText("No runs yet.")).toBeVisible();
});

test("sidebar navigation reaches every destination and returns to runs", async ({ page }) => {
  await page.goto("/tempest");
  await page.getByRole("button", { name: "New proof" }).click();
  await expect(page.getByRole("heading", { name: "New proof" })).toBeVisible();
  await expect(page).toHaveURL(/\/tempest\/prove/);
  await page.locator(".sidebar").getByRole("link", { name: "Watch" }).click();
  await expect(page.getByRole("heading", { name: "Watch" })).toBeVisible();
  await expect(page).toHaveURL(/\/tempest\/watch/);
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  await expect(page.getByRole("heading", { name: "Logs" })).toBeVisible();
  // Settings is no longer a destination INSIDE this surface (ADR-0082): it opens the app's
  // one settings home over it, on the proof-engine tab, and the runs list is still behind.
  await page.getByTestId("tempest-open-settings").click();
  await expect(settingsPanel(page).getByRole("heading", { name: "Settings" })).toBeVisible();
  await closeSettings(page);
  await page.locator(".sidebar").getByRole("link", { name: "Runs" }).click();
  await expect(page.getByText("No runs yet.")).toBeVisible();
});
