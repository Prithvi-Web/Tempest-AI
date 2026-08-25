"""C5 gate pins (module pulled forward from C10, ADR-0088):
`feature_ledger --every-feature-classified --no-verdict-vocab-in-platform` (L30, L31, L36.3).

Every check is proven to FAIL on a violating ledger: a gate that cannot fail is decoration,
and this one guards a file that was hand-maintained and unread for five phases.

The anti-vacuity arms matter most. A ledger gate's characteristic failure is not a wrong
answer — it is silently measuring nothing, because a column was renamed, a table reshaped, or
a heading moved, and the parser quietly matched zero rows and reported green. Those arms are
`TestVacuity`, and they are the reason this module fails on an unrecognised table instead of
skipping it.
"""

from pathlib import Path

import pytest

from tempest.dev import feature_ledger

_ARGS = ["--every-feature-classified", "--no-verdict-vocab-in-platform"]
# What `make verify` actually runs — the real ledger is held to all three arms.
_FULL = [*_ARGS, "--verifying-tests-resolve"]

_PASSING = """\
# FEATURES — fixture

> **Status vocabulary:** `ADOPTED` · `IN_PROGRESS` · `NOT_STARTED` · `SHIPPED` · `PLANNED`.

## Part 1 — LibreChat capabilities (the parity denominator)

### Providers and models

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC01 | Endpoint breadth | PROOF_ADJACENT | C4 | NOT_STARTED | `provider_matrix` |
| LC02 | Reasoning render | PLATFORM | C4 | ADOPTED | E2E render test |
| LC03 | Subagents | PROOF_NATIVE | C5 | SHIPPED (P4) | `subagent_bench` |

**Denominator: 3 rows. Parity % is computed over these.**

## Part 2 — Tempest capabilities (never reduced, never demoted)

### The engine — shipped

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T01 | Nine-stage differential engine | PROOF_NATIVE | SHIPPED | `make verify` |

### The agent — planned

| # | Capability | Rel. | Phase | Status | Gate |
|---|---|---|---|---|---|
| T02 | Adversarial self-validation | PROOF_NATIVE | 24 | PLANNED | `mutation_bench` |

### Known-open, carried honestly

| # | Item | Phase | Note |
|---|---|---|---|
| T03 | TypeScript execution half | C0 → 3 | Analysis half is done |
| T04 | A recorded demo | owner | No hermetic gate can assert it |
"""


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    """A minimal ledger that PASSES, for tests to then break one property at a time."""
    path = tmp_path / "docs" / "FEATURES-V3.md"
    path.parent.mkdir(parents=True)
    path.write_text(_PASSING, encoding="utf-8")
    return path


def _run(ledger: Path) -> int:
    return feature_ledger.main([*_ARGS, "--ledger", str(ledger)])


def _rewrite(ledger: Path, old: str, new: str) -> None:
    """Swap one substring, asserting it was actually there — a fixture edit that silently
    matched nothing would make the test below pass for the wrong reason."""
    body = ledger.read_text(encoding="utf-8")
    assert old in body, f"fixture drift: {old!r} not in the passing ledger"
    ledger.write_text(body.replace(old, new, 1), encoding="utf-8")


class TestPassing:
    def test_a_clean_ledger_passes(self, ledger: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(ledger) == 0
        assert "L30 holds" in capsys.readouterr().out

    def test_the_real_ledger_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The production command, against the file it exists to measure."""
        assert feature_ledger.main(_FULL) == 0
        assert "L30 holds" in capsys.readouterr().out

    def test_repo_root_marker_walk_finds_the_repository(self) -> None:
        assert (feature_ledger._repo_root() / "packages" / "desktop").is_dir()

    def test_a_missing_ledger_fails(self, tmp_path: Path) -> None:
        assert feature_ledger.main([*_ARGS, "--ledger", str(tmp_path / "nope.md")]) == 1


class TestVacuity:
    """The failure mode that matters: measuring nothing and reporting green."""

    def test_a_ledger_with_no_feature_rows_fails_rather_than_passing_vacuously(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "empty.md"
        path.write_text("# nothing here\n", encoding="utf-8")
        assert feature_ledger.main([*_ARGS, "--ledger", str(path)]) == 1

    def test_an_unrecognised_table_shape_fails_instead_of_being_skipped(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| # | Capability | Rel. | Phase | Status | Verifying test |",
            "| # | Capability | Relationship | Phase | Status | Verifying test |",
        )
        assert _run(ledger) == 1

    def test_a_renamed_status_column_cannot_silently_drop_three_rows(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| # | Capability | Rel. | Phase | Status | Verifying test |",
            "| # | Capability | Rel. | Phase | State | Verifying test |",
        )
        assert _run(ledger) == 1

    def test_a_fenced_example_table_is_documentation_not_structure(self, ledger: Path) -> None:
        body = ledger.read_text(encoding="utf-8")
        ledger.write_text(
            body + "\n```markdown\n| # | Capability | Rel. | Phase | Status | Verifying test |\n"
            "|---|---|---|---|---|---|\n| LC01 | dup | | | | |\n```\n",
            encoding="utf-8",
        )
        assert _run(ledger) == 0


class TestRelationship:
    def test_a_blank_relationship_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger, "| LC01 | Endpoint breadth | PROOF_ADJACENT |", "| LC01 | Endpoint breadth |  |"
        )
        assert _run(ledger) == 1

    def test_an_invented_relationship_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| LC01 | Endpoint breadth | PROOF_ADJACENT |",
            "| LC01 | Endpoint breadth | PROOF_ISH |",
        )
        assert _run(ledger) == 1

    def test_a_lowercase_relationship_is_not_the_vocabulary(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| LC01 | Endpoint breadth | PROOF_ADJACENT |",
            "| LC01 | Endpoint breadth | proof_adjacent |",
        )
        assert _run(ledger) == 1


class TestStatus:
    def test_an_invented_status_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| C4 | NOT_STARTED |", "| C4 | NEARLY_DONE |")
        assert _run(ledger) == 1

    def test_a_blank_status_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| C4 | NOT_STARTED |", "| C4 |  |")
        assert _run(ledger) == 1

    def test_a_shipped_row_may_name_the_feature_that_satisfies_it(self, ledger: Path) -> None:
        assert _run(ledger) == 0  # the fixture's LC03 is `SHIPPED (P4)`

    def test_a_shipped_row_with_an_empty_provenance_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "SHIPPED (P4)", "SHIPPED ()")
        assert _run(ledger) == 1


class TestEvidence:
    def test_an_empty_verifying_test_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| C4 | NOT_STARTED | `provider_matrix` |", "| C4 | NOT_STARTED |  |")
        assert _run(ledger) == 1

    def test_a_placeholder_dash_is_not_a_verifying_test(self, ledger: Path) -> None:
        _rewrite(ledger, "| C4 | NOT_STARTED | `provider_matrix` |", "| C4 | NOT_STARTED | — |")
        assert _run(ledger) == 1

    def test_an_empty_capability_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC01 | Endpoint breadth |", "| LC01 |  |")
        assert _run(ledger) == 1


class TestPhase:
    def test_an_unfinished_row_with_a_blank_phase_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger, "| PROOF_ADJACENT | C4 | NOT_STARTED |", "| PROOF_ADJACENT |  | NOT_STARTED |"
        )
        assert _run(ledger) == 1

    def test_a_nonsense_phase_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| PROOF_ADJACENT | C4 | NOT_STARTED |",
            "| PROOF_ADJACENT | soon | NOT_STARTED |",
        )
        assert _run(ledger) == 1

    def test_a_shipped_row_needs_no_future_phase(self, ledger: Path) -> None:
        assert _run(ledger) == 0  # the fixture's T01 table carries no Phase column at all

    def test_a_phase_range_is_a_phase(self, ledger: Path) -> None:
        assert _run(ledger) == 0  # the fixture's T03 is `C0 → 3`


class TestIdentity:
    def test_a_duplicate_id_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC02 | Reasoning render |", "| LC01 | Reasoning render |")
        assert _run(ledger) == 1

    def test_an_id_duplicated_between_a_feature_and_an_open_item_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger, "| T03 | TypeScript execution half |", "| T01 | TypeScript execution half |"
        )
        assert _run(ledger) == 1

    def test_a_malformed_id_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC01 | Endpoint breadth |", "| LC-1 | Endpoint breadth |")
        assert _run(ledger) == 1

    def test_a_lettered_suffix_is_a_legitimate_id(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC02 | Reasoning render |", "| LC01b | Reasoning render |")
        assert _run(ledger) == 0


class TestDenominator:
    def test_a_stale_denominator_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "**Denominator: 3 rows.", "**Denominator: 2 rows.")
        assert _run(ledger) == 1

    def test_a_missing_denominator_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "**Denominator: 3 rows. Parity % is computed over these.**", "")
        assert _run(ledger) == 1

    def test_adding_a_part_one_row_without_moving_the_denominator_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "\n**Denominator: 3 rows.",
            "| LC04 | A new upstream capability | PLATFORM | C7 | NOT_STARTED | E2E |\n"
            "\n**Denominator: 3 rows.",
        )
        assert _run(ledger) == 1


class TestVerdictVocabularyInPlatformRows:
    def test_a_platform_row_borrowing_a_verdict_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC02 | Reasoning render |", "| LC02 | Renders UNPROVEN inline |")
        assert _run(ledger) == 1

    def test_a_platform_rows_verifying_test_may_not_borrow_one_either(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| C4 | ADOPTED | E2E render test |",
            "| C4 | ADOPTED | asserts the DIVERGENT badge renders |",
        )
        assert _run(ledger) == 1

    def test_a_proof_native_row_may_name_the_vocabulary_it_owns(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC03 | Subagents |", "| LC03 | Subagents reporting UNPROVEN |")
        assert _run(ledger) == 0

    def test_lowercase_english_is_not_the_reserved_vocabulary(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| LC02 | Reasoning render |",
            "| LC02 | Reasoning render, unproven and divergent from upstream |",
        )
        assert _run(ledger) == 0

    def test_a_substring_is_not_a_token(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC02 | Reasoning render |", "| LC02 | UNPROVENANCE tracking |")
        assert _run(ledger) == 0

    def test_the_vocabulary_arm_is_separately_armed(self, ledger: Path) -> None:
        """The two flags police different laws, and each must bite on its own — a row that is
        correctly CLASSIFIED can still borrow the vocabulary it is forbidden."""
        _rewrite(ledger, "| LC02 | Reasoning render |", "| LC02 | Renders UNPROVEN inline |")
        classified = ["--every-feature-classified", "--ledger", str(ledger)]
        assert feature_ledger.main(classified) == 0
        vocabulary = ["--no-verdict-vocab-in-platform", "--ledger", str(ledger)]
        assert feature_ledger.main(vocabulary) == 1


class TestKnownOpenItems:
    def test_an_open_item_may_not_smuggle_a_status(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| T04 | A recorded demo | owner | No hermetic gate can assert it |",
            "| T04 | A recorded demo | owner | ADOPTED |",
        )
        assert _run(ledger) == 1

    def test_an_open_item_with_no_note_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "| T04 | A recorded demo | owner | No hermetic gate can assert it |",
            "| T04 | A recorded demo | owner |  |",
        )
        assert _run(ledger) == 1

    def test_an_open_item_with_no_phase_fails(self, ledger: Path) -> None:
        _rewrite(ledger, "| T04 | A recorded demo | owner |", "| T04 | A recorded demo |  |")
        assert _run(ledger) == 1


class TestVerifyingTestsResolve:
    """Ledger rule 1, made mechanical: a finished row must cite a test that EXISTS.

    This is the arm that separates an instrument from a document that checks itself. Every
    other arm reads the ledger against the ledger; this one reads it against the tree.
    """

    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        """A tiny Tempest-shaped tree with exactly one real test defined in it."""
        tests = tmp_path / "packages" / "engine" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_real.py").write_text(
            "def test_a_real_pin() -> None:\n    pass\n"
            "# a mention of test_only_in_a_comment must not resolve\n",
            encoding="utf-8",
        )
        rust = tmp_path / "packages" / "desktop" / "src-tauri" / "src"
        rust.mkdir(parents=True)
        (rust / "lib.rs").write_text(
            "fn not_a_test() {}\n\n    #[test]\n    fn a_real_rust_pin() {}\n", encoding="utf-8"
        )
        return tmp_path

    def _ledger_citing(self, tree: Path, evidence: str, status: str = "ADOPTED") -> Path:
        path = tree / "LEDGER.md"
        path.write_text(
            "## Part 1 — LibreChat capabilities\n\n"
            "| # | Capability | Rel. | Phase | Status | Verifying test |\n"
            "|---|---|---|---|---|---|\n"
            f"| LC01 | A capability | PLATFORM | C5 | {status} | {evidence} |\n\n"
            "**Denominator: 1 rows. Parity % is computed over these.**\n\n"
            "## Part 2 — Tempest capabilities\n",
            encoding="utf-8",
        )
        return path

    def _run(self, tree: Path, path: Path) -> int:
        return feature_ledger.main(
            ["--verifying-tests-resolve", "--ledger", str(path), "--root", str(tree)]
        )

    def test_a_row_citing_a_defined_python_test_resolves(self, tree: Path) -> None:
        assert self._run(tree, self._ledger_citing(tree, "`test_a_real_pin` pins it")) == 0

    def test_a_row_citing_a_defined_rust_test_resolves(self, tree: Path) -> None:
        assert self._run(tree, self._ledger_citing(tree, "`a_real_rust_pin` (cargo)")) == 0

    def test_a_row_citing_a_test_nobody_wrote_fails(self, tree: Path) -> None:
        assert self._run(tree, self._ledger_citing(tree, "`test_that_was_never_written`")) == 1

    def test_a_name_that_appears_only_in_a_comment_does_not_resolve(self, tree: Path) -> None:
        """A mention is not a definition — otherwise citing a test in a TODO would discharge
        the row that names it."""
        assert self._run(tree, self._ledger_citing(tree, "`test_only_in_a_comment`")) == 1

    def test_a_finished_row_citing_nothing_at_all_fails(self, tree: Path) -> None:
        assert self._run(tree, self._ledger_citing(tree, "an end-to-end render test")) == 1

    def test_an_unfinished_row_is_not_asked_for_a_test_that_exists(self, tree: Path) -> None:
        """NOT_STARTED names the test that WILL verify it; requiring it to exist already would
        forbid the ledger from planning."""
        path = self._ledger_citing(tree, "a future E2E test", status="NOT_STARTED")
        assert self._run(tree, path) == 0

    def test_the_arm_is_separately_armed(self, tree: Path) -> None:
        path = self._ledger_citing(tree, "`test_that_was_never_written`")
        assert feature_ledger.main(["--every-feature-classified", "--ledger", str(path)]) == 0
        assert self._run(tree, path) == 1

    def test_a_fiction_cited_BESIDE_a_real_test_still_fails(self, tree: Path) -> None:
        """The weakness this arm was strengthened to close, and it was found the hard way:
        while correcting LC03 the author invented `test_platform_catalog`, and the row passed
        because a real gate name resolved in the same cell. A token shaped like a test must
        exist on its own account."""
        path = self._ledger_citing(tree, "`test_a_real_pin` and `test_never_written_at_all`")
        assert self._run(tree, path) == 1

    def test_a_non_test_identifier_beside_a_real_test_is_fine(self, tree: Path) -> None:
        """The counter-test that keeps the rule from crying wolf: rows legitimately cite
        flags, file names and API shapes, and none of those is a test that must exist."""
        path = self._ledger_citing(tree, "`test_a_real_pin`, with a `Range:` header and `llamacpp`")
        assert self._run(tree, path) == 0

    def test_the_index_finds_the_real_repositorys_own_gates(self) -> None:
        """A resolver that matched nothing would pass every row vacuously."""
        names = feature_ledger.verifier_index(feature_ledger._repo_root())
        assert "agent_bench" in names
        assert "subagent_bench" in names
        assert "TestSteering" in names
        assert "14-editor-budgets.spec" in names
        assert len(names) > 1000

    def test_the_index_holds_only_tests_and_gates(self) -> None:
        """The bar a finished row clears. Its first version indexed every definition of any
        kind, so ordinary English cleared it — a row reading "proven by the `read` path end to
        end" resolved because something somewhere is named `read`."""
        names = feature_ledger.verifier_index(feature_ledger._repo_root())
        for word in ("read", "done", "state", "value", "open", "close", "verify", "check"):
            assert word not in names, f"{word!r} is English, not a verifier"

    def test_an_adopted_row_citing_only_english_fails(self, tree: Path) -> None:
        path = self._ledger_citing(tree, "proven by the `read` path end to end")
        assert self._run(tree, path) == 1


class TestVacuityClosed:
    """Every hole an adversarial audit demonstrated, pinned so it cannot reopen.

    All of these made a FALSE thing report green: rows a reader cannot see being counted,
    rows a reader CAN see going uncounted, and the resolver accepting ordinary English. They
    are the reason this class exists rather than a comment — an exploit fixed without a pin is
    an exploit waiting for the next refactor.
    """

    def _hidden_rows(self) -> str:
        rows = "\n".join(
            f"| LC9{i} | fabricated {i} | PLATFORM | C10 | ADOPTED | `agent_bench` |"
            for i in range(3)
        )
        return (
            "<!--\n| # | Capability | Rel. | Phase | Status | Verifying test |\n"
            "|---|---|---|---|---|---|\n" + rows + "\n-->\n"
        )

    def test_a_table_hidden_in_an_html_comment_is_not_counted(self, ledger: Path) -> None:
        """It rendered as nothing and parsed as three ADOPTED capabilities."""
        _rewrite(
            ledger, "\n**Denominator: 3 rows.", self._hidden_rows() + "\n**Denominator: 6 rows."
        )
        assert _run(ledger) == 1

    def test_an_indented_table_is_documentation_not_structure(self, ledger: Path) -> None:
        """Four spaces renders a literal code block; the fenced form was already excluded."""
        _rewrite(ledger, "| LC01 | Endpoint breadth", "    | LC01 | Endpoint breadth")
        assert _run(ledger) == 1

    def test_a_stray_heading_cannot_reparent_rows_out_of_part_one(self, ledger: Path) -> None:
        """Membership is positional. One inserted heading moved fourteen real rows out of the
        parity denominator and raised the published number without deleting anything."""
        _rewrite(ledger, "| LC03 | Subagents", "## Recently shipped upstream\n\n| LC03 | Subagents")
        assert _run(ledger) == 1

    def test_two_part_one_headings_fail(self, ledger: Path) -> None:
        _rewrite(ledger, "## Part 2 —", "## Part 1 — again\n\n## Part 2 —")
        assert _run(ledger) == 1

    def test_a_row_missing_its_outer_pipe_is_not_silently_skipped(self, ledger: Path) -> None:
        """GFM renders it; a `startswith("|")` parser does not see it."""
        _rewrite(ledger, "| LC03 | Subagents", "LC03 | Subagents")
        assert _run(ledger) == 1

    def test_a_blockquoted_row_is_not_silently_skipped(self, ledger: Path) -> None:
        _rewrite(ledger, "| LC03 | Subagents", "> | LC03 | Subagents")
        assert _run(ledger) == 1

    def test_a_depiped_open_table_cannot_vanish_with_its_smuggled_claim(self, ledger: Path) -> None:
        """The worst of them: the known-open table stopped looking like a table, and the gate
        reported "0 open items carried with a phase and a reason" without one complaint."""
        _rewrite(
            ledger,
            "| T04 | A recorded demo | owner | No hermetic gate can assert it |",
            "T04 | A recorded demo | owner | ADOPTED — recorded and shipped |",
        )
        assert _run(ledger) == 1

    def test_a_status_word_in_the_item_cell_is_caught_too(self, ledger: Path) -> None:
        _rewrite(ledger, "| T04 | A recorded demo |", "| T04 | A recorded demo, ADOPTED |")
        assert _run(ledger) == 1

    def test_a_second_denominator_claim_fails(self, ledger: Path) -> None:
        """First match wins, so a second claim lets the number a reader sees say anything."""
        _rewrite(
            ledger,
            "**Denominator: 3 rows. Parity % is computed over these.**",
            "**Denominator: 3 rows. Parity % is computed over these.**\n\n"
            "**Denominator: 9999 rows. Parity % is computed over these.**",
        )
        assert _run(ledger) == 1

    def test_a_part_one_row_after_the_denominator_claim_fails(self, ledger: Path) -> None:
        _rewrite(
            ledger,
            "\n## Part 2 —",
            "| LC80 | a late row | PLATFORM | C10 | ADOPTED | `agent_bench` |\n\n## Part 2 —",
        )
        assert _run(ledger) == 1

    def test_a_platform_row_cannot_hide_a_verdict_in_its_phase_cell(self, ledger: Path) -> None:
        _rewrite(ledger, "| PLATFORM | C4 | ADOPTED |", "| PLATFORM | C4 UNPROVEN | ADOPTED |")
        assert _run(ledger) == 1


class TestClosedPhaseArm:
    """`--no-unfinished-rows-in-closed-phases`, which had no tests at all and was silenceable
    six different ways from the plan file."""

    _PLAN = (
        "## Phase C4 — done\n\n- [x] a finished box\n\n"
        "## Phase C5 — done\n\n- [x] another finished box\n\n"
        "## Phase C6 — open\n\n- [ ] an unfinished box\n"
    )

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "PLAN-V3.md").write_text(self._PLAN, encoding="utf-8")
        path = tmp_path / "docs" / "FEATURES-V3.md"
        path.write_text(
            _PASSING.replace(
                "| LC01 | Endpoint breadth | PROOF_ADJACENT | C4 |",
                "| LC01 | Endpoint breadth | PROOF_ADJACENT | C5 |",
            ),
            encoding="utf-8",
        )
        return tmp_path

    def _run(self, repo: Path, plan: str | None = None) -> int:
        if plan is not None:
            (repo / "docs" / "PLAN-V3.md").write_text(plan, encoding="utf-8")
        return feature_ledger.main(
            [
                "--no-unfinished-rows-in-closed-phases",
                "--ledger",
                str(repo / "docs" / "FEATURES-V3.md"),
                "--plan",
                str(repo / "docs" / "PLAN-V3.md"),
            ]
        )

    def test_an_unfinished_row_owned_by_a_closed_phase_fails(self, repo: Path) -> None:
        assert self._run(repo) == 1

    def test_a_row_owned_by_an_open_phase_passes(self, repo: Path) -> None:
        ledger = repo / "docs" / "FEATURES-V3.md"
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(
                "| PROOF_ADJACENT | C5 |", "| PROOF_ADJACENT | C6 |", 1
            ),
            encoding="utf-8",
        )
        assert self._run(repo) == 0

    def test_an_unticked_box_inside_a_fence_cannot_reopen_a_phase(self, repo: Path) -> None:
        plan = self._PLAN.replace(
            "## Phase C6 — open", "```bash\n- [ ] a box in a fence\n```\n\n## Phase C6 — open"
        )
        assert self._run(repo, plan) == 1

    def test_an_uppercase_tick_still_counts_as_done(self, repo: Path) -> None:
        assert self._run(repo, self._PLAN.replace("- [x] another", "- [X] another")) == 1

    def test_a_star_bullet_still_counts_as_a_box(self, repo: Path) -> None:
        assert self._run(repo, self._PLAN.replace("- [x] another", "* [x] another")) == 1

    def test_a_non_phase_heading_does_not_donate_its_boxes_backwards(self, repo: Path) -> None:
        plan = self._PLAN.replace(
            "## Phase C6 — open",
            "## Notes on C5 (not a phase)\n\n- [ ] a stray box\n\n## Phase C6 — open",
        )
        assert self._run(repo, plan) == 1

    def test_a_reformatted_phase_heading_does_not_bleed_onto_its_predecessor(
        self, repo: Path
    ) -> None:
        assert self._run(repo, self._PLAN.replace("## Phase C6 — open", "## C6 — open")) == 1

    def test_a_zero_padded_phase_cannot_dodge_the_comparison(self, repo: Path) -> None:
        ledger = repo / "docs" / "FEATURES-V3.md"
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(
                "| PROOF_ADJACENT | C5 |", "| PROOF_ADJACENT | C05 |", 1
            ),
            encoding="utf-8",
        )
        assert self._run(repo) == 1

    def test_a_missing_plan_fails_rather_than_passing_vacuously(self, repo: Path) -> None:
        (repo / "docs" / "PLAN-V3.md").unlink()
        assert self._run(repo) == 1


class TestTheArmsThatWereUnpinned:
    """Arms an adversarial pass proved had no test that fails when they stop failing.

    Each of these existed and worked; what was missing was a test that DISCRIMINATES it. The
    pins that named them passed through a different arm — so neutering the real one left the
    suite green, which is the same "cannot fail" defect these gates exist to catch, one level
    up.
    """

    def test_an_unrecognised_header_fails_even_when_the_denominator_still_matches(
        self, ledger: Path
    ) -> None:
        """The header arm, isolated. The two tests that named it renamed a PART 1 header, so
        the dropped rows also broke the denominator and the failure came from there. Rename a
        Part 2 header and only the header arm can object — and on the real ledger that mutation
        silently dropped eight shipped rows while printing "L30 holds"."""
        _rewrite(
            ledger,
            "| # | Capability | Rel. | Status | Gate |",
            "| # | Capability | Rel. | Status | Evidence |",
        )
        assert _run(ledger) == 1

    def test_part_one_membership_survives_an_intervening_heading(self, ledger: Path) -> None:
        """Membership is POSITIONAL — between the two part headings — not a string test on the
        nearest heading. An ordinary subsection heading inside Part 1 must not evict the rows
        beneath it from the parity denominator; under the old text-based rule it did, and the
        published percentage moved without a row changing."""
        _rewrite(
            ledger,
            "### Providers and models",
            "## Notes on providers (an ordinary section, not a part)\n\n### Providers and models",
        )
        assert _run(ledger) == 0

    def test_a_ledger_with_only_open_items_fails_rather_than_holding_vacuously(
        self, tmp_path: Path
    ) -> None:
        """The anti-vacuity arm, isolated with a denominator of 0 so nothing else can object.
        A ledger that classifies nothing must never report that L30 holds."""
        path = tmp_path / "empty-features.md"
        path.write_text(
            "## Part 1 — LibreChat capabilities\n\n"
            "**Denominator: 0 rows. Parity % is computed over these.**\n\n"
            "## Part 2 — Tempest capabilities\n\n"
            "### Known-open, carried honestly\n\n"
            "| # | Item | Phase | Note |\n|---|---|---|---|\n"
            "| T01 | An open thing | C8 | Because reasons |\n",
            encoding="utf-8",
        )
        assert feature_ledger.main([*_ARGS, "--ledger", str(path)]) == 1
