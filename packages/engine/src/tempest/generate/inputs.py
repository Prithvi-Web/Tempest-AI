"""Assemble per-target candidate inputs from parameter pools, under budget, deterministically."""

import random
from dataclasses import dataclass

from tempest.execute.runner import TargetIntrospection
from tempest.generate.strategies import parse_annotation, values_for


@dataclass(frozen=True)
class Budget:
    max_inputs: int = 300
    max_wall_seconds: float = 30.0
    seed: int = 0


@dataclass(frozen=True)
class CandidateInput:
    args_literal: str
    kwargs_literal: str
    provenance: str  # TYPE_DERIVED | CORPUS_MINED | MUTATED


_POSITIONAL_KINDS = {"POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD"}


def generate_inputs(
    introspection: TargetIntrospection, *, mined: list[object], budget: Budget
) -> list[CandidateInput]:
    rng = random.Random(budget.seed)
    positional = [p for p in introspection.params if p.kind in _POSITIONAL_KINDS]
    keyword_only = [p for p in introspection.params if p.kind == "KEYWORD_ONLY"]

    pools: list[list[object]] = []
    for i, param in enumerate(positional):
        annotation = parse_annotation(param.annotation) if param.annotation else None
        pools.append(values_for(annotation, seed=budget.seed * 1000 + i, mined=mined))

    required_count = sum(1 for p in positional if p.default_literal is None)
    arity_options = sorted({required_count, len(positional)})

    candidates: list[CandidateInput] = []
    seen: set[tuple[str, str]] = set()
    depth = max((len(pool) for pool in pools), default=1)
    for round_i in range(depth * 2):
        if len(candidates) >= budget.max_inputs:
            break
        arity = arity_options[round_i % len(arity_options)]
        args = tuple(
            pool[(round_i + rng.randrange(3)) % len(pool)] if pool else None
            for pool in pools[:arity]
        )
        kwargs: dict[str, object] = {}
        for j, param in enumerate(keyword_only):
            if param.default_literal is None or rng.random() < 0.5:
                annotation = parse_annotation(param.annotation) if param.annotation else None
                pool = values_for(annotation, seed=budget.seed * 7000 + j, mined=mined)
                if pool:
                    kwargs[param.name] = pool[round_i % len(pool)]
        key = (repr(args), repr(kwargs))
        if key not in seen:
            seen.add(key)
            candidates.append(
                CandidateInput(
                    args_literal=repr(args), kwargs_literal=repr(kwargs), provenance="TYPE_DERIVED"
                )
            )
    return candidates[: budget.max_inputs]
