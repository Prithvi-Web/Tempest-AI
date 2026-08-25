/**
 * Local models, through the REAL panel (ADR-0080, T36).
 *
 * The one question unit tests cannot answer: does pressing Download in the settings panel move
 * a real progress bar and end with a real file? That crosses the engine's downloader, boundary
 * A, the host command, boundary B, react-query's poll, and the panel's own states — and every
 * one of those was green while the whole path was untested.
 *
 * Nothing on the path is mocked (L4). The bytes come from the bridge's model-file peer over
 * real HTTP with real `Range:` support; the engine's e2e catalogue row carries the real sha256
 * of those bytes, so the download's verification is fully live — a peer that served anything
 * else would fail the hash, not the test. The one stand-in is the model SERVER, which is a
 * child of the Rust host this browser harness replaces; it answers what the real command
 * answers on a machine with no `llama-server`, and serving is pinned in Rust where it lives.
 *
 * **A real model is never downloaded.** The catalogue's four rows point at huggingface.co and
 * are gigabytes; the row this drives is the loopback one, gated on TEMPEST_DEV plus an
 * explicit loopback base, and the engine refuses that variable if it names anything else.
 */
import { expect, test } from "./fixtures";
import { closeSettings, openModelsFromRail, settingsPanel } from "./settings-home";

const BRIDGE_URL = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;
const ROW = "tempest-e2e-tiny";

/** Arm the model-file peer: how many pieces the body arrives in, and the pause between them. */
async function armPeer(body: { chunks?: number; delayMs?: number }): Promise<void> {
  const reply = await fetch(`${BRIDGE_URL}/admin/hf-peer`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!reply.ok) throw new Error(`hf-peer arm failed: ${reply.status}`);
}

async function peerState(): Promise<{ requests: { range: string | null }[]; bytes: number }> {
  const reply = await fetch(`${BRIDGE_URL}/admin/hf-peer/state`);
  return (await reply.json()) as { requests: { range: string | null }[]; bytes: number };
}

/** The percentage the panel is currently showing for the row, or null when it shows none. */
async function shownPercent(page: import("@playwright/test").Page): Promise<number | null> {
  const progress = page.getByTestId(`progress-${ROW}`);
  if (!(await progress.isVisible().catch(() => false))) return null;
  const text = (await progress.textContent()) ?? "";
  const found = /(\d+)%/.exec(text);
  return found ? Number(found[1]) : null;
}

test("the cost is on screen before the spend, and the catalogue is real", async ({ page }) => {
  await page.goto("/");
  const panel = await openModelsFromRail(page);
  await expect(panel.getByRole("heading", { name: "Local models" })).toBeVisible();

  // L21, applied to disk: the size, the licence and the free space are all on screen BEFORE
  // any button, because gigabytes are a cost.
  const row = page.getByTestId(`model-${ROW}`);
  await expect(row).toBeVisible();
  await expect(row).toContainText("apache-2.0");
  await expect(row).toContainText("GB");
  await expect(page.getByTestId(`download-${ROW}`)).toBeEnabled();

  // The shipped rows are here too, and they are the real catalogue — not a fixture.
  await expect(page.getByTestId("model-qwen3-0.6b-q8")).toBeVisible();
  await expect(page.getByTestId("model-phi-4-mini-q4")).toContainText("mit");

  // ADR-0080 §6's honest refusal: no runner on this machine, said BEFORE anyone clicks Serve.
  await expect(page.getByTestId("runner-missing")).toContainText("brew install llama.cpp");
  await expect(page.getByTestId("models-unavailable")).toHaveCount(0);
});

test("pressing Download moves a real progress bar and ends with a verified file", async ({
  page,
}) => {
  // Twenty-four pieces a fifth of a second apart: about five seconds of transfer, so the
  // panel's 500 ms poll has roughly ten chances to show a number. The producer is the slow
  // one on purpose — loopback would otherwise deliver the whole body before the page could
  // react, and the test would be racing the network stack rather than watching a poll.
  await armPeer({ chunks: 24, delayMs: 200 });
  await page.goto("/");
  await openModelsFromRail(page);

  const before = await peerState();
  expect(before.requests).toHaveLength(0);

  await page.getByTestId(`download-${ROW}`).click();

  // Progress appears...
  await expect(page.getByTestId(`progress-${ROW}`)).toBeVisible({ timeout: 15_000 });
  const first = await shownPercent(page);
  expect(first).not.toBeNull();

  // ...and MOVES. This is the assertion the whole spec exists for: it is the only thing that
  // can tell a working poll from a panel frozen at 0%, and the poll is a `refetchInterval`
  // that turns itself on when a download appears in the data. If it never started, this waits
  // out its timeout with the number unchanged.
  await expect
    .poll(async () => (await shownPercent(page)) ?? -1, {
      message: "the download percentage never advanced — the catalogue poll did not run",
      timeout: 20_000,
    })
    .toBeGreaterThan(first ?? 0);

  // The row settles as installed, and the file on disk is the one the row records: the engine
  // verified its sha256 before promoting it, so "installed" here means "hashed and matched".
  await expect(page.getByTestId(`installed-${ROW}`)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId(`progress-${ROW}`)).toHaveCount(0);
  await expect(page.getByTestId(`download-${ROW}`)).toHaveCount(0);
  await expect(page.getByTestId(`stray-${ROW}`)).toHaveCount(0);

  // Serve is offered but refused, honestly, for the one reason that is true here.
  await expect(page.getByTestId(`serve-${ROW}`)).toBeDisabled();

  const after = await peerState();
  expect(after.requests.length).toBeGreaterThanOrEqual(1);
  const firstRequest = after.requests.at(0);
  expect(firstRequest?.range).toBeNull(); // a fresh download asks for the whole file

  // It survives a reload, because it is a file and not a piece of React state. (A reload
  // closes the dialog with the rest of the page, so the home is reopened — which also proves
  // the rail entry works from a cold load.)
  await page.reload();
  await openModelsFromRail(page);
  await expect(page.getByTestId(`installed-${ROW}`)).toBeVisible();
});

test("Remove frees the space and the row offers the download again", async ({ page }) => {
  await page.goto("/");
  await openModelsFromRail(page);
  // The previous test installed it; if this spec is run alone, install it here.
  if ((await page.getByTestId(`download-${ROW}`).count()) > 0) {
    await armPeer({ chunks: 1, delayMs: 0 });
    await page.getByTestId(`download-${ROW}`).click();
    await expect(page.getByTestId(`installed-${ROW}`)).toBeVisible({ timeout: 30_000 });
  }

  await page.getByTestId(`remove-${ROW}`).click();
  await expect(page.getByTestId(`download-${ROW}`)).toBeVisible();
  await expect(page.getByTestId(`installed-${ROW}`)).toHaveCount(0);
  await expect(page.getByTestId(`paused-${ROW}`)).toHaveCount(0);
  // Deletion exists in the first version because a feature that can fill a disk and not empty
  // it is not finished (ADR-0080 §3), and the panel is where a person can reach it.
  await expect(page.getByTestId(`remove-${ROW}`)).toHaveCount(0);
});

test("stopping a download keeps what arrived, and resuming asks only for the rest", async ({
  page,
}) => {
  // Slow enough that Stop lands mid-body rather than racing the last chunk.
  await armPeer({ chunks: 30, delayMs: 250 });
  await page.goto("/");
  await openModelsFromRail(page);
  if ((await page.getByTestId(`remove-${ROW}`).count()) > 0) {
    await page.getByTestId(`remove-${ROW}`).click();
    await expect(page.getByTestId(`download-${ROW}`)).toBeVisible();
  }

  await page.getByTestId(`download-${ROW}`).click();
  await expect(page.getByTestId(`progress-${ROW}`)).toBeVisible({ timeout: 15_000 });
  // Wait for real bytes before stopping: a cancel before the first chunk keeps no partial, and
  // this spec is about the partial.
  await expect
    .poll(async () => (await shownPercent(page)) ?? -1, { timeout: 20_000 })
    .toBeGreaterThan(0);
  await page.getByTestId(`stop-${ROW}`).click();

  // The partial is kept and NAMED — that is the whole reason `Range:` resume is worth having,
  // and until this panel showed it, a stopped download was gigabytes with no UI that could
  // mention them, let alone free them.
  await expect(page.getByTestId(`paused-${ROW}`)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId(`paused-${ROW}`)).toContainText("already downloaded");
  await expect(page.getByTestId(`download-${ROW}`)).toContainText("Resume download");
  // And it can be thrown away from here, which `installed`-only Remove made impossible.
  await expect(page.getByTestId(`remove-${ROW}`)).toBeVisible();

  await armPeer({ chunks: 1, delayMs: 0 });
  const beforeResume = (await peerState()).requests.length;
  await page.getByTestId(`download-${ROW}`).click();
  await expect(page.getByTestId(`installed-${ROW}`)).toBeVisible({ timeout: 30_000 });

  const requests = (await peerState()).requests;
  expect(requests.length).toBeGreaterThan(beforeResume);
  const resumed = requests.at(-1)?.range ?? "";
  expect(resumed).toMatch(/^bytes=\d+-$/);
  // The resumed request asked to start somewhere past zero — it continued rather than
  // restarting, which is the difference the partial exists to make.
  const askedFrom = Number(/^bytes=(\d+)-$/.exec(resumed)?.[1] ?? "0");
  expect(askedFrom).toBeGreaterThan(0);
});

test("a keyless turn offers the local-model way out, and it goes to the panel", async ({
  page,
}) => {
  // ADR-0080 §8. The contract half of this shipped with no consumer: the engine has carried
  // `remedy: "local-model"` on the error part since the feature landed and nothing read it,
  // so a user told "no API key" was not told the thing that makes this app different.
  //
  // The engine genuinely has no Anthropic key — the bridge strips every `*_API_KEY` from the
  // sidecar's environment, so this is the real keyless path and not a scripted one, and the
  // suite cannot bill anybody even on a machine where the developer exports one.
  await page.goto("/");
  await page.getByTestId("model-selector-button").click();
  await page.getByText("Anthropic", { exact: true }).first().click();

  await page.getByTestId("text-input").click();
  await page.getByTestId("text-input").fill("Say something without a key");
  await page.getByTestId("send-button").click();

  await expect(page.getByText(/no API key/i).first()).toBeVisible({ timeout: 30_000 });
  const remedy = page.getByTestId("local-model-remedy");
  await expect(remedy).toBeVisible();
  await expect(remedy).toContainText("no key needed");

  // And it is real, not decoration: it opens the panel that solves the problem — OVER the
  // conversation (ADR-0082). It used to navigate to `/tempest/settings`, which took a person
  // who had just been told "no API key" out of the message they were reading.
  await page.getByTestId("local-model-remedy-link").click();
  const panel = settingsPanel(page);
  await expect(panel.getByRole("heading", { name: "Local models" })).toBeVisible();
  await expect(panel.getByTestId(`model-${ROW}`)).toBeVisible();
  await expect(page.getByTestId("local-model-remedy")).toBeVisible(); // still in the chat behind
});

/** Arm the bridge's local-discovery peer: the model ids a running `llama-server` would report
 * from `GET /v1/models` — which are FILE PATHS, the shape ADR-0085's naming fix turns into
 * names on the way to the picker. An empty list is a machine with nothing serving. */
/** Open the model picker and search it, the way a person does.
 *
 * The search control is a `combobox` that the picker AUTO-FOCUSES on open, and the visible
 * "Search models…" is a sibling label rather than a placeholder attribute — so
 * `getByPlaceholder` waits for an element that does not exist, and the test times out on the
 * fill rather than on anything it is about. Typing at the keyboard is both correct and what
 * the user actually does.
 */
async function searchModels(page: import("@playwright/test").Page, text: string) {
  await page.getByTestId("model-selector-button").click();
  await expect(page.getByRole("combobox").first()).toBeFocused();
  await page.keyboard.type(text);
  return page.getByRole("option", { name: new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) });
}

async function armLocalPeer(models: string[]): Promise<void> {
  const reply = await fetch(`${BRIDGE_URL}/admin/local-peer`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ models }),
  });
  if (!reply.ok) throw new Error(`local-peer arm failed: ${reply.status}`);
}

test("serving a model makes it PICKABLE, without a reload", async ({ page }) => {
  // ADR-0085, found by pressing Serve in the real shipped app.
  //
  // The client's `[endpoints]` and `[models]` queries are both `staleTime: Infinity,
  // refetchOnMount: false` — read once at boot and never again. The model server is off by
  // default and starts only when a person asks, so the model world is always fetched BEFORE
  // any local model exists. Serving one therefore left the picker exactly as empty as it was
  // at launch, and the chat header read "default" instead of naming the model. Quitting and
  // relaunching does not help: the server is a child of the app and dies with it, so the next
  // boot probes an empty port again. Without this the local model could never be chosen by
  // name at all.
  //
  // What is real here and what stands in, stated: the ENGINE's discovery is real, against the
  // bridge's real loopback `/v1/models` peer over real HTTP. Only the HOST's answer to
  // "did the server start" is the harness's, because starting a real child is Rust's job and
  // is pinned there (shim.js says so at the branch).
  const gguf =
    "/Users/someone/Library/Application Support/com.prithvi.tempest/models/x/Qwen3-0.6B-Q8_0.gguf";
  await armLocalPeer([]);
  await page.goto("/");

  // Before: nothing is served, so the picker offers no local model — and says so by having
  // no result for it rather than by rendering an empty row.
  await expect(await searchModels(page, "Qwen3-0.6B")).toHaveCount(0);
  await page.keyboard.press("Escape");

  // A server comes up, and the user presses Serve in the one settings home.
  await armLocalPeer([gguf]);
  const panel = await openModelsFromRail(page);
  const serve = panel.getByTestId(`serve-${ROW}`);
  if ((await serve.count()) === 0) {
    // This spec can run alone; install the loopback row first if an earlier one did not.
    await armPeer({ chunks: 1, delayMs: 0 });
    await panel.getByTestId(`download-${ROW}`).click();
    await expect(panel.getByTestId(`installed-${ROW}`)).toBeVisible({ timeout: 30_000 });
  }
  await panel.getByTestId(`serve-${ROW}`).click();
  await expect(panel.getByTestId("server-running")).toBeVisible({ timeout: 15_000 });
  await closeSettings(page);

  // After: the picker knows. No reload, no restart — the SAME page that could not see it a
  // moment ago now offers it, BY NAME rather than by the absolute path the runner reports.
  await expect(await searchModels(page, "Qwen3-0.6B")).toHaveCount(1, { timeout: 15_000 });
  await expect(page.getByRole("option", { name: "Qwen3-0.6B-Q8_0" })).toBeVisible();
  // The user's home directory is not the label (ADR-0085's other half).
  await expect(page.getByText("/Users/someone/Library")).toHaveCount(0);
  await page.keyboard.press("Escape");

  // And the ENGINE was really re-asked since the server came up — the name did not come out
  // of a cache, a fixture, or the harness's own idea of what a model is called. The counter
  // is reset by the arm above, so this is a claim about THIS serve.
  const peer = await fetch(`${BRIDGE_URL}/admin/local-peer`).then((r) => r.json());
  expect(peer.probes).toBeGreaterThan(0);

  // Stopping puts it back: a model that is no longer served must stop being offered.
  const again = await openModelsFromRail(page);
  await again.getByTestId("stop-server").click();
  await armLocalPeer([]);
  await closeSettings(page);
  await expect(await searchModels(page, "Qwen3-0.6B")).toHaveCount(0, { timeout: 15_000 });
});
