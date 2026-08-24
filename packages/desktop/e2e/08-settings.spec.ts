/**
 * The app's ONE settings home (ADR-0082) — every Tempest setting, in the dialog every other
 * setting already lived in.
 *
 * This spec used to drive `/tempest/settings`, a second settings page inside the proof
 * surface. The owner's requirement ended that: *"i want the settings of the tempest tool and
 * the Tempest AI to also be fully integrated into one spot."* What is pinned here is that the
 * move kept every behaviour — the key round trip, the persisted document, the runner
 * discovery, the diagnostic bundle — and that all three doors into the home really open it.
 *
 * The UI is driven for real; the keychain itself is the Rust host's job and is stood in for by
 * the shim with the exact same validation semantics (see shim.js) — the real storage,
 * idempotent clear, and spawn-env injection are proven by cargo tests in src-tauri.
 *
 * The planted key is letter-segmented fiction (trap 19) — the same fixture the redaction gate
 * proves gets scrubbed from every outbound surface (24/24).
 */
import { expect, test } from "./fixtures";
import {
  closeSettings,
  openModelsFromRail,
  openProofEngineSettings,
  openSettingsFromAccountMenu,
  selectSettingsTab,
  settingsPanel,
} from "./settings-home";

const PLANTED_KEY = "sk-ant-api03-PLANTED-FAKE-TEMPEST-KEYFIXTURE-AAAABBBBCCCC";

test("all three doors reach ONE home, and each lands where it promised", async ({ page }) => {
  await page.goto("/");

  // The rail's Models entry: local models AND provider keys, in one tab.
  const fromRail = await openModelsFromRail(page);
  await expect(fromRail.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(fromRail.getByRole("tab", { name: "Models", selected: true })).toBeVisible();
  await expect(fromRail.getByRole("heading", { name: "Local models" })).toBeVisible();
  await expect(fromRail.getByRole("heading", { name: "Provider keys" })).toBeVisible();
  await closeSettings(page);

  // Upstream's own door still lands on General — the move added tabs, it did not move theirs.
  const fromMenu = await openSettingsFromAccountMenu(page);
  await expect(fromMenu.getByRole("tab", { name: "General", selected: true })).toBeVisible();
  await closeSettings(page);

  // And the proof surface's deep link opens the engine tab over the runs list — one home,
  // more than one door, and never a second settings page.
  const fromDeepLink = await openProofEngineSettings(page);
  await expect(
    fromDeepLink.getByRole("tab", { name: "Proof engine", selected: true }),
  ).toBeVisible();
  await expect(fromDeepLink.getByRole("heading", { name: "Evidence storage" })).toBeVisible();
  await closeSettings(page);
  await expect(page).toHaveURL(/\/tempest$/);
});

test("the proof surface's own rail opens the one home rather than a second page", async ({
  page,
}) => {
  await page.goto("/tempest");
  await page.getByTestId("tempest-open-settings").click();
  const panel = settingsPanel(page);
  await expect(panel.getByRole("tab", { name: "Proof engine", selected: true })).toBeVisible();
  // The proof surface is still behind it — the user never left the runs list.
  await closeSettings(page);
  await expect(page.locator(".tempest-views")).toBeVisible();
});

test("the engine key has a clear home: reject junk, save, recognize, remove", async ({ page }) => {
  await page.goto("/");
  const panel = await openModelsFromRail(page);
  const field = panel.getByRole("textbox", { name: "Anthropic API key for the proof engine" });

  // A paste accident is rejected with the host's actionable message — nothing is stored.
  await field.fill("https://console.anthropic.com/keys");
  await panel.getByRole("button", { name: "Save key" }).click();
  await expect(panel.getByText(/does not look like an Anthropic API key/)).toBeVisible();
  await expect(field).toBeVisible(); // still unconfigured

  // A real-shaped key saves; the page then knows ONLY {configured, last4} (L9).
  await field.fill(PLANTED_KEY);
  await panel.getByRole("button", { name: "Save key" }).click();
  await expect(panel.getByText("Key configured")).toBeVisible();
  await expect(panel.getByText(`ends in ${PLANTED_KEY.slice(-4)}`)).toBeVisible();
  await expect(field).toHaveCount(0); // the secret field is gone

  // The status survives closing and reopening the home (it is host state, not page state).
  await closeSettings(page);
  const again = await openModelsFromRail(page);
  await expect(again.getByText("Key configured")).toBeVisible();

  // Removing returns to the unconfigured state.
  await again.getByRole("button", { name: "Remove key" }).click();
  await expect(
    again.getByRole("textbox", { name: "Anthropic API key for the proof engine" }),
  ).toBeVisible();
  await expect(again.getByText("Key configured")).toHaveCount(0);
});

test("the key can be tested live, and the answer is stated plainly", async ({ page }) => {
  await page.goto("/");
  const panel = await openModelsFromRail(page);
  await panel
    .getByRole("textbox", { name: "Anthropic API key for the proof engine" })
    .fill(PLANTED_KEY);
  await panel.getByRole("button", { name: "Save key" }).click();
  await expect(panel.getByText("Key configured")).toBeVisible();

  // The engine has no key in ITS environment (the shim's keychain stand-in cannot inject one
  // into an already-running sidecar — the real host injects at spawn), so the honest answer
  // is the keyless one. What this pins is the whole round trip: button → host → engine →
  // rendered sentence, with nothing invented in between.
  await panel.getByRole("button", { name: "Test key" }).click();
  await expect(panel.getByText(/no API key is configured/)).toBeVisible();
});

test("sync, storage and privacy show REAL configuration and persist it", async ({
  page,
  bridge,
}) => {
  const info = await bridge.info();
  const panel = await openProofEngineSettings(page);

  // Storage states the truth about this machine: the engine's own data dir, live usage.
  await expect(panel.getByRole("heading", { name: "Evidence storage" })).toBeVisible();
  await expect(panel.getByText(info.dataDir, { exact: false })).toBeVisible();
  await expect(panel.getByTestId("budget-value")).toHaveText("unlimited");

  // Privacy: telemetry is off until the user says otherwise, and saying so sticks.
  const telemetry = panel.getByRole("switch", { name: "Share anonymous usage counters" });
  await expect(telemetry).not.toBeChecked();
  await telemetry.check();
  await expect(telemetry).toBeChecked();

  // Sync: a server URL and the source-sharing default (off — the privacy posture).
  const shareSource = panel.getByRole("switch", {
    name: "Include source code in pushed bundles",
  });
  await expect(shareSource).not.toBeChecked();
  await panel.getByRole("textbox", { name: "Team server URL" }).fill("https://team.example.com");
  await panel.getByRole("textbox", { name: "Team server URL" }).blur();
  await expect(panel.getByRole("button", { name: "Push now" })).toBeEnabled();

  // Everything above is one document in the engine — a full reload proves it was persisted,
  // not held in React state.
  const reopened = await openProofEngineSettings(page);
  await expect(reopened.getByRole("switch", { name: "Share anonymous usage counters" })).toBeChecked();
  await expect(reopened.getByRole("textbox", { name: "Team server URL" })).toHaveValue(
    "https://team.example.com",
  );

  // …and turning it back off persists too (the toggle is not one-way).
  await reopened.getByRole("switch", { name: "Share anonymous usage counters" }).uncheck();
  const third = await openProofEngineSettings(page);
  await expect(
    third.getByRole("switch", { name: "Share anonymous usage counters" }),
  ).not.toBeChecked();
});

test("a bundle budget can be set, and it is stated in human units", async ({ page }) => {
  const panel = await openProofEngineSettings(page);
  await expect(panel.getByTestId("budget-value")).toHaveText("unlimited");
  // Slider index 1 is the first real budget (100 MB) — set it by keyboard, the way a
  // keyboard-only user would.
  const slider = panel.getByRole("slider", { name: "Bundle budget" });
  await slider.focus();
  await slider.press("ArrowRight");
  await expect(panel.getByTestId("budget-value")).toHaveText("100.0 MB");
  const reopened = await openProofEngineSettings(page);
  await expect(reopened.getByTestId("budget-value")).toHaveText("100.0 MB");
});

test("a diagnostic bundle is written locally, described, and revealable by bare name", async ({
  page,
}) => {
  const panel = await openProofEngineSettings(page);
  await panel.getByRole("button", { name: "Export diagnostic bundle" }).click();
  await expect(panel.getByText(/^Wrote tempest-diagnostic-.*\.zip$/)).toBeVisible();
  await expect(panel.getByText(/REVIEW EVERY FILE BEFORE SENDING/)).toBeVisible();

  await panel.getByRole("button", { name: "Show in Finder" }).click();
  const revealed = await page.evaluate(() => window.__E2E__.revealed);
  expect(revealed).toHaveLength(1);
  // The UI may only ever name a leaf inside the data folder — never a path (commands.rs).
  expect(revealed[0]).toMatch(/^tempest-diagnostic-[0-9T]+\.zip$/);

  await panel.getByRole("button", { name: "Open data folder" }).click();
  expect(await page.evaluate(() => window.__E2E__.revealed)).toEqual([revealed[0], null]);
});

test("the editor's runners have a home, and say whether they can be found", async ({ page }) => {
  // Phase 20.6. All three runners were environment-variable-only, which the handoff named as
  // one of three reasons Phase 20 could not be called complete: an undiscoverable feature is
  // one nobody has, and the owner of this product does not launch apps from a shell with an
  // env prefix.
  const panel = await openProofEngineSettings(page);
  await expect(panel.getByRole("heading", { name: "Editor runners" })).toBeVisible({
    timeout: 30_000,
  });

  // A fresh install has none, and says so rather than showing an empty box with no explanation.
  await expect(panel.getByTestId("runner-status-python_lsp")).toHaveText(/not configured/);
  await expect(panel.getByTestId("runner-status-local_model")).toHaveText(/not configured/);

  // Typing a command that does not exist is reported as such — "I typed it and nothing
  // happened" is exactly the failure this surface exists to prevent.
  await panel.getByTestId("runner-python_lsp").fill("definitely-not-a-real-binary-xyz --stdio");
  await panel.getByTestId("save-runners").click();
  await expect(panel.getByTestId("runner-status-python_lsp")).toHaveText(
    /not found on this machine/,
  );

  // ...and one that does exist is reported found.
  await panel.getByTestId("runner-python_lsp").fill("/bin/sh -c true");
  await panel.getByTestId("save-runners").click();
  await expect(panel.getByTestId("runner-status-python_lsp")).toHaveText(/found: \/bin\/sh -c true/);

  // The value survives a reload, because a setting that does not persist is not a setting.
  const reopened = await openProofEngineSettings(page);
  await expect(reopened.getByTestId("runner-python_lsp")).toHaveValue("/bin/sh -c true");
});

test("settings are SEARCHABLE across both halves of the product, from one box", async ({
  page,
}) => {
  // The strongest single argument for one home over two: a person who types "model" finds the
  // local models AND the provider keys AND the theme, without knowing which half of the app
  // owns which. Two settings pages cannot do this at any price.
  await page.goto("/");
  const panel = await openSettingsFromAccountMenu(page);
  const search = panel.getByRole("textbox", { name: /search/i });
  await search.fill("local model");
  await expect(panel.getByText("Models ›", { exact: false })).toBeVisible();
  await expect(panel.getByTestId("model-qwen3-0.6b-q8")).toBeVisible();

  await search.fill("diagnostic");
  await expect(panel.getByRole("button", { name: "Export diagnostic bundle" })).toBeVisible();
  await expect(panel.getByText("Proof engine ›", { exact: false })).toBeVisible();
});
