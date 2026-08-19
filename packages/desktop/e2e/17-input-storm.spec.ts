/**
 * Phase 20 exit gate — the input-storm test: 15 keys/s for 60 s, ZERO dropped keystrokes.
 *
 * F11's acceptance criteria name this number exactly, so it is run exactly: 900 keystrokes at a
 * 66 ms cadence into a real CodeMirror instance with inline completion live. The property is
 * absolute — every character typed must be in the document afterwards, in order. Not "most", not
 * "within tolerance": a dropped keystroke in an editor is the defect users never forgive.
 *
 * "WITH INLINE COMPLETION LIVE" WAS NOT TRUE. The extension's only trigger is the F11 keymap
 * entry — no updateListener, no debounce, no on-type trigger — and the storm typed 900
 * identifier characters and never pressed it. `policyField` stayed `idle` for the whole run,
 * `source()` was never called, no widget was ever built, and the spec's own comment said the
 * opposite. It would have passed unchanged against a completion path that blocked the main
 * thread on every request. F11 is now pressed periodically DURING the storm, and the run
 * asserts that ghost text actually appeared — so the machinery this spec claims to stress is
 * provably running while the keys arrive.
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

  // A repeating, self-checking payload: every character is an ordinary identifier character or a
  // space, so nothing here triggers auto-indent, bracket closing, or any other input the editor
  // inserts on the user's behalf — which would make "what came out" legitimately differ from
  // "what went in" and turn a correctness assertion into an argument about editor features.
  //
  // Each burst ENDS with " calc" so the caret is sitting on a completable prefix when F11 is
  // pressed: `calc` resolves against `calculateTotal`, which the fixture defines. Without that
  // the whole payload is one 900-character identifier, `prefixAt` returns all of it, nothing in
  // the document extends it, and F11 would answer "no suggestion" — which is how a storm that
  // presses F11 could still fail to exercise the completion path.
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  const BURST = 100;
  const TAIL = " calc";
  const payload = Array.from({ length: TOTAL_KEYS / BURST }, (_, burst) =>
    Array.from(
      { length: BURST - TAIL.length },
      (_unused, i) => alphabet[(burst * BURST + i) % alphabet.length],
    ).join("") + TAIL,
  ).join("");

  // F11 at every burst boundary, so the completion machinery is genuinely working while the keys
  // arrive. Typing is done in slices rather than one `type()` call for that reason alone.
  let suggestionsSeen = 0;
  const started = Date.now();
  for (let offset = 0; offset < payload.length; offset += BURST) {
    await page.keyboard.type(payload.slice(offset, offset + BURST), { delay: DELAY_MS });
    await page.keyboard.press("F11");
    // Not awaited with a long timeout: the point is that the editor keeps up, so a suggestion
    // that has not rendered almost immediately must not stall the storm and distort its cadence.
    if (await page.getByTestId("ghost-text").isVisible().catch(() => false)) {
      suggestionsSeen += 1;
    }
    // Whatever F11 produced, it must not survive into what is typed next — and dismissing is
    // itself a cursor-and-policy event under load, which is the interaction being stressed.
    await page.keyboard.press("Escape");
  }
  const elapsedSeconds = (Date.now() - started) / 1000;

  // If this is 0 the storm ran with the machinery switched off, which is the state this spec
  // spent its whole life in while claiming otherwise.
  expect(
    suggestionsSeen,
    "inline completion must actually have run during the storm",
  ).toBeGreaterThan(0);

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
    // EVERY widget, not an enumerated one. Widgets are real DOM inside `.cm-content`, so they
    // count toward `textContent` while being no part of the file. This stripped only the ghost
    // text, and once the storm actually started pressing F11 the RISK BADGE arrived too — the
    // run failed with the document's tail reading "…no recorded runs name this symbol", i.e.
    // the ruler was wrong, not the editor. 16-inline-completion.spec.ts hit this exact defect
    // when the badge landed and wrote down the same lesson: a ruler that must be updated
    // whenever a widget is added is a ruler that will silently be wrong the next time one is.
    for (const widget of Array.from(clone.querySelectorAll("[data-testid]"))) {
      widget.remove();
    }
    return clone.textContent ?? "";
  });

  const typed = docText.slice(-TOTAL_KEYS);
  expect(typed.length, "every keystroke must have landed").toBe(TOTAL_KEYS);
  // Compared as a whole rather than counted: order matters as much as arrival, and a count
  // would pass on 900 characters in the wrong sequence.
  expect(typed, "the document must contain exactly what was typed, in order").toBe(payload);
});
