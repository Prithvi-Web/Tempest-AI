/**
 * Query-param routing — the full grammar, both directions. parseRoute must accept anything
 * (a hand-edited or stale URL degrades to the runs list, never a crash), and routeHref must
 * emit exactly what parseRoute reads back (the round-trip property below).
 */
import { describe, expect, it } from "vitest";

import { parseRoute, routeHref, type Route } from "./router";

describe("parseRoute", () => {
  it("reads every id-carrying view", () => {
    expect(parseRoute("?view=run&id=3")).toEqual({ view: "run", id: 3 });
    expect(parseRoute("?view=target&id=12")).toEqual({ view: "target", id: 12 });
    expect(parseRoute("?view=divergence&id=7")).toEqual({ view: "divergence", id: 7 });
  });

  it("reads every plain view", () => {
    expect(parseRoute("?view=prove")).toEqual({ view: "prove" });
    expect(parseRoute("?view=logs")).toEqual({ view: "logs" });
    expect(parseRoute("?view=watch")).toEqual({ view: "watch" });
    expect(parseRoute("?view=composer")).toEqual({ view: "composer" });
    expect(parseRoute("?view=settings")).toEqual({ view: "settings" });
  });

  it("reads the editor route, which carries two strings rather than an id", () => {
    expect(parseRoute("?view=editor&repo=%2Fsrc%2Fproj&file=src%2Fmain.py")).toEqual({
      view: "editor",
      repo: "/src/proj",
      file: "src/main.py",
    });
  });

  it("survives the characters real filenames contain", () => {
    // `&` and `#` in a filename would end the query string early if they were not encoded.
    const route: Route = {
      view: "editor",
      repo: "/Users/me/My Project",
      file: "src/a&b#c/héllo wörld.py",
    };
    expect(parseRoute(routeHref(route))).toEqual(route);
  });

  it("refuses a half-specified editor link instead of opening an empty buffer", () => {
    expect(parseRoute("?view=editor")).toEqual({ view: "runs" });
    expect(parseRoute("?view=editor&repo=%2Fsrc")).toEqual({ view: "runs" });
    expect(parseRoute("?view=editor&file=main.py")).toEqual({ view: "runs" });
    // Empty strings are not paths either.
    expect(parseRoute("?view=editor&repo=&file=")).toEqual({ view: "runs" });
  });

  it("degrades junk to the runs list instead of crashing", () => {
    for (const junk of [
      "",
      "?",
      "?view=nope",
      "?view=run", // no id — must NOT become run #0 (Number(null) is 0)
      "?view=run&id=NaN",
      "?view=run&id=0", // ids are 1-based; 0 is never a row
      "?view=run&id=-2",
      "?view=run&id=1.5",
      "?id=3",
    ]) {
      expect(parseRoute(junk)).toEqual({ view: "runs" });
    }
  });

  it("round-trips every route through its own href", () => {
    const routes: Route[] = [
      { view: "runs" },
      { view: "prove" },
      { view: "logs" },
      { view: "watch" },
      { view: "composer" },
      { view: "settings" },
      { view: "run", id: 5 },
      { view: "target", id: 6 },
      { view: "divergence", id: 7 },
    ];
    for (const route of routes) {
      expect(parseRoute(routeHref(route))).toEqual(route);
    }
  });
});
