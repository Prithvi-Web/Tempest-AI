/**
 * Frontend crash honesty (HANDOFF-WORLD-CLASS §1.1), re-scoped per ADR-0077.
 *
 * THE DELTA, STATED. The legacy webview installed `window` error/unhandledrejection listeners
 * (src/reportUiError.ts installUiErrorReporting) and this spec drove them with planted page
 * errors. The platform seam's copy deliberately has NO window listeners: in the shipped app
 * the tempest:// host's console tap owns the window-level channel (platform_web.rs forwards
 * every uncaught error to the host's stderr), and a second listener would double-count every
 * failure. What survives in product code — and is therefore what this spec pins — is the
 * EXPLICIT path: a component that caught a failure and knows what it is reports it through
 * the typed command. The one such component is EditorChunkBoundary, whose failure mode
 * (a lazy editor chunk that never loads: stale hash after an update, offline first open) is
 * staged here for real by refusing the chunk request. The engine leg is unchanged: typed
 * command → bridge → engine → obslog → the LOGS view the user actually opens. The L9
 * redaction of report contents is pinned where redaction lives — the engine's own tests —
 * since no window listener remains for a planted-email page error to ride through.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

// Refusing the editor chunk makes Chromium log the failed resource and the module loader
// state its failure — that noise is the staged breakage (including the lazy loader's
// `reading 'default'` TypeError on the client's reload-once retry of a failed preload).
// Anything else still fails the suite.
test.use({
  allowedConsoleErrors:
    /Failed to load resource|ERR_FAILED|dynamically imported module|Importing a module script failed|reading 'default'/,
});

async function fixtureProject(): Promise<{ repo: string; file: string }> {
  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-uierr-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  await writeFile(join(repo, "sample.py"), "def greet(name):\n    return name\n", "utf8");
  return { repo, file: "sample.py" };
}

/** Refuse every editor-chunk request, so the lazy import genuinely fails in the page. */
async function breakEditorChunk(page: import("@playwright/test").Page): Promise<void> {
  // ONLY the tempest editor's own glue chunk. `codemirror-core` must stay reachable: the
  // vendored client's main entry statically imports it (it is in index.html's modulepreload
  // list), so refusing it breaks the whole boot rather than staging an editor-chunk failure.
  await page.route(/assets\/CodeMirrorHost[^/]*\.js$/, (route) => route.abort());
}

test("a failed editor chunk is caught and stated, never a blank window", async ({ page }) => {
  const { repo, file } = await fixtureProject();
  await breakEditorChunk(page);
  await page.goto(`/tempest/editor?repo=${encodeURIComponent(repo)}&file=${encodeURIComponent(file)}`);

  // The boundary catches the rejected import and renders the honest sentence — announced,
  // not merely coloured — while the rest of the app stays alive around it.
  const failed = page.getByTestId("editor-chunk-failed");
  await expect(failed).toBeVisible({ timeout: 15_000 });
  await expect(failed).toHaveAttribute("role", "alert");
  await expect(failed).toContainText("The editor could not be loaded");
  await expect(page.getByTestId("editor-host")).toHaveCount(0);
  await expect(page.locator(".sidebar")).toBeVisible(); // the failure is contained, not total
});

test("the caught failure is reported into the engine's obslog, visibly", async ({ page }) => {
  const { repo, file } = await fixtureProject();
  await breakEditorChunk(page);
  await page.goto(`/tempest/editor?repo=${encodeURIComponent(repo)}&file=${encodeURIComponent(file)}`);
  await expect(page.getByTestId("editor-chunk-failed")).toBeVisible({ timeout: 15_000 });

  // The boundary's componentDidCatch sent the typed report; the REAL engine recorded it.
  // "editor-chunk" is the source string EditorChunkBoundary reports under. `.first()`
  // because the store accumulates one row per staged failure across this file's tests (and
  // the client retries a failed chunk once), and any one of them proves the path.
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();
  await expect(page.getByRole("row", { name: /editor-chunk/ }).first()).toBeVisible({
    timeout: 15_000,
  });
});
