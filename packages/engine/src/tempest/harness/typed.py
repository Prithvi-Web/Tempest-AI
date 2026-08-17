"""Type-driven constructor synthesis — the deterministic rung BEFORE the LLM (ADR-0026,
the `TypeDrivenSynthesizer` the architecture spec names).

An instance method on a typed dataclass is mechanically constructible: fields with
defaults need nothing, and defaultless fields with builtin-shaped annotations get their
zero value. The adapter is derived from the AST ALONE — user code is never imported in
this process (L6); acceptance is the same sandboxed execution probe every adapter passes.
No key, no network, fully offline (L8). Anything non-mechanical returns None and falls
through to the LLM rung (key-gated) with honesty intact.
"""

import ast
from pathlib import Path

from tempest.execute.sandbox import Sandbox
from tempest.harness.llm import InstanceAdapter
from tempest.harness.synth import SynthesisFailure, synthesize

_ZERO_VALUES: dict[str, str] = {
    "int": "0",
    "float": "0.0",
    "str": "''",
    "bool": "False",
    "bytes": "b''",
    "list": "[]",
    "dict": "{}",
    "set": "set()",
    "tuple": "()",
    "frozenset": "frozenset()",
}


def synthesize_dataclass_adapter(
    *,
    base_root: Path,
    head_root: Path,
    module: str,
    owner_class: str,
    method: str,
    head_source: str,
    sandbox: Sandbox,
    seed: int = 0,
) -> InstanceAdapter | None:
    """None = not mechanically constructible (not a dataclass, a field defies zero-values,
    or the probe rejected the guess) — the caller falls through to the next rung."""
    code = _render_adapter(head_source, module, owner_class, method)
    if code is None:
        return None

    adapter_module = f"_tempest_typed_adapter_{owner_class.lower()}_{method.lower()}"
    for root in (base_root, head_root):
        (root / f"{adapter_module}.py").write_text(code, encoding="utf-8")
    validated = synthesize(base_root, adapter_module, "adapter", sandbox=sandbox, seed=seed)
    if isinstance(validated, SynthesisFailure) or validated.probe_raised:
        # The mechanical guess does not fit this class (e.g. __post_init__ rejects zero
        # values, or every probe raised — which could BE the constructor raising, and an
        # unattributable raise must never anchor a comparison). Nothing was "declined";
        # the next rung simply gets its turn.
        return None
    return InstanceAdapter(module=adapter_module, qualname="adapter", from_cache=False)


def _render_adapter(head_source: str, module: str, owner_class: str, method: str) -> str | None:
    try:
        tree = ast.parse(head_source)
    except SyntaxError:
        return None
    cls = next(
        (
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, ast.ClassDef) and node.name == owner_class
        ),
        None,
    )
    if cls is None or not _is_dataclass(cls):
        return None
    ctor_args = _constructor_args(cls)
    if ctor_args is None:
        return None
    params = _method_params(cls, method)
    if params is None:
        return None
    signature = ", ".join(f"{name}: {annotation}" for name, annotation in params)
    call = ", ".join(name for name, _ in params)
    return (
        f"from {module} import {owner_class}\n"
        f"\n"
        f"\n"
        f"def adapter({signature}):\n"
        f"    return {owner_class}({ctor_args}).{method}({call})\n"
    )


def _is_dataclass(cls: ast.ClassDef) -> bool:
    for deco in cls.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = target.attr if isinstance(target, ast.Attribute) else None
        if name is None and isinstance(target, ast.Name):
            name = target.id
        if name == "dataclass":
            return True
    return False


def _constructor_args(cls: ast.ClassDef) -> str | None:
    """Keyword arguments for the defaultless fields (zero values); defaulted fields are
    left to their defaults. None when any field is not mechanically zero-valuable."""
    parts: list[str] = []
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.value is not None:
            continue  # has a default (or a field(...) call) — the constructor handles it
        zero = _zero_value(node.annotation)
        if zero is None:
            return None
        parts.append(f"{node.target.id}={zero}")
    return ", ".join(parts)


def _zero_value(annotation: ast.expr) -> str | None:
    if isinstance(annotation, ast.Name):
        return _ZERO_VALUES.get(annotation.id)
    if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name):
        return _ZERO_VALUES.get(annotation.value.id)  # list[int] → [], dict[str, int] → {}
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # X | None (either side) → None is always a constructible value.
        for side in (annotation.left, annotation.right):
            if isinstance(side, ast.Constant) and side.value is None:
                return "None"
    return None


def _method_params(cls: ast.ClassDef, method: str) -> list[tuple[str, str]] | None:
    fn = next(
        (node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method),
        None,
    )
    if fn is None:
        return None
    params: list[tuple[str, str]] = []
    for arg in fn.args.args[1:]:  # skip self
        if arg.annotation is None:
            return None  # unannotated parameter: input generation has nothing to go on
        params.append((arg.arg, ast.unparse(arg.annotation)))
    if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs or fn.args.posonlyargs:
        return None
    return params
