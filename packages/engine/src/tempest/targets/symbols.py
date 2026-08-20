"""Symbol extraction (changed lines → innermost enclosing defs) and classification.

UNREACHABLE targets are the product's most important honesty surface (master spec: suppressing
them is the single worst failure mode) — every one carries an actionable reason_detail.
"""

import ast
from dataclasses import dataclass

from tempest.model import ReasonCode, TargetClassification
from tempest.targets.io_surface import IO_BUILTINS, IO_MODULES


@dataclass(frozen=True)
class SymbolSpan:
    symbol: str
    span: tuple[int, int]
    nested: bool
    is_async: bool
    is_generator: bool
    owner_class: str | None
    is_static: bool
    is_classmethod: bool


@dataclass(frozen=True)
class ClassifiedSymbol:
    symbol: SymbolSpan
    classification: TargetClassification
    reason_code: ReasonCode | None
    reason_detail: str | None


type _Def = ast.FunctionDef | ast.AsyncFunctionDef


def _full_span(node: _Def) -> tuple[int, int]:
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return (start, node.end_lineno or node.lineno)


def _is_generator(node: _Def) -> bool:
    """True iff the def itself yields — yields inside nested defs don't count."""
    stack: list[ast.AST] = list(node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return False


def _collect_defs(tree: ast.Module) -> list[SymbolSpan]:
    spans: list[SymbolSpan] = []

    def visit(
        node: ast.AST, name_path: tuple[str, ...], class_ctx: str | None, fn_depth: int
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, (*name_path, child.name), child.name, fn_depth)
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                deco_names = {
                    d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                    for d in child.decorator_list
                }
                spans.append(
                    SymbolSpan(
                        symbol=".".join((*name_path, child.name)),
                        span=_full_span(child),
                        nested=fn_depth > 0,
                        is_async=isinstance(child, ast.AsyncFunctionDef),
                        is_generator=_is_generator(child),
                        owner_class=class_ctx,
                        is_static="staticmethod" in deco_names,
                        is_classmethod="classmethod" in deco_names,
                    )
                )
                visit(child, (*name_path, child.name), None, fn_depth + 1)
            else:
                visit(child, name_path, class_ctx, fn_depth)

    visit(tree, (), None, 0)
    return spans


def all_symbol_names(src: str) -> frozenset[str]:
    """Every dotted def name in the module — used to tell added symbols from changed ones."""
    return frozenset(s.symbol for s in _collect_defs(ast.parse(src)))


def enclosing_symbols(src: str, changed_lines: set[int]) -> list[SymbolSpan]:
    """The innermost def enclosing each changed line, unique, in source order."""
    tree = ast.parse(src)
    spans = _collect_defs(tree)
    chosen: dict[str, SymbolSpan] = {}
    for line in sorted(changed_lines):
        best: SymbolSpan | None = None
        for s in spans:
            lo, hi = s.span
            if lo <= line <= hi and (best is None or s.span[0] >= best.span[0]):
                best = s
        if best is not None:
            chosen[best.symbol] = best
    return sorted(chosen.values(), key=lambda s: s.span[0])


def classify_symbol(src: str, sym: SymbolSpan) -> ClassifiedSymbol:
    if sym.nested:
        return _unreachable(
            sym,
            f"`{sym.symbol}` is a closure — it only exists inside its enclosing function and "
            "cannot be imported or invoked in isolation.",
        )
    if sym.is_generator:
        return _unreachable(
            sym,
            f"`{sym.symbol}` is a generator; v1 compares concrete return values, not lazy "
            "iteration. Materialize it (e.g. a list-returning wrapper) to make it provable.",
        )
    if sym.owner_class is not None and not sym.is_static and not sym.is_classmethod:
        return _unreachable(
            sym,
            f"`{sym.symbol}` is an instance method — invoking it requires constructing "
            f"`{sym.owner_class}()`. Tempest attempts that deterministically from the class's "
            f"`__init__` (or its dataclass fields) and accepts the result only if it really "
            f"runs; this message means that attempt was not made or did not survive execution. "
            f"A @staticmethod or module-level function wrapping the logic is always provable.",
        )

    if _touches_io(src, sym):
        return ClassifiedSymbol(sym, TargetClassification.IMPURE_RECORDABLE, None, None)
    return ClassifiedSymbol(sym, TargetClassification.PURE_CANDIDATE, None, None)


def _unreachable(sym: SymbolSpan, detail: str) -> ClassifiedSymbol:
    return ClassifiedSymbol(
        sym, TargetClassification.UNREACHABLE, ReasonCode.TARGET_UNREACHABLE, detail
    )


def _touches_io(src: str, sym: SymbolSpan, depth: int = 2) -> bool:
    """Does the symbol's body (or a same-module callee, up to `depth`) reach the IO allowlist?"""
    tree = ast.parse(src)
    aliases = _import_aliases(tree)
    module_defs = {
        node.name: node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    target = _find_def(tree, sym)
    if target is None:
        return True  # cannot even locate it → treat as impure, never as provably pure
    return _scan(target, aliases, module_defs, depth, seen=set())


def _find_def(tree: ast.Module, sym: SymbolSpan) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and _full_span(node) == sym.span
        ):
            return node
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """local name → root module it came from."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            root = node.module.split(".")[0]
            for a in node.names:
                aliases[a.asname or a.name] = root
    return aliases


def _scan(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    aliases: dict[str, str],
    module_defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    depth: int,
    seen: set[str],
) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Global | ast.Nonlocal):
            return True
        if isinstance(node, ast.Name):
            root = aliases.get(node.id)
            if root in IO_MODULES:
                return True
            if node.id in IO_BUILTINS and node.id not in module_defs:
                return True
        if isinstance(node, ast.Call):
            callee = node.func
            if (
                isinstance(callee, ast.Name)
                and callee.id in module_defs
                and callee.id not in seen
                and depth > 0
            ):
                seen.add(callee.id)
                if _scan(module_defs[callee.id], aliases, module_defs, depth - 1, seen):
                    return True
    return False
