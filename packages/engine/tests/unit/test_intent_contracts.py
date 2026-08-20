"""F2 — Intent Contracts. The safety property is the whole test file.

F2's gate says **zero** unintended divergences may be classified as intended, because a false
`INTENDED` is the one outcome that converts evidence into false reassurance: the user asked for a
change in one place, something else changed too, and the product told them it was expected. Every
design decision below exists to make that unreachable, and every test here attacks it.

The classifier is deliberately dull — exact names, one explicit wildcard form, no inference. A
cleverer matcher would be a machine for generating false INTENDEDs.

States enumerated before the tests (trap 43): a symbol explicitly permitted · explicitly forbidden
· in BOTH lists · in neither · a `Class.*` wildcard · a `module.*` wildcard · a name that merely
shares a prefix · a name that merely shares a stem · `*` alone · an empty pattern · an empty
intent · a contract file that does not exist · one that is not TOML · one whose `intent` is not a
string · one whose lists are not lists of strings · a model reply that is fenced · one that is not
TOML · a model that tries to rename the intent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tempest.agent import contracts
from tempest.agent.contracts import (
    INTENDED,
    UNCLASSIFIED,
    UNINTENDED,
    ContractError,
    IntentContract,
)


def _c(**kw: object) -> IntentContract:
    base: dict[str, object] = {"intent": "fix the rounding on refunds; nothing else changes"}
    base.update(kw)
    return IntentContract(**base)  # type: ignore[arg-type]


class TestNothingIsIntendedUnlessItWasSaidSoOutLoud:
    def test_an_explicitly_permitted_symbol_is_intended(self) -> None:
        assert (
            _c(may_change=("billing.refund.round_amount",)).classify("billing.refund.round_amount")
            == INTENDED
        )

    def test_a_symbol_nobody_mentioned_is_unclassified_never_intended(self) -> None:
        """The default answer for an unpredicted divergence is "nobody predicted this", and F2
        says that is the one shown MOST prominently."""
        assert (
            _c(may_change=("billing.refund.round_amount",)).classify("billing.tax.compute")
            == UNCLASSIFIED
        )

    def test_an_explicitly_forbidden_symbol_is_unintended(self) -> None:
        assert (
            _c(must_not_change=("billing.tax.compute",)).classify("billing.tax.compute")
            == UNINTENDED
        )

    def test_a_symbol_in_both_lists_resolves_to_unintended(self) -> None:
        """A contradiction in the contract. The honest resolution of an ambiguity is the one that
        SHOWS the user the divergence, not the one that hides it."""
        both = _c(may_change=("a.b",), must_not_change=("a.b",))
        assert both.classify("a.b") == UNINTENDED

    def test_an_empty_contract_classifies_everything_unclassified(self) -> None:
        assert _c().classify("anything.at.all") == UNCLASSIFIED

    def test_every_answer_is_one_of_the_three(self) -> None:
        contract = _c(may_change=("a.b",), must_not_change=("c.d",))
        for name in ("a.b", "c.d", "e.f", "", "..."):
            assert contract.classify(name) in contracts.CLASSIFICATIONS


class TestTheMatcherCannotBeTrickedIntoAFalseIntended:
    @pytest.mark.parametrize(
        "permitted,asked",
        [
            ("Refund.round", "Refund.rounding"),  # shares a stem
            ("pkg.a", "pkg.ab"),  # shares a prefix
            ("pkg.mod.fn", "otherpkg.mod.fn"),  # shares a suffix
            ("pkg.mod", "pkg.module.fn"),  # prefix without the dot boundary
        ],
    )
    def test_a_merely_similar_name_is_not_a_match(self, permitted: str, asked: str) -> None:
        """A `startswith` rule would call every one of these INTENDED. Each is a real name shape,
        and each would be a false reassurance about a symbol nobody permitted."""
        assert _c(may_change=(permitted,)).classify(asked) == UNCLASSIFIED

    def test_a_class_wildcard_matches_its_members_and_stops_there(self) -> None:
        contract = _c(may_change=("billing.Refund.*",))
        assert contract.classify("billing.Refund.round") == INTENDED
        assert contract.classify("billing.Refund") == INTENDED
        assert contract.classify("billing.RefundLog.round") == UNCLASSIFIED

    def test_a_module_wildcard_matches_its_symbols_and_stops_there(self) -> None:
        contract = _c(may_change=("billing.refund.*",))
        assert contract.classify("billing.refund.round_amount") == INTENDED
        assert contract.classify("billing.refunds.round_amount") == UNCLASSIFIED

    def test_permitting_everything_is_refused_at_construction(self) -> None:
        """A contract that permits everything makes every divergence INTENDED, which is exactly
        what the gate forbids. It is not a contract; it is the absence of one."""
        for star in ("*", ".*", "  *  "):
            with pytest.raises(ContractError, match="not an intent"):
                _c(may_change=(star,))

    def test_an_empty_pattern_is_refused(self) -> None:
        with pytest.raises(ContractError, match="matches nothing"):
            _c(may_change=("",))

    def test_a_contract_must_remember_what_it_was_compiled_from(self) -> None:
        with pytest.raises(ContractError, match="the intent it was compiled from"):
            IntentContract(intent="   ")


class TestTheFileTheUserEdits:
    def test_a_contract_round_trips_through_the_file(self, tmp_path: Path) -> None:
        original = _c(
            may_change=("billing.refund.round_amount", "billing.Refund.*"),
            must_not_change=("billing.tax.compute",),
        )
        contracts.save(tmp_path, "task-1", original)
        loaded = contracts.load(tmp_path, "task-1")
        assert loaded == original

    def test_the_file_explains_itself(self, tmp_path: Path) -> None:
        """A contract the user cannot understand is a contract the user cannot correct, and an
        uncorrected contract is a machine for misclassification."""
        contracts.save(tmp_path, "task-1", _c(may_change=("a.b",)))
        body = contracts.path_for(tmp_path, "task-1").read_text(encoding="utf-8")
        for phrase in ("may_change", "must_not_change", "UNCLASSIFIED", "yours to edit"):
            assert phrase in body

    def test_no_contract_is_a_real_answer_not_an_error(self, tmp_path: Path) -> None:
        """A task nobody stated an intent for is proved identically; every divergence is simply
        unclassified, which is the honest description of it."""
        assert contracts.load(tmp_path, "never-written") is None

    def test_a_task_id_cannot_place_the_file_outside_the_contracts_directory(
        self, tmp_path: Path
    ) -> None:
        target = contracts.path_for(tmp_path, "../../escape")
        assert target.parent == tmp_path / contracts.CONTRACTS_DIR
        assert ".." not in target.name

    def test_quotes_and_newlines_in_an_intent_survive(self, tmp_path: Path) -> None:
        """The intent is the user's words. A serializer that mangled them would make the file a
        record of something the user did not say."""
        tricky = 'fix "rounding"\nnothing\\else changes'
        contracts.save(tmp_path, "t", _c(intent=tricky))
        loaded = contracts.load(tmp_path, "t")
        assert loaded is not None and loaded.intent == tricky

    def test_malformed_toml_is_refused_not_ignored(self, tmp_path: Path) -> None:
        path = contracts.path_for(tmp_path, "t")
        path.parent.mkdir(parents=True)
        path.write_text("intent = [unclosed", encoding="utf-8")
        with pytest.raises(ContractError, match="not valid TOML"):
            contracts.load(tmp_path, "t")

    def test_a_non_string_intent_is_refused(self, tmp_path: Path) -> None:
        path = contracts.path_for(tmp_path, "t")
        path.parent.mkdir(parents=True)
        path.write_text("intent = 7\n", encoding="utf-8")
        with pytest.raises(ContractError, match="must be a string"):
            contracts.load(tmp_path, "t")

    def test_a_malformed_list_is_refused_rather_than_emptied(self, tmp_path: Path) -> None:
        """Skipping a malformed `must_not_change` would turn a contract that forbids changes into
        one that forbids nothing — a typo silently becoming a permission."""
        path = contracts.path_for(tmp_path, "t")
        path.parent.mkdir(parents=True)
        path.write_text('intent = "x"\nmust_not_change = "a.b"\n', encoding="utf-8")
        with pytest.raises(ContractError, match="list of strings"):
            contracts.load(tmp_path, "t")

    def test_a_list_with_a_non_string_entry_is_refused(self, tmp_path: Path) -> None:
        path = contracts.path_for(tmp_path, "t")
        path.parent.mkdir(parents=True)
        path.write_text('intent = "x"\nmay_change = ["a.b", 7]\n', encoding="utf-8")
        with pytest.raises(ContractError, match="list of strings"):
            contracts.load(tmp_path, "t")


class TestTheModelProposesAndDoesNotDecide:
    def test_a_structured_reply_becomes_a_contract(self) -> None:
        reply = (
            'intent = "whatever the model thought"\n'
            'may_change = ["billing.refund.round_amount"]\n'
            'must_not_change = ["billing.tax.compute"]\n'
        )
        got = contracts.draft_from_text(reply, intent="fix rounding; nothing else")
        assert got.may_change == ("billing.refund.round_amount",)
        assert got.must_not_change == ("billing.tax.compute",)

    def test_the_users_words_survive_the_models_paraphrase(self) -> None:
        """A contract records what the USER asked for. A model's restatement — however faithful —
        would make the file a record of what a model understood instead."""
        reply = 'intent = "Adjust refund rounding behaviour."\nmay_change = ["a.b"]\n'
        got = contracts.draft_from_text(reply, intent="fix the rounding on refunds")
        assert got.intent == "fix the rounding on refunds"

    def test_a_fenced_reply_is_accepted(self) -> None:
        """Models fence code even when told not to. Refusing over a formatting habit would throw
        away a contract that is otherwise exact."""
        reply = '```toml\nintent = "x"\nmay_change = ["a.b"]\n```'
        assert contracts.draft_from_text(reply, intent="i").may_change == ("a.b",)

    def test_a_fence_without_a_closing_line_is_still_accepted(self) -> None:
        reply = '```\nintent = "x"\nmay_change = ["a.b"]'
        assert contracts.draft_from_text(reply, intent="i").may_change == ("a.b",)

    def test_prose_instead_of_a_contract_is_refused(self) -> None:
        with pytest.raises(ContractError, match="not valid TOML"):
            contracts.draft_from_text("Sure! I'd be happy to help.", intent="i")

    def test_a_model_cannot_smuggle_in_permission_for_everything(self) -> None:
        """The construction guard is what enforces this, so it holds no matter who authored the
        contract — the model, the user's editor, or a future caller."""
        reply = 'intent = "x"\nmay_change = ["*"]\n'
        with pytest.raises(ContractError, match="not an intent"):
            contracts.draft_from_text(reply, intent="i")

    def test_the_drafting_prompt_tells_the_model_it_is_not_deciding(self) -> None:
        """L17 in the words the model actually receives."""
        assert "not deciding whether the change is correct" in contracts.DRAFT_SYSTEM_PROMPT
        assert "When in doubt, leave it out" in contracts.DRAFT_SYSTEM_PROMPT
