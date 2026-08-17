import { afterEach, describe, expect, it } from "vitest";

import { type SelectedTarget, selectTargets } from "../src/analyze.ts";
import { RpcError } from "../src/rpc.ts";
import { allLines, cleanupProjects, makeProject } from "./helpers.ts";

afterEach(cleanupProjects);

function bySymbol(targets: SelectedTarget[]): Map<string, SelectedTarget> {
  return new Map(targets.map((t) => [t.symbol, t]));
}

describe("changed-line → symbol resolution", () => {
  const source = [
    "export function add(a: number, b: number): number {", // 1
    "  return a + b;", // 2
    "}", // 3
    "", // 4
    "export const scale = (x: number): number => {", // 5
    "  const inner = (y: number): number => y * 2;", // 6
    "  return inner(x);", // 7
    "};", // 8
    "", // 9
    "export class Calc {", // 10
    "  static clamp(v: number): number {", // 11
    "    return v < 0 ? 0 : v;", // 12
    "  }", // 13
    "  twice(v: number): number {", // 14
    "    return v * 2;", // 15
    "  }", // 16
    "}", // 17
    "", // 18
    "export default function (n: number): number {", // 19
    "  return n - 1;", // 20
    "}", // 21
  ].join("\n");

  it("resolves lines to the innermost enclosing declaration (fn, arrow const, methods)", () => {
    const root = makeProject({ "src/mod.ts": source });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/mod.ts", changedLines: [2, 6, 7, 12, 15, 20] }],
    });
    const map = bySymbol(targets);
    expect([...map.keys()]).toEqual(["add", "scale", "scale.inner", "Calc.clamp", "Calc.twice", "default"]);
    expect(map.get("add")).toMatchObject({
      kind: "function",
      span: [1, 3],
      exported: true,
      classification: "PURE_CANDIDATE",
    });
    expect(map.get("scale")).toMatchObject({ kind: "arrowConst", span: [5, 8] });
    expect(map.get("scale.inner")).toMatchObject({ kind: "arrowConst", classification: "UNREACHABLE" });
    expect(map.get("Calc.clamp")).toMatchObject({
      kind: "staticMethod",
      classification: "PURE_CANDIDATE",
      span: [11, 13],
    });
    expect(map.get("Calc.twice")).toMatchObject({ kind: "method", classification: "UNREACHABLE" });
    expect(map.get("default")).toMatchObject({ kind: "function", exported: true, span: [19, 21] });
  });

  it("ignores changed lines outside any function-like and dedupes repeated lines", () => {
    const root = makeProject({ "src/mod.ts": source });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/mod.ts", changedLines: [4, 18, 2, 2, 3] }],
    });
    expect(targets.map((t) => t.symbol)).toEqual(["add"]);
  });

  it("resolves a change on a decorator line to the decorated method, span included", () => {
    const root = makeProject({
      "src/svc.ts": [
        "function log(): MethodDecorator {", // 1
        "  return () => undefined;", // 2
        "}", // 3
        "export class Svc {", // 4
        "  @log()", // 5
        "  run(n: number): number {", // 6
        "    return n + 1;", // 7
        "  }", // 8
        "}", // 9
      ].join("\n"),
    });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/svc.ts", changedLines: [5] }],
    });
    expect(targets).toHaveLength(1);
    expect(targets[0]).toMatchObject({ symbol: "Svc.run", span: [5, 8], kind: "method" });
  });

  it("resolves nested function declarations to the closure, not the outer function", () => {
    const root = makeProject({
      "src/nested.ts": [
        "export function outer(x: number): number {", // 1
        "  function inner(y: number): number {", // 2
        "    return y + 1;", // 3
        "  }", // 4
        "  return inner(x);", // 5
        "}", // 6
      ].join("\n"),
    });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/nested.ts", changedLines: [3, 5] }],
    });
    const map = bySymbol(targets);
    expect(map.get("outer.inner")?.classification).toBe("UNREACHABLE");
    expect(map.get("outer.inner")?.reasonDetail).toContain("closure");
    expect(map.get("outer")?.classification).toBe("PURE_CANDIDATE");
  });

  it("rejects a missing changed file with an actionable RpcError", () => {
    const root = makeProject({ "src/mod.ts": source });
    expect(() =>
      selectTargets({
        projectRoot: root,
        changedFiles: [{ path: "src/nope.ts", changedLines: [1] }],
      }),
    ).toThrowError(RpcError);
  });
});

describe("classification rules", () => {
  it("marks generator, instance members, and non-exported symbols UNREACHABLE with details", () => {
    const source = [
      "export async function fetchIt(u: string): Promise<string> {", // 1
      "  return u;", // 2
      "}", // 3
      "export function* gen(n: number): Generator<number> {", // 4
      "  yield n;", // 5
      "}", // 6
      "function hidden(a: number): number {", // 7
      "  return a;", // 8
      "}", // 9
      "const hiddenArrow = (a: number): number => a + 1;", // 10
      "export class Box {", // 11
      "  constructor(readonly v: number) {", // 12
      "    this.v = v;", // 13
      "  }", // 14
      "  get val(): number {", // 15
      "    return this.v;", // 16
      "  }", // 17
      "}", // 18
      "class PrivateSvc {", // 19
      "  static calc(n: number): number {", // 20
      "    return n * 3;", // 21
      "  }", // 22
      "}", // 23
      "function laterExported(n: number): number {", // 24
      "  return n * 5;", // 25
      "}", // 26
      "export { laterExported };", // 27
    ].join("\n");
    const root = makeProject({ "src/rules.ts": source });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/rules.ts", changedLines: allLines(source) }],
    });
    const map = bySymbol(targets);

    // ADR-0028: the execution worker awaits promises — async is runnable now.
    expect(map.get("fetchIt")).toMatchObject({ isAsync: true, classification: "PURE_CANDIDATE" });

    expect(map.get("gen")).toMatchObject({ isGenerator: true, classification: "UNREACHABLE" });
    expect(map.get("gen")?.reasonDetail).toContain("generator");

    expect(map.get("hidden")).toMatchObject({ exported: false, classification: "UNREACHABLE" });
    expect(map.get("hidden")?.reasonDetail).toContain(
      "not exported; cannot be imported in isolation",
    );
    expect(map.get("hiddenArrow")?.reasonDetail).toContain(
      "not exported; cannot be imported in isolation",
    );

    expect(map.get("Box.constructor")).toMatchObject({
      kind: "constructor",
      classification: "UNREACHABLE",
    });
    expect(map.get("Box.val")).toMatchObject({ kind: "getAccessor", classification: "UNREACHABLE" });

    // a static method is invocable — but not when its class cannot be imported
    expect(map.get("PrivateSvc.calc")).toMatchObject({
      kind: "staticMethod",
      exported: false,
      classification: "UNREACHABLE",
    });
    expect(map.get("PrivateSvc.calc")?.reasonDetail).toContain("not exported");

    // `export { name }` statements count as exported
    expect(map.get("laterExported")).toMatchObject({
      exported: true,
      classification: "PURE_CANDIDATE",
    });
  });

  it("classifies every listed IO surface as IMPURE_RECORDABLE", () => {
    const source = [
      'import { readFileSync } from "node:fs";',
      'import * as h from "http";',
      'import https from "https";',
      'import { connect } from "net";',
      'import { spawn as sp } from "child_process";',
      'import { randomUUID } from "crypto";',
      'import { createHash } from "crypto";',
      'const cp = require("child_process");',
      "export function useFs(p: string): string { return readFileSync(p, 'utf8'); }",
      "export function useHttp(): unknown { return h.STATUS_CODES; }",
      "export function useHttps(): unknown { return https.globalAgent; }",
      "export function useNet(): unknown { return connect; }",
      "export function useProc(): unknown { return sp; }",
      "export function useRequireProc(): unknown { return cp; }",
      "export function useCryptoImport(): string { return randomUUID(); }",
      "export function useCryptoGlobal(): string { return crypto.randomUUID(); }",
      "export function useEnv(): string | undefined { return process.env['HOME']; }",
      "export function useDateNow(): number { return Date.now(); }",
      "export function useNewDate(): number { return new Date().getTime(); }",
      "export function useMathRandom(): number { return Math.random(); }",
      "export function useTimer(cb: () => void): void { setTimeout(cb, 10); }",
      "export async function useFetch(u: string): Promise<number> {",
      "  const r = await fetch(u);",
      "  return r.status;",
      "}",
      "export function pureMath(a: number, b: number): number { return a * b; }",
      "export function pureHash(s: string): unknown { return createHash(s); }",
      "export function wrapsFs(p: string): string { return useFs(p); }",
      "export function wrapsWrapper(p: string): string { return wrapsFs(p); }",
    ].join("\n");
    const root = makeProject({ "src/io.ts": source });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/io.ts", changedLines: allLines(source) }],
    });
    const map = bySymbol(targets);

    const impure = [
      "useFs",
      "useHttp",
      "useHttps",
      "useNet",
      "useProc",
      "useRequireProc",
      "useCryptoImport",
      "useEnv",
      "useTimer",
      "useFetch",
    ];
    for (const symbol of impure) {
      expect(map.get(symbol)?.classification, symbol).toBe("IMPURE_RECORDABLE");
    }
    expect(map.get("pureMath")?.classification).toBe("PURE_CANDIDATE");
    // ADR-0028: Date.now / new Date / Math.random / global crypto randomness are pinned by
    // the execution worker's determinism shims — ambient-deterministic, not IO. The IMPORTED
    // node:crypto surface (useCryptoImport) binds the unpatched module and stays impure.
    for (const symbol of ["useDateNow", "useNewDate", "useMathRandom", "useCryptoGlobal"]) {
      expect(map.get(symbol)?.classification, symbol).toBe("PURE_CANDIDATE");
    }
    // crypto is only impure through its random* surface
    expect(map.get("pureHash")?.classification).toBe("PURE_CANDIDATE");
    // same-module callee scan, depth 2 (mirrors the Python classifier)
    expect(map.get("wrapsFs")?.classification).toBe("IMPURE_RECORDABLE");
    expect(map.get("wrapsWrapper")?.classification).toBe("IMPURE_RECORDABLE");
  });
});

describe("tsconfig path aliases", () => {
  it("loads the project's tsconfig and resolves aliased imports without misclassifying", () => {
    const root = makeProject({
      "tsconfig.json": JSON.stringify({
        compilerOptions: {
          target: "ES2022",
          module: "ESNext",
          moduleResolution: "bundler",
          strict: true,
          baseUrl: ".",
          paths: { "@lib/*": ["src/lib/*"] },
        },
        include: ["src"],
      }),
      "src/lib/helper.ts": "export function double(n: number): number { return n * 2; }\n",
      "src/main.ts": [
        'import { double } from "@lib/helper";',
        "",
        "export function quad(n: number): number {",
        "  return double(double(n));",
        "}",
      ].join("\n"),
    });
    const { targets } = selectTargets({
      projectRoot: root,
      changedFiles: [{ path: "src/main.ts", changedLines: [4] }],
    });
    expect(targets).toHaveLength(1);
    // "@lib" is a path alias, not an IO module — the aliased import must not poison purity
    expect(targets[0]).toMatchObject({
      symbol: "quad",
      filePath: "src/main.ts",
      exported: true,
      classification: "PURE_CANDIDATE",
    });
  });
});
