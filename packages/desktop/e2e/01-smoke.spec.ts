/** The app boots against a real engine: healthy masthead, honest empty state, navigation. */
import { expect, test } from "./fixtures";

test("the app reaches a healthy engine and shows the empty runs state", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".masthead .word")).toHaveText("T E M P E S T");
  // The engine banner settles on version + schema once getHealth answers.
  await expect(page.locator(".masthead .green")).toContainText(/engine .+ · schema v/, {
    timeout: 15_000,
  });
  // A fresh data dir means an honest empty state, not a spinner and not an error.
  await expect(page.getByText("No runs yet.")).toBeVisible();
});

test("navigation: NEW PROOF and LOGS are reachable and return to runs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "NEW PROOF" }).click();
  await expect(page.getByRole("heading", { name: "NEW PROOF" })).toBeVisible();
  await expect(page).toHaveURL(/view=prove/);
  await page.getByRole("link", { name: "runs" }).click();
  await page.getByRole("button", { name: "LOGS" }).click();
  await expect(page.getByRole("heading", { name: "LOGS" })).toBeVisible();
  await page.getByRole("link", { name: "runs" }).click();
  await expect(page.getByText("No runs yet.")).toBeVisible();
});
