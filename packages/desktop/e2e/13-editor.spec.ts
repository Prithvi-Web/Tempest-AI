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
  await expect(refusal).toHaveText("no such file in the project");
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
