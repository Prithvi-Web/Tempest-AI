"""The execution index — what ran, clustered into behaviour classes, with citable examples.

Every test here executes REAL code in a REAL sandbox (L4). The clustering is pure and is tested
directly; the observing is driven end to end because "we ran it and this is what happened" is the
only claim this module makes, and a mock of the runner would be a mock of the claim.

States enumerated before the tests (trap 43): a function that returns · one that raises · one that
does both depending on input · one that prints · one that cannot be introspected · one whose every
input is unprovable · a symbol with no behaviour at all · a second run over the same symbol.
"""

from __future__ import annotations

from pathlib import Path

from tempest.execute.sandbox import ProcessSandbox
from tempest.index import execution, structure
from tempest.index.store import index_for, symbol_rows
from tempest.model import InputOutcome, Observation, RaisedInfo, Timing

SANDBOX = ProcessSandbox()


def _repo(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


def _obs(
    *,
    outcome: InputOutcome = InputOutcome.COMPLETED,
    value: object | None = 1,
    present: bool = True,
    raised: RaisedInfo | None = None,
    stdout: str = "",
) -> Observation:
    return Observation(
        outcome=outcome,
        return_present=present,
        return_canon=value,
        raised=raised,
        stdout=stdout,
        timing=Timing(wall_ns=1, cpu_ns=1),
    )


class TestBehaviourClasses:
    def test_two_calls_returning_the_same_TYPE_are_one_behaviour(self) -> None:
        """`total([1,2])` and `total([3,4])` are the same behaviour observed twice. Keying on the
        VALUE would make every input its own class and the index unbounded."""
        assert execution.behaviour_key(_obs(value=3)) == execution.behaviour_key(_obs(value=99))

    def test_a_different_returned_type_is_a_different_behaviour(self) -> None:
        assert execution.behaviour_key(_obs(value=3)) != execution.behaviour_key(_obs(value="3"))

    def test_raising_is_not_returning(self) -> None:
        raised = _obs(present=False, value=None, raised=RaisedInfo("ValueError", "b", "no"))
        assert execution.behaviour_key(raised) != execution.behaviour_key(_obs())

    def test_two_different_exception_TYPES_are_two_behaviours(self) -> None:
        a = _obs(present=False, value=None, raised=RaisedInfo("ValueError", "b", "x"))
        b = _obs(present=False, value=None, raised=RaisedInfo("TypeError", "b", "x"))
        assert execution.behaviour_key(a) != execution.behaviour_key(b)

    def test_the_exception_MESSAGE_does_not_split_a_class(self) -> None:
        """A message carrying the input value would make every input its own class again."""
        a = _obs(present=False, value=None, raised=RaisedInfo("ValueError", "b", "bad: 1"))
        b = _obs(present=False, value=None, raised=RaisedInfo("ValueError", "b", "bad: 2"))
        assert execution.behaviour_key(a) == execution.behaviour_key(b)


class TestStoring:
    def test_a_class_keeps_its_count_and_two_representatives(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('m.py','d',1,0)")
            conn.execute(
                "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
                "signature, doc) VALUES (1, 'm', 'f', 'function', 1, 2, '()', '')"
            )
            run_id = execution.record_run(conn, "rev", "test")
            inputs = [("(1,)", "{}"), ("(22222,)", "{}"), ("(333,)", "{}")]
            classes = execution.store_observations(
                conn,
                run_id=run_id,
                symbol_id=1,
                inputs=inputs,
                observations=[_obs(), _obs(), _obs()],
            )
            assert classes == 1
            rows = execution.behaviours_of(conn, 1)
            assert rows[0]["inputs"] == 3
            examples = rows[0]["examples"]
            assert len(examples) == 2, "the shortest input and the longest — the edges"
            assert examples[0]["args"] == "(1,)"
            assert examples[1]["args"] == "(22222,)"

    def test_a_single_input_class_keeps_one_representative(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            conn.execute("INSERT INTO files (path, digest, lines, indexed) VALUES ('m.py','d',1,0)")
            conn.execute(
                "INSERT INTO symbols (file_id, module, qualname, kind, line_start, line_end, "
                "signature, doc) VALUES (1, 'm', 'f', 'function', 1, 2, '()', '')"
            )
            run_id = execution.record_run(conn, "rev", "test")
            execution.store_observations(
                conn, run_id=run_id, symbol_id=1, inputs=[("(1,)", "{}")], observations=[_obs()]
            )
            assert len(execution.behaviours_of(conn, 1)[0]["examples"]) == 1


class TestObservingForReal:
    def test_returns_and_raises_are_both_recorded(self, tmp_path: Path) -> None:
        root = _repo(
            tmp_path,
            **{
                # The guard fires on a CLASS of inputs rather than on one value. A fixture that
                # raises only for `None` depends on the generator happening to sample `None`,
                # which it does not always do once repo literals are mined into the pool — the
                # test would then pass or fail on luck rather than on behaviour.
                "m.py": (
                    "def parse(text):\n"
                    "    if not isinstance(text, str):\n"
                    "        raise ValueError('parse wants a string')\n"
                    "    return text.strip()\n"
                )
            },
        )
        with index_for(root) as conn:
            structure.build(conn, root)
            rows = {r.qualname: r for r in symbol_rows(conn)}
            stats = execution.observe(
                conn,
                root,
                [execution.SymbolTarget(rows["parse"].id, "m", "parse")],
                SANDBOX,
                revision="rev",
                max_inputs=30,
            )
            assert stats.symbols_observed == 1
            kinds = {b["raised_type"] for b in execution.behaviours_of(conn, rows["parse"].id)}
            assert "ValueError" in kinds
            assert "" in kinds, "at least one input returned rather than raising"

    def test_a_symbol_that_cannot_be_introspected_is_reported_not_skipped(
        self, tmp_path: Path
    ) -> None:
        """ "Nothing was observed" and "nothing COULD be observed" are different answers, and the
        second is the honest half of "which functions have never been exercised?"."""
        root = _repo(tmp_path, **{"m.py": "def f():\n    return 1\n"})
        with index_for(root) as conn:
            structure.build(conn, root)
            stats = execution.observe(
                conn,
                root,
                [execution.SymbolTarget(1, "m", "does_not_exist")],
                SANDBOX,
                revision="rev",
            )
            assert stats.symbols_observed == 0
            assert stats.unreachable and "introspect" in stats.unreachable[0][1]

    def test_never_exercised_names_exactly_the_symbols_with_no_behaviour(
        self, tmp_path: Path
    ) -> None:
        root = _repo(
            tmp_path,
            **{"m.py": "def seen(x):\n    return x\n\n\ndef unseen(x):\n    return x\n"},
        )
        with index_for(root) as conn:
            structure.build(conn, root)
            rows = {r.qualname: r for r in symbol_rows(conn)}
            execution.observe(
                conn,
                root,
                [execution.SymbolTarget(rows["seen"].id, "m", "seen")],
                SANDBOX,
                revision="rev",
                max_inputs=6,
            )
            assert execution.never_exercised(conn) == [rows["unseen"].id]

    def test_latest_run_is_the_evidence_behind_an_absence(self, tmp_path: Path) -> None:
        with index_for(tmp_path) as conn:
            assert execution.latest_run(conn) is None
            first = execution.record_run(conn, "a", "test")
            second = execution.record_run(conn, "b", "test")
            assert first != second
            assert execution.latest_run(conn) == second


class TestWhatCannotBeObserved:
    """ "Nothing was observed" and "nothing COULD be observed" are different answers, and the
    second one is the honest half of "which functions have never been exercised?"."""

    def test_a_symbol_with_no_generated_inputs_is_reported(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, **{"m.py": "def f(x):\n    return x\n"})
        with index_for(root) as conn:
            structure.build(conn, root)
            rows = {r.qualname: r for r in symbol_rows(conn)}
            stats = execution.observe(
                conn,
                root,
                [execution.SymbolTarget(rows["f"].id, "m", "f")],
                SANDBOX,
                revision="rev",
                max_inputs=0,
            )
            assert stats.symbols_observed == 0
            assert stats.unreachable == (("f", "no inputs could be generated for it"),)

    def test_a_symbol_whose_every_result_is_unrepresentable_is_reported(
        self, tmp_path: Path
    ) -> None:
        """A value the comparison layer cannot represent supports no claim: there is nothing to
        show a reader, and a citation nobody can read is not evidence."""
        root = _repo(tmp_path, **{"m.py": "def f(x):\n    return object()\n"})
        with index_for(root) as conn:
            structure.build(conn, root)
            rows = {r.qualname: r for r in symbol_rows(conn)}
            stats = execution.observe(
                conn,
                root,
                [execution.SymbolTarget(rows["f"].id, "m", "f")],
                SANDBOX,
                revision="rev",
                max_inputs=6,
            )
            assert stats.symbols_observed == 0
            assert (
                stats.unreachable[0][1]
                == "every generated input produced an unrepresentable result"
            )
