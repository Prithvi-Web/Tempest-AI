import { afterEach, describe, expect, it } from "vitest";

import { valuePools } from "../src/pools.ts";
import { RpcError } from "../src/rpc.ts";
import { cleanupProjects, makeProject } from "./helpers.ts";

afterEach(cleanupProjects);

const PRIMITIVES = [
  "export function combine(n: number, s: string, flag: boolean): string {",
  "  return flag ? s : String(n);",
  "}",
].join("\n");

describe("valuePools", () => {
  it("compiles number/string/boolean edge pools with specials for non-JSON numerics", () => {
    const root = makeProject({ "src/mod.ts": PRIMITIVES });
    const { symbol, filePath, parameters } = valuePools({
      projectRoot: root,
      filePath: "src/mod.ts",
      symbol: "combine",
    });
    expect(symbol).toBe("combine");
    expect(filePath).toBe("src/mod.ts");
    expect(parameters).toHaveLength(3);

    const [n, s, flag] = parameters;
    expect(n).toMatchObject({ name: "n", typeText: "number", optional: false, typed: true });
    expect(n?.values).toEqual([0, 1, -1, 2147483647, -2147483648, 1000000, 0.5]);
    expect(n?.specials).toEqual(["NaN", "Infinity", "-Infinity"]);

    expect(s?.typed).toBe(true);
    expect(s?.values).toEqual(["", "a", "abc", " ", "ünïcode-✓", "line\nbreak"]);
    expect(s?.specials).toEqual([]);

    expect(flag?.values).toEqual([true, false]);
  });

  it("builds array pools from element edges", () => {
    const root = makeProject({
      "src/mod.ts": "export function total(xs: number[]): number { return xs.length; }",
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "total" });
    const [xs] = parameters;
    expect(xs?.typed).toBe(true);
    expect(xs?.values[0]).toEqual([]);
    expect(xs?.values[1]).toEqual([0]);
    expect(xs?.values[2]).toEqual([0, 1, -1, 2147483647]);
    expect(xs?.values[3]).toEqual([0, 1, -1, 2147483647, 0, 1, -1, 2147483647]);
  });

  it("concatenates union member pools and carries null through", () => {
    const root = makeProject({
      "src/mod.ts":
        "export function pick(v: number | string | null): string { return String(v); }",
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "pick" });
    const [v] = parameters;
    expect(v?.typed).toBe(true);
    expect(v?.values).toContain(0);
    expect(v?.values).toContain("");
    expect(v?.values).toContain(null);
    expect(v?.specials).toContain("NaN");
  });

  it("marks optional parameters and adds the undefined special", () => {
    const root = makeProject({
      "src/mod.ts": "export function opt(n?: number): number { return n ?? 0; }",
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "opt" });
    const [n] = parameters;
    expect(n?.optional).toBe(true);
    expect(n?.typed).toBe(true);
    expect(n?.values).toContain(0);
    expect(n?.specials).toContain("NaN");
    expect(n?.specials).toContain("undefined");
  });

  it("falls back to the mixed pool with typed:false for unknown and class-instance types", () => {
    const root = makeProject({
      "src/mod.ts": [
        "export function anyIn(v: unknown, d: Date): number {",
        "  return v === d ? 1 : 0;",
        "}",
      ].join("\n"),
    });
    const { parameters } = valuePools({
      projectRoot: root,
      filePath: "src/mod.ts",
      symbol: "anyIn",
    });
    for (const parameter of parameters) {
      expect(parameter.typed).toBe(false);
      expect(parameter.values).toContain(0);
      expect(parameter.values).toContain("");
      expect(parameter.values).toContain(true);
      expect(parameter.values).toContain(null);
    }
  });

  it("builds structural objects for interface types (full + required-only)", () => {
    const root = makeProject({
      "src/mod.ts": [
        "interface Point { x: number; y?: number }",
        "export function norm(p: Point): number { return p.x + (p.y ?? 0); }",
      ].join("\n"),
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "norm" });
    const [p] = parameters;
    expect(p?.typed).toBe(true);
    expect(p?.values[0]).toEqual({ x: 0, y: 0 });
    expect(p?.values[1]).toEqual({ x: 1 });
  });

  it("mirrors the dict edges for index-signature types", () => {
    const root = makeProject({
      "src/mod.ts": [
        "export function tally(m: Record<string, number>): number {",
        "  return Object.keys(m).length;",
        "}",
      ].join("\n"),
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "tally" });
    const [m] = parameters;
    expect(m?.typed).toBe(true);
    expect(m?.values[0]).toEqual({});
    expect(m?.values[1]).toEqual({ "": 0, a: 1, abc: -1 });
  });

  it("resolves parameter types through tsconfig path aliases", () => {
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
      "src/lib/types.ts": "export interface Vec { x: number; y: number }\n",
      "src/main.ts": [
        'import type { Vec } from "@lib/types";',
        "export function mag(v: Vec): number { return v.x * v.x + v.y * v.y; }",
      ].join("\n"),
    });
    const { parameters } = valuePools({ projectRoot: root, filePath: "src/main.ts", symbol: "mag" });
    const [v] = parameters;
    expect(v?.typed).toBe(true);
    expect(v?.values[0]).toEqual({ x: 0, y: 0 });
  });

  it("addresses methods by their dotted symbol path", () => {
    const root = makeProject({
      "src/mod.ts": [
        "export class Calc {",
        "  static clamp(v: number, lo: number): number {",
        "    return v < lo ? lo : v;",
        "  }",
        "}",
      ].join("\n"),
    });
    const { parameters } = valuePools({
      projectRoot: root,
      filePath: "src/mod.ts",
      symbol: "Calc.clamp",
    });
    expect(parameters.map((p) => p.name)).toEqual(["v", "lo"]);
  });

  it("is deterministic: two runs produce byte-identical pools", () => {
    const root = makeProject({
      "src/mod.ts": [
        "interface Cfg { name: string; retries?: number }",
        "export function go(c: Cfg, tags: string[], mode: 'a' | 'b'): string {",
        "  return c.name + tags.length + mode;",
        "}",
      ].join("\n"),
    });
    const call = (): unknown =>
      valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "go" });
    expect(JSON.stringify(call())).toBe(JSON.stringify(call()));
  });

  it("rejects an unknown symbol with the known-symbol list", () => {
    const root = makeProject({ "src/mod.ts": PRIMITIVES });
    try {
      valuePools({ projectRoot: root, filePath: "src/mod.ts", symbol: "nope" });
      expect.unreachable("expected RpcError");
    } catch (err) {
      expect(err).toBeInstanceOf(RpcError);
      expect((err as RpcError).message).toContain("symbol not found");
      expect((err as RpcError).message).toContain("combine");
    }
  });
});
