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
import { settingsPanel } from "./settings-home";

test("landmarks: the subtree's nav, per-view main, live engine status", async ({ page }) => {
  await page.goto("/tempest");
  // "Primary" belonged to the webview that owned the whole window; inside the platform client
  // the subtree's rail is one navigation among the client's own, named for what it is.
  await expect(page.getByRole("navigation", { name: "Tempest" })).toBeVisible();
  await expect(page.locator("main")).toHaveCount(1);
  const status = page.locator(".sidebar-foot");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveAttribute("aria-live", "polite");
});

test("the skip link surfaces on focus and moves focus into the content", async ({
  page,
}) => {
  // The webview owned the window, so the skip link was the FIRST Tab stop of the page. Inside
  // the platform client the host shell's chrome tabs first — the window's tab order is the
  // client's to arrange, not this subtree's. What remains the subtree's own claim, asserted
  // here: its skip link surfaces when focused and lands focus on the subtree's content
  // landmark (#tempest-main-content — the absorbed id, prefixed against collision).
  await page.goto("/tempest");
  const skip = page.locator(".skip-link");
  await skip.focus();
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible(); // it surfaces only while focused
  await page.keyboard.press("Enter");
  await expect(page.locator("#tempest-main-content")).toBeFocused();
});

test("after in-app navigation, focus lands on the new view's title", async ({ page }) => {
  await page.goto("/tempest");
  // Logs rather than Settings: settings is a dialog now, not a destination in this surface
  // (ADR-0082), and the behaviour under test is the SPA focus move on in-app navigation —
  // which needs a real route change to be about anything. The dialog's own focus contract is
  // asserted below, where it belongs.
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  await expect(page.getByRole("heading", { name: "Logs" })).toBeFocused();
  // …and the whole app is drivable from the keyboard from there: Tab reaches a real control.
  await page.keyboard.press("Tab");
  const focusedTag = await page.evaluate(() => document.activeElement?.tagName);
  // SELECT is here because the Logs view's first control is its level filter. The point of the
  // assertion is that Tab from the title reaches an OPERABLE control rather than nothing.
  expect(["A", "BUTTON", "INPUT", "SELECT"]).toContain(focusedTag);
});

test("the settings home traps focus and gives it back where it was", async ({ page }) => {
  // The other half of what the test above used to cover. A dialog owes a keyboard user three
  // things — focus moves in, Escape closes it, and focus returns to the control that opened
  // it — and the settings home became a dialog for Tempest's settings at ADR-0082, so those
  // three now apply to them.
  await page.goto("/tempest");
  const opener = page.getByTestId("tempest-open-settings");
  await opener.click();
  const panel = settingsPanel(page);
  await expect(panel).toBeVisible();

  // Focus is INSIDE the dialog, not left behind on the rail. Headless UI focuses the dialog
  // CONTAINER — the element carrying `role="dialog"`, which is its full-screen wrapper here
  // and not the panel (spec 21 documents that split, and it is why this reads the wrapper).
  // Measured rather than assumed: an assertion against the panel fails, and would have been
  // the wrong bar anyway.
  const inside = await page.evaluate(() =>
    document.querySelector('[role="dialog"]')?.contains(document.activeElement) ?? false,
  );
  expect(inside).toBe(true);

  // And the trap really holds: Tab from the container lands on a control inside the PANEL,
  // not on something behind the scrim.
  await page.keyboard.press("Tab");
  const reached = await page.evaluate(() => {
    const dialogPanel = document.querySelector('[id^="headlessui-dialog-panel"]');
    return {
      inPanel: dialogPanel?.contains(document.activeElement) ?? false,
      tag: document.activeElement?.tagName,
    };
  });
  expect(reached.inPanel).toBe(true);
  expect(["A", "BUTTON", "INPUT", "SELECT"]).toContain(reached.tag);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("prefers-reduced-motion quiets the view transition to an instant", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/tempest");
  const quieted = await page.locator("main").evaluate((el) => {
    const s = getComputedStyle(el);
    return { name: s.animationName, duration: s.animationDuration };
  });
  // 1ms, deliberately NOT `none`: a suppressed animation still fires animationend, so a
  // component awaiting one cannot hang — the same rule the client seam applies to
  // transitions (theme.css §6). The name surviving is the mechanism working: the motion
  // exists, at a duration no human perceives.
  expect(quieted.name).toBe("view-in");
  expect(quieted.duration).toBe("0.001s");
  // The no-preference case keeps the 180ms view-in — motion exists, it just yields.
  //
  // `reducedMotion: null` was used here and meant "inherit the SYSTEM default", which made the
  // assertion depend on an OS setting the test does not control. It passed on the author's Mac
  // and failed the first time it ever ran on a fresh CI runner — found the day the E2E suite was
  // added to CI, which is the entire reason it was added (trap 44). Naming the state explicitly
  // is what makes this a test about the stylesheet rather than about the machine.
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/tempest");
  const restored = await page.locator("main").evaluate((el) => {
    const s = getComputedStyle(el);
    return { name: s.animationName, duration: s.animationDuration };
  });
  expect(restored.name).toBe("view-in");
  expect(restored.duration).toBe("0.18s");
});

test("no view forces horizontal scroll at 200% zoom, tables excepted by design", async ({
  page,
}) => {
  // Platform delta, stated. The legacy stylesheet put `overflow-wrap: anywhere` on every table
  // cell, so at 200% zoom columns collapsed to fit and nothing scrolled sideways. The seam's
  // C4 pass reversed that FOR TABLE CELLS on purpose — its own comment: inside the platform
  // client the content column is permanently narrower, and mid-word breaks in system columns
  // read as damage ("DIVERGE NT"); headers and verdict chips keep their words whole
  // (tempest-views.css, the 200%-zoom section). The bar that survives, asserted here: every
  // view's non-table content still fits — a DATA TABLE is the only surface allowed to exceed
  // the column, and only because whole words were chosen over sideways scroll.
  await page.setViewportSize({ width: 590, height: 400 });
  for (const url of [
    "/tempest",
    "/tempest/prove",
    "/tempest/watch",
    "/tempest/logs",
    // `/tempest/settings` is gone from this list on purpose (ADR-0082): it is a redirect into
    // the app's ONE settings home now, not a view with a `.content` column of its own. The
    // dialog's own geometry is pinned by spec 21 and its controls by spec 08.
    // The editor route, with a repo that does not exist: the REFUSAL surface is a view like any
    // other and must not overflow either. The view shipped outside this loop entirely, which is
    // how it also shipped with no stylesheet.
    "/tempest/editor?repo=%2Fnope&file=main.py",
  ]) {
    await page.goto(url);
    await expect(page.locator("main")).toBeVisible();
    const overflow = await page.evaluate(() => {
      const content = document.querySelector(".content");
      if (!content) return { page: -1, sansTables: -1 };
      const whole = content.scrollWidth - content.clientWidth;
      // The same measurement with the tables' width taken out of the layout: what remains is
      // every other surface's claim, and that claim is unchanged from the desktop bar.
      const tables = Array.from(content.querySelectorAll("table")) as HTMLElement[];
      const saved = tables.map((t) => t.style.display);
      for (const t of tables) t.style.display = "none";
      const sansTables = content.scrollWidth - content.clientWidth;
      tables.forEach((t, i) => (t.style.display = saved[i] ?? ""));
      return { page: whole, sansTables };
    });
    expect(
      overflow.sansTables,
      `${url}: non-table content must not overflow horizontally at 200% zoom`,
    ).toBeLessThanOrEqual(0);
  }
});
