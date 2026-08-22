/**
 * The absorbed views' URL space (routes.ts) — the full exported API, both directions.
 *
 * Replaces router.test.ts + useRoute.test.tsx (ADR-0077): the query-param grammar and the
 * hand-rolled history hook are react-router's job inside the platform client, so what remains
 * OURS to pin is this module — every href builder emits a path under the one mount point, the
 * editor's two arbitrary strings survive their own contents, and `rowId` refuses to turn a
 * missing or malformed id into row #0 (the same refusal `parseRoute` made, now at the router's
 * param boundary). The navigation behavior itself (push, back button, id adapters redirecting
 * to the list) is pinned end-to-end by the Playwright suite against the real router.
 */
import { describe, expect, it } from "vitest";

import {
  TEMPEST_BASE,
  composerPath,
  divergencePath,
  editorPath,
  logsPath,
  provePath,
  rowId,
  runPath,
  runsPath,
  settingsPath,
  targetPath,
  watchPath,
} from "../../platform/client/tempest/views/routes";

describe("the path builders", () => {
  it("agree with the mount point, which is stated once", () => {
    expect(TEMPEST_BASE).toBe("/tempest");
    expect(runsPath()).toBe(TEMPEST_BASE);
  });

  it("build every plain view's path under the mount point", () => {
    expect(provePath()).toBe("/tempest/prove");
    expect(watchPath()).toBe("/tempest/watch");
    expect(composerPath()).toBe("/tempest/composer");
    expect(logsPath()).toBe("/tempest/logs");
    expect(settingsPath()).toBe("/tempest/settings");
  });

  it("build every id-carrying view's path", () => {
    expect(runPath(3)).toBe("/tempest/runs/3");
    expect(targetPath(12)).toBe("/tempest/targets/12");
    expect(divergencePath(7)).toBe("/tempest/divergences/7");
  });
});

describe("editorPath", () => {
  it("carries the project and the file as search params", () => {
    const href = editorPath("/src/proj", "src/main.py");
    expect(href.startsWith("/tempest/editor?")).toBe(true);
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("repo")).toBe("/src/proj");
    expect(params.get("file")).toBe("src/main.py");
  });

  it("survives the characters real filenames contain", () => {
    // `&` and `#` in a filename would end the query string early if they were not encoded —
    // the same property the query-param router pinned, kept across the re-platform.
    const repo = "/Users/me/My Project";
    const file = "src/a&b#c/héllo wörld.py";
    const href = editorPath(repo, file);
    expect(href).not.toContain("#");
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("repo")).toBe(repo);
    expect(params.get("file")).toBe(file);
  });
});

describe("rowId", () => {
  it("reads a positive integer id", () => {
    expect(rowId("3")).toBe(3);
    expect(rowId("12")).toBe(12);
  });

  it("refuses a missing id rather than becoming row #0", () => {
    // Number(undefined) is NaN and Number("") is 0 — the presence check must come first.
    expect(rowId(undefined)).toBeNull();
    expect(rowId("")).toBeNull();
  });

  it("refuses everything that is not a 1-based row id", () => {
    for (const junk of ["NaN", "nope", "0", "-2", "1.5", "1e3x", " "]) {
      expect(rowId(junk), `rowId(${JSON.stringify(junk)})`).toBeNull();
    }
  });

  it("round-trips the id every builder emits", () => {
    for (const id of [1, 5, 41]) {
      expect(rowId(runPath(id).split("/").pop())).toBe(id);
      expect(rowId(targetPath(id).split("/").pop())).toBe(id);
      expect(rowId(divergencePath(id).split("/").pop())).toBe(id);
    }
  });
});
