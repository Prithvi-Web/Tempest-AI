/**
 * F12's two RENDER budgets (§5): a 500-file changeset under 300 ms, and 60 fps while scrolling.
 *
 * Tagged `@bench` and EXCLUDED from `make verify` for the same reason `14-editor-budgets` is: a
 * measurement taken while a correctness suite competes for the machine is a measurement of the
 * suite. This writes `bench/composer-metrics.json`; run it deliberately, on a quiet machine.
 *
 * **The proof is deliberately taken out of the measurement, by the FIXTURE.** F12's 300 ms budget
 * is about RENDERING five hundred files' worth of hunks, not about proving them — proving a
 * 500-file change is minutes of real execution and would swamp the number by three orders of
 * magnitude. So every change here is a module-level CONSTANT: a thousand real hunks, a thousand
 * real rows each carrying its real verdict column, and nothing for the engine to execute, so the
 * proof is empty and instant. The render is the full-size one and the engine time is not smuggled
 * into it. An earlier draft said it achieved this with `accepted: []` and did not do it — the
 * rows only exist after the first compose, so there was nothing to reject yet (trap 45).
 *
 * Both numbers are taken INSIDE the page. Timing `page.click` from the Playwright side would
 * include the CDP round trip, and a 300 ms budget cannot afford to include the instrument.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path, { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "./fixtures";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const OUT = join(REPO_ROOT, "bench", "composer-metrics.json");

/** F12's stated changeset size. Two changes per file, so a thousand rows. */
const FILES = 500;

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

function bigRepo(): string {
  const repo = mkdtempSync(path.join(tmpdir(), "tempest-composer-bench-"));
  git(repo, "init", "-b", "main");
  writeFileSync(path.join(repo, ".tempest-first-party"), "tempest-first-party-fixture-v1\n");
  // TWO constants per file, spaced so `git diff --unified=3` does not coalesce them (trap 59),
  // and no function change at all: 1000 hunks the composer must render, 0 targets to execute.
  const body = (i: number, offset: number) =>
    `FIRST_${i} = ${offset}\n\n\n` +
    [0, 1, 2, 3].map((n) => `def spacer_${i}_${n}():\n    return ${n}`).join("\n\n") +
    `\n\n\nSECOND_${i} = ${offset}\n`;
  for (const offset of [0, 1]) {
    for (let i = 0; i < FILES; i += 1) {
      writeFileSync(path.join(repo, `mod_${i}.py`), body(i, offset));
    }
    git(repo, "add", "-A");
    git(repo, "commit", "-m", offset === 0 ? "base" : "head", "--no-gpg-sign");
    git(repo, "branch", offset === 0 ? "base" : "head");
  }
  return repo;
}

test("@bench composer render and scroll budgets", async ({ page }) => {
  test.setTimeout(600_000);
  const repo = bigRepo();

  await page.goto("/tempest/composer");
  await expect(page.getByRole("heading", { name: "Composer" })).toBeVisible();
  await page.locator('input[name="repo"]').fill(repo);
  await page.locator('input[name="base"]').fill("base");
  await page.locator('input[name="head"]').fill("head");

  await page.getByRole("button", { name: "Compose" }).click();
  await expect(page.getByTestId("composer-count")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByTestId("composer-count")).toContainText(`${FILES * 2} hunks`);

  // Taken BEFORE the toggle. An earlier draft read it afterwards, when a key change had
  // unmounted the list, and recorded 0 rows and a -1 scroll — both of which sailed past
  // `toBeLessThan` and made the whole spec green about a page it never looked at (trap 47).
  const mounted = await page.getByTestId("composer-row").count();

  // The render measurement: toggling one row re-renders the whole list from state already in
  // memory — no network, no engine, just React and layout.
  const renderMs = await page.evaluate(() => {
    const start = performance.now();
    const first = document.querySelector<HTMLInputElement>(".composer-row input[type=checkbox]");
    first?.click();
    return performance.now() - start;
  });

  // The scroll measurement: how long a full window replacement takes, averaged over 20 jumps.
  // 60 fps means 16.7 ms per frame, so this is the number that decides whether a scroll stutters.
  const scrollMs = await page.evaluate(() => {
    const viewport = document.querySelector<HTMLElement>('[data-testid="composer-viewport"]');
    if (!viewport) return -1;
    const samples: number[] = [];
    for (let i = 0; i < 20; i += 1) {
      const start = performance.now();
      viewport.scrollTop = i * 900;
      viewport.dispatchEvent(new Event("scroll"));
      void viewport.offsetHeight; // force layout, so the number includes it
      samples.push(performance.now() - start);
    }
    samples.sort((a, b) => a - b);
    return samples[Math.floor(samples.length * 0.95)] ?? -1;
  });

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(
    OUT,
    `${JSON.stringify(
      {
        composer_hunks: FILES * 2,
        composer_rows_mounted: mounted,
        composer_render_ms: Number(renderMs.toFixed(1)),
        composer_scroll_p95_ms: Number(scrollMs.toFixed(1)),
      },
      null,
      2,
    )}\n`,
    "utf-8",
  );

  // Asserted here rather than only written, because unlike the editor budgets these do not have
  // a perf_suite row yet (ADR-0061) and a number nothing reads is a number nobody checks.
  // Lower bounds first: every one of these can be satisfied by an absent element, and an
  // assertion that a missing thing is small is not an assertion.
  expect(mounted).toBeGreaterThan(5);
  expect(renderMs).toBeGreaterThan(0);
  expect(scrollMs).toBeGreaterThanOrEqual(0);

  expect(mounted).toBeLessThan(40);
  expect(renderMs).toBeLessThan(300);
  expect(scrollMs).toBeLessThan(16.7);
});
