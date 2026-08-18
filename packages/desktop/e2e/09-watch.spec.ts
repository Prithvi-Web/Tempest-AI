/**
 * Watch — the continuous agent driven from the app (ADR-0029, HANDOFF-WORLD-CLASS §2.4).
 *
 * The REAL engine watches a REAL git repository: the spec commits a behavior change with git
 * and waits for Tempest to notice, prove it, and land a verdict. The point being pinned is
 * the design claim — a watched commit becomes an ORDINARY run, so the row links into the same
 * run view with the same evidence. Nothing here is mocked (Law L4).
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test } from "./fixtures";

// Watch is process-wide state in the engine: a spec that leaves it armed would prove another
// spec's repository. Disarm after every test, whatever happened inside it. The first status
// fetch is in flight right after goto, so wait for EITHER button before deciding — an
// instant isVisible() probe would race it and skip the disarm.
test.afterEach(async ({ page }) => {
  await page.goto("/?view=watch");
  await expect(page.getByRole("button", { name: /Start watching|Stop watching/ })).toBeVisible();
  const stop = page.getByRole("button", { name: "Stop watching" });
  if (await stop.isVisible()) await stop.click();
  await expect(page.getByRole("button", { name: "Start watching" })).toBeVisible();
});

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

function watchedRepo(): string {
  const repo = mkdtempSync(path.join(tmpdir(), "tempest-watch-"));
  git(repo, "init", "-b", "main");
  // The first-party marker + TEMPEST_DEV in the bridge let the process sandbox run it (ADR-0008).
  writeFileSync(path.join(repo, ".tempest-first-party"), "tempest-first-party-fixture-v1\n");
  writeFileSync(path.join(repo, "core.py"), "def double(x: int) -> int:\n    return x * 2\n");
  git(repo, "add", "-A");
  git(repo, "commit", "-m", "one", "--no-gpg-sign");
  return repo;
}

test("watching a repo proves each new commit as an ordinary run", async ({ page }) => {
  test.slow(); // a real differential prove runs inside this test
  const repo = watchedRepo();

  await page.goto("/?view=watch");
  await expect(page.getByRole("heading", { name: "Watch" })).toBeVisible();
  await expect(page.getByText("No commits have been proven by watching yet.")).toBeVisible();

  await page.getByRole("textbox", { name: "Repository folder (full path)" }).fill(repo);
  await page.getByRole("spinbutton", { name: "Check every (seconds)" }).fill("1");
  await page.getByRole("spinbutton", { name: "Input budget per target" }).fill("6");
  await page.getByRole("button", { name: "Start watching" }).click();

  await expect(page.getByText("watching", { exact: true })).toBeVisible();
  await expect(page.getByText("Nothing yet — commit something")).toBeVisible();

  // A real commit, with a real behavior change.
  writeFileSync(path.join(repo, "core.py"), "def double(x: int) -> int:\n    return x * 2 + 1\n");
  git(repo, "add", "-A");
  git(repo, "commit", "-m", "two", "--no-gpg-sign");

  // Tempest notices, proves, and states a verdict — all without another click.
  const row = page.locator("tbody tr").first();
  await expect(row).toBeVisible({ timeout: 60_000 });
  await expect(row.getByText("DIVERGENT")).toBeVisible({ timeout: 120_000 });

  // …and that row IS a run: clicking it lands in the ordinary run view with the evidence.
  await row.click();
  await expect(page.getByRole("heading", { name: /^run #\d+/ })).toBeVisible();
  await expect(page.getByText("double")).toBeVisible();

});

test("a folder that is not a repository is refused, and nothing starts", async ({ page }) => {
  await page.goto("/?view=watch");
  await page
    .getByRole("textbox", { name: "Repository folder (full path)" })
    .fill("/definitely/not/a/repo/anywhere");
  await page.getByRole("button", { name: "Start watching" }).click();
  await expect(page.getByText(/is not an existing directory on this machine/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Start watching" })).toBeVisible();
});
