/**
 * C5 back half — a tool-bearing agent turn through the REAL UI (LC14/LC16/LC18/LC19).
 *
 * The whole re-target on one screen: an agent built on the boundary-D registry runs a chat
 * turn through `run_task` — the model asks for `run_command`, the turn PARKS on the approval
 * UI (LC18), the human approves, the command runs in the sandbox, the run step and its
 * mechanical activity header render (LC19), and the reply streams to a durable finish. The
 * model is the bridge's scripted non-stream peer; the repository, the shadow worktree, the
 * approval round-trip and the proof are all real (L4).
 */
import { expect, test } from "./fixtures";

const BRIDGE = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;

test("an agent turn parks on approval, runs the tool, and finishes durably", async ({
  page,
  request,
}) => {
  // A real first-party repository for the shadow/proof machinery.
  const repoReply = await request.post(`${BRIDGE}/admin/make-repo`);
  expect(repoReply.ok()).toBeTruthy();
  const { repo } = await repoReply.json();

  // The agent, configured through the same wire the builder uses.
  const created = await request.post("/api/agents", {
    data: {
      provider: "Ollama (local)",
      model: "test-model",
      name: "Spec 24 agent",
      instructions: "Do what is asked.",
      tools: ["read_file", "run_command"],
      tempest_repo: repo,
    },
  });
  expect(created.status()).toBe(200);
  const agent = await created.json();

  // Script the peer: one run_command turn, then a finishing answer.
  await request.post(`${BRIDGE}/admin/chat-peer`, {
    data: {
      script: [
        {
          text: "Running the check now.",
          tool_calls: [{ name: "run_command", arguments: { argv: ["echo", "spec24-ran"] } }],
        },
        { text: "The command finished; all set." },
      ],
    },
  });

  // Select the agent for CHAT through the builder's own Select affordance.
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Builder" }).click();
  await page.getByRole("combobox").first().click();
  await page.getByPlaceholder("Search agents by name").fill("Spec 24");
  await page.getByRole("option", { name: /Spec 24 agent/ }).click();
  await page.getByRole("button", { name: "Select Agent" }).click();

  // The turn: type, send, and PARK on the approval (LC18).
  await page.getByRole("textbox", { name: "Message input" }).fill("Run the check");
  await page.getByRole("button", { name: "Send message" }).click();

  const approve = page.getByRole("button", { name: /approve/i }).first();
  await approve.waitFor({ timeout: 30_000 });
  // Parked: the call the user is being asked about is named on the card itself.
  await expect(page.getByText("run_command").first()).toBeVisible();
  // Approve SELECTS the decision; the batch goes with the submit button (one submit
  // covers every paused call in the action — the client's own contract).
  await approve.click();
  await page.getByRole("button", { name: /submit/i }).first().click();

  await expect(page.getByText("The command finished; all set.")).toBeVisible({
    timeout: 60_000,
  });

  // LC19, as the vendored grouper actually renders it: the mechanical header CLAIMS its
  // batch, so the label and the call it covers are one collapsible group — not a header
  // floating above an unrelated, un-headed card. The label must FOLLOW its calls in the
  // content parts for the grouper to claim them, which is the invariant this asserts from
  // the outside: a `button` whose accessible name is the label and whose body names the call.
  const group = page.getByRole("button", { name: /Running commands/ }).first();
  await expect(group).toBeVisible({ timeout: 30_000 });
  await expect(group).toContainText("run_command");

  // The approved command REALLY RAN. Neither previous witness showed that: the reply text
  // comes from the scripted peer, which advances on the next completion whatever the tool
  // did, and the string "run_command" is put on the wire by `on_run_step` — emitted from
  // ToolCallStarted, BEFORE the dispatch — so both were already true of a turn whose
  // approved call was dropped instead of run. The command's own OUTPUT is the only witness
  // that cannot be produced without executing it, and it lives inside the group.
  await group.click();
  // The card also says, in its own words, that the call RAN rather than that it was
  // cancelled — the phase the vendored renderer derives from `progress`. A finished call
  // that omits the field resolves to 'cancelled' and is announced that way to a screen
  // reader, so this is the accessible-name assertion, not decoration.
  const card = page.getByRole("button", { name: /Ran run_command/ }).first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.click();
  await expect(page.getByText(/spec24-ran/).first()).toBeVisible({ timeout: 30_000 });

  // Durable: the finished turn survives a reload with the same content (the final frame
  // is a persistence receipt, and the persisted message mirrors the stream).
  await page.reload();
  await expect(page.getByText("The command finished; all set.")).toBeVisible({
    timeout: 15_000,
  });
});
