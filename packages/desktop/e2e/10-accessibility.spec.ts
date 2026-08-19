/**
 * Accessibility pass (HANDOFF-WORLD-CLASS §3.3): keyboard, screen-reader landmarks, motion
 * preference, and 200% zoom — asserted against the REAL webview, not a checklist document.
 *
 * "200% zoom" is exercised the way WebKit actually implements it: doubling zoom halves the
 * CSS viewport, so a 1180×800 window at 200% lays out at 590×400 — the assertion is that no
 * view forces the content column to scroll horizontally at that size (evidence strings wrap;
 * only designed scroll containers like .mono-block scroll inside themselves).
 */
import { expect, test } from "./fixtures";

test("landmarks: primary nav, per-view main, live engine status", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
  const status = page.locator(".sidebar-foot");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveAttribute("aria-live", "polite");
});

test("the skip link is the first Tab stop and moves focus into the content", async ({
  page,
}) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.locator(".skip-link");
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible(); // it surfaces only while focused
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});

test("after in-app navigation, focus lands on the new view's title", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sidebar").getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeFocused();
  // …and the whole app is drivable from the keyboard from there: Tab reaches a real control.
  await page.keyboard.press("Tab");
  const focusedTag = await page.evaluate(() => document.activeElement?.tagName);
  expect(["A", "BUTTON", "INPUT"]).toContain(focusedTag);
});

test("prefers-reduced-motion kills the view transition", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const animation = await page
    .locator("main")
    .evaluate((el) => getComputedStyle(el).animationName);
  expect(animation).toBe("none");
  // The no-preference case keeps the 180ms view-in — motion exists, it just yields.
  //
  // `reducedMotion: null` was used here and meant "inherit the SYSTEM default", which made the
  // assertion depend on an OS setting the test does not control. It passed on the author's Mac
  // and failed the first time it ever ran on a fresh CI runner — found the day the E2E suite was
  // added to CI, which is the entire reason it was added (trap 44). Naming the state explicitly
  // is what makes this a test about the stylesheet rather than about the machine.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  const restored = await page
    .locator("main")
    .evaluate((el) => getComputedStyle(el).animationName);
  expect(restored).toBe("view-in");
});

test("no view forces horizontal scroll at 200% zoom", async ({ page }) => {
  await page.setViewportSize({ width: 590, height: 400 });
  for (const url of [
    "/",
    "/?view=prove",
    "/?view=watch",
    "/?view=logs",
    "/?view=settings",
    // The editor route, with a repo that does not exist: the REFUSAL surface is a view like any
    // other and must not overflow either. The view shipped outside this loop entirely, which is
    // how it also shipped with no stylesheet.
    "/?view=editor&repo=%2Fnope&file=main.py",
  ]) {
    await page.goto(url);
    await expect(page.locator("main")).toBeVisible();
    const overflow = await page.evaluate(() => {
      const content = document.querySelector(".content");
      if (!content) return -1;
      return content.scrollWidth - content.clientWidth;
    });
    expect(overflow, `${url} must not overflow horizontally at 200% zoom`).toBeLessThanOrEqual(0);
  }
});
