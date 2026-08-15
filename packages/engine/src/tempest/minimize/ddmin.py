"""Structural greedy shrinking over the input tree. The invariant that may never break
(§14.3, property-tested): every accepted reduction reproduces the SAME DivergenceClass —
a minimizer that drifts to a different bug is a lie.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import cast

from tempest.compare.canonical import parse_input_literal
from tempest.compare.compare import Diverged

type RerunFn = Callable[[str, str], Diverged | None]

_MAX_ATTEMPTS = 200


@dataclass(frozen=True)
class MinimizedInput:
    args_literal: str
    kwargs_literal: str
    shrink_path: tuple[str, ...]
    attempts_used: int


def minimize_input(
    rerun: RerunFn, args_literal: str, kwargs_literal: str, *, max_attempts: int = _MAX_ATTEMPTS
) -> MinimizedInput | None:
    original = rerun(args_literal, kwargs_literal)
    if original is None:
        return None
    target_class = original.divergence_class

    current_args = tuple(cast("tuple[object, ...]", parse_input_literal(args_literal)))
    current_kwargs = dict(cast("dict[str, object]", parse_input_literal(kwargs_literal)))
    attempts = 1
    path: list[str] = []

    improved = True
    while improved and attempts < max_attempts:
        improved = False
        for cand_args, cand_kwargs, note in _candidates(current_args, current_kwargs):
            if attempts >= max_attempts:
                break
            args_text, kwargs_text = repr(cand_args), repr(cand_kwargs)
            if (args_text, kwargs_text) == (repr(current_args), repr(current_kwargs)):
                continue
            attempts += 1
            result = rerun(args_text, kwargs_text)
            if result is not None and result.divergence_class is target_class:
                current_args, current_kwargs = cand_args, cand_kwargs
                path.append(note)
                improved = True
                break

    return MinimizedInput(
        args_literal=repr(current_args),
        kwargs_literal=repr(current_kwargs),
        shrink_path=tuple(path),
        attempts_used=attempts,
    )


def _candidates(
    args: tuple[object, ...], kwargs: dict[str, object]
) -> Iterator[tuple[tuple[object, ...], dict[str, object], str]]:
    for i, value in enumerate(args):
        for smaller, note in _shrink_value(value):
            yield (*args[:i], smaller, *args[i + 1 :]), kwargs, f"args[{i}]: {note}"
    for key in sorted(kwargs, key=repr):
        rest = {k: v for k, v in kwargs.items() if k != key}
        yield args, rest, f"dropped kwarg {key!r}"
        for smaller, note in _shrink_value(kwargs[key]):
            yield args, {**kwargs, key: smaller}, f"kwargs[{key!r}]: {note}"


def _shrink_value(value: object, depth: int = 0) -> Iterator[tuple[object, str]]:
    if depth > 4:
        return
    if isinstance(value, bool):
        if value:
            yield False, "True→False"
        return
    if isinstance(value, int):
        if value != 0:
            yield 0, f"{value}→0"
            half = value // 2 if value > 0 else -(-value // 2)
            if half not in (0, value):
                yield half, f"{value}→{half}"
            step = value - 1 if value > 0 else value + 1
            # A ±1 step never equals a plain int (bools were handled above, and transport
            # literals cannot smuggle exotic int subclasses in); the guard stays defensive.
            if step != value:  # pragma: no branch — int ±1 always differs
                yield step, f"{value}→{step}"
        return
    if isinstance(value, float):
        if value != 0.0:
            yield 0.0, f"{value!r}→0.0"
            yield value / 2, f"{value!r}→{value / 2!r}"
            if value == value and abs(value) != float("inf"):
                rounded = float(round(value))
                if rounded != value:
                    yield rounded, f"{value!r}→{rounded!r}"
        return
    if isinstance(value, str):
        n = len(value)
        if n == 0:
            return
        yield "", f"str[{n}]→''"
        if n > 1:
            yield value[: n // 2], f"str[{n}]→first half"
            yield value[n // 2 :], f"str[{n}]→second half"
            yield value[:-1], f"str[{n}]→drop last"
            yield value[1:], f"str[{n}]→drop first"
        simple = "a" * n
        if simple != value:
            yield simple, f"str[{n}]→'a'*{n}"
        return
    if isinstance(value, bytes):
        n = len(value)
        if n == 0:
            return
        yield b"", f"bytes[{n}]→b''"
        if n > 1:
            yield value[: n // 2], f"bytes[{n}]→first half"
            yield value[:-1], f"bytes[{n}]→drop last"
        return
    if isinstance(value, list | tuple):
        seq = list(value)
        wrap = (lambda x: x) if isinstance(value, list) else tuple
        n = len(seq)
        if n == 0:
            return
        yield wrap([]), f"seq[{n}]→empty"
        if n > 1:
            yield wrap(seq[: n // 2]), f"seq[{n}]→first half"
            yield wrap(seq[n // 2 :]), f"seq[{n}]→second half"
            for i in range(min(n, 8)):
                yield wrap(seq[:i] + seq[i + 1 :]), f"seq[{n}]→drop [{i}]"
        for i in range(min(n, 4)):
            for smaller, note in _shrink_value(seq[i], depth + 1):
                yield wrap([*seq[:i], smaller, *seq[i + 1 :]]), f"[{i}].{note}"
        return
    if isinstance(value, dict):
        keys = sorted(value, key=repr)
        if not keys:
            return
        yield {}, f"dict[{len(keys)}]→empty"
        for k in keys[:8]:
            yield {kk: vv for kk, vv in value.items() if kk != k}, f"dict→drop {k!r}"
        for k in keys[:4]:
            for smaller, note in _shrink_value(value[k], depth + 1):
                yield {**value, k: smaller}, f"[{k!r}].{note}"
        return
    if isinstance(value, set | frozenset):
        items = sorted(value, key=repr)
        if not items:
            return
        wrap_set = set if isinstance(value, set) else frozenset
        yield wrap_set(), f"set[{len(items)}]→empty"
        for item in items[:8]:
            yield wrap_set(x for x in items if x != item), f"set→drop {item!r}"
        return
