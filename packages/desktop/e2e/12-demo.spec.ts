/**
 * Onboarding (Phase 18): the activation path, timed. One click in an empty app must reach a
 * visible divergence in under 90 seconds — the engine writes a real demo repository, proves
 * it for real, and the run view fills with live evidence. Both verdicts appear (the rounding
 * "cleanup" DIVERGENT, the honest label refactor EQUIVALENT_UNDER_BUDGET), because teaching
 * the verdict vocabulary is the demo's actual job.
 */
import { expect, test } from "./fixtures";

test("one click reaches a real divergence in under 90 seconds", async ({ page }) => {
  test.slow(); // a real differential prove runs inside this test
  const started = Date.now();

  await page.goto("/");
  await expect(page.getByText("No runs yet.")).toBeVisible();
  await page.getByRole("button", { name: "Try a demo proof" }).click();

  // Straight into the ordinary run view — the demo is a run, not a tour.
  await expect(page).toHaveURL(/view=run&id=\d+/);
  await expect(page.locator(".statusline .chip").first()).toHaveText("DIVERGENT", {
    timeout: 90_000,
  });
  expect(Date.now() - started, "activation bar: first divergence <90s").toBeLessThan(90_000);

  // Both vocabulary lessons on one screen.
  await expect(page.getByRole("cell", { name: "final_price" })).toBeVisible();
  await expect(page.locator(".chip.EQUIVALENT_UNDER_BUDGET").first()).toBeVisible();

  // The evidence chain is real: divergence → minimized input → repro text.
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/view=target&id=\d+/);
  await page.locator("tbody tr", { has: page.locator(".chip.DIVERGENT") }).first().click();
  await expect(page).toHaveURL(/view=divergence&id=\d+/);
  await expect(page.getByText("Tempest minimized reproduction")).toBeVisible();
});
