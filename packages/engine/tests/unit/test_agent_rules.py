"""F15 + P3 — a behavioural rule is a wall, not advice (Phase 23).

The gate F15 names is *"a behavioural rule violation is blocked by the engine even when the model
is explicitly instructed to violate it"*, and the reason that is achievable at all is that no part
of the enforcement runs through the model: the rules are read from disk by the host, folded into
the contract the classifier consumes, and applied after the model's turn is over.

States enumerated before the tests (trap 43): no rules at all · a root rule · a directory-local
rule · a rule whose scope does not reach the changed files · a rule that contradicts the task's
own contract · a rule file with a typo · a rule file that is not valid TOML · a rule trying to
WIDEN what may change · a task with no contract that a rule governs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tempest.agent import contracts as contracts_mod
from tempest.agent import rules as rules_mod


def _write(repo: Path, rel: str, body: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


class TestLoading:
    def test_a_repo_with_no_rules_answers_with_none_of_them(self, tmp_path: Path) -> None:
        assert rules_mod.load(tmp_path) == []

    def test_a_root_rule_governs_everything(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            ".tempest/rules/billing.toml",
            '[[rule]]\nname = "billing is frozen"\nmust_not_change = ["charge"]\nwhy = "money"\n',
        )
        (rule,) = rules_mod.load(tmp_path)
        assert rule.name == "billing is frozen"
        assert rule.must_not_change == ("charge",)
        assert rule.governs("anything/at/all.py")

    def test_a_directory_local_rule_governs_only_its_subtree(self, tmp_path: Path) -> None:
        _write(tmp_path, "billing/rules.toml", '[[rule]]\nmust_not_change = ["refund"]\n')
        (rule,) = rules_mod.load(tmp_path)
        assert rule.scope == "billing"
        assert rule.governs("billing/refunds.py")
        assert rule.governs("billing")
        assert not rule.governs("billinginfo/other.py"), "a prefix is not a directory"
        assert not rule.governs("shipping/other.py")

    def test_a_typo_is_refused_rather_than_ignored(self, tmp_path: Path) -> None:
        """A rule that silently fails to load is worse than no rule: the user believes the wall
        is there. `must_not_chnage` is the whole failure mode in one keystroke."""
        _write(tmp_path, ".tempest/rules/x.toml", '[[rule]]\nmust_not_chnage = ["charge"]\n')
        with pytest.raises(rules_mod.RuleError, match="must_not_chnage"):
            rules_mod.load(tmp_path)

    def test_a_file_that_is_not_toml_is_refused(self, tmp_path: Path) -> None:
        _write(tmp_path, ".tempest/rules/x.toml", "this is not toml [[[")
        with pytest.raises(rules_mod.RuleError):
            rules_mod.load(tmp_path)

    def test_a_file_with_no_rule_tables_is_refused(self, tmp_path: Path) -> None:
        _write(tmp_path, ".tempest/rules/x.toml", 'name = "not a rule table"\n')
        with pytest.raises(rules_mod.RuleError, match=r"\[\[rule\]\]"):
            rules_mod.load(tmp_path)


class TestApplying:
    def _contract(self) -> contracts_mod.IntentContract:
        return contracts_mod.IntentContract(
            intent="tidy the refund path", may_change=("refund", "charge")
        )

    def test_a_rule_forbids_a_symbol_the_task_contract_permitted(self, tmp_path: Path) -> None:
        """The whole feature in one assertion. The task asked to change `charge`; the standing
        rule says it may not. The rule is the user's standing decision and the contract is one
        task's request, so the rule wins."""
        _write(tmp_path, ".tempest/rules/x.toml", '[[rule]]\nmust_not_change = ["charge"]\n')
        applied = rules_mod.apply_to(
            self._contract(), rules_mod.load(tmp_path), files=("billing/charge.py",)
        )
        assert applied.contract is not None
        assert "charge" in applied.contract.must_not_change
        assert "charge" not in applied.contract.may_change
        assert applied.contract.classify("charge") == contracts_mod.UNINTENDED
        assert applied.contract.classify("refund") == contracts_mod.INTENDED

    def test_a_rule_that_does_not_reach_the_files_changes_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path, "billing/rules.toml", '[[rule]]\nmust_not_change = ["charge"]\n')
        contract = self._contract()
        applied = rules_mod.apply_to(
            contract, rules_mod.load(tmp_path), files=("shipping/label.py",)
        )
        assert applied.contract is contract and applied.applied == ()

    def test_a_rule_may_never_WIDEN_what_may_change(self, tmp_path: Path) -> None:
        """The escalation this design refuses. An agent can write files; if a rule could add to
        `may_change`, an agent could grant itself permission by writing a rule."""
        _write(
            tmp_path,
            ".tempest/rules/x.toml",
            '[[rule]]\nmay_change = ["everything_else"]\nmust_not_change = ["charge"]\n',
        )
        applied = rules_mod.apply_to(
            contracts_mod.IntentContract(intent="do a thing"),
            rules_mod.load(tmp_path),
            files=("app.py",),
        )
        assert applied.contract is not None
        assert applied.contract.may_change == ()
        assert applied.contract.classify("everything_else") == contracts_mod.UNCLASSIFIED

    def test_a_task_with_no_contract_still_gets_the_rule(self, tmp_path: Path) -> None:
        """ "The user did not state an intent" is not permission."""
        _write(
            tmp_path,
            ".tempest/rules/x.toml",
            '[[rule]]\nname = "billing is frozen"\nmust_not_change = ["charge"]\n',
        )
        applied = rules_mod.apply_to(None, rules_mod.load(tmp_path), files=("app.py",))
        assert applied.contract is not None
        assert applied.contract.classify("charge") == contracts_mod.UNINTENDED
        assert "billing is frozen" in applied.contract.intent

    def test_a_task_with_no_contract_and_no_governing_rule_stays_uncontracted(
        self, tmp_path: Path
    ) -> None:
        """Not an empty contract: an empty one would make the repair loop engage on a task
        nobody stated an intent for, which is exactly F2's objection."""
        applied = rules_mod.apply_to(None, rules_mod.load(tmp_path), files=("app.py",))
        assert applied.contract is None

    def test_the_reason_travels_with_the_rule(self, tmp_path: Path) -> None:
        """A wall with no explanation is indistinguishable from a bug."""
        _write(
            tmp_path,
            ".tempest/rules/x.toml",
            '[[rule]]\nname = "billing"\nmust_not_change = ["charge"]\n'
            'why = "every change here is a refund incident"\n',
        )
        applied = rules_mod.apply_to(None, rules_mod.load(tmp_path), files=("app.py",))
        assert "refund incident" in applied.explain()

    def test_no_rules_says_so_rather_than_printing_an_empty_heading(self, tmp_path: Path) -> None:
        applied = rules_mod.apply_to(None, [], files=("app.py",))
        assert applied.explain() == "no behavioural rules applied to this task"


class TestTheShapesAFileCanTakeAndShouldNot:
    def test_a_rule_list_of_non_tables_is_refused(self, tmp_path: Path) -> None:
        """`rule = ["billing"]` parses as TOML and is not a rule. Reading it as one would drop
        every key and produce a wall with nothing behind it."""
        _write(tmp_path, ".tempest/rules/x.toml", 'rule = ["billing"]\n')
        with pytest.raises(rules_mod.RuleError, match="must be a table"):
            rules_mod.load(tmp_path)

    def test_a_rules_file_inside_the_rules_directory_is_not_read_twice(
        self, tmp_path: Path
    ) -> None:
        """`.tempest/rules/rules.toml` is matched by both passes — the glob over the rules
        directory and the walk for directory-local files. Reading it twice would double every
        clause it declares and give it a `.tempest/rules` scope, which governs nothing."""
        _write(tmp_path, ".tempest/rules/rules.toml", '[[rule]]\nmust_not_change = ["charge"]\n')
        loaded = rules_mod.load(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].scope == "", "read as a ROOT rule, which is where it lives"

    def test_a_rule_with_no_stated_reason_still_reads_cleanly(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            ".tempest/rules/x.toml",
            '[[rule]]\nname = "frozen"\nmust_not_change = ["charge"]\n',
        )
        applied = rules_mod.apply_to(None, rules_mod.load(tmp_path), files=("app.py",))
        text = applied.explain()
        assert "frozen" in text and "must not change: charge" in text
        assert "because:" not in text

    def test_a_rule_that_forbids_nothing_says_so_rather_than_printing_an_empty_clause(
        self, tmp_path: Path
    ) -> None:
        _write(tmp_path, ".tempest/rules/x.toml", '[[rule]]\nname = "documentation only"\n')
        applied = rules_mod.apply_to(
            contracts_mod.IntentContract(intent="do a thing"),
            rules_mod.load(tmp_path),
            files=("app.py",),
        )
        assert "must not change: (nothing)" in applied.explain()
