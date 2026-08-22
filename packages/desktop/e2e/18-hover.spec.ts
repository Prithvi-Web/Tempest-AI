/**
 * Phase 20.5 — `lsp_hover` is REACHABLE, and its answers reach the user.
 *
 * The multiplexer shipped in 20.2 with a typed command, a generated binding and eighteen Rust
 * tests against real subprocesses, and nothing in the webview ever called it. `grep -rn hover
 * packages/desktop/src` returned nothing but CSS. The handoff listed it first among what was NOT
 * done, and this spec is what makes that sentence false — so its FIRST assertion is simply that
 * the command is issued at all.
 *
 * What this harness can and cannot prove, stated plainly: there is no Rust host and no installed
 * language server here, so the shim answers `Unsupported` exactly as the real command does on a
 * fresh install. The rendered paths beyond that are reached by scripting ONE answer through the
 * shim — a seam in the test double, not in product code — because a tooltip that renders a
 * server's failure is worth pinning and no harness could otherwise reach it. What is NOT proved
 * here is the Rust side of hover; that is `cargo test`'s 29 lsp tests, against real subprocesses.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

const SOURCE = "def calculateTotal(items):\n    return sum(items)\n";

async function openEditor(page: import("@playwright/test").Page) {
  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-hover-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  await writeFile(join(repo, "sample.py"), SOURCE, "utf8");
  await page.goto(`/tempest/editor?repo=${encodeURIComponent(repo)}&file=sample.py`);
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });
  return { repo, content };
}

/** Rest the pointer over a word until CodeMirror's hover delay elapses. */
async function hoverWord(page: import("@playwright/test").Page, word: string) {
  const target = page.locator(".cm-content").getByText(word, { exact: false }).first();
  await target.hover();
  // CodeMirror's own hoverTime is 300 ms; give it room without making the spec a timing test.
  await page.waitForTimeout(600);
}

test("hovering a symbol reaches lsp_hover — the command 20.2 shipped with no caller", async ({
  page,
}) => {
  const { repo } = await openEditor(page);
  await hoverWord(page, "calculateTotal");

  const calls = await page.evaluate(() => window.__E2E__.hovered);
  expect(calls.length, "the editor must actually ask the host").toBeGreaterThan(0);
  const call = calls[0]!;
  expect(call.repoPath).toBe(repo);
  expect(call.path).toBe("sample.py");
  // Zero-based, as LSP requires: `calculateTotal` is on the first line.
  expect(call.line).toBe(0);
  expect(call.character).toBeGreaterThan(0);
  // The CURRENT buffer goes with it — the multiplexer follows edits with didChange (20.4a), and
  // sending nothing (or something stale) would put that fix straight back.
  expect(call.textLength).toBe(SOURCE.length);
});

test("with no language server configured, hovering shows nothing and says nothing", async ({
  page,
}) => {
  // The fresh-install state, and the shim answers it exactly as the real command does:
  // Err(Unsupported), NOT ok(null). A tooltip on every hover reading "no language server" would
  // be noise; an error toast would be worse. Silence here is the product decision, and the
  // console-clean gate in fixtures.ts is what proves it is silent rather than merely invisible.
  await openEditor(page);
  await hoverWord(page, "calculateTotal");
  await expect(page.getByTestId("hover-info")).toHaveCount(0);
  await expect(page.getByTestId("hover-problem")).toHaveCount(0);
  expect((await page.evaluate(() => window.__E2E__.hovered)).length).toBeGreaterThan(0);
});

test("what the server says is what the user sees", async ({ page }) => {
  await openEditor(page);
  await page.evaluate(() =>
    window.__E2E__.scriptHover({ ok: { contents: "(function) calculateTotal(items) -> int" } }),
  );
  await hoverWord(page, "calculateTotal");

  const tip = page.getByTestId("hover-info");
  await expect(tip).toBeVisible({ timeout: 5_000 });
  await expect(tip).toHaveText("(function) calculateTotal(items) -> int");
  // Named for assistive technology: CodeMirror's tooltip container carries no role of its own.
  await expect(tip).toHaveAttribute("role", "tooltip");
});

test("a configured server's failure is a sentence, never silence", async ({ page }) => {
  // The distinction the whole module exists for. Silence means "asked, and there is nothing to
  // say"; rendering a timed-out server the same way teaches the user their tooling works.
  await openEditor(page);
  await page.evaluate(() =>
    window.__E2E__.scriptHover({ error: { kind: "timeout", language: "python" } }),
  );
  await hoverWord(page, "calculateTotal");

  const problem = page.getByTestId("hover-problem");
  await expect(problem).toBeVisible({ timeout: 5_000 });
  await expect(problem).toContainText("python");
  await expect(problem).toContainText("did not answer in time");
  await expect(page.getByTestId("hover-info")).toHaveCount(0);
});

test("hover contents are rendered as TEXT, never as markup", async ({ page }) => {
  // A language server is an arbitrary binary reading the user's source, and this is the renderer
  // — the one place in this product where hostile output is displayed. `textContent`, not
  // `innerHTML`: markdown rendering here would be a script-injection surface for a server.
  await openEditor(page);
  await page.evaluate(() =>
    window.__E2E__.scriptHover({ ok: { contents: "<img src=x onerror=alert(1)>done" } }),
  );
  await hoverWord(page, "calculateTotal");

  const tip = page.getByTestId("hover-info");
  await expect(tip).toBeVisible({ timeout: 5_000 });
  await expect(tip).toHaveText("<img src=x onerror=alert(1)>done");
  expect(await tip.locator("img").count(), "no element may be built from server text").toBe(0);
});
