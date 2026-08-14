"""Canonical value encoding — the equivalence substrate for every comparison (master spec stage 7).

Invariants (tested in tests/unit/test_canonical.py):
- equal-by-value data structures encode to identical bytes regardless of dict/set ordering
- NaN == NaN; -0.0 and 0.0 stay distinguishable; bool is not int; bytes are not str
- objects fall back to a structural fingerprint (type + public attrs); when neither value
  encoding nor fingerprinting works, `Unrepresentable` is raised — a value is never silently equal
"""

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
