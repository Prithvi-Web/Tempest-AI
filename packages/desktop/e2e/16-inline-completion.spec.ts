/**
 * Phase 20.3b (F11) — ghost text end to end in a real CodeMirror instance.
 *
 * The DECISIONS (which answer to believe, what counts as acceptance) are unit-tested to 100% in
 * completionPolicy.test.ts, because a race is the thing an E2E suite pins worst. What these
 * specs pin is the half unit tests cannot see: that a suggestion appears on screen, that Tab
 * takes it, that typing makes it go away, and that it is a WIDGET — never text in the document
 * until accepted.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

async function projectWith(body: string) {
  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-f11-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  await writeFile(join(repo, "sample.py"), body, "utf8");
  return repo;
}

function editorUrl(repo: string, file = "sample.py"): string {
  return `/?view=editor&repo=${encodeURIComponent(repo)}&file=${encodeURIComponent(file)}`;
}

/**
 * The DOCUMENT's text — the ghost widget excluded.
 *
 * `.cm-content.textContent` includes the suggestion, because a widget decoration is real DOM
 * inside the content element. That is exactly the distinction these specs exist to check, so
 * measuring it with plain textContent would have asserted the opposite of what it claimed: the
 * first version of this spec did, and reported "ghost text is in the document" as a failure of
 * the editor rather than of the ruler.
 */
async function documentText(page: import("@playwright/test").Page): Promise<string> {
  return page.evaluate(() => {
    const content = document.querySelector(".cm-content");
    if (content === null) return "";
    const clone = content.cloneNode(true) as HTMLElement;
    for (const ghost of Array.from(clone.querySelectorAll('[data-testid="ghost-text"]'))) {
      ghost.remove();
    }
    return clone.textContent ?? "";
  });
}

test("F11 offers a completion as ghost text, and Tab takes it", async ({ page }) => {
  const repo = await projectWith("def calculateTotal(items):\n    return sum(items)\n\ncalc");
  await page.goto(editorUrl(repo));
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });

  // Put the caret at the end of the partially typed identifier.
  await content.click();
  await page.keyboard.press("ControlOrMeta+End");

  await page.keyboard.press("F11");
  const ghost = page.getByTestId("ghost-text");
  await expect(ghost, "F11 must offer the identifier the file already contains").toBeVisible({
    timeout: 10_000,
  });
  await expect(ghost).toHaveText("ulateTotal");

  // Until Tab, the suggestion is a widget: it is on SCREEN but not in the document. That is
  // what "no layout thrash" buys — the line never reflows on a suggestion arriving.
  const beforeAccept = await documentText(page);
  expect(beforeAccept.endsWith("calc"), "ghost text must not be in the document yet").toBe(true);

  await page.keyboard.press("Tab");
  await expect(page.getByTestId("ghost-text")).toHaveCount(0);
  const afterAccept = await documentText(page);
  expect(
    afterAccept.trimEnd().endsWith("calculateTotal"),
    "after Tab the completion IS in the document",
  ).toBe(true);
});

test("typing dismisses a suggestion rather than leaving it stale on screen", async ({ page }) => {
  const repo = await projectWith("def renderRow(x):\n    return x\n\nrend");
  await page.goto(editorUrl(repo));
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });
  await content.click();
  await page.keyboard.press("ControlOrMeta+End");

  await page.keyboard.press("F11");
  await expect(page.getByTestId("ghost-text")).toBeVisible({ timeout: 10_000 });

  await page.keyboard.type("X");
  // The suggestion described a document that no longer exists. It must not linger.
  await expect(page.getByTestId("ghost-text")).toHaveCount(0);
});

test("Escape dismisses without inserting anything", async ({ page }) => {
  const repo = await projectWith("def parseHeader(x):\n    return x\n\npars");
  await page.goto(editorUrl(repo));
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });
  await content.click();
  await page.keyboard.press("ControlOrMeta+End");

  await page.keyboard.press("F11");
  await expect(page.getByTestId("ghost-text")).toBeVisible({ timeout: 10_000 });
  const before = await documentText(page);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("ghost-text")).toHaveCount(0);
  const after = await documentText(page);
  expect(after, "Escape must never insert").toBe(before);
});
