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

test("a tool-bearing agent can be built entirely in the UI, repository and all", async ({
  page,
  request,
}) => {
  // ADR-0083. `tempest_repo` was settable over the API and had NO UI, so the capability the
  // owner asked for — "the tempest that i integrated is more of like a tool that the AI will
  // use to accomplish important tasks" — could not be reached from inside the app at all: an
  // agent built here had no repository, and a tool-bearing turn with no repository refuses to
  // start. Spec 24 proves the runtime; this proves a person can get to it.
  const repoReply = await request.post(
    `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}/admin/make-repo`,
  );
  expect(repoReply.ok()).toBeTruthy();
  const { repo } = await repoReply.json();

  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();
  await page.getByPlaceholder("Agent name").fill("Spec 23 tool agent");
  await page
    .getByPlaceholder("The system instructions that the agent uses")
    .fill("Prove what you change.");

  // The field is always present — a persona agent may legitimately have no repository — but
  // it says nothing alarming until tools make one necessary.
  await expect(page.getByTestId("tempest-repo-field")).toBeVisible();
  await expect(page.getByTestId("tempest-repo-missing")).toHaveCount(0);

  // Add a tool that acts on a checkout. NOW the field owes the user a warning, at the moment
  // they are still building rather than at the moment they send their first message (L15.3).
  await page.getByRole("button", { name: "Add tools" }).click();
  const library = page.getByRole("dialog").filter({ hasText: "Tool Library" });
  await library.getByText("Prove", { exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("tempest-repo-missing")).toBeVisible();

  await page.getByTestId("tempest-repo-input").fill(repo);
  await expect(page.getByTestId("tempest-repo-missing")).toHaveCount(0);

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
  await expect(page.getByText(/successfully created/i).first()).toBeVisible();

  // It REACHED THE STORE. The payload composer is a whitelist, so a field the form holds and
  // the composer does not name is dropped silently on the way out — which is exactly what
  // happened before this change and is invisible from the form alone.
  const listed = await request.get("/api/agents");
  expect(listed.status()).toBe(200);
  const rows = (await listed.json()).data as Array<Record<string, unknown>>;
  const created = rows.find((row) => row.name === "Spec 23 tool agent");
  expect(created, "the agent is in the store").toBeTruthy();
  expect(created?.tempest_repo).toBe(repo);
  expect(created?.tools).toContain("prove");

  // …and it comes BACK into the form on edit. `AgentSelect` filters incoming agent fields
  // through the default form values, so a field missing from those defaults renders empty
  // over a stored value and the next save erases it.
  await page.reload();
  await page.getByRole("button", { name: "Agent Builder" }).waitFor();
  if (!(await page.getByPlaceholder("Agent name").isVisible())) {
    await page.getByRole("button", { name: "Agent Builder" }).click();
  }
  await page.getByRole("combobox").first().click();
  await page.getByPlaceholder("Search agents by name").fill("Spec 23 tool");
  await page.getByRole("option", { name: /Spec 23 tool agent/ }).click();
  await expect(page.getByTestId("tempest-repo-input")).toHaveValue(repo);
});

test("the blank slate offers a proof agent, and gets out of the way once used", async ({
  page,
}) => {
  // ADR-0083. A new user's agent list is EMPTY and the tool library has seven entries with no
  // opinion about what to do with them. This is the shortcut to an agent that knows how to use
  // the proof engine — and, just as importantly, it stops offering itself the moment the
  // person has made a decision of their own, so it can never overwrite their work.
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();

  const preset = page.getByTestId("proof-agent-preset");
  await expect(preset).toBeVisible();
  await page.getByTestId("use-proof-agent-preset").click();

  // It filled the two things a person cannot be expected to type…
  await expect(page.getByPlaceholder("Agent name")).toHaveValue("Proof agent");
  const instructions = page.getByPlaceholder("The system instructions that the agent uses");
  await expect(instructions).toContainText("shadow worktree");
  await expect(instructions).toContainText("UNPROVEN");
  // …the proof tools are on the agent…
  await expect(page.getByText("Prove", { exact: true }).first()).toBeVisible();
  // …and the repository is now the one thing standing between this and a working agent, which
  // is exactly what the warning says.
  await expect(page.getByTestId("tempest-repo-missing")).toBeVisible();
  await expect(page.getByTestId("tempest-repo-input")).toHaveValue("");

  // …and the offer withdraws itself rather than sitting there able to clobber the choices.
  await expect(preset).toHaveCount(0);
});

test("the preset never appears over work someone has already started", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();
  await expect(page.getByTestId("proof-agent-preset")).toBeVisible();
  await page.getByPlaceholder("Agent name").fill("My own agent");
  await expect(page.getByTestId("proof-agent-preset")).toHaveCount(0);
});
