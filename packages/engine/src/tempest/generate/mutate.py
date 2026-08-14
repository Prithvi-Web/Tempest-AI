"""Structural mutation over literal input trees — fuel for coverage-guided search."""

import random
from typing import cast

from tempest.compare.canonical import parse_input_literal


def mutate_input(args_literal: str, kwargs_literal: str, *, seed: int) -> tuple[str, str]:
    rng = random.Random(seed)
    try:
        args = list(cast("tuple[object, ...]", parse_input_literal(args_literal)))
        kwargs = dict(cast("dict[str, object]", parse_input_literal(kwargs_literal)))
    except (ValueError, SyntaxError):
        return args_literal, kwargs_literal
    if args and (not kwargs or rng.random() < 0.8):
        i = rng.randrange(len(args))
        args[i] = _mutate_value(args[i], rng)
    elif kwargs:
        key = rng.choice(sorted(kwargs))
        kwargs[key] = _mutate_value(kwargs[key], rng)
    return repr(tuple(args)), repr(kwargs)


def _mutate_value(value: object, rng: random.Random, depth: int = 0) -> object:
    if depth > 4:
        return value
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return rng.choice([value + 1, value - 1, value * 2, -value, 0, value or 1])
    if isinstance(value, float):
        return rng.choice([value + 1.0, value / 2 if value else 1.0, -value, 0.0, value * 10])
    if isinstance(value, str):
        choices: list[object] = [
            "",
            value + "a",
            value[:-1],
            value.upper(),
            value * 2,
            value.swapcase(),
        ]
        return rng.choice([c for c in choices if c != value] or [value + "x"])
    if isinstance(value, bytes):
        return rng.choice([b"", value + b"\x00", value[:-1]])
    if isinstance(value, list):
        if not value:
            return [0]
        copy = list(value)
        op = rng.random()
        if op < 0.33:
            copy.pop(rng.randrange(len(copy)))
        elif op < 0.66:
            copy.append(copy[rng.randrange(len(copy))])
        else:
            i = rng.randrange(len(copy))
            copy[i] = _mutate_value(copy[i], rng, depth + 1)
        return copy
    if isinstance(value, tuple):
        return tuple(_mutate_value(list(value), rng, depth + 1))  # type: ignore[arg-type]  # list mutation then re-tuple
    if isinstance(value, dict):
        if not value:
            return {"k": 0}
        dcopy = dict(value)
        key = rng.choice(sorted(dcopy, key=repr))
        if rng.random() < 0.5:
            del dcopy[key]
        else:
            dcopy[key] = _mutate_value(dcopy[key], rng, depth + 1)
        return dcopy
    if isinstance(value, set):
        return {v for v in value if rng.random() < 0.8} or {0}
    return value
