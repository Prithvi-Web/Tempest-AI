/**
 * F12 — the composer, driven from the app against a REAL repository (ADR-0061).
 *
 * The third column is the whole feature, so this spec is about the column: that every hunk gets
 * a row, that the row carries the ENGINE's verdict rather than a word the UI chose, that a hunk
 * touching nothing executable says so instead of going blank, and that a 1000-hunk changeset
 * mounts a screenful of DOM rather than a thousand.
 *
 * A real git repo, the real sidecar, the real differential engine. Nothing is mocked (L4).
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "./fixtures";

const GIT_ENV = {
  GIT_AUTHOR_NAME: "t",
  GIT_AUTHOR_EMAIL: "t@t",
  GIT_COMMITTER_NAME: "t",
  GIT_COMMITTER_EMAIL: "t@t",
  PATH: "/usr/bin:/bin",
};

function git(repo: string, ...args: string[]): void {
  execFileSync("git", ["-C", repo, ...args], { env: { ...GIT_ENV, HOME: repo } });
}

/**
 * `files` modules, each with TWO well-separated changes: a function whose behaviour moves, and a
 * constant nothing executes. Separated by spacers because `git diff --unified=3` coalesces
 * changes closer together than twice its context into one hunk (trap 59) — without them this
 * fixture would quietly be half the size it claims.
 */
function composedRepo(files: number): string {
  const repo = mkdtempSync(path.join(tmpdir(), "tempest-composer-"));
  git(repo, "init", "-b", "main");
  writeFileSync(path.join(repo, ".tempest-first-party"), "tempest-first-party-fixture-v1\n");
  const body = (i: number, offset: number) =>
    `def total_${i}(xs):\n    return sum(xs) + ${offset}\n\n\n` +
    [0, 1, 2, 3].map((n) => `def spacer_${i}_${n}():\n    return ${n}`).join("\n\n") +
    `\n\n\nCONSTANT_${i} = ${offset}\n`;

  for (let i = 0; i < files; i += 1) {
    writeFileSync(path.join(repo, `mod_${i}.py`), body(i, 0));
  }
  git(repo, "add", "-A");
  git(repo, "commit", "-m", "base", "--no-gpg-sign");
  git(repo, "branch", "base");
  for (let i = 0; i < files; i += 1) {
    writeFileSync(path.join(repo, `mod_${i}.py`), body(i, 1));
  }
  git(repo, "add", "-A");
  git(repo, "commit", "-m", "head", "--no-gpg-sign");
  git(repo, "branch", "head");
  return repo;
}

async function compose(page: import("@playwright/test").Page, repo: string): Promise<void> {
  await page.goto("/?view=composer");
  await expect(page.getByRole("heading", { name: "Composer" })).toBeVisible();
  await page.locator('input[name="repo"]').fill(repo);
  await page.locator('input[name="base"]').fill("base");
  await page.locator('input[name="head"]').fill("head");
  await page.getByRole("button", { name: "Compose" }).click();
  await expect(page.getByTestId("composer-count")).toBeVisible({ timeout: 240_000 });
}

test("every hunk gets a row carrying the engine's own verdict", async ({ page }) => {
  test.slow(); // a real differential prove runs inside this test
  const repo = composedRepo(2);

  await compose(page, repo);
  await expect(page.getByTestId("composer-count")).toContainText("4 hunks");

  // The behaviour change is on the record, in the engine's vocabulary (L2) — the UI never
  // invents one, so a chip reading DIVERGENT is the engine speaking.
  await expect(page.locator(".chip.DIVERGENT").first()).toBeVisible();

  // And the constant-only hunks say what they are rather than going blank. A blank cell beside
  // a code change reads as reassurance nobody produced.
  await expect(page.getByText("no executable symbol").first()).toBeVisible();
});

test("rejecting a hunk re-proves the smaller change rather than filtering evidence", async ({
  page,
}) => {
  test.slow();
  const repo = composedRepo(2);

  await compose(page, repo);
  const before = await page.getByTestId("composer-count").textContent();
  expect(before).toContain("4 accepted");

  // Toggling changes the SELECTION, which is a different change and gets its own proof — the
  // bundle id in the count line is how you can tell it was re-proved and not re-filtered.
  const bundleBefore = (before ?? "").split("proved as").pop()?.trim();
  await page.locator(".composer-row input[type=checkbox]").first().uncheck();
  await expect(page.getByTestId("composer-count")).toContainText("3 accepted", {
    timeout: 120_000,
  });
  const after = await page.getByTestId("composer-count").textContent();
  expect((after ?? "").split("proved as").pop()?.trim()).not.toEqual(bundleBefore);
});

test("a large changeset mounts a screenful of rows, not all of them", async ({ page }) => {
  test.slow();
  // 25 files -> 50 hunks. The property is that the DOM holds a screenful rather than the whole
  // list, and 50 rows against a ~14-row viewport shows that as clearly as 1000 would; the proof
  // underneath is real, and every file added to this fixture is real execution time spent
  // re-demonstrating something the first twenty-five already showed.
  const repo = composedRepo(25);

  await compose(page, repo);
  await expect(page.getByTestId("composer-count")).toContainText("50 hunks");

  const mounted = await page.getByTestId("composer-row").count();
  expect(mounted).toBeGreaterThan(0);
  expect(mounted).toBeLessThan(30);

  // Scrolling moves the window rather than growing it: the DOM node count stays flat, which is
  // the property that makes 60 fps possible at a thousand rows.
  await page.getByTestId("composer-viewport").evaluate((el) => {
    el.scrollTop = 1500;
  });
  await expect.poll(async () => page.getByTestId("composer-row").count()).toBeLessThan(30);
});
