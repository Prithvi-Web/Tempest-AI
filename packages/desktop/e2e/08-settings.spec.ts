/**
 * Settings — the BYOK Anthropic key (HANDOFF-WORLD-CLASS §3.2). The UI is driven for real;
 * the keychain itself is the Rust host's job and is stood in for by the shim with the exact
 * same validation semantics (see shim.js) — the real storage, idempotent clear, and
 * spawn-env injection are proven by cargo tests in src-tauri.
 *
 * The planted key is letter-segmented fiction (trap 19) — the same fixture the redaction
 * gate proves gets scrubbed from every outbound surface (24/24).
 */
import { expect, test } from "./fixtures";

const PLANTED_KEY = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC";

test("the API key has a clear home: reject junk, save, recognize, remove", async ({ page }) => {
  await page.goto("/?view=settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Anthropic API key" })).toBeVisible();

  // A paste accident is rejected with the host's actionable message — nothing is stored.
  await page.getByRole("textbox", { name: "API key" }).fill("https://console.anthropic.com/keys");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByText(/does not look like an Anthropic API key/)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "API key" })).toBeVisible(); // still unconfigured

  // A real-shaped key saves; the page then knows ONLY {configured, last4} (L9).
  await page.getByRole("textbox", { name: "API key" }).fill(PLANTED_KEY);
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByText("Key configured")).toBeVisible();
  await expect(page.getByText(`ends in ${PLANTED_KEY.slice(-4)}`)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "API key" })).toHaveCount(0); // the secret field is gone

  // The status survives navigation (it is host state, not page state).
  await page.locator(".sidebar").getByRole("link", { name: "Runs" }).click();
  await page.locator(".sidebar").getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText("Key configured")).toBeVisible();

  // Removing returns to the unconfigured state.
  await page.getByRole("button", { name: "Remove key" }).click();
  await expect(page.getByRole("textbox", { name: "API key" })).toBeVisible();
  await expect(page.getByText("Key configured")).toHaveCount(0);
});
