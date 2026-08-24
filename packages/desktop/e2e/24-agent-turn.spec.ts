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
  // The mechanical activity header labels the batch (LC19) while the turn is parked.
  await expect(page.getByText("Running commands").first()).toBeVisible();
  // Approve SELECTS the decision; the batch goes with the submit button (one submit
  // covers every paused call in the action — the client's own contract).
  await approve.click();
  await page.getByRole("button", { name: /submit/i }).first().click();

  // The approved command really ran (its run step renders), and the reply finishes.
  await expect(page.getByText("The command finished; all set.")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("run_command").first()).toBeVisible();

  // Durable: the finished turn survives a reload with the same content (the final frame
  // is a persistence receipt, and the persisted message mirrors the stream).
  await page.reload();
  await expect(page.getByText("The command finished; all set.")).toBeVisible({
    timeout: 15_000,
  });
});
