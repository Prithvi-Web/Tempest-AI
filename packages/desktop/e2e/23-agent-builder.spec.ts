/**
 * C5 back half — the no-code agent builder over the host seam (LC08/LC09, ADR-0075).
 *
 * The vendored builder UI is adopted whole; what these specs pin is the RE-TARGET: the
 * `agents` endpoint key mounting the surface at all, the Tool Library rendering exactly the
 * boundary-D registry (runtime_check's single source, here proven at the glass), and an
 * agent created through the real UI persisting in the platform store and coming back
 * EDITABLE after a reload — the first boot of this surface failed exactly there, with the
 * ACL probe unanswered and the owner locked out of their own agent ("Agent Not Available").
 */
import { expect, test } from "./fixtures";

/** The seven boundary-D tools, by the display names the picker derives from the manifest. */
const REGISTRY = [
  "Read file",
  "List dir",
  "Search text",
  "Write file",
  "Run command",
  "Prove",
  "Ask user",
];

test("the tool library is the boundary-D registry, rendered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();
  await page.getByRole("button", { name: "Add tools" }).click();

  const dialog = page.getByRole("dialog").filter({ hasText: "Tool Library" });
  await expect(dialog).toBeVisible();
  for (const name of REGISTRY) {
    await expect(dialog.getByText(name, { exact: true })).toBeVisible();
  }
  // The descriptions are the manifest's own sentences, not UI copy: the shadow-worktree
  // wording exists nowhere in the vendored client, only in agent_tools.rs.
  await expect(dialog.getByText(/shadow worktree/i).first()).toBeVisible();
  await page.keyboard.press("Escape");
});

test("an agent created in the builder persists and reloads editable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();

  await page.getByPlaceholder("Agent name").fill("Spec agent 23");
  await page.getByPlaceholder("The system instructions that the agent uses").fill("Be terse.");

  // The model sub-panel: provider then model, then back. The pickers are search+listbox.
  await page.getByRole("button", { name: "Select a model" }).first().click();
  await page.getByRole("button", { name: "Back to builder" }).waitFor();
  const combos = page.getByRole("combobox");
  await combos.nth(1).click();
  await page.getByPlaceholder("Search provider by name").waitFor();
  await page.getByRole("option", { name: "Ollama (local)" }).click();
  await combos.nth(2).click();
  await page.getByRole("option", { name: "test-model" }).click();
  await page.getByRole("button", { name: "Back to builder" }).click();

  await page.getByRole("button", { name: "Create", exact: true }).click();
  // .first(): the toast renders its text twice (visible chip + aria-live announcement).
  await expect(page.getByText(/successfully created/i).first()).toBeVisible();

  // Reload: the agent must come back from the STORE, into an EDITABLE panel. The panel
  // remembers being open across reloads, so the nav click happens only when it is not —
  // clicking unconditionally TOGGLES an open panel shut.
  await page.reload();
  await page.getByRole("button", { name: "Agent Builder" }).waitFor();
  if (!(await page.getByPlaceholder("Agent name").isVisible())) {
    await page.getByRole("button", { name: "Agent Builder" }).click();
  }
  await page.getByRole("combobox").first().click();
  await page.getByPlaceholder("Search agents by name").fill("Spec agent");
  await page.getByRole("option", { name: /Spec agent 23/ }).click();

  // The edit-gate pin: a permission failure renders "Agent Not Available" with no form at
  // all, so the name field carrying its value IS the assertion that the local principal
  // owns what it created.
  await expect(page.getByPlaceholder("Agent name")).toHaveValue("Spec agent 23");
  await expect(page.getByText("Agent Not Available")).toHaveCount(0);
});
