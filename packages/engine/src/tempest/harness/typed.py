"""Type-driven constructor synthesis — the deterministic rung BEFORE the LLM (ADR-0026,
the `TypeDrivenSynthesizer` the architecture spec names; widened to plain classes in
Phase 19a, ADR-0048).

An instance method is mechanically constructible when its receiver is: a **dataclass**
whose defaultless fields carry builtin-shaped annotations, or a **plain class** whose
`__init__` parameters are each either defaulted or annotated with something that has a
zero value. Both derive a constructor call from the AST ALONE — user code is never
imported in this process (L6) — and both are accepted only by the same sandboxed
execution probe. No key, no network, fully offline (L8). Anything non-mechanical returns
None and falls through to the LLM rung (key-gated) with honesty intact.

**Why the plain-class arm exists.** `docs/METRICS.md` records 112 of 130 UNPROVEN
real-world targets as `TARGET_UNREACHABLE` — 86% of everything unproven, an order of
magnitude above the next bucket, and every one an instance method. Before Phase 19a they
all fell past this rung to the key-gated one, so the engine-first answer to QV1 ran
straight into QV2 (who pays) for no reason except that a constructor was never attempted.

**Why widening it is safe.** Acceptance was already execution, not review. Rendering a
call is a *guess*; the probe on BASE is what decides. The two arms differ only in where
the argument list comes from — dataclass FIELDS, or `__init__`'s SIGNATURE — and a
dataclass with a generated constructor must keep taking the field path, because reading
an `__init__` it does not have would construct it empty and silently lose every field.
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
    written = [root / f"{adapter_module}.py" for root in (base_root, head_root)]
    for path in written:
        path.write_text(code, encoding="utf-8")
    validated = synthesize(base_root, adapter_module, "adapter", sandbox=sandbox, seed=seed)
    if isinstance(validated, SynthesisFailure) or validated.probe_raised:
        # The mechanical guess does not fit this class (e.g. __post_init__ rejects zero
        # values, or every probe raised — which could BE the constructor raising, and an
        # unattributable raise must never anchor a comparison). Nothing was "declined";
        # the next rung simply gets its turn.
        #
        # REMOVE the shim. Phase 19a widened this rung from dataclasses to every plain class, so
        # refusals went from a handful to the common case, and each one used to leave a module
        # behind in BOTH worktrees. Those trees are what the differential runner executes and
        # what coverage is attributed against, and a `.tempest` shadow worktree is a real git
        # worktree the user can open. Litter there is not cosmetic.
        for path in written:
            path.unlink(missing_ok=True)
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
    if cls is None:
        return None
    # WHICH constructor is real decides which arm reads it. A `@dataclass` normally has no
    # `__init__` in its body and gets a generated one from its fields — so the field path is the
    # only one that can see its parameters. A `@dataclass(init=False)` with a hand-written
    # `__init__` is the opposite: the generated constructor does not exist, and reading fields
    # would describe a signature nothing accepts. So the presence of an explicit `__init__` wins
    # over the decorator, for both kinds of class.
    explicit_init = _explicit_init(cls)
    if isinstance(explicit_init, _UnusableInit):
        return None
    if isinstance(explicit_init, ast.FunctionDef):
        ctor_args = _init_constructor_args(explicit_init)
    elif _is_dataclass(cls):
        ctor_args = _constructor_args(cls)
    else:
        # A plain class with no `__init__` of its own. `Cls()` is the guess; a base class may
        # still demand arguments, which the AST cannot see and the probe settles.
        ctor_args = ""
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


class _UnusableInit:
    """A constructor that exists but can never build an instance.

    A distinct TYPE rather than a bare `object()` so the three outcomes stay legible to
    `mypy --strict`: `ast.FunctionDef` (read its signature), `None` (the class declares no
    `__init__`, so a bare `Cls()` is licensed), and this (give up). `... | object | None`
    would have collapsed to `object` and checked nothing.
    """


_UNUSABLE_INIT = _UnusableInit()


def _explicit_init(cls: ast.ClassDef) -> ast.FunctionDef | _UnusableInit | None:
    """The class's own `__init__`; `None` when it declares none; `_UNUSABLE_INIT` when the one
    it declares cannot produce an instance.

    `async def __init__` is the unusable case: Python requires `__init__` to return None, and an
    async function returns a coroutine, so `Cls()` raises `TypeError` before any body runs. The
    probe would catch it — but a give-up we can prove from the AST should not cost a sandbox
    spawn, and "no `__init__`" and "an `__init__` that cannot work" are different facts.
    """
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            return node
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "__init__":
            return _UNUSABLE_INIT
    return None


def _init_constructor_args(fn: ast.FunctionDef) -> str | None:
    """The argument list for a plain class's `__init__`, or None when it is not mechanical.

    Every parameter is either satisfied by its own default (omit it) or given a zero value from
    its annotation. One unannotated defaultless parameter is enough to give up: there is nothing
    to derive a value FROM, and inventing one is what the LLM rung is for.

    `*args`/`**kwargs` are omitted rather than refused — both are satisfied by passing nothing.

    Positional-only parameters must be passed POSITIONALLY. `def __init__(self, fee, /)` raises
    `TypeError: got some positional-only arguments passed as keyword arguments` for `fee=0`, and
    a probe failing on our own rendering bug would look exactly like a class that is not
    constructible — a wrong answer arrived at honestly, which is the worst kind.
    """
    positional: list[str] = []
    keyword: list[str] = []

    # `defaults` right-aligns against posonlyargs + args TOGETHER, and `self` is the first of
    # them (in posonlyargs when the signature uses `/`, otherwise in args).
    slots = list(fn.args.posonlyargs) + list(fn.args.args)
    first_defaulted = len(slots) - len(fn.args.defaults)
    for index, arg in enumerate(slots):
        if index == 0:
            continue  # self
        if index >= first_defaulted:
            continue  # its own default satisfies it
        if arg.annotation is None:
            return None
        zero = _zero_value(arg.annotation)
        if zero is None:
            return None
        if index < len(fn.args.posonlyargs):
            positional.append(zero)
        else:
            keyword.append(f"{arg.arg}={zero}")

    # kw_defaults aligns 1:1 with kwonlyargs; None means "no default".
    for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True):
        if default is not None:
            continue
        if arg.annotation is None:
            return None
        zero = _zero_value(arg.annotation)
        if zero is None:
            return None
        keyword.append(f"{arg.arg}={zero}")

    return ", ".join(positional + keyword)


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
