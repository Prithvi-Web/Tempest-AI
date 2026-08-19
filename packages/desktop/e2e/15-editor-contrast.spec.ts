/**
 * Phase 20.1 — the editor's syntax palette is legible in BOTH schemes, measured.
 *
 * CodeMirror ships a highlight style tuned for a white page. Dropped into this app's dark
 * palette it rendered keywords at roughly 1.7:1 — present, unreadable, and invisible to every
 * gate, because the editor route was in neither the screenshot pass nor the accessibility spec.
 * A colour that is "obviously fine" is exactly the kind of claim this suite exists to check, so
 * the ratio is computed rather than eyeballed: WCAG 2.2 SC 1.4.3 wants 4.5:1 for body text.
 */
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "./fixtures";

/** Relative luminance, WCAG 2.x definition. */
function luminance(color: string): number {
  const parts = color.match(/\d+(\.\d+)?/g);
  // A colour this cannot parse must fail loudly: silently scoring 0 would turn an unreadable
  // token into a passing ratio, which is the exact failure this spec exists to prevent.
  if (parts === null || parts.length < 3) throw new Error(`unparsable colour: ${color}`);
  const channels = parts.slice(0, 3).map((raw) => {
    const s = Number(raw) / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const [r, g, b] = channels as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const sorted = [luminance(a), luminance(b)].sort((x, y) => y - x);
  const [hi, lo] = sorted as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

for (const scheme of ["light", "dark"] as const) {
  test(`every syntax colour clears 4.5:1 in ${scheme}`, async ({ page }) => {
    const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-contrast-"));
    await mkdir(join(repo, ".git"), { recursive: true });
    await writeFile(
      join(repo, "sample.py"),
      "def greet(name):\n    # a comment\n    count = 42\n    return 'hello ' + name\n",
      "utf8",
    );

    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/?view=editor&repo=${encodeURIComponent(repo)}&file=sample.py`);
    const content = page.getByTestId("editor-host").locator(".cm-content");
    await expect(content).toBeVisible({ timeout: 30_000 });

    const probe = await page.evaluate(() => {
      const host = document.querySelector(".editor-host");
      if (host === null) throw new Error("no editor host");
      const background = getComputedStyle(host).backgroundColor;
      const spans: Array<[string, string]> = [];
      for (const el of Array.from(host.querySelectorAll(".cm-line span"))) {
        const text = el.textContent?.trim();
        if (text) spans.push([text.slice(0, 16), getComputedStyle(el).color]);
      }
      return { background, spans };
    });

    // If the highlighter ever stops emitting spans this test must fail loudly rather than pass
    // over an empty list — a vacuous "all colours are fine" is worse than no check.
    expect(probe.spans.length, "syntax spans are present to measure").toBeGreaterThan(2);
    for (const [text, color] of probe.spans) {
      expect(
        contrast(color, probe.background),
        `"${text}" at ${color} on ${probe.background} (${scheme})`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });
}

test("the find panel is themed and the app's global input rule does not reach into it", async ({
  page,
}) => {
  // Cmd-F is live because basicSetup installs searchKeymap. The panel shipped with CM6's light
  // default inside the dark editor, and `input, select { width: 100% }` — unconditional, outside
  // every media query — stretched its option checkboxes to the panel's full width.
  const repo = await mkdtemp(join(tmpdir(), "tempest-e2e-find-"));
  await mkdir(join(repo, ".git"), { recursive: true });
  await writeFile(join(repo, "sample.py"), "def greet(name):\n    return name\n", "utf8");

  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/?view=editor&repo=${encodeURIComponent(repo)}&file=sample.py`);
  const content = page.getByTestId("editor-host").locator(".cm-content");
  await expect(content).toBeVisible({ timeout: 30_000 });

  await content.click();
  await page.keyboard.press("ControlOrMeta+f");
  const panel = page.locator(".editor-host .cm-panel.cm-search");
  await expect(panel).toBeVisible();

  const probe = await page.evaluate(() => {
    const panelEl = document.querySelector(".editor-host .cm-panel.cm-search");
    const host = document.querySelector(".editor-host");
    if (panelEl === null || host === null) throw new Error("no search panel");
    const boxes = Array.from(panelEl.querySelectorAll('input[type="checkbox"]'));
    return {
      panelBg: getComputedStyle(panelEl).backgroundColor,
      hostBg: getComputedStyle(host).backgroundColor,
      widths: boxes.map((b) => b.getBoundingClientRect().width),
      hostWidth: host.getBoundingClientRect().width,
    };
  });

  // The panel belongs to the app's dark surface, not CodeMirror's white default.
  expect(probe.panelBg).not.toBe("rgb(245, 245, 245)");
  expect(luminance(probe.panelBg), "panel is a dark surface in dark mode").toBeLessThan(0.5);
  // Checkboxes are checkbox-sized, not panel-sized.
  expect(probe.widths.length, "the search panel has option checkboxes").toBeGreaterThan(0);
  for (const w of probe.widths) {
    expect(w, "a checkbox must not be stretched to the panel width").toBeLessThan(40);
  }
});
