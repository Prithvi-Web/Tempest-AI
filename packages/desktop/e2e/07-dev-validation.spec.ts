/**
 * Boundary B deep validation (§9b / HANDOFF-WORLD-CLASS 1.3): dev builds check every
 * command result against the generated domain schema. The positive case is implicit —
 * every other spec in this suite runs through the validating unwrap() and would trip the
 * console-clean gate on any violation. This spec proves the net actually CATCHES: a
 * corrupted payload must throw, and a real payload must not.
 */
import { expect, test } from "./fixtures";

// The deliberate corrupt-payload probe makes the validator console.error by design.
test.use({ allowedConsoleErrors: /Boundary B contract violation/ });

test("the dev-mode schema net rejects off-contract payloads and passes real ones", async ({
  page,
}) => {
  await page.goto("/");
  // getHealth has answered once the masthead is green — the dev validator is loaded.
  await expect(page.locator(".masthead .green")).toBeVisible({ timeout: 15_000 });
  await expect
    .poll(async () => page.evaluate(() => typeof window.__TEMPEST_DEV_VALIDATE__))
    .toBe("function");

  const verdicts = await page.evaluate(() => {
    const validate = window.__TEMPEST_DEV_VALIDATE__;
    if (!validate) throw new Error("dev validator not installed");
    const outcome = { corruptThrew: false, realPassed: false, unknownCommandThrew: false };
    try {
      // RunCreated requires run_id: integer — a string is exactly the class of drift
      // (i64-vs-string, renamed field) the generators are supposed to make impossible.
      validate("startLocalProve", { run_id: "not-a-number" });
    } catch {
      outcome.corruptThrew = true;
    }
    try {
      validate("startLocalProve", { run_id: 41 });
      outcome.realPassed = true;
    } catch {
      /* leaves realPassed false */
    }
    try {
      validate("someUnknownCommand", {});
    } catch {
      outcome.unknownCommandThrew = true;
    }
    return outcome;
  });

  expect(verdicts).toEqual({ corruptThrew: true, realPassed: true, unknownCommandThrew: true });
});
