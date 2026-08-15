"""The last branch gap (100% gate): a mutation seed that lands on the kwargs arm even when
positional args exist — both mutation arms are real behavior, both stay pinned."""

import random

from tempest.generate.mutate import mutate_input


def test_nullary_input_passes_through_unmutated() -> None:
    assert mutate_input("()", "{}", seed=0) == ("()", "{}"), (
        "nothing to mutate: a nullary input must come back exactly as it went in"
    )


def test_mutation_can_choose_kwargs_even_when_args_exist() -> None:
    seed = next(
        s for s in range(200) if random.Random(s).random() >= 0.8
    )  # first roll ≥ 0.8 → the kwargs arm despite non-empty args
    args_literal, kwargs_literal = mutate_input("(1, 2)", "{'k': 3}", seed=seed)
    assert args_literal == "(1, 2)", "args must be untouched on the kwargs arm"
    assert kwargs_literal != "{'k': 3}", "the kwarg value must actually mutate"
