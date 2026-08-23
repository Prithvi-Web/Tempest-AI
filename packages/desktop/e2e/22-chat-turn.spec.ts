/**
 * The C5 headline, end to end: typing a message in the REAL vendored chat surface produces a
 * REAL streamed answer — the engine's turn service streams from a genuine OpenAI-wire peer
 * (the bridge's, reached exactly as a local runner would be), frames ride the ledger, the
 * harness serves them as REAL SSE, and the untouched client renders them. No mocks anywhere
 * on the path (L4): what these specs watch is the same protocol the app ships, on the sse.js
 * transport leg; the boundary-B leg is pinned by the vitest state-machine suite and the
 * installed-app demo.
 */
import { expect, test } from "./fixtures";

const BRIDGE_URL = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;

async function armPeer(body: Record<string, unknown>): Promise<void> {
  const reply = await fetch(`${BRIDGE_URL}/admin/chat-peer`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!reply.ok) throw new Error(`chat-peer arm failed: ${reply.status}`);
}

async function resumePeer(): Promise<void> {
  await fetch(`${BRIDGE_URL}/admin/chat-peer/resume`, { method: "POST" });
}

async function peerState(): Promise<{ closedEarly: boolean; requests: unknown[] }> {
  const reply = await fetch(`${BRIDGE_URL}/admin/chat-peer/state`);
  return (await reply.json()) as { closedEarly: boolean; requests: unknown[] };
}

/** Select the keyless local endpoint the peer answers for. */
async function pickOllama(page: import("@playwright/test").Page): Promise<void> {
  await page.getByTestId("model-selector-button").click();
  await page.getByText("Ollama (local)", { exact: true }).first().click();
  const model = page.getByText("test-model", { exact: true }).first();
  if (await model.isVisible().catch(() => false)) {
    await model.click();
  }
  // The trigger renders the MODEL name once one is chosen.
  await expect(page.getByTestId("model-selector-button")).toContainText("test-model");
}

async function send(page: import("@playwright/test").Page, text: string): Promise<void> {
  await page.getByTestId("text-input").click();
  await page.getByTestId("text-input").fill(text);
  await page.getByTestId("send-button").click();
}

test("a typed message becomes a live streamed answer, and the turn survives a reload", async ({
  page,
}) => {
  await armPeer({ chunks: ["The answer ", "streams ", "in pieces."] });
  await page.goto("/");
  await pickOllama(page);
  await send(page, "Stream me an answer");

  // The user's own message renders, then the assistant's reply arrives streamed.
  await expect(page.getByText("Stream me an answer").first()).toBeVisible();
  await expect(page.getByText("The answer streams in pieces.").first()).toBeVisible({
    timeout: 20_000,
  });

  // The final frame is a persistence receipt: a full reload rebuilds the conversation from
  // the durable store — the rail lists it, both bubbles return.
  await page.reload();
  await expect(page.getByText("Stream me an answer").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("The answer streams in pieces.").first()).toBeVisible();
});

test("tokens are visible MID-turn — streaming is streaming, not a buffered dump", async ({
  page,
}) => {
  await armPeer({ chunks: ["First light. ", "Then the rest."], holdAfterFirst: true });
  await page.goto("/");
  await pickOllama(page);
  await send(page, "Hold after the first chunk");

  // The peer is holding after chunk one — what is on screen NOW proves live delivery.
  await expect(page.getByText("First light.").first()).toBeVisible({ timeout: 20_000 });
  const finished = page.getByText("First light. Then the rest.");
  expect(await finished.count()).toBe(0);

  await resumePeer();
  await expect(page.getByText("First light. Then the rest.").first()).toBeVisible({
    timeout: 20_000,
  });
});

test("stop mid-stream keeps the partial reply and really hangs up the provider", async ({
  page,
}) => {
  // Two staged holds: after chunk 0 (where the stop lands) and after chunk 1 (whose
  // release writes into a socket the engine tore down seconds earlier — the deterministic
  // observation of the hangup, not a buffer race).
  await armPeer({
    chunks: ["Partial thought ", ...Array.from({ length: 200 }, (_, i) => `chunk${i} `)],
    holds: [0, 1],
  });
  await page.goto("/");
  await pickOllama(page);
  await send(page, "Talk forever");
  await expect(page.getByText("Partial thought").first()).toBeVisible({ timeout: 20_000 });

  await page.getByTestId("stop-generation-button").click();
  await resumePeer(); // chunk 1 flows: the engine's parked read observes the cancel and closes

  // The stop control yields on the abort ACK; the ENGINE settles when the torn-down stream
  // unwinds. The status endpoint is the settlement barrier (the same contract the reload
  // path reads) — polling it is deterministic where a UI signal would be a race (trap 61).
  await expect(page.getByTestId("stop-generation-button")).toBeHidden({ timeout: 15_000 });
  const conversationId = page.url().split("/c/")[1] ?? "";
  await expect
    .poll(
      async () => {
        const reply = await fetch(
          `http://localhost:${process.env.E2E_PLATFORM_PORT ?? 4180}/api/agents/chat/status/${conversationId}`,
        );
        return ((await reply.json()) as { active: boolean }).active;
      },
      { timeout: 15_000, message: "the aborted turn must settle engine-side" },
    )
    .toBe(false);

  // The partial reply STAYS — an aborted turn is honest, not blank.
  await expect(page.getByText("Partial thought").first()).toBeVisible({ timeout: 15_000 });

  // The engine settled seconds ago; releasing the second hold writes into the socket it
  // closed — the observation that the provider really stopped being paid.
  await resumePeer();
  await expect
    .poll(async () => (await peerState()).closedEarly, {
      timeout: 15_000,
      message: "the upstream connection must actually die",
    })
    .toBe(true);

  // And the conversation is idle again: a fresh send works on the same thread.
  await armPeer({ chunks: ["Recovered."] });
  await send(page, "And now?");
  await expect(page.getByText("Recovered.").first()).toBeVisible({ timeout: 20_000 });
});

test("the second turn carries the first as context, root first", async ({ page }) => {
  await armPeer({ chunks: ["Turn one answer."] });
  await page.goto("/");
  await pickOllama(page);
  await send(page, "Question one");
  await expect(page.getByText("Turn one answer.").first()).toBeVisible({ timeout: 20_000 });

  await armPeer({ chunks: ["Turn two answer."] });
  await send(page, "Question two");
  await expect(page.getByText("Turn two answer.").first()).toBeVisible({ timeout: 20_000 });

  const state = await peerState();
  const last = state.requests.at(-1) as { messages: { role: string; content: string }[] };
  expect(last.messages.map((m) => [m.role, m.content])).toEqual([
    ["user", "Question one"],
    ["assistant", "Turn one answer."],
    ["user", "Question two"],
  ]);
});
