/**
 * Phase 20 exit gate — the input-storm test: 15 keys/s for 60 s, ZERO dropped keystrokes.
 *
 * F11's acceptance criteria name this number exactly, so it is run exactly: 900 keystrokes at a
 * 66 ms cadence into a real CodeMirror instance with inline completion live. The property is
 * absolute — every character typed must be in the document afterwards, in order. Not "most", not
 * "within tolerance": a dropped keystroke in an editor is the defect users never forgive.
 *
 * It is deliberately a CORRECTNESS spec, not a @bench one. Whether the machine is fast is a
 * measurement; whether the editor loses your typing is a fact, and a busy machine is precisely
 * when an input pipeline drops things. Sixty seconds is the price of knowing.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

/** The gate's numbers, verbatim. */
const KEYS_PER_SECOND = 15;
const DURATION_SECONDS = 60;
const TOTAL_KEYS = KEYS_PER_SECOND * DURATION_SECONDS;
const DELAY_MS = 1000 / KEYS_PER_SECOND;

test("15 keys/s for 60 s, zero dropped keystrokes", async ({ page }) => {
  test.setTimeout(240_000);

  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-storm-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  // A completable identifier, so inline completion is genuinely working during the storm rather
  // than idling — the point is that the editor keeps up WITH its machinery running.
  await writeFile(join(repo, "storm.py"), "def calculateTotal(items):\n    return sum(items)\n\n", "utf8");

  await page.goto(`/?view=editor&repo=${encodeURIComponent(repo)}&file=storm.py`);
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });
  await content.click();
  await page.keyboard.press("ControlOrMeta+End");

  // A repeating, self-checking payload: every character is an ordinary identifier character, so
  // nothing here triggers auto-indent, bracket closing, or any other input the editor inserts on
  // the user's behalf — which would make "what came out" legitimately differ from "what went in"
  // and turn a correctness assertion into an argument about editor features.
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  const payload = Array.from({ length: TOTAL_KEYS }, (_, i) => alphabet[i % alphabet.length]).join("");

  const started = Date.now();
  await page.keyboard.type(payload, { delay: DELAY_MS });
  const elapsedSeconds = (Date.now() - started) / 1000;

  // The storm has to have actually been a storm. If Playwright delivered the keys far slower
  // than 15/s the test proves nothing about load, and passing it would be a false assurance.
  expect(
    elapsedSeconds,
    `the storm must last about ${DURATION_SECONDS}s, not stretch out`,
  ).toBeLessThan(DURATION_SECONDS * 2.5);

  const docText = await page.evaluate(() => {
    const el = document.querySelector(".cm-content");
    if (el === null) return "";
    const clone = el.cloneNode(true) as HTMLElement;
    // Ghost text is on screen but not in the file; counting it would inflate the result.
    for (const ghost of Array.from(clone.querySelectorAll('[data-testid="ghost-text"]'))) {
      ghost.remove();
    }
    return clone.textContent ?? "";
  });

  const typed = docText.slice(-TOTAL_KEYS);
  expect(typed.length, "every keystroke must have landed").toBe(TOTAL_KEYS);
  // Compared as a whole rather than counted: order matters as much as arrival, and a count
  // would pass on 900 characters in the wrong sequence.
  expect(typed, "the document must contain exactly what was typed, in order").toBe(payload);
});
