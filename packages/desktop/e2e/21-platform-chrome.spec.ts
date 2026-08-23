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
 *
 * The glass assertions PIN the transparency preference rather than inheriting the host's:
 * theme.css §7 deliberately answers `prefers-reduced-transparency: reduce` with solid
 * surfaces, and GitHub's macOS runner images ship with that preference ON — the first CI run
 * of this spec failed on exactly that, measuring the runner's accessibility settings instead
 * of the code. Both preference states are asserted, so the accessible branch is pinned too.
 */
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

async function emulateTransparency(page: Page, value: "no-preference" | "reduce") {
  // Playwright's emulateMedia() has no reducedTransparency knob at this pin; CDP's
  // setEmulatedMedia is the same mechanism one level down, Chromium-only like the suite.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-transparency", value }],
  });
}

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
  // that is the exact property whose violation created the containing block. Pinned under
  // an explicit no-preference so the assertion is about theme.css, not the host's
  // accessibility settings (the CI runner ships with reduce-transparency ON).
  const readFilters = () =>
    panel.evaluate((el) => {
      const wrapper = el.closest('[role="dialog"]');
      if (!wrapper) throw new Error("the panel must live inside the dialog wrapper");
      return {
        wrapper: getComputedStyle(wrapper).backdropFilter,
        panel: getComputedStyle(el).backdropFilter,
        panelBackground: getComputedStyle(el).backgroundColor,
      };
    });

  await emulateTransparency(page, "no-preference");
  const glass = await readFilters();
  expect(glass.wrapper).toBe("none");
  expect(glass.panel).toContain("blur");

  // A reader who asked for reduced transparency gets a SOLID panel (theme.css §7's media
  // block), the wrapper still carries no filter, and the panel stays where it was — the
  // accessible branch re-declares the same selectors and deserves its own pin.
  await emulateTransparency(page, "reduce");
  const solid = await readFilters();
  expect(solid.wrapper).toBe("none");
  expect(solid.panel).toBe("none");
  expect(solid.panelBackground).toMatch(/^rgb\(/); // rgb(...), no alpha channel: fully opaque
  const solidBox = await panel.boundingBox();
  if (!solidBox) throw new Error("the dialog panel must keep its box under reduce");
  expect(solidBox.y).toBeGreaterThanOrEqual(0);
  expect(solidBox.y + solidBox.height).toBeLessThanOrEqual(viewport.height + 1);
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
