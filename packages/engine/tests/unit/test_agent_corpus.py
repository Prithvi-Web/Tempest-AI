"""The agent corpus as a set of CLAIMS, checked without running it.

`_agent_corpus.py` states its own composition in prose — "22 a correct loop repairs, 6 it cannot,
8 dishonest outcomes it must refuse…" — and in this project a stated composition is a deliverable
like any other. The review found the previous numbers wrong (52 tasks and 13 not-engaged, against
an actual 55 and 16), so they are asserted here rather than described.

Running the corpus is `make verify`'s job and takes minutes. Everything here is structural and
takes milliseconds, which is the point: the shape of the corpus should be gated on every test run,
not only when someone spends four minutes on the benchmarks.
"""

from __future__ import annotations

from collections import Counter

from tempest.agent import contracts as contracts_mod
from tempest.dev._agent_corpus import NO_DIVERGENCE, TASKS

#: The composition the module's own docstring states. One place, checked against the tuple.
STATED = {
    "succeeded": 22,
    "failed": 6,
    "cheated": 8,
    "abandoned": 3,
    "not-engaged": 16,
}


class TestTheStatedCompositionIsTrue:
    def test_the_counts_match_the_prose(self) -> None:
        assert Counter(t.expect_repair for t in TASKS) == Counter(STATED)

    def test_the_total_is_what_the_docstring_says(self) -> None:
        assert len(TASKS) == sum(STATED.values()) == 55

    def test_the_corpus_meets_the_phase_gate_floor(self) -> None:
        """PLAN-V2 §21 runs `agent_bench --tasks 50`. Fewer than fifty tasks and that exits 2."""
        assert len(TASKS) >= 50

    def test_the_docstring_prints_the_same_numbers(self) -> None:
        """The prose and the tuple are two statements of one fact, so they are compared. A
        composition that drifts from its own description is the defect this test exists for."""
        from pathlib import Path

        from tempest.dev import _agent_corpus

        module_text = Path(_agent_corpus.__file__).read_text(encoding="utf-8")
        assert "55-task" in module_text
        for word, count in (
            ("**22**", 22),
            ("**6**", 6),
            ("**8**", 8),
            ("**3**", 3),
            ("**16**", 16),
        ):
            assert word in module_text, f"the docstring no longer states {count}"


class TestEveryTaskIsWellFormed:
    def test_names_are_unique(self) -> None:
        names = [t.name for t in TASKS]
        assert len(set(names)) == len(names)

    def test_every_task_declares_an_outcome_for_the_repair_gate(self) -> None:
        """`repair_bench` skips a task with no `expect_repair`, and a silently skipped task is a
        smaller corpus reported under the full name (trap 44)."""
        assert all(t.expect_repair for t in TASKS)

    def test_every_expected_outcome_is_one_the_gate_understands(self) -> None:
        allowed = {"succeeded", "failed", "cheated", "abandoned", "not-engaged"}
        assert {t.expect_repair for t in TASKS} <= allowed

    def test_every_classification_is_a_real_verdict_word(self) -> None:
        allowed = {
            contracts_mod.INTENDED,
            contracts_mod.UNINTENDED,
            contracts_mod.UNCLASSIFIED,
            NO_DIVERGENCE,
        }
        for task in TASKS:
            assert set(task.expect_classification.values()) <= allowed, task.name

    def test_a_task_without_a_contract_cannot_expect_a_repair(self) -> None:
        """The loop only engages when there is a stated intent. A task that had no contract and
        expected a repair would be asking for a guess about what the user wanted."""
        for task in TASKS:
            if not task.has_contract:
                assert task.expect_repair == "not-engaged", task.name

    def test_every_script_ends_by_stopping(self) -> None:
        """A script whose last entry is an edit never lets the conversation end, so the task
        measures the turn budget rather than the behaviour it was written for."""
        for task in TASKS:
            assert task.script[-1] is None, task.name

    def test_the_cheats_are_the_ones_the_spec_names_plus_the_ones_we_found(self) -> None:
        """F3's gate requires an adversarial test per cheat, permanently. Naming them here means
        deleting one is a visible act rather than a quiet shrinking of the corpus."""
        cheats = {t.name for t in TASKS if t.expect_repair == "cheated"}
        assert {
            "model-deletes-the-function",
            "model-breaks-the-import",
            "model-empties-the-file",
            "model-renames-the-symbol",
            "model-hides-the-function-behind-a-lambda",
            "model-raises-at-import-time",
            "model-exits-the-interpreter-at-import-time",
            "model-breaks-the-helper-it-was-not-asked-about",
        } == cheats

    def test_the_repair_rate_the_corpus_can_reach_clears_the_bar(self) -> None:
        """A corpus whose best possible rate is under the bar makes the gate unpassable however
        good the product is — which is what the 15-task corpus did (4/7 = 57% against a 60% bar,
        and nobody had noticed because the cheat failure masked it)."""
        attempted = STATED["succeeded"] + STATED["failed"]
        assert STATED["succeeded"] / attempted >= 0.60
