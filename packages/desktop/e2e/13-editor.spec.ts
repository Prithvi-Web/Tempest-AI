/**
 * Phase 20.1 — the editor surface, end to end: a REAL file on disk, read by the host, rendered
 * by a REAL CodeMirror 6 instance in the REAL webview.
 *
 * Scope, stated plainly. `pathguard`'s RULES (absolute paths, `..`, symlink escapes, the
 * credential denylist, binary files, oversize) are pinned by 26 Rust tests, because in this
 * suite the page runs in a browser rather than in Tauri and the Rust command is not the thing
 * executing. What these specs pin is the half Rust cannot see: that bytes off a disk arrive in
 * a mounted editor, that a refusal reaches the user as a sentence, and that CodeMirror is not
 * parsed until someone actually opens a file.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

async function fixtureProject(): Promise<{ repo: string; file: string }> {
  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-editor-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  await mkdir(join(repo, "src"), { recursive: true });
  await writeFile(
    join(repo, "src", "greet.py"),
    "def greet(name):\n    return f'hello {name}'\n",
    "utf8",
  );
  return { repo, file: "src/greet.py" };
}

function editorUrl(repo: string, file: string): string {
  return `/?view=editor&repo=${encodeURIComponent(repo)}&file=${encodeURIComponent(file)}`;
}

test("a real file opens in a real CodeMirror instance", async ({ page }) => {
  const { repo, file } = await fixtureProject();
  await page.goto(editorUrl(repo, file));

  const host = page.getByTestId("editor-host");
  await expect(host).toBeVisible({ timeout: 15_000 });
  // `.cm-content` is CodeMirror's own contenteditable — its presence proves CM6 mounted, not
  // that a <div> rendered.
  await expect(host.locator(".cm-content")).toBeVisible();
  await expect(host).toContainText("def greet(name):");
  await expect(host).toContainText("hello {name}");
  await expect(page.getByTestId("editor-path")).toHaveText(file);
  // The editor must have a height and a visible frame: it shipped once with no CSS rule at all,
  // which the screenshot pass would have caught had it been looking at this view.
  const box = await host.boundingBox();
  expect(box, "the editor host has a layout box").not.toBeNull();
  expect(box!.height, "the editor has a real height, not a collapsed container").toBeGreaterThan(
    200,
  );
});

test("the editor is typable and renders what was typed", async ({ page }) => {
  const { repo, file } = await fixtureProject();
  await page.goto(editorUrl(repo, file));
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 15_000 });

  await content.click();
  await page.keyboard.type("# typed by the keystroke spec\n");
  await expect(content).toContainText("# typed by the keystroke spec");
});

test("a file that is not there is refused as a sentence, not a crash", async ({ page }) => {
  const { repo } = await fixtureProject();
  await page.goto(editorUrl(repo, "src/absent.py"));

  const refusal = page.getByTestId("editor-refusal");
  await expect(refusal).toBeVisible({ timeout: 15_000 });
  // The reason AND what to do about it: a refusal that only says "no" makes the user guess.
  await expect(refusal).toContainText("no such file in the project");
  await expect(refusal).toContainText("Check the path");
  // Announced, not merely coloured — a screen reader must hear the refusal.
  await expect(refusal).toHaveAttribute("role", "alert");
  // A refusal is a product surface: no editor is mounted behind it.
  await expect(page.getByTestId("editor-host")).toHaveCount(0);
});

test("CodeMirror is not parsed until a file is opened", async ({ page }) => {
  // The 545 KB editor bundle must stay off the path to first paint (ADR-0034, §5 cold launch).
  const editorChunks: string[] = [];
  page.on("response", (r) => {
    if (/codemirror|lang-python|lang-javascript/i.test(r.url())) editorChunks.push(r.url());
  });

  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });
  expect(editorChunks, "editor chunks loaded before any file was opened").toEqual([]);
});

test("the editor is reachable from the product, not only by typing a URL", async ({
  page,
  bridge,
}) => {
  // 20.1 shipped an editor nothing navigated to: no link, no button, no file tree. A surface a
  // user cannot reach is not a surface. This pins the route into the product.
  const { fixture } = await bridge.info();
  await page.goto("/?view=prove");
  await page.locator("#repo").fill(fixture.repo);
  await page.locator("#base").fill(fixture.base);
  await page.locator("#head").fill(fixture.head);
  await page.getByRole("button", { name: "Prove it" }).click();
  await expect(page).toHaveURL(/view=run&id=\d+/, { timeout: 30_000 });
  await expect(page.locator(".statusline .chip").first()).toHaveText(/DIVERGENT|EQUIVALENT/, {
    timeout: 240_000,
  });

  await page.locator("tbody tr").first().click();
  await expect(page).toHaveURL(/view=target&id=\d+/);

  const open = page.getByTestId("open-in-editor");
  await expect(open, "a target must offer to open its own source").toBeVisible({
    timeout: 15_000,
  });
  await open.click();
  await expect(page).toHaveURL(/view=editor/);

  // Scope, stated: what this pins is REACHABILITY — that the product navigates to the editor
  // route carrying a real repo and a real file. Whether that particular file is present in the
  // fixture's WORKING TREE is a different question: a prove compares base..head inside git
  // worktrees, so a changed file need not exist in the checked-out tree, and the editor then
  // says so. Both outcomes are correct product behaviour and the honest assertion covers both.
  // That the editor mounts for a file that IS present is pinned by the first spec in this file.
  await expect(
    page.getByTestId("editor-host").or(page.getByTestId("editor-refusal")),
    "the editor route must render either the file or a stated reason",
  ).toBeVisible({ timeout: 15_000 });
});
