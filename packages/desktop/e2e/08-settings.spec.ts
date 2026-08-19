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

test("the key can be tested live, and the answer is stated plainly", async ({ page }) => {
  await page.goto("/?view=settings");
  await page.getByRole("textbox", { name: "API key" }).fill(PLANTED_KEY);
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByText("Key configured")).toBeVisible();

  // The engine has no key in ITS environment (the shim's keychain stand-in cannot inject one
  // into an already-running sidecar — the real host injects at spawn), so the honest answer
  // is the keyless one. What this pins is the whole round trip: button → host → engine →
  // rendered sentence, with nothing invented in between.
  await page.getByRole("button", { name: "Test key" }).click();
  await expect(page.getByText(/no API key is configured/)).toBeVisible();
});

test("sync, storage and privacy show REAL configuration and persist it", async ({
  page,
  bridge,
}) => {
  const info = await bridge.info();
  await page.goto("/?view=settings");

  // Storage states the truth about this machine: the engine's own data dir, live usage.
  await expect(page.getByRole("heading", { name: "Storage" })).toBeVisible();
  await expect(page.getByText(info.dataDir, { exact: false })).toBeVisible();
  await expect(page.getByText("unlimited")).toBeVisible();

  // Privacy: telemetry is off until the user says otherwise, and saying so sticks.
  const telemetry = page.getByRole("switch", { name: "Share anonymous usage counters" });
  await expect(telemetry).not.toBeChecked();
  await telemetry.check();
  await expect(telemetry).toBeChecked();

  // Sync: a server URL and the source-sharing default (off — the privacy posture).
  const shareSource = page.getByRole("switch", {
    name: "Include source code in pushed bundles",
  });
  await expect(shareSource).not.toBeChecked();
  await page.getByRole("textbox", { name: "Team server URL" }).fill("https://team.example.com");
  await page.getByRole("textbox", { name: "Team server URL" }).blur();
  await expect(page.getByRole("button", { name: "Push now" })).toBeEnabled();

  // Everything above is one document in the engine — reload proves it was persisted, not
  // held in React state.
  await page.reload();
  await expect(page.getByRole("switch", { name: "Share anonymous usage counters" })).toBeChecked();
  await expect(page.getByRole("textbox", { name: "Team server URL" })).toHaveValue(
    "https://team.example.com",
  );

  // …and turning it back off persists too (the toggle is not one-way).
  await page.getByRole("switch", { name: "Share anonymous usage counters" }).uncheck();
  await page.reload();
  await expect(
    page.getByRole("switch", { name: "Share anonymous usage counters" }),
  ).not.toBeChecked();
});

test("a bundle budget can be set, and it is stated in human units", async ({ page }) => {
  await page.goto("/?view=settings");
  await expect(page.getByText("unlimited")).toBeVisible();
  // Slider index 1 is the first real budget (100 MB) — set it by keyboard, the way a
  // keyboard-only user would.
  const slider = page.getByRole("slider", { name: "Bundle budget" });
  await slider.focus();
  await slider.press("ArrowRight");
  await expect(page.getByText("100.0 MB")).toBeVisible();
  await page.reload();
  await expect(page.getByText("100.0 MB")).toBeVisible();
});

test("a diagnostic bundle is written locally, described, and revealable by bare name", async ({
  page,
}) => {
  await page.goto("/?view=settings");
  await page.getByRole("button", { name: "Export diagnostic bundle" }).click();
  await expect(page.getByText(/^Wrote tempest-diagnostic-.*\.zip$/)).toBeVisible();
  await expect(page.getByText(/REVIEW EVERY FILE BEFORE SENDING/)).toBeVisible();

  await page.getByRole("button", { name: "Show in Finder" }).click();
  const revealed = await page.evaluate(() => window.__E2E__.revealed);
  expect(revealed).toHaveLength(1);
  // The UI may only ever name a leaf inside the data folder — never a path (commands.rs).
  expect(revealed[0]).toMatch(/^tempest-diagnostic-[0-9T]+\.zip$/);

  await page.getByRole("button", { name: "Open data folder" }).click();
  expect(await page.evaluate(() => window.__E2E__.revealed)).toEqual([revealed[0], null]);
});

test("the editor's runners have a home, and say whether they can be found", async ({ page }) => {
  // Phase 20.6. Both runners were environment-variable-only, which the handoff named as one of
  // three reasons Phase 20 could not be called complete: an undiscoverable feature is one nobody
  // has, and the owner of this product does not launch apps from a shell with an env prefix.
  await page.goto("/?view=settings");
  await expect(page.getByRole("heading", { name: "Editor runners" })).toBeVisible({
    timeout: 30_000,
  });

  // A fresh install has none, and says so rather than showing an empty box with no explanation.
  await expect(page.getByTestId("runner-status-python_lsp")).toHaveText(/not configured/);
  await expect(page.getByTestId("runner-status-local_model")).toHaveText(/not configured/);

  // Typing a command that does not exist is reported as such — "I typed it and nothing happened"
  // is exactly the failure this surface exists to prevent.
  await page.getByTestId("runner-python_lsp").fill("definitely-not-a-real-binary-xyz --stdio");
  await page.getByTestId("save-runners").click();
  await expect(page.getByTestId("runner-status-python_lsp")).toHaveText(
    /not found on this machine/,
  );

  // ...and one that does exist is reported found.
  await page.getByTestId("runner-python_lsp").fill("/bin/sh -c true");
  await page.getByTestId("save-runners").click();
  await expect(page.getByTestId("runner-status-python_lsp")).toHaveText(/found: \/bin\/sh -c true/);

  // The value survives a reload, because a setting that does not persist is not a setting.
  await page.reload();
  await expect(page.getByTestId("runner-python_lsp")).toHaveValue("/bin/sh -c true");
});
