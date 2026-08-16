/**
 * Engine lifecycle honesty: a dead sidecar surfaces as "engine unreachable — retrying"
 * (never a silent stale UI), recovery turns the masthead green again, and the supervisor's
 * sidecar-state-event genuinely triggers a refetch of every stale query.
 *
 * The bridge SIGKILLs / respawns the real sidecar process group — the same crash the Rust
 * supervisor handles in the app. Even with the engine deliberately dead the console must
 * stay clean: errors ride in-band as invoke results, exactly as under the real Tauri host.
 */
import { expect, test } from "./fixtures";

test("a dead engine is stated honestly and recovery is automatic", async ({ page, bridge }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });

  await bridge.engineDown();
  // A fresh load with a dead engine must say so — never render as healthy.
  await page.reload();
  await expect(page.getByText("engine unreachable — retrying")).toBeVisible({
    timeout: 20_000,
  });

  // Recovery: the health probe keeps retrying and the masthead settles green again.
  await bridge.engineUp();
  await expect(page.locator(".sidebar-foot .green")).toContainText(/engine .+ · schema v/, {
    timeout: 60_000,
  });
  await expect(page.getByText(/No runs yet|targets|run/).first()).toBeVisible();
});

test("the sidecar healthy event refetches stale queries", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });

  // The supervisor's "healthy" event → App invalidates every query → list_runs refetches.
  const refetch = page.waitForRequest(
    (request) =>
      request.url().includes("/invoke") &&
      request.method() === "POST" &&
      (request.postDataJSON() as { cmd?: string }).cmd === "list_runs",
    { timeout: 10_000 },
  );
  const delivered = await page.evaluate(() =>
    window.__E2E__.emit("sidecar-state-event", { state: "healthy" }),
  );
  expect(delivered).toBeGreaterThan(0);
  await refetch;
});
