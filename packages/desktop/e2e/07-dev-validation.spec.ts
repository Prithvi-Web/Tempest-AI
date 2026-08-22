/**
 * Boundary B deep validation (§9b / HANDOFF-WORLD-CLASS 1.3), relocated per ADR-0077.
 *
 * The legacy webview ran this net itself (src/devValidate.ts, dev builds only); the platform
 * client's seam deliberately carries no ajv, so the net lives in the BRIDGE now
 * (e2e/contract-net.mjs): every engine reply is validated against the generated domain schema
 * before the page sees it. The positive case is implicit — every other spec in this suite
 * runs through the validating bridge, and a violation would surface as an in-band error and
 * fail whatever assertion depended on the data. This spec proves the net actually CATCHES:
 * a scripted corruption must be refused at the boundary, recorded in the ledger, and never
 * rendered — and the next honest reply must pass.
 */
import { expect, test } from "./fixtures";

const BRIDGE_URL = `http://127.0.0.1:${process.env.E2E_BRIDGE_PORT ?? 39755}`;

interface Violation {
  operation: string;
  detail: string;
  at: string;
}

async function contractLedger(): Promise<Violation[]> {
  const res = await fetch(`${BRIDGE_URL}/admin/contract-ledger`);
  if (!res.ok) throw new Error(`bridge /admin/contract-ledger ${res.status}`);
  return ((await res.json()) as { violations: Violation[] }).violations;
}

test("the bridge schema net rejects off-contract payloads and passes real ones", async ({
  page,
}) => {
  // Every command the boot flow issued was validated; a clean boot IS the pass case.
  await page.goto("/tempest");
  await expect(page.locator(".sidebar-foot .green")).toBeVisible({ timeout: 15_000 });
  const before = await contractLedger();
  expect(before, "an honest boot must not have tripped the net").toEqual([]);

  // Script exactly ONE corrupted listLogs reply, then walk to the view that issues it.
  const armed = await fetch(`${BRIDGE_URL}/admin/corrupt-next`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ operation: "listLogs" }),
  });
  expect(armed.ok).toBe(true);

  const refused = page.waitForResponse(async (response) => {
    if (!response.url().includes("/invoke")) return false;
    const body = (await response.json()) as { error?: { kind?: string; message?: string } };
    return body.error?.kind === "contract";
  });
  await page.locator(".sidebar").getByRole("link", { name: "Logs" }).click();

  // The corrupted reply was refused AT THE BOUNDARY: in-band, engine-shaped, named.
  const response = await refused;
  const body = (await response.json()) as { error: { kind: string; message: string } };
  expect(body.error.message).toContain("Boundary B contract violation");

  // …and recorded, with the operation and the ajv reason — the evidence the net caught it.
  const after = await contractLedger();
  expect(after).toHaveLength(1);
  expect(after[0]!.operation).toBe("listLogs");
  expect(after[0]!.detail).toContain("must be array");

  // The corruption was one-shot: the logs view's own poll refetches an honest reply and the
  // REAL records render — recovery, and the off-contract payload never reached the screen.
  const rows = page.locator("tbody tr");
  await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBeGreaterThan(0);
  expect(await contractLedger()).toHaveLength(1); // no second violation from the recovery
});
