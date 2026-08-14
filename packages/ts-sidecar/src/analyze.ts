/**
 * Stage-1 target selection for TypeScript: changed lines → innermost enclosing function-like
 * declaration → classification. Mirrors the Python side (`tempest/targets/symbols.py`):
 * UNREACHABLE is the honesty surface — every one carries an actionable reasonDetail.
 *
 * TS-specific rule with no Python counterpart: a module-level symbol that is not exported cannot
 * be reached by `import`/`require` at all, so it is UNREACHABLE ("not exported; cannot be
 * imported in isolation") rather than silently dropped.
 */
import {
  type ArrowFunction,
  type ClassDeclaration,
  type ConstructorDeclaration,
  type FunctionDeclaration,
  type FunctionExpression,
  type GetAccessorDeclaration,
  type MethodDeclaration,
  Node,
  type SetAccessorDeclaration,
  type SourceFile,
} from "ts-morph";

import { absolutePath, loadProject, relativePosixPath } from "./project.ts";
import { INVALID_PARAMS, RpcError } from "./rpc.ts";

export type FunctionLikeNode =
  | FunctionDeclaration
  | MethodDeclaration
  | ConstructorDeclaration
  | GetAccessorDeclaration
  | SetAccessorDeclaration
  | ArrowFunction
  | FunctionExpression;

export type SymbolKind =
  | "function"
  | "arrowConst"
  | "functionExpressionConst"
  | "method"
  | "staticMethod"
  | "constructor"
  | "getAccessor"
  | "setAccessor";

export type Classification = "PURE_CANDIDATE" | "IMPURE_RECORDABLE" | "UNREACHABLE";

export interface SelectedTarget {
  symbol: string;
  filePath: string;
  span: [number, number];
  exported: boolean;
  kind: SymbolKind;
  isAsync: boolean;
  isGenerator: boolean;
  classification: Classification;
  reasonDetail?: string;
}

export interface ChangedFile {
  path: string;
  changedLines: number[];
}

export interface SelectTargetsParams {
  projectRoot: string;
  changedFiles: ChangedFile[];
}

/** One named function-like found in a source file (nested ones included — they classify as closures). */
export interface CollectedSymbol {
  node: FunctionLikeNode;
  symbol: string;
  kind: SymbolKind;
  span: [number, number];
  startOffset: number;
  nested: boolean;
  isAsync: boolean;
  isGenerator: boolean;
  ownerClass: ClassDeclaration | undefined;
  isStatic: boolean;
}

/** IO surfaces whose mere reference makes a symbol IMPURE_RECORDABLE (TS mirror of io_surface.py). */
const IO_MODULES: ReadonlySet<string> = new Set(["fs", "http", "https", "net", "child_process"]);
const IO_GLOBALS: ReadonlySet<string> = new Set(["setTimeout"]);
const CRYPTO_RANDOM = /^(random|getRandomValues)/;
const CALLEE_SCAN_DEPTH = 2;

export function selectTargets(params: SelectTargetsParams): { targets: SelectedTarget[] } {
  const project = loadProject(
    params.projectRoot,
    params.changedFiles.map((f) => f.path),
  );
  const targets: SelectedTarget[] = [];
  for (const changed of params.changedFiles) {
    const abs = absolutePath(params.projectRoot, changed.path);
    const sourceFile = project.getSourceFile(abs);
    if (sourceFile === undefined) {
      throw new RpcError(INVALID_PARAMS, `file not loaded into project: ${abs}`);
    }
    const filePath = relativePosixPath(params.projectRoot, sourceFile);
    const symbols = collectSymbols(sourceFile);
    const exportedNodes = exportedDeclarationNodes(sourceFile);
    const context = buildScanContext(sourceFile, symbols);
    for (const symbol of enclosingSymbols(symbols, changed.changedLines)) {
      targets.push(classifySymbol(symbol, filePath, exportedNodes, context));
    }
  }
  return { targets };
}

/** The innermost symbol enclosing each changed line, unique, in source order (symbols.py mirror). */
export function enclosingSymbols(
  symbols: readonly CollectedSymbol[],
  changedLines: readonly number[],
): CollectedSymbol[] {
  const chosen = new Map<string, CollectedSymbol>();
  for (const line of [...changedLines].sort((a, b) => a - b)) {
    let best: CollectedSymbol | undefined;
    for (const s of symbols) {
      const [lo, hi] = s.span;
      if (lo <= line && line <= hi && (best === undefined || s.startOffset >= best.startOffset)) {
        best = s;
      }
    }
    if (best !== undefined) {
      chosen.set(best.symbol, best);
    }
  }
  return [...chosen.values()].sort(
    (a, b) => a.span[0] - b.span[0] || a.startOffset - b.startOffset,
  );
}

export function collectSymbols(sourceFile: SourceFile): CollectedSymbol[] {
  const collected: CollectedSymbol[] = [];
  sourceFile.forEachDescendant((node) => {
    if (!isFunctionLike(node) || !hasBody(node)) {
      return;
    }
    const ownName = nameComponentOf(node);
    if (ownName === undefined) {
      return; // anonymous callbacks belong to their enclosing named symbol, like Python lambdas
    }
    const pathParts: string[] = [];
    let ownerClass: ClassDeclaration | undefined;
    let nested = false;
    for (const ancestor of node.getAncestors()) {
      if (Node.isClassDeclaration(ancestor)) {
        pathParts.unshift(ancestor.getName() ?? "default");
        if (ownerClass === undefined && isDirectClassMember(node, ancestor)) {
          ownerClass = ancestor;
        }
      } else if (isFunctionLike(ancestor)) {
        nested = true;
        const component = nameComponentOf(ancestor);
        if (component !== undefined) {
          pathParts.unshift(component);
        }
      }
    }
    collected.push({
      node,
      symbol: [...pathParts, ownName].join("."),
      kind: kindOf(node),
      span: spanOf(node),
      startOffset: node.getStart(),
      nested,
      isAsync: isAsyncNode(node),
      isGenerator: isGeneratorNode(node),
      ownerClass,
      isStatic: Node.isMethodDeclaration(node) ? node.isStatic() : false,
    });
  });
  return collected;
}

function classifySymbol(
  s: CollectedSymbol,
  filePath: string,
  exportedNodes: ReadonlySet<Node>,
  context: ScanContext,
): SelectedTarget {
  const exported = isExportedSymbol(s, exportedNodes);
  const base = {
    symbol: s.symbol,
    filePath,
    span: s.span,
    exported,
    kind: s.kind,
    isAsync: s.isAsync,
    isGenerator: s.isGenerator,
  };
  const unreachable = (reasonDetail: string): SelectedTarget => ({
    ...base,
    classification: "UNREACHABLE",
    reasonDetail,
  });

  if (s.nested) {
    return unreachable(
      `\`${s.symbol}\` is a closure — it only exists inside its enclosing function and cannot ` +
        "be imported or invoked in isolation.",
    );
  }
  if (s.isAsync) {
    return unreachable(
      `\`${s.symbol}\` is an async function; v1 invokes synchronous callables only. ` +
        "Wrap the logic in a sync function to make it provable.",
    );
  }
  if (s.isGenerator) {
    return unreachable(
      `\`${s.symbol}\` is a generator; v1 compares concrete return values, not lazy iteration. ` +
        "Materialize it (e.g. an array-returning wrapper) to make it provable.",
    );
  }
  const className = s.ownerClass?.getName() ?? "default";
  if (s.kind === "constructor") {
    return unreachable(
      `\`${s.symbol}\` is a constructor — v1 does not synthesize instances. ` +
        "Move the logic into a static method or module-level function to make it provable.",
    );
  }
  if (s.kind === "getAccessor" || s.kind === "setAccessor") {
    return unreachable(
      `\`${s.symbol}\` is a property accessor — invoking it requires constructing ` +
        `\`${className}\`, and v1 does not synthesize instances. A static method or ` +
        "module-level function wrapping the logic is provable.",
    );
  }
  if (s.kind === "method") {
    return unreachable(
      `\`${s.symbol}\` is an instance method — invoking it requires constructing ` +
        `\`${className}\`, and v1 does not synthesize instances. A static method or ` +
        "module-level function wrapping the logic is provable.",
    );
  }
  if (!exported) {
    return unreachable(
      `\`${s.symbol}\` is not exported; cannot be imported in isolation. ` +
        "Export it (or an exported wrapper around it) to make it provable.",
    );
  }
  if (touchesIo(s.node, context, CALLEE_SCAN_DEPTH, new Set())) {
    return { ...base, classification: "IMPURE_RECORDABLE" };
  }
  return { ...base, classification: "PURE_CANDIDATE" };
}

function isExportedSymbol(s: CollectedSymbol, exportedNodes: ReadonlySet<Node>): boolean {
  if (s.nested) {
    return false;
  }
  if (s.ownerClass !== undefined) {
    return exportedNodes.has(s.ownerClass);
  }
  const node: Node = s.node;
  if (Node.isArrowFunction(node) || Node.isFunctionExpression(node)) {
    const parent = node.getParent();
    return Node.isVariableDeclaration(parent) && exportedNodes.has(parent);
  }
  return exportedNodes.has(node);
}

/** Every declaration node reachable through this file's exports (covers `export {x}` and default). */
function exportedDeclarationNodes(sourceFile: SourceFile): Set<Node> {
  const nodes = new Set<Node>();
  for (const declarations of sourceFile.getExportedDeclarations().values()) {
    for (const declaration of declarations) {
      nodes.add(declaration);
    }
  }
  return nodes;
}

// ---------------------------------------------------------------------------
// Impurity scan (TS mirror of symbols.py `_touches_io`): the body — or a same-module callee up
// to CALLEE_SCAN_DEPTH — referencing an IO surface makes the symbol IMPURE_RECORDABLE.
// ---------------------------------------------------------------------------

interface ImportedBinding {
  root: string;
  imported: string; // original exported name, or "*" (namespace/require) or "default"
}

export interface ScanContext {
  aliases: ReadonlyMap<string, ImportedBinding>;
  moduleFunctions: ReadonlyMap<string, FunctionLikeNode>;
}

export function buildScanContext(
  sourceFile: SourceFile,
  symbols: readonly CollectedSymbol[],
): ScanContext {
  const aliases = new Map<string, ImportedBinding>();
  for (const importDecl of sourceFile.getImportDeclarations()) {
    const root = rootModule(importDecl.getModuleSpecifierValue());
    const defaultImport = importDecl.getDefaultImport();
    if (defaultImport !== undefined) {
      aliases.set(defaultImport.getText(), { root, imported: "default" });
    }
    const namespaceImport = importDecl.getNamespaceImport();
    if (namespaceImport !== undefined) {
      aliases.set(namespaceImport.getText(), { root, imported: "*" });
    }
    for (const named of importDecl.getNamedImports()) {
      const imported = named.getNameNode().getText();
      const local = named.getAliasNode()?.getText() ?? imported;
      aliases.set(local, { root, imported });
    }
  }
  collectRequireAliases(sourceFile, aliases);
  const moduleFunctions = new Map<string, FunctionLikeNode>();
  for (const s of symbols) {
    if (!s.nested && s.ownerClass === undefined) {
      moduleFunctions.set(s.symbol, s.node);
    }
  }
  return { aliases, moduleFunctions };
}

/** `const fs = require("fs")` / `const { readFileSync } = require("fs")` at module level. */
function collectRequireAliases(
  sourceFile: SourceFile,
  aliases: Map<string, ImportedBinding>,
): void {
  for (const statement of sourceFile.getVariableStatements()) {
    for (const declaration of statement.getDeclarations()) {
      const initializer = declaration.getInitializer();
      if (
        initializer === undefined ||
        !Node.isCallExpression(initializer) ||
        initializer.getExpression().getText() !== "require"
      ) {
        continue;
      }
      const [argument] = initializer.getArguments();
      if (argument === undefined || !Node.isStringLiteral(argument)) {
        continue;
      }
      const root = rootModule(argument.getLiteralValue());
      const nameNode = declaration.getNameNode();
      if (Node.isIdentifier(nameNode)) {
        aliases.set(nameNode.getText(), { root, imported: "*" });
      } else if (Node.isObjectBindingPattern(nameNode)) {
        for (const element of nameNode.getElements()) {
          const local = element.getNameNode().getText();
          const imported = element.getPropertyNameNode()?.getText() ?? local;
          aliases.set(local, { root, imported });
        }
      }
    }
  }
}

function rootModule(specifier: string): string {
  const bare = specifier.startsWith("node:") ? specifier.slice(5) : specifier;
  return bare.split("/")[0] ?? bare;
}

export function touchesIo(
  fn: FunctionLikeNode,
  context: ScanContext,
  depth: number,
  seen: Set<string>,
): boolean {
  let found = false;
  fn.forEachDescendant((node, traversal) => {
    if (referencesIoSurface(node, context) || callsIoCallee(node, context, depth, seen)) {
      found = true;
      traversal.stop();
    }
  });
  return found;
}

function referencesIoSurface(node: Node, context: ScanContext): boolean {
  if (Node.isIdentifier(node)) {
    const parent = node.getParent();
    if (Node.isPropertyAccessExpression(parent) && parent.getNameNode() === node) {
      return false; // `x.setTimeout` — property names are checked at the access expression
    }
    const text = node.getText();
    const binding = context.aliases.get(text);
    if (binding !== undefined) {
      if (IO_MODULES.has(binding.root)) {
        return true;
      }
      if (binding.root === "crypto" && CRYPTO_RANDOM.test(binding.imported)) {
        return true;
      }
    }
    return IO_GLOBALS.has(text) && !context.moduleFunctions.has(text);
  }
  if (Node.isPropertyAccessExpression(node)) {
    const expression = node.getExpression();
    if (!Node.isIdentifier(expression)) {
      return false;
    }
    const objectName = expression.getText();
    const root = context.aliases.get(objectName)?.root ?? objectName;
    const property = node.getName();
    return (
      (root === "process" && property === "env") ||
      (objectName === "Date" && property === "now") ||
      (objectName === "Math" && property === "random") ||
      (root === "crypto" && CRYPTO_RANDOM.test(property))
    );
  }
  if (Node.isNewExpression(node)) {
    return node.getExpression().getText() === "Date";
  }
  if (Node.isCallExpression(node)) {
    const callee = node.getExpression();
    if (Node.isIdentifier(callee) && callee.getText() === "require") {
      const [argument] = node.getArguments();
      return (
        argument !== undefined &&
        Node.isStringLiteral(argument) &&
        IO_MODULES.has(rootModule(argument.getLiteralValue()))
      );
    }
  }
  return false;
}

function callsIoCallee(node: Node, context: ScanContext, depth: number, seen: Set<string>): boolean {
  if (!Node.isCallExpression(node) || depth <= 0) {
    return false;
  }
  const callee = node.getExpression();
  if (!Node.isIdentifier(callee)) {
    return false;
  }
  const name = callee.getText();
  const target = context.moduleFunctions.get(name);
  if (target === undefined || seen.has(name)) {
    return false;
  }
  seen.add(name);
  return touchesIo(target, context, depth - 1, seen);
}

// ---------------------------------------------------------------------------
// Node-shape helpers
// ---------------------------------------------------------------------------

function isFunctionLike(node: Node): node is FunctionLikeNode {
  return (
    Node.isFunctionDeclaration(node) ||
    Node.isMethodDeclaration(node) ||
    Node.isConstructorDeclaration(node) ||
    Node.isGetAccessorDeclaration(node) ||
    Node.isSetAccessorDeclaration(node) ||
    Node.isArrowFunction(node) ||
    Node.isFunctionExpression(node)
  );
}

function hasBody(node: FunctionLikeNode): boolean {
  return Node.isArrowFunction(node) || node.getBody() !== undefined;
}

function isDirectClassMember(node: FunctionLikeNode, classDecl: ClassDeclaration): boolean {
  return (
    (Node.isMethodDeclaration(node) ||
      Node.isConstructorDeclaration(node) ||
      Node.isGetAccessorDeclaration(node) ||
      Node.isSetAccessorDeclaration(node)) &&
    node.getParent() === classDecl
  );
}

/** The symbol-path component a function-like contributes; undefined = anonymous. */
function nameComponentOf(node: FunctionLikeNode): string | undefined {
  if (Node.isFunctionDeclaration(node)) {
    return node.getName() ?? "default";
  }
  if (Node.isConstructorDeclaration(node)) {
    return "constructor";
  }
  if (
    Node.isMethodDeclaration(node) ||
    Node.isGetAccessorDeclaration(node) ||
    Node.isSetAccessorDeclaration(node)
  ) {
    return node.getName();
  }
  const parent = node.getParent();
  if (Node.isVariableDeclaration(parent) && Node.isIdentifier(parent.getNameNode())) {
    return parent.getName();
  }
  return undefined;
}

function kindOf(node: FunctionLikeNode): SymbolKind {
  if (Node.isFunctionDeclaration(node)) {
    return "function";
  }
  if (Node.isArrowFunction(node)) {
    return "arrowConst";
  }
  if (Node.isFunctionExpression(node)) {
    return "functionExpressionConst";
  }
  if (Node.isConstructorDeclaration(node)) {
    return "constructor";
  }
  if (Node.isGetAccessorDeclaration(node)) {
    return "getAccessor";
  }
  if (Node.isSetAccessorDeclaration(node)) {
    return "setAccessor";
  }
  return node.isStatic() ? "staticMethod" : "method";
}

/**
 * Inclusive 1-based line span. Decorators are inside the node's span (probe-verified); for
 * variable-bound functions the span starts at the `const`/`export const` statement so the
 * declaration line itself resolves to the symbol (symbols.py includes the decorator/def line).
 */
function spanOf(node: FunctionLikeNode): [number, number] {
  if (Node.isArrowFunction(node) || Node.isFunctionExpression(node)) {
    const parent = node.getParent();
    if (Node.isVariableDeclaration(parent)) {
      const statement = parent.getVariableStatement();
      if (statement !== undefined) {
        return [statement.getStartLineNumber(), statement.getEndLineNumber()];
      }
    }
  }
  return [node.getStartLineNumber(), node.getEndLineNumber()];
}

function isAsyncNode(node: FunctionLikeNode): boolean {
  return (
    (Node.isFunctionDeclaration(node) ||
      Node.isMethodDeclaration(node) ||
      Node.isArrowFunction(node) ||
      Node.isFunctionExpression(node)) &&
    node.isAsync()
  );
}

function isGeneratorNode(node: FunctionLikeNode): boolean {
  return (
    (Node.isFunctionDeclaration(node) ||
      Node.isMethodDeclaration(node) ||
      Node.isFunctionExpression(node)) &&
    node.isGenerator()
  );
}
