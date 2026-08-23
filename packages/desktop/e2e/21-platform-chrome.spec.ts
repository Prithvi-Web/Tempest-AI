/**
 * Platform chrome — the shell's own furniture, pinned where it broke.
 *
 * The settings dialog is the one Headless UI v2 dialog in the vendored client, and Headless UI
 * puts `role="dialog"` on the full-screen WRAPPER, not the panel (Radix puts it on the panel).
 * The storm-glass overlay rule keyed on `[role='dialog']` therefore landed backdrop-filter on
 * the wrapper — and a backdrop-filter creates a containing block for fixed descendants, so the
 * scrim collapsed to a zero-height box (no dimming) and the panel centered against the
 * wrapper's static position below the fold (clipped at the window's bottom edge). The suite
 * stayed green because nothing asserted GEOMETRY: every control was still clickable where it
 * lay. These specs assert the geometry.
 */
import { expect, test } from "./fixtures";

test("the settings dialog opens centered over a dimmed page", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nav-user").click();
  await page.getByTestId("nav-settings").click();

  const panel = page.locator('[id^="headlessui-dialog-panel"]');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Settings" })).toBeVisible();

  const viewport = page.viewportSize();
  if (!viewport) throw new Error("viewport size must exist in the e2e browser");
  const panelBox = await panel.boundingBox();
  if (!panelBox) throw new Error("the dialog panel must have a box");

  // A real dialog, not an empty shell (trap 60: every upper bound needs a lower bound).
  expect(panelBox.width).toBeGreaterThan(400);
  expect(panelBox.height).toBeGreaterThan(300);

  // Fully inside the viewport — the defect clipped the bottom half off-screen.
  expect(panelBox.y).toBeGreaterThanOrEqual(0);
  expect(panelBox.y + panelBox.height).toBeLessThanOrEqual(viewport.height + 1);

  // Centered both ways (the flex container is items-center justify-center).
  const dx = Math.abs(panelBox.x + panelBox.width / 2 - viewport.width / 2);
  const dy = Math.abs(panelBox.y + panelBox.height / 2 - viewport.height / 2);
  expect(dx).toBeLessThanOrEqual(8);
  expect(dy).toBeLessThanOrEqual(8);

  // The scrim really covers the page (the defect collapsed it to zero height).
  const scrim = page.locator("div.fixed.inset-0.bg-black");
  const scrimBox = await scrim.boundingBox();
  if (!scrimBox) throw new Error("the scrim must have a box");
  expect(scrimBox.width).toBeGreaterThanOrEqual(viewport.width - 1);
  expect(scrimBox.height).toBeGreaterThanOrEqual(viewport.height - 1);

  // Glass belongs on the PANEL; the wrapper must never carry a backdrop-filter again —
  // that is the exact property whose violation created the containing block.
  const filters = await panel.evaluate((el) => {
    const wrapper = el.closest('[role="dialog"]');
    if (!wrapper) throw new Error("the panel must live inside the dialog wrapper");
    return {
      wrapper: getComputedStyle(wrapper).backdropFilter,
      panel: getComputedStyle(el).backdropFilter,
    };
  });
  expect(filters.wrapper).toBe("none");
  expect(filters.panel).toContain("blur");
});

test("the rail wears the Tempest mark, top-left, actually loaded", async ({ page }) => {
  await page.goto("/");
  const mark = page.getByAltText("Tempest AI");
  await expect(mark).toBeVisible();

  const box = await mark.boundingBox();
  if (!box) throw new Error("the mark must have a box");
  expect(box.width).toBeGreaterThanOrEqual(20); // rendered at real size, not collapsed
  expect(box.x).toBeLessThan(60); // in the rail…
  expect(box.y).toBeLessThan(120); // …at its top

  // The asset genuinely served (a 404 would also trip the console-clean gate, but an
  // assertion that reads the loaded bitmap says WHICH failure happened).
  const loaded = await mark.evaluate((el) => (el as HTMLImageElement).naturalWidth > 0);
  expect(loaded).toBe(true);
});
