"""F3 — the judgement, which is the part a repair loop gets wrong.

The spec's hard requirement is not "repairs work". It is: **zero repairs that succeed by
weakening the contract, deleting the divergent path, or making the target unreachable — one
adversarial test per cheat, permanent.** Each of those three has a test class here, and each is
written as the cheat rather than as the guard, so it keeps failing if the guard is ever relaxed.

These are pure functions over bundle-shaped data, so the doubles below carry data only — no
execution is simulated (L4). The cheats are also exercised end to end against real proofs in
`test_agent_repair.py`.

States enumerated before the tests (trap 43): nothing left to fix · unintended remain ·
unclassified remain · the contract changed · a target stopped being provable · a target went
UNPROVEN rather than vanishing · a target was ADDED · a target's verdict changed but stayed
conclusive · several cheats at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from tempest.agent import contracts as contracts_mod
from tempest.agent.repair import judge, proven_targets
from tempest.model import Verdict


@dataclass(frozen=True)
class _Target:
    qualname: str
    verdict: Verdict


@dataclass(frozen=True)
class _Bundle:
    targets: tuple[_Target, ...]


@dataclass(frozen=True)
class _Classified:
    classification: str


def _bundle(**verdicts: Verdict) -> _Bundle:
    return _Bundle(targets=tuple(_Target(q, v) for q, v in verdicts.items()))


_CLEAN = "contract-v1"


class TestProvenTargets:
    def test_only_conclusive_verdicts_count(self) -> None:
        """UNPROVEN and ERROR are exactly the states a cheat produces, so they are not evidence
        that a target is still being watched."""
        got = proven_targets(
            _bundle(
                a=Verdict.DIVERGENT,
                b=Verdict.EQUIVALENT_UNDER_BUDGET,
                c=Verdict.UNPROVEN,
                d=Verdict.ERROR,
            )
        )
        assert set(got) == {"a", "b"}


class TestARepairThatActuallyRepaired:
    def test_no_divergences_and_nothing_lost_is_success(self) -> None:
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.EQUIVALENT_UNDER_BUDGET),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert ok and "matches the contract" in reason

    def test_intended_divergences_may_remain(self) -> None:
        """The user asked for those. A repair loop that demanded zero divergences would fight the
        change it was asked to make."""
        ok, _ = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.DIVERGENT),
            divergences=(_Classified(contracts_mod.INTENDED),),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert ok

    def test_a_targets_verdict_may_change_as_long_as_it_stays_conclusive(self) -> None:
        ok, _ = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.EQUIVALENT_UNDER_BUDGET),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert ok

    def test_a_new_target_appearing_is_not_a_failure(self) -> None:
        """Repairs add helpers. Only a SHRINK of the proven set is a cheat."""
        ok, _ = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(
                a=Verdict.EQUIVALENT_UNDER_BUDGET, helper=Verdict.EQUIVALENT_UNDER_BUDGET
            ),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert ok


class TestItDidNotFixTheBehaviour:
    def test_remaining_unintended_divergences_fail(self) -> None:
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.DIVERGENT),
            divergences=(_Classified(contracts_mod.UNINTENDED),),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok and "unintended divergence" in reason

    def test_remaining_unclassified_divergences_fail(self) -> None:
        """Unclassified is not "probably fine". Nobody predicted it, which is worse news than a
        forbidden change, and F2 shows it most prominently for that reason."""
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.DIVERGENT),
            divergences=(_Classified(contracts_mod.UNCLASSIFIED),),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok and "unclassified" in reason


class TestCheatOneWeakeningTheContract:
    """Adversarial, permanent. The claim must be MET, never moved."""

    def test_a_changed_contract_fails_even_with_zero_divergences(self) -> None:
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.EQUIVALENT_UNDER_BUDGET),
            divergences=(),
            contract_before=_CLEAN,
            contract_after="contract-v2-now-permits-everything",
        )
        assert not ok
        assert "the claim was moved, not met" in reason

    def test_it_fails_even_when_the_new_contract_would_call_it_intended(self) -> None:
        """The most tempting shape: rewrite the contract so the divergence is expected, then
        report success. The check is on the FILE, so what the new contract says is irrelevant."""
        ok, _ = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.DIVERGENT),
            divergences=(_Classified(contracts_mod.INTENDED),),
            contract_before=_CLEAN,
            contract_after="rewritten",
        )
        assert not ok


class TestCheatTwoDeletingTheDivergentPath:
    """Adversarial, permanent. Nothing diverges because nothing runs."""

    def test_a_target_that_vanished_fails(self) -> None:
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT, "b": Verdict.EQUIVALENT_UNDER_BUDGET},
            after_bundle=_bundle(b=Verdict.EQUIVALENT_UNDER_BUDGET),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok
        assert "stopped being provable: a" in reason
        assert "because the evidence did" in reason

    def test_deleting_every_target_is_not_a_perfect_score(self) -> None:
        ok, _ = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok


class TestCheatThreeMakingTheTargetUnreachable:
    """Adversarial, permanent. The symbol still exists; the engine can no longer run it."""

    def test_a_target_that_went_unproven_fails(self) -> None:
        """This is the subtle one — the target is still THERE, so a set-membership check over all
        targets would pass. Only counting CONCLUSIVE verdicts catches it."""
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(a=Verdict.UNPROVEN),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok and "stopped being provable: a" in reason

    def test_a_target_that_went_to_error_fails(self) -> None:
        ok, _ = judge(
            before={"a": Verdict.EQUIVALENT_UNDER_BUDGET},
            after_bundle=_bundle(a=Verdict.ERROR),
            divergences=(),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok


class TestWhenSeveralThingsAreWrongTheWorstIsNamed:
    def test_a_changed_contract_outranks_a_lost_target(self) -> None:
        """The reason shown to a user should name the worst thing, not the first thing noticed."""
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT},
            after_bundle=_bundle(),
            divergences=(_Classified(contracts_mod.UNINTENDED),),
            contract_before=_CLEAN,
            contract_after="rewritten",
        )
        assert not ok and "contract changed" in reason

    def test_a_lost_target_outranks_a_remaining_divergence(self) -> None:
        ok, reason = judge(
            before={"a": Verdict.DIVERGENT, "b": Verdict.DIVERGENT},
            after_bundle=_bundle(b=Verdict.DIVERGENT),
            divergences=(_Classified(contracts_mod.UNINTENDED),),
            contract_before=_CLEAN,
            contract_after=_CLEAN,
        )
        assert not ok and "stopped being provable" in reason


@dataclass(frozen=True)
class _Class:
    value: str


@dataclass(frozen=True)
class _Divergence:
    divergence_class: _Class
    detail: str
    minimized_args: str
    minimized_kwargs: str
    base_summary: str
    head_summary: str


class TestTheEvidencePacket:
    """What the model is handed. Facts copied from the bundle, never a summary someone wrote."""

    def _packet(self, contract: contracts_mod.IntentContract | None) -> object:
        from tempest.agent.repair import evidence_for

        return evidence_for(
            _Target("billing.refund.round_amount", Verdict.DIVERGENT),
            _Divergence(
                divergence_class=_Class("RETURN_VALUE"),
                detail="return values differ",
                minimized_args="(2.345,)",
                minimized_kwargs="{}",
                base_summary="returned 2.35",
                head_summary="returned 2.34",
            ),
            contract,
        )

    def test_it_carries_the_minimized_input_not_the_whole_set(self) -> None:
        """Minimization exists so a human — or a model — reasons about the smallest failing
        case. Handing over every input undoes that."""
        packet = self._packet(None)
        body = packet.render()  # type: ignore[attr-defined]
        assert "(2.345,)" in body
        assert "returned 2.35" in body and "returned 2.34" in body
        assert "billing.refund.round_amount" in body

    def test_it_quotes_the_clause_that_was_violated(self) -> None:
        contract = contracts_mod.IntentContract(
            intent="only touch tax", must_not_change=("billing.refund.*",)
        )
        body = self._packet(contract).render()  # type: ignore[attr-defined]
        assert 'must_not_change = "billing.refund.*"' in body

    def test_an_unlisted_symbol_is_described_as_unlisted_not_as_forbidden(self) -> None:
        """The two are different facts and repairing against the wrong one wastes an attempt."""
        contract = contracts_mod.IntentContract(
            intent="only touch tax", may_change=("billing.tax",)
        )
        body = self._packet(contract).render()  # type: ignore[attr-defined]
        assert "not listed in may_change" in body
        assert "only touch tax" in body

    def test_with_no_contract_it_says_so_rather_than_inventing_a_rule(self) -> None:
        """An agent told it violated a clause that does not exist repairs against a fiction."""
        body = self._packet(None).render()  # type: ignore[attr-defined]
        assert "no contract on file" in body

    def test_it_names_the_three_cheats_so_the_model_is_told_they_are_detected(self) -> None:
        body = self._packet(None).render()  # type: ignore[attr-defined]
        assert "Do not edit the contract" in body
        assert "do not delete the symbol" in body
        assert "unreachable" in body


class TestTheOutcomeReportsWhatHappened:
    """F3: never hide the loop. The attempts are returned, and a cheat is visible in them."""

    def _attempt(self, number: int, cheat: str = "") -> object:
        from tempest.agent.repair import RepairAttempt

        packet = TestTheEvidencePacket()._packet(None)
        return RepairAttempt(
            number=number,
            packet=packet,  # type: ignore[arg-type]
            unintended_after=1,
            unclassified_after=0,
            cheat=cheat,
        )

    def test_an_outcome_with_no_cheats_says_so(self) -> None:
        from tempest.agent.repair import RepairOutcome

        outcome = RepairOutcome(
            succeeded=True,
            attempts=(self._attempt(1), self._attempt(2)),  # type: ignore[arg-type]
            reason="fixed",
        )
        assert not outcome.cheated
        assert len(outcome.attempts) == 2, "every attempt is kept, not just the last"

    def test_a_single_cheating_attempt_marks_the_whole_outcome(self) -> None:
        """One attempt that tried to move the goalposts is a fact about the run, and it stays
        visible even if a later attempt succeeded honestly."""
        from tempest.agent.repair import RepairOutcome

        outcome = RepairOutcome(
            succeeded=True,
            attempts=(self._attempt(1, cheat="edited the contract"), self._attempt(2)),  # type: ignore[arg-type]
            reason="fixed on the second try",
        )
        assert outcome.cheated


class TestTheClauseNamesTheRightPattern:
    def test_the_matching_pattern_is_quoted_not_the_first_one_listed(self) -> None:
        """A contract usually forbids several things. Quoting the first entry rather than the one
        that actually matched would send the model to repair an unrelated symbol."""
        from tempest.agent.repair import _clause_for

        contract = contracts_mod.IntentContract(
            intent="only touch tax",
            must_not_change=("billing.audit.*", "billing.ledger.post", "billing.refund.*"),
        )
        assert (
            _clause_for("billing.refund.round", contract) == 'must_not_change = "billing.refund.*"'
        )


class TestPickingWhichDivergenceToRepair:
    """`_first_offender` walks the bundle for the first target the contract does not allow.

    One at a time is deliberate: the minimized repro is a fitness function, and a model handed
    five at once optimises for none of them.
    """

    def _bundle_with(self, *targets: object) -> object:
        @dataclass(frozen=True)
        class _B:
            targets: tuple[object, ...]

        return _B(targets=tuple(targets))

    def _target(self, qualname: str, *, diverges: bool) -> object:
        @dataclass(frozen=True)
        class _Div:
            divergence_class: _Class
            detail: str
            minimized_args: str
            minimized_kwargs: str
            base_summary: str
            head_summary: str

        @dataclass(frozen=True)
        class _T:
            qualname: str
            divergences: tuple[object, ...]

        div = _Div(_Class("RETURN_VALUE"), "differs", "(1,)", "{}", "1", "2")
        return _T(qualname=qualname, divergences=(div,) if diverges else ())

    def test_it_skips_targets_the_contract_allows(self) -> None:
        from tempest.agent.orchestrator import ClassifiedDivergence, _first_offender

        contract = contracts_mod.IntentContract(intent="x", must_not_change=("b",))
        bundle = self._bundle_with(
            self._target("a", diverges=True), self._target("b", diverges=True)
        )
        packet = _first_offender(
            bundle,
            (
                ClassifiedDivergence("a", contracts_mod.INTENDED, "fine"),
                ClassifiedDivergence("b", contracts_mod.UNINTENDED, "not fine"),
            ),
            contract,
        )
        assert packet is not None and packet.qualname == "b"

    def test_an_offender_the_bundle_does_not_carry_yields_nothing(self) -> None:
        """Defensive. The two come from the same proof today, so this should be unreachable —
        but "should be" is the kind of claim this project tests rather than asserts, and
        returning a packet about a target that is not in the bundle would send the model to
        repair something the evidence never mentioned."""
        from tempest.agent.orchestrator import ClassifiedDivergence, _first_offender

        contract = contracts_mod.IntentContract(intent="x", must_not_change=("ghost",))
        bundle = self._bundle_with(self._target("a", diverges=True))
        assert (
            _first_offender(
                bundle,
                (ClassifiedDivergence("ghost", contracts_mod.UNINTENDED, "gone"),),
                contract,
            )
            is None
        )

    def test_a_matching_target_with_no_divergence_record_is_skipped(self) -> None:
        from tempest.agent.orchestrator import ClassifiedDivergence, _first_offender

        contract = contracts_mod.IntentContract(intent="x", must_not_change=("a",))
        bundle = self._bundle_with(self._target("a", diverges=False))
        assert (
            _first_offender(
                bundle,
                (ClassifiedDivergence("a", contracts_mod.UNINTENDED, "no record"),),
                contract,
            )
            is None
        )


class TestTellingARevertFromADeletion:
    """The newest and subtlest piece of F3, and the one the coverage gate caught untested.

    A bundle carries only CHANGED symbols, so a symbol that is PUT BACK vanishes from it exactly
    as a DELETED one does. `reverted_symbols` is the only thing that can tell them apart, and it
    does it by comparing the symbol's SOURCE at baseline and head.

    It was written to fix a real false positive (reverting collateral damage was being called a
    cheat) and it introduced a real false negative, which is recorded in HANDOFF-NEXT §0 rather
    than hidden: a symbol restored byte-for-byte inside a module the agent broke some OTHER way
    is excused here, because its source really is identical. These tests pin what the function
    does today, including that gap, so a future fix has to change a test on purpose.

    States (trap 43): put back · deleted · still different · a lost name the bundle never carried ·
    a file that does not exist at a revision · a head that does not parse.
    """

    BASE = "def total(xs):\n    return sum(xs)\n\n\ndef biggest(xs):\n    return max(xs)\n"

    def _bundle(self) -> object:
        @dataclass(frozen=True)
        class _T:
            qualname: str
            file_path: str

        @dataclass(frozen=True)
        class _B:
            targets: tuple[object, ...]

        return _B(targets=(_T("total", "app.py"), _T("biggest", "app.py")))

    def _reader(self, head_text: str | None) -> object:
        def read(sha: str, _path: str) -> str | None:
            return self.BASE if sha == "base" else head_text

        return read

    def _call(self, lost: set[str], head_text: str | None) -> frozenset[str]:
        from tempest.agent.repair import reverted_symbols

        return reverted_symbols(
            lost=lost,
            first_bundle=self._bundle(),
            read_source=self._reader(head_text),
            baseline="base",
            head="head",
        )

    def test_a_symbol_put_back_is_excused(self) -> None:
        """`biggest` restored while `total` stays changed — the correct repair of collateral
        damage, and the case that used to be reported as a cheat."""
        head = "def total(xs):\n    return sum(xs) + 1\n\n\ndef biggest(xs):\n    return max(xs)\n"
        assert self._call({"biggest"}, head) == frozenset({"biggest"})

    def test_a_symbol_that_is_gone_is_not_excused(self) -> None:
        head = "def total(xs):\n    return sum(xs) + 1\n"
        assert self._call({"biggest"}, head) == frozenset()

    def test_a_symbol_that_is_still_different_is_not_excused(self) -> None:
        head = "def total(xs):\n    return sum(xs)\n\n\ndef biggest(xs):\n    return min(xs)\n"
        assert self._call({"biggest"}, head) == frozenset()

    def test_a_lost_name_the_bundle_never_carried_is_skipped(self) -> None:
        """Defensive: without a file path there is nothing to compare, and guessing would be
        the one direction that turns a cheat into a pass."""
        assert self._call({"ghost"}, self.BASE) == frozenset()

    def test_a_file_missing_at_a_revision_is_not_evidence_of_a_revert(self) -> None:
        assert self._call({"biggest"}, None) == frozenset()

    def test_a_head_that_does_not_parse_is_not_evidence_of_a_revert(self) -> None:
        """Conservative on purpose. An unparseable head is a broken tree, not a restored one."""
        assert self._call({"biggest"}, "def total(xs:\n    oops\n") == frozenset()

    def test_the_known_gap_is_pinned_so_a_fix_must_change_it_deliberately(self) -> None:
        """HANDOFF-NEXT §0. The agent restores `biggest` byte-for-byte AND breaks the module with
        an unrelated import. The source really is identical, so this function excuses it — and
        `repair_bench` therefore miscounts that task as a repair.

        This test asserts TODAY'S behaviour, not the desired behaviour. When the gap is fixed it
        must fail, and whoever fixes it has to come here and say so.
        """
        head = (
            "import no_such_module_xyz\n\n\n"
            "def total(xs):\n    return sum(xs) + 1\n\n\ndef biggest(xs):\n    return max(xs)\n"
        )
        assert self._call({"biggest"}, head) == frozenset({"biggest"}), (
            "if this now returns an empty set the gap is fixed — update HANDOFF-NEXT §0 and "
            "ADR-0050, and check `collateral-damage-repaired` did not regress"
        )
