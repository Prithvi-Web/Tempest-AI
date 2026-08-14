"""Canonical value encoding — the equivalence substrate for every comparison (master spec stage 7).

Invariants (tested in tests/unit/test_canonical.py):
- equal-by-value data structures encode to identical bytes regardless of dict/set ordering
- NaN == NaN; -0.0 and 0.0 stay distinguishable; bool is not int; bytes are not str
- objects fall back to a structural fingerprint (type + public attrs); when neither value
  encoding nor fingerprinting works, `Unrepresentable` is raised — a value is never silently equal
"""

import ast
import base64
import dataclasses
import json
import math
import types

MAX_DEPTH = 64

# A canonical tree is JSON-serializable: scalars stay raw; everything else is a tagged dict.
type Canon = bool | int | str | dict[str, object] | None


class Unrepresentable(Exception):
    """The value cannot be canonically encoded — the input must surface as UNPROVEN, not equal."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_REJECTED_TYPES = (
    types.FunctionType,
    types.LambdaType,
    types.MethodType,
    types.BuiltinFunctionType,
    types.ModuleType,
    types.GeneratorType,
    types.CoroutineType,
    type,
)


def parse_input_literal(text: str) -> object:
    """Parse the transport form of an input: Python literals extended with nan/inf.

    `repr()` emits `nan`/`inf`/`-inf` for those floats, which `ast.literal_eval` rejects. This
    parser validates the AST down to literal nodes plus the bare names nan/inf, then evaluates
    with an empty builtins namespace — it cannot execute code.
    """
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        pass
    tree = ast.parse(text, mode="eval")
    if not _is_extended_literal(tree.body):
        raise ValueError(f"not a transportable input literal: {text[:80]!r}")
    return eval(  # AST-validated to literals + nan/inf, empty builtins
        compile(tree, "<input-literal>", "eval"),
        {"__builtins__": {}},
        # set/frozenset: the validator admits exactly these two constructors over literal
        # args (repr() emits them); they must resolve here or valid inputs NameError.
        {"nan": math.nan, "inf": math.inf, "set": set, "frozenset": frozenset},
    )


def _is_extended_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return node.id in ("nan", "inf")
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, ast.USub | ast.UAdd) and _is_extended_literal(node.operand)
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_is_extended_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_extended_literal(k) for k in node.keys) and all(
            _is_extended_literal(v) for v in node.values
        )
    if isinstance(node, ast.Call):
        # repr() of set()/frozenset({...}) — allow exactly those constructors over literal args.
        return (
            isinstance(node.func, ast.Name)
            and node.func.id in ("set", "frozenset")
            and not node.keywords
            and all(_is_extended_literal(a) for a in node.args)
        )
    return False


def canonicalize(obj: object) -> Canon:
    return _encode(obj, seen=set(), depth=0)


def canonical_bytes(canon: Canon) -> bytes:
    return json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sort_key(canon: Canon) -> bytes:
    return canonical_bytes(canon)


def _encode(obj: object, seen: set[int], depth: int) -> Canon:
    if depth > MAX_DEPTH:
        raise Unrepresentable(f"nesting deeper than {MAX_DEPTH}")

    if obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        hexval = "nan" if math.isnan(obj) else obj.hex()
        return {"__t": "float", "v": hexval}
    if isinstance(obj, bytes | bytearray):
        return {"__t": "bytes", "v": base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, _REJECTED_TYPES):
        raise Unrepresentable(f"cannot canonicalize {type(obj).__name__}")

    oid = id(obj)
    if oid in seen:
        raise Unrepresentable("cyclic structure")
    seen.add(oid)
    try:
        if isinstance(obj, list | tuple):
            tag = "list" if isinstance(obj, list) else "tuple"
            return {"__t": tag, "v": [_encode(x, seen, depth + 1) for x in obj]}
        if isinstance(obj, set | frozenset):
            tag = "set" if isinstance(obj, set) else "frozenset"
            items = [_encode(x, seen, depth + 1) for x in obj]
            items.sort(key=_sort_key)
            return {"__t": tag, "v": items}
        if isinstance(obj, dict):
            pairs = [
                [_encode(k, seen, depth + 1), _encode(v, seen, depth + 1)] for k, v in obj.items()
            ]
            pairs.sort(key=lambda kv: _sort_key(kv[0]))
            return {"__t": "dict", "v": pairs}
        return _fingerprint(obj, seen, depth)
    finally:
        seen.discard(oid)


def _fingerprint(obj: object, seen: set[int], depth: int) -> Canon:
    """Structural fingerprint: qualified type + canonicalized public attributes."""
    type_name = f"{type(obj).__module__}.{type(obj).__qualname__}"
    attrs: dict[str, object]
    if dataclasses.is_dataclass(obj):
        attrs = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
    elif hasattr(obj, "__dict__"):
        attrs = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    elif (slots := getattr(type(obj), "__slots__", None)) is not None:
        names = [slots] if isinstance(slots, str) else [str(s) for s in slots]
        attrs = {n: getattr(obj, n) for n in names if not n.startswith("_") and hasattr(obj, n)}
    else:
        raise Unrepresentable(f"no value encoding or structural fingerprint for {type_name}")
    encoded = [[name, _encode(value, seen, depth + 1)] for name, value in sorted(attrs.items())]
    return {"__t": "obj", "type": type_name, "v": encoded}
