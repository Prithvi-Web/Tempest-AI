"""Type-derived value pools: curated edge cases + Hypothesis `from_type` examples + mined
constants. Every emitted value round-trips repr → ast.literal_eval (the transport invariant).
"""

import ast
import contextlib
import math
import random
from typing import Any

from hypothesis import given, seed, settings
from hypothesis import strategies as st

_SAFE_NAMES: dict[str, object] = {
    "int": int,
    "str": str,
    "float": float,
    "bool": bool,
    "bytes": bytes,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "frozenset": frozenset,
    "None": None,
    "NoneType": type(None),
    "object": object,
    "Any": object,
    "Optional": None,  # replaced below via typing
    "List": list,
    "Dict": dict,
    "Tuple": tuple,
    "Set": set,
}


def parse_annotation(text: str) -> object | None:
    """Safely evaluate a type annotation string against a fixed namespace of builtin types.

    Anything referencing unknown names — user classes, callables, dunder tricks — returns None
    (→ mixed-pool generation). Nothing here can execute user code: the AST is validated to be
    names/subscripts/tuples/BinOp(|) only before evaluation.
    """
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    if not _is_type_expression(tree.body):
        return None
    import typing

    namespace = dict(_SAFE_NAMES)
    namespace["Optional"] = typing.Optional
    try:
        result: object = eval(  # AST-validated: names/subscripts/| only, fixed namespace
            compile(tree, "<annotation>", "eval"), {"__builtins__": {}}, namespace
        )
    except Exception:
        return None
    return result


def _is_type_expression(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _SAFE_NAMES
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Subscript):
        return _is_type_expression(node.value) and _is_type_expression_or_tuple(node.slice)
    if isinstance(node, ast.BinOp):
        return (
            isinstance(node.op, ast.BitOr)
            and _is_type_expression(node.left)
            and _is_type_expression(node.right)
        )
    return False


def _is_type_expression_or_tuple(node: ast.expr) -> bool:
    if isinstance(node, ast.Tuple):
        return all(_is_type_expression(e) for e in node.elts)
    return _is_type_expression(node)


_EDGE_CASES: dict[object, list[object]] = {
    int: [0, 1, -1, 2, 7, -13, 255, 256, -256, 10**6, 2**31 - 1, -(2**31), 2**63],
    float: [0.0, -0.0, 1.0, -1.5, 0.5, 1e-9, 1e300, -1e300, math.inf, -math.inf, math.nan],
    str: ["", "a", "abc", " ", "0", "None", "hello world", "ünïcode-✓", "line\nbreak", "'quoted'"],
    bool: [True, False],
    bytes: [b"", b"\x00", b"abc", b"\xff\xfe"],
}


def _literal_ok(value: object) -> bool:
    from tempest.compare.canonical import parse_input_literal

    try:
        parsed = parse_input_literal(repr(value))
    except (ValueError, SyntaxError, RecursionError):
        return False
    if isinstance(value, float) and math.isnan(value):
        return isinstance(parsed, float) and math.isnan(parsed)
    return bool(parsed == value) and type(parsed) is type(value)


def _hypothesis_examples(strategy: st.SearchStrategy[Any], count: int) -> list[object]:
    collected: list[object] = []

    # Explicit @seed, NOT derandomize=True: derandomize derives its stream from a digest of the
    # test function (source/path-dependent), so a frozen PyInstaller runtime generated different
    # inputs than the venv CLI — caught by the cli-vs-desktop parity gate. A literal seed is
    # identical in every runtime.
    @seed(1729)
    @settings(max_examples=count, database=None, deadline=None)
    @given(strategy)
    def collect(value: object) -> None:
        collected.append(value)

    try:
        collect()
    except Exception:
        return []
    return collected


def values_for(annotation: object | None, *, seed: int, mined: list[object]) -> list[object]:
    """Deterministic candidate pool for one parameter."""
    rng = random.Random(seed)
    pool: list[object] = []

    if annotation is None:
        for typ in (int, str, float, bool):
            pool.extend(_EDGE_CASES[typ][:6])
        pool.extend([None, [], {}, (1, 2), [1, 2, 3], {"k": 1}])
    else:
        pool.extend(_edge_cases_for(annotation))
        with contextlib.suppress(Exception):
            # from_type takes the runtime type object we parsed
            pool.extend(_hypothesis_examples(st.from_type(annotation), 25))  # type: ignore[arg-type]

    pool.extend(m for m in mined if _matches(annotation, m))
    filtered: list[object] = []
    seen: set[str] = set()
    for v in pool:
        if not _literal_ok(v):
            continue
        key = repr(v)
        if key not in seen:
            seen.add(key)
            filtered.append(v)
    rng.shuffle(filtered)
    # Boundary values must survive the cap: put a slice of edges first, shuffled tail after.
    edges = [v for v in filtered if _is_edge(annotation, v)]
    rest = [v for v in filtered if not _is_edge(annotation, v)]
    return (edges + rest)[:80]


def _edge_cases_for(annotation: object) -> list[object]:
    if annotation in _EDGE_CASES:
        return list(_EDGE_CASES[annotation])
    origin = getattr(annotation, "__origin__", None)
    args: tuple[object, ...] = getattr(annotation, "__args__", ())
    if origin is None:
        import types as _types

        if isinstance(annotation, _types.UnionType) or str(annotation).startswith(
            "typing.Optional"
        ):
            out: list[object] = []
            for arg in getattr(annotation, "__args__", ()):
                out.extend(_edge_cases_for(arg) if arg is not type(None) else [None])
            return out
        return []
    element = list(_edge_cases_for(args[0]))[:4] if args else [0, "a"]
    if origin is list:
        return [[], [element[0]] if element else [], element, element * 2]
    if origin is tuple:
        return [tuple(element[: len(args) or 2])] if element else [()]
    if origin is set:
        return [set(), {element[0]} if element else set()]
    if origin is frozenset:
        return [frozenset(), frozenset({element[0]}) if element else frozenset()]
    if origin is dict and len(args) == 2:
        keys = _edge_cases_for(args[0])[:3]
        vals = _edge_cases_for(args[1])[:3]
        return [{}, dict(zip(keys, vals, strict=False))]
    return []


def _is_edge(annotation: object | None, v: object) -> bool:
    if annotation in _EDGE_CASES:
        return v in _EDGE_CASES[annotation] or (
            isinstance(v, float)
            and isinstance(annotation, type)
            and annotation is float
            and (v != v or v in (0.0,))
        )
    return False


def _matches(annotation: object | None, value: object) -> bool:
    """Does a mined value belong in this parameter's pool? Typed pools stay inside the
    DECLARED contract — that is what the annotation is for. (While mining was dead — trap
    38 — the old fall-through for generic annotations was invisible; alive, it fed mined
    scalars to `list[int]` parameters, and pyfix's no-op refactors "diverged" on exception
    messages for inputs outside their own types.)"""
    if annotation is None:
        return True
    if isinstance(annotation, type):
        return isinstance(value, annotation) and not (
            annotation is not bool and isinstance(value, bool)
        )
    import types as _types

    args: tuple[object, ...] = getattr(annotation, "__args__", ())
    if isinstance(annotation, _types.UnionType) or str(annotation).startswith("typing.Optional"):
        return any((value is None) if arg is type(None) else _matches(arg, value) for arg in args)
    origin = getattr(annotation, "__origin__", None)
    if origin in (list, set, frozenset):
        if not isinstance(value, origin):
            return False
        element = args[0] if args else None
        return all(_matches(element, item) for item in value)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if not args or (len(args) == 2 and args[1] is Ellipsis):
            element = args[0] if args else None
            return all(_matches(element, item) for item in value)
        return len(value) == len(args) and all(
            _matches(arg, item) for arg, item in zip(args, value, strict=True)
        )
    if origin is dict:
        if not isinstance(value, dict):
            return False
        if len(args) == 2:
            key_t, val_t = args[0], args[1]
        else:
            key_t, val_t = None, None
        return all(_matches(key_t, k) and _matches(val_t, v) for k, v in value.items())
    # An annotation this vocabulary cannot describe (user generics, protocols): admit the
    # mined value — the probe-and-compare machinery is the judge of last resort there.
    return True
