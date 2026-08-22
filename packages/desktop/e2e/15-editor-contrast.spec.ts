/**
 * Phase 20.1 — the editor's syntax palette is legible in BOTH schemes, measured.
 *
 * CodeMirror ships a highlight style tuned for a white page. Dropped into this app's dark
 * palette it rendered keywords at roughly 1.7:1 — present, unreadable, and invisible to every
 * gate, because the editor route was in neither the screenshot pass nor the accessibility spec.
 * A colour that is "obviously fine" is exactly the kind of claim this suite exists to check, so
 * the ratio is computed rather than eyeballed: WCAG 2.2 SC 1.4.3 wants 4.5:1 for body text.
 *
 * ## The ruler was wrong, which is worse than a colour being wrong
 *
 * Every span was measured against `getComputedStyle(host).backgroundColor` — the editor's own
 * surface — no matter what the element actually sits on. So the gutter (`--surface-sunken`) and
 * the risk badge (also `--surface-sunken`) were scored against `--surface`, which is a different
 * colour, and a badge at a real 4.30:1 measured as a passing 5.07:1. It also enumerated only
 * `.cm-line span`, so the two widgets F11 draws — ghost text and the risk badge — did not exist
 * when the probe ran and could never have been measured at all.
 *
 * Both are fixed here: the probe walks up from each element to the nearest ancestor with a
 * non-transparent background and measures against THAT, and it presses F11 first so the widgets
 * are on screen. A gate that measures the wrong pair of colours is not a weaker gate; it is a
 * gate that reports green about something it never looked at.
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
      // The trailing `gre` is what gives F11 something to complete (`greet`, defined above), so
      // the two widgets this spec now measures actually render. Without it the caret sits after
      // a newline, `prefixAt` returns "", and F11 correctly offers nothing.
      "def greet(name):\n    # a comment\n    count = 42\n    return 'hello ' + name\n\ngre",
      "utf8",
    );

    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(`/tempest/editor?repo=${encodeURIComponent(repo)}&file=sample.py`);
    const content = page.getByTestId("editor-host").locator(".cm-content");
    await expect(content).toBeVisible({ timeout: 30_000 });

    // Put F11's two widgets on screen. They are the only editor text the old probe could not
    // see, and one of them is the badge whose whole job is to be read.
    await content.click();
    await page.keyboard.press("ControlOrMeta+End");
    await page.keyboard.press("F11");
    await expect(page.getByTestId("ghost-text")).toBeVisible({ timeout: 10_000 });
    // The badge is attached AFTER the suggestion, once the divergence lookup answers — so it has
    // to be waited for, not assumed. Without this the probe raced it and the run passed or
    // failed by timing, which is worse than either verdict.
    await expect(page.getByTestId("risk-badge")).toBeVisible({ timeout: 10_000 });

    // EVERY badge state, not only the one this harness can reach.
    //
    // `unmeasured` is the only level a run with no recorded divergences produces, so `elevated`
    // and `high` — the two the indicator exists for — were never on screen when the probe ran.
    // One of them shipped at 4.16:1 for exactly that reason. These are real elements carrying
    // the SHIPPED classes, mounted in the real editor, so what is measured is the CSS the app
    // ships; only the trigger is synthetic, because no fixture can make the engine record a
    // HEADLINE divergence from inside a contrast test.
    await page.evaluate(() => {
      const host = document.querySelector(".editor-host");
      if (host === null) throw new Error("no editor host to mount the badge states on");
      // Mounted beside the content, NOT inside `.cm-content`: CodeMirror observes mutations
      // there and reconciles foreign nodes away — the first attempt did that and took the ghost
      // widget with it, which the assertions below caught.
      const strip = document.createElement("div");
      strip.setAttribute("data-testid", "probe-strip");
      // The badge renders on the cursor's line, so the probe carries the active line's tint.
      // That is the one thing the harness supplies; the COLOURS being measured are entirely the
      // app's, read from the shipped `.cm-risk-*` rules.
      strip.style.background = getComputedStyle(
        document.querySelector(".cm-activeLine") ?? host,
      ).backgroundColor;
      for (const level of ["unmeasured", "elevated", "high"]) {
        const span = document.createElement("span");
        span.className = `cm-risk-badge cm-risk-${level}`;
        span.setAttribute("data-testid", `probe-risk-${level}`);
        span.textContent = `⚠ ${level} — 2 divergences recorded here`;
        strip.appendChild(span);
      }
      host.appendChild(strip);
    });

    const probe = await page.evaluate(() => {
      const host = document.querySelector(".editor-host");
      if (host === null) throw new Error("no editor host");
      // The colour a pixel of this element is ACTUALLY drawn on.
      //
      // Two things the first version got wrong. It measured every span against the editor
      // host's own background regardless of what the element sits on — so the gutter and the
      // risk badge, both on `--surface-sunken`, were scored against `--surface`. And a
      // translucent layer was then treated as if it were opaque: the active line is
      // `rgba(255,255,255,0.055)`, and stopping there reports the contrast against a colour
      // that does not exist on screen. Layers are composited, bottom-up, to an opaque base.
      const parse = (css: string): [number, number, number, number] => {
        const n = css.match(/[\d.]+/g)?.map(Number) ?? [];
        const [r = 0, g = 0, b = 0, a = 1] = n;
        return [r, g, b, a];
      };
      const over = (
        top: [number, number, number, number],
        bottom: [number, number, number, number],
      ): [number, number, number, number] => [
        top[0] * top[3] + bottom[0] * (1 - top[3]),
        top[1] * top[3] + bottom[1] * (1 - top[3]),
        top[2] * top[3] + bottom[2] * (1 - top[3]),
        1,
      ];
      const rgb = (c: [number, number, number, number]): string =>
        `rgb(${Math.round(c[0])}, ${Math.round(c[1])}, ${Math.round(c[2])})`;

      const backdropOf = (el: Element): [number, number, number, number] => {
        const layers: Array<[number, number, number, number]> = [];
        for (let node: Element | null = el; node !== null; node = node.parentElement) {
          const c = parse(getComputedStyle(node).backgroundColor);
          if (c[3] === 0) continue;
          layers.push(c);
          if (c[3] === 1) break;
        }
        let base = layers.pop() ?? parse(getComputedStyle(document.body).backgroundColor);
        if (base[3] < 1) base = over(base, [255, 255, 255, 1]);
        for (let i = layers.length - 1; i >= 0; i -= 1) {
          const layer = layers[i];
          if (layer !== undefined) base = over(layer, base);
        }
        return base;
      };
      const measured: Array<[string, string, string]> = [];
      const selectors = [
        ".cm-line span",
        ".cm-gutters .cm-lineNumbers .cm-gutterElement",
        '[data-testid="ghost-text"]',
        '[data-testid="risk-badge"]',
        '[data-testid^="probe-risk-"]',
      ];
      for (const selector of selectors) {
        for (const el of Array.from(host.querySelectorAll(selector))) {
          const text = el.textContent?.trim();
          if (!text) continue;
          const style = getComputedStyle(el);
          const background = backdropOf(el);
          // `opacity` and a translucent text colour both multiply into what the eye receives, so
          // a colour scored without them is not the colour on screen. Ghost text ships at
          // `opacity: 0.85`, which is a real reduction in contrast, not a decoration.
          const text_color = parse(style.color);
          const alpha = Number(style.opacity);
          const effective = over(
            [text_color[0], text_color[1], text_color[2], text_color[3] * alpha],
            background,
          );
          // Named by the element's own testid where it has one, not by the SELECTOR that found
          // it: a prefix selector like `[data-testid^="probe-risk-"]` matches three different
          // elements and would label all three identically, so the presence assertions below
          // could not tell them apart — and would pass while two of the three were missing.
          const name = el.getAttribute("data-testid") ?? selector;
          const label = `${name} ${text.slice(0, 14)}${alpha < 1 ? ` @${style.opacity}` : ""}`;
          measured.push([label, rgb(effective), rgb(background)]);
        }
      }
      return { measured };
    });

    // If the highlighter ever stops emitting spans this test must fail loudly rather than pass
    // over an empty list — a vacuous "all colours are fine" is worse than no check.
    expect(probe.measured.length, "editor text is present to measure").toBeGreaterThan(2);
    for (const kind of [
      "ghost-text",
      "risk-badge",
      ".cm-gutters",
      "probe-risk-unmeasured",
      "probe-risk-elevated",
      "probe-risk-high",
    ]) {
      expect(
        probe.measured.some(([label]) => label.includes(kind)),
        `${kind} must be on screen and measured, not silently absent`,
      ).toBe(true);
    }
    for (const [label, color, background] of probe.measured) {
      expect(
        contrast(color, background),
        `${label} at ${color} on ${background} (${scheme})`,
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
  await page.goto(`/tempest/editor?repo=${encodeURIComponent(repo)}&file=sample.py`);
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
