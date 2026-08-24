/**
 * Driving the app's ONE settings home (ADR-0082).
 *
 * Tempest's settings used to be a page inside the proof surface, reached at
 * `/tempest/settings`. They are now tabs in the app's own settings dialog, which is where
 * every other setting in the product already lived. These helpers are the three ways a person
 * actually gets there, so the specs drive the real doors rather than a test-only shortcut.
 */
import { expect, type Page } from "@playwright/test";

/** The Headless UI panel the dialog renders into (spec 21 pins its geometry). */
export function settingsPanel(page: Page) {
  return page.locator('[id^="headlessui-dialog-panel"]');
}

/** The rail's Models entry — the owner's "download local models on the vertical navigation
 * bar". Opens the home on the Models tab. */
export async function openModelsFromRail(page: Page) {
  await page.getByTestId("nav-panel-tempest-models").click();
  const panel = settingsPanel(page);
  await expect(panel).toBeVisible();
  return panel;
}

/** The deep link the proof surface's own rail item and every older bookmark use. Opens the
 * home on the Proof engine tab and returns the view to the runs list. */
export async function openProofEngineSettings(page: Page) {
  await page.goto("/tempest/settings");
  const panel = settingsPanel(page);
  await expect(panel).toBeVisible();
  return panel;
}

/** The account menu — upstream's own door, unchanged, landing on General. */
export async function openSettingsFromAccountMenu(page: Page) {
  await page.getByTestId("nav-user").click();
  await page.getByTestId("nav-settings").click();
  const panel = settingsPanel(page);
  await expect(panel).toBeVisible();
  return panel;
}

/** Switch tabs inside the open dialog, by its visible name. */
export async function selectSettingsTab(page: Page, name: string) {
  await settingsPanel(page).getByRole("tab", { name }).click();
}

export async function closeSettings(page: Page) {
  await settingsPanel(page).getByRole("button", { name: "Close Settings" }).click();
  await expect(settingsPanel(page)).toHaveCount(0);
}
