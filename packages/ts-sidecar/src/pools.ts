/**
 * Type→value pools: for each parameter of a target symbol, a deterministic JSON pool of candidate
 * values mirroring the Python edge pools (`tempest/generate/strategies.py`). Non-JSON numerics
 * (NaN, Infinity, -Infinity) and `undefined` travel as strings in a `specials` field. A type we
 * cannot understand yields the mixed pool with `typed: false` — a labeled guess, never a silent one.
 */
import { type Node, SymbolFlags, type Type } from "ts-morph";

import { collectSymbols } from "./analyze.ts";
import { absolutePath, loadProject, relativePosixPath } from "./project.ts";
import { INVALID_PARAMS, RpcError } from "./rpc.ts";

export interface ValuePoolsParams {
  projectRoot: string;
  filePath: string;
  symbol: string;
}

export interface ParamPool {
  name: string;
  typeText: string;
  optional: boolean;
  typed: boolean;
  values: unknown[];
  specials: string[];
}

export interface ValuePoolsResult {
  symbol: string;
  filePath: string;
  parameters: ParamPool[];
}

const NUMBER_VALUES: readonly number[] = [0, 1, -1, 2 ** 31 - 1, -(2 ** 31), 1e6, 0.5];
const NUMBER_SPECIALS: readonly string[] = ["NaN", "Infinity", "-Infinity"];
const STRING_VALUES: readonly string[] = ["", "a", "abc", " ", "ünïcode-✓", "line\nbreak"];
const MIXED_VALUES: readonly unknown[] = [
  0,
  1,
  -1,
  0.5,
  1e6,
  "",
  "a",
  "abc",
  " ",
  true,
  false,
  null,
  [1, 2, 3],
  [],
  { k: 1 },
];
const MAX_POOL_SIZE = 80;
const MAX_DEPTH = 3;

interface Pool {
  values: unknown[];
  specials: string[];
  typed: boolean;
}

export function valuePools(params: ValuePoolsParams): ValuePoolsResult {
  const project = loadProject(params.projectRoot, [params.filePath]);
  const abs = absolutePath(params.projectRoot, params.filePath);
  const sourceFile = project.getSourceFile(abs);
  if (sourceFile === undefined) {
    throw new RpcError(INVALID_PARAMS, `file not loaded into project: ${abs}`);
  }
  const symbols = collectSymbols(sourceFile);
  const target = symbols.find((s) => s.symbol === params.symbol);
  if (target === undefined) {
    const known = symbols.map((s) => s.symbol).sort();
    throw new RpcError(
      INVALID_PARAMS,
      `symbol not found: \`${params.symbol}\` in ${params.filePath}. ` +
        `Known symbols: ${known.length > 0 ? known.join(", ") : "(none)"}`,
    );
  }
  const parameters: ParamPool[] = target.node.getParameters().map((parameter) => {
    const type = parameter.getType();
    const pool = poolForType(type, MAX_DEPTH, parameter);
    const optional = parameter.isOptional();
    const specials = dedupeStrings(optional ? [...pool.specials, "undefined"] : pool.specials);
    return {
      name: parameter.getName(),
      typeText: type.getText(parameter),
      optional,
      typed: pool.typed,
      values: dedupeValues(pool.values).slice(0, MAX_POOL_SIZE),
      specials,
    };
  });
  return {
    symbol: params.symbol,
    filePath: relativePosixPath(params.projectRoot, sourceFile),
    parameters,
  };
}

function poolForType(type: Type, depth: number, location: Node): Pool {
  if (depth <= 0) {
    return mixedPool();
  }
  if (type.isBoolean()) {
    return typed([true, false]);
  }
  if (type.isBooleanLiteral()) {
    return typed([type.getText() === "true"]);
  }
  if (type.isNumber()) {
    return { values: [...NUMBER_VALUES], specials: [...NUMBER_SPECIALS], typed: true };
  }
  if (type.isString()) {
    return typed([...STRING_VALUES]);
  }
  if (type.isNumberLiteral() || type.isStringLiteral() || type.isEnumLiteral()) {
    const literal = type.getLiteralValue();
    return literal === undefined ? mixedPool() : typed([literal]);
  }
  if (type.isNull()) {
    return typed([null]);
  }
  if (type.isUndefined() || isVoidLike(type)) {
    return { values: [], specials: ["undefined"], typed: true };
  }
  if (type.isUnion()) {
    return unionPool(type, depth, location);
  }
  if (type.isTuple()) {
    return tuplePool(type, depth, location);
  }
  if (type.isArray() || type.isReadonlyArray()) {
    return arrayPool(type, depth, location);
  }
  if (
    type.isAny() ||
    type.isUnknown() ||
    type.isNever() ||
    type.isTypeParameter() ||
    type.isClass() ||
    type.getCallSignatures().length > 0
  ) {
    return mixedPool();
  }
  if (type.isObject()) {
    return objectPool(type, depth, location);
  }
  return mixedPool();
}

/** Union member pools concatenated in declaration order (strategies.py union handling). */
function unionPool(type: Type, depth: number, location: Node): Pool {
  const values: unknown[] = [];
  const specials: string[] = [];
  let typed = true;
  for (const member of type.getUnionTypes()) {
    const pool = poolForType(member, depth, location);
    values.push(...pool.values);
    specials.push(...pool.specials);
    typed = typed && pool.typed;
  }
  return { values, specials: dedupeStrings(specials), typed };
}

function tuplePool(type: Type, depth: number, location: Node): Pool {
  const members = type.getTupleElements().map((member) => poolForType(member, depth - 1, location));
  const tuple = members.map((pool) => pool.values[0] ?? null);
  return {
    values: [tuple],
    specials: [],
    typed: members.every((pool) => pool.typed),
  };
}

/** Mirror of the Python list edges: `[[], [e0], edges, edges×2]`. */
function arrayPool(type: Type, depth: number, location: Node): Pool {
  const elementType = type.getArrayElementType() ?? type.getTypeArguments()[0];
  if (elementType === undefined) {
    return mixedPool();
  }
  const element = poolForType(elementType, depth - 1, location);
  const edges = element.values.slice(0, 4);
  const values: unknown[] = [[]];
  if (edges.length > 0) {
    values.push([edges[0]], edges, [...edges, ...edges]);
  }
  return { values, specials: [], typed: element.typed };
}

/** Index-signature types mirror the Python dict edges; property types build structural objects. */
function objectPool(type: Type, depth: number, location: Node): Pool {
  const stringIndexType = type.getStringIndexType();
  if (stringIndexType !== undefined) {
    const valuePool = poolForType(stringIndexType, depth - 1, location);
    const keys = STRING_VALUES.slice(0, 3);
    const entry: Record<string, unknown> = {};
    keys.forEach((key, i) => {
      if (i < valuePool.values.length) {
        entry[key] = valuePool.values[i];
      }
    });
    return { values: [{}, entry], specials: [], typed: valuePool.typed };
  }
  const properties = type.getProperties().slice(0, 6);
  if (properties.length === 0) {
    return typed([{}]);
  }
  const propertyTypes = properties.map((property) => property.getTypeAtLocation(location));
  if (propertyTypes.some((propertyType) => propertyType.getCallSignatures().length > 0)) {
    // Method-bearing shapes (Date, class instances behind interfaces, callback-carrying
    // configs) cannot travel as JSON — a labeled mixed guess, never a fake structural object.
    return mixedPool();
  }
  const first: Record<string, unknown> = {};
  const requiredOnly: Record<string, unknown> = {};
  let typedAll = true;
  for (const [i, property] of properties.entries()) {
    const propertyType = propertyTypes[i];
    if (propertyType === undefined) {
      continue;
    }
    const pool = poolForType(propertyType, depth - 1, location);
    typedAll = typedAll && pool.typed;
    first[property.getName()] = pool.values[0] ?? null;
    if (!property.hasFlags(SymbolFlags.Optional)) {
      requiredOnly[property.getName()] = pool.values[1] ?? pool.values[0] ?? null;
    }
  }
  return { values: [first, requiredOnly], specials: [], typed: typedAll };
}

function isVoidLike(type: Type): boolean {
  return type.getText() === "void";
}

function mixedPool(): Pool {
  return { values: [...MIXED_VALUES], specials: [], typed: false };
}

function typed(values: unknown[]): Pool {
  return { values, specials: [], typed: true };
}

function dedupeValues(values: readonly unknown[]): unknown[] {
  const seen = new Set<string>();
  const out: unknown[] = [];
  for (const value of values) {
    const key = JSON.stringify(value) ?? "undefined";
    if (!seen.has(key)) {
      seen.add(key);
      out.push(value);
    }
  }
  return out;
}

function dedupeStrings(values: readonly string[]): string[] {
  return [...new Set(values)];
}
