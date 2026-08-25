"""C5 gate pins (module pulled forward from C12, ADR-0088):
`parity_ledger --print-percentage` (L35).

L35 — feature parity is MEASURED, not asserted, and the README publishes the number. The two
halves are equally load-bearing: a percentage computed but unpublished is a number nobody can
be held to, and a percentage published but uncomputed is the assertion L35 exists to stop. So
the gate fails when the README omits it, and fails when the README disagrees with the ledger.

The `SHIPPED` decision (ADR-0088) is pinned here rather than left to a comment: a LibreChat
capability Tempest already satisfies IS at parity, so `SHIPPED` counts toward the numerator.
The counter-test matters — under the old ADOPTED-only reading the number is different, and an
unstated choice between two defensible answers is exactly the unmeasured claim L35 forbids.
"""

from pathlib import Path

import pytest

from tempest.dev import parity_ledger

_ARGS = ["--print-percentage"]

_LEDGER = """\
# FEATURES — fixture

> **Parity numerator:** a row counts toward parity when its status is `ADOPTED` or `SHIPPED`.

## Part 1 — LibreChat capabilities (the parity denominator)

| # | Capability | Rel. | Phase | Status | Verifying test |
|---|---|---|---|---|---|
| LC01 | Adopted thing | PLATFORM | C5 | ADOPTED | `agent_bench` |
| LC02 | Already ours | PROOF_NATIVE | C5 | SHIPPED (P4) | `subagent_bench` |
| LC03 | Not yet | PLATFORM | C7 | NOT_STARTED | E2E |
| LC04 | Also not yet | PLATFORM | C7 | NOT_STARTED | E2E |

**Denominator: 4 rows. Parity % is computed over these.**

## Part 2 — Tempest capabilities

| # | Capability | Rel. | Status | Gate |
|---|---|---|---|---|
| T01 | An engine thing | PROOF_NATIVE | SHIPPED | `make verify`; `corpus_check` |
"""

# 2 of 4 = 50.0%. Part 2 rows must NOT move it — they are not LibreChat capabilities.
_README = """\
# Fixture

- **LibreChat feature parity: 2 / 4 capabilities (50.0%)** — measured by `parity_ledger`.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FEATURES-V3.md").write_text(_LEDGER, encoding="utf-8")
    (tmp_path / "README.md").write_text(_README, encoding="utf-8")
    return tmp_path


def _run(repo: Path) -> int:
    return parity_ledger.main([*_ARGS, "--root", str(repo)])


def _rewrite(path: Path, old: str, new: str) -> None:
    body = path.read_text(encoding="utf-8")
    assert old in body, f"fixture drift: {old!r} not found"
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


class TestPassing:
    def test_a_consistent_repository_passes(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(repo) == 0
        assert "50.0%" in capsys.readouterr().out

    def test_the_real_repository_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert parity_ledger.main(_ARGS) == 0
        assert "L35 holds" in capsys.readouterr().out

    def test_the_percentage_is_printed(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(repo) == 0
        out = capsys.readouterr().out
        assert "2" in out and "4" in out and "%" in out


class TestArithmetic:
    def test_shipped_counts_toward_parity(self, repo: Path) -> None:
        """The ADR-0088 decision, pinned. A capability Tempest already has IS at parity."""
        assert _run(repo) == 0  # 2/4 with LC02 SHIPPED counted

    def test_demoting_the_shipped_row_moves_the_number(self, repo: Path) -> None:
        """The counter-test: if SHIPPED were NOT counted the answer would be 1/4, so this
        pins that the choice is real rather than incidental."""
        _rewrite(repo / "docs" / "FEATURES-V3.md", "SHIPPED (P4)", "NOT_STARTED")
        assert _run(repo) == 1  # README still says 2/4
        _rewrite(repo / "README.md", "2 / 4 capabilities (50.0%)", "1 / 4 capabilities (25.0%)")
        assert _run(repo) == 0

    def test_part_two_rows_do_not_inflate_the_numerator(self, repo: Path) -> None:
        """T01 is SHIPPED but is a Tempest capability, not a LibreChat one. Counting it would
        make the parity number measure the wrong thing."""
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "| T01 | An engine thing | PROOF_NATIVE | SHIPPED | `make verify`; `corpus_check` |",
            "| T01 | An engine thing | PROOF_NATIVE | SHIPPED | `make verify`; `corpus_check` |\n"
            "| T02 | Another engine thing | PROOF_NATIVE | SHIPPED | `roundtrip` |",
        )
        assert _run(repo) == 0  # still 2/4

    def test_adopting_a_row_without_republishing_fails(self, repo: Path) -> None:
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "| C7 | NOT_STARTED | E2E |",
            "| C7 | ADOPTED | `agent_bench` |",
        )
        assert _run(repo) == 1

    def test_adding_an_upstream_row_lowers_the_percentage(self, repo: Path) -> None:
        """Ledger rule 4: the denominator is supposed to move, and the README must follow."""
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "\n**Denominator: 4 rows.",
            "| LC05 | New upstream capability | PLATFORM | C8 | NOT_STARTED | E2E |\n"
            "\n**Denominator: 5 rows.",
        )
        assert _run(repo) == 1
        _rewrite(repo / "README.md", "2 / 4 capabilities (50.0%)", "2 / 5 capabilities (40.0%)")
        assert _run(repo) == 0


class TestPublication:
    def test_a_readme_that_publishes_no_number_fails(self, repo: Path) -> None:
        (repo / "README.md").write_text("# Fixture\n\nNothing about parity.\n", encoding="utf-8")
        assert _run(repo) == 1

    def test_a_readme_naming_a_different_numerator_fails(self, repo: Path) -> None:
        _rewrite(repo / "README.md", "2 / 4", "3 / 4")
        assert _run(repo) == 1

    def test_a_readme_naming_a_different_denominator_fails(self, repo: Path) -> None:
        _rewrite(repo / "README.md", "2 / 4", "2 / 9")
        assert _run(repo) == 1

    def test_a_readme_whose_percentage_disagrees_with_its_own_fraction_fails(
        self, repo: Path
    ) -> None:
        _rewrite(repo / "README.md", "(50.0%)", "(99.9%)")
        assert _run(repo) == 1

    def test_a_missing_readme_fails(self, repo: Path) -> None:
        (repo / "README.md").unlink()
        assert _run(repo) == 1


class TestDeclaredRule:
    def test_a_ledger_that_declares_a_different_numerator_rule_fails(self, repo: Path) -> None:
        """The document and the code may not disagree about what parity MEANS. Changing the
        rule takes an ADR and both edits, never one."""
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "a row counts toward parity when its status is `ADOPTED` or `SHIPPED`.",
            "a row counts toward parity when its status is `ADOPTED`.",
        )
        assert _run(repo) == 1

    def test_a_ledger_declaring_no_rule_at_all_fails(self, repo: Path) -> None:
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "> **Parity numerator:** a row counts toward parity when its status is "
            "`ADOPTED` or `SHIPPED`.\n",
            "",
        )
        assert _run(repo) == 1


class TestStructure:
    def test_a_ledger_the_parser_rejects_fails_here_too(self, repo: Path) -> None:
        """One parser, one truth: parity is not computed over a ledger feature_ledger cannot
        read, because a number derived from a misread file is worse than no number."""
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "| # | Capability | Rel. | Phase | Status | Verifying test |",
            "| # | Capability | Relationship | Phase | Status | Verifying test |",
        )
        assert _run(repo) == 1

    def test_a_ledger_with_no_part_one_rows_fails_rather_than_dividing_by_zero(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "FEATURES-V3.md").write_text("# empty\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# r\n", encoding="utf-8")
        assert parity_ledger.main([*_ARGS, "--root", str(tmp_path)]) == 1

    def test_a_missing_ledger_fails(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# r\n", encoding="utf-8")
        assert parity_ledger.main([*_ARGS, "--root", str(tmp_path)]) == 1


class TestPublishedMeansVisible:
    """L35's second half says the README PUBLISHES the number. An audit showed the check could
    be satisfied by text no reader sees, while the visible prose claimed something else — so
    the gate was reporting green over exactly the unmeasured claim the law exists to stop."""

    def test_a_correct_number_inside_a_code_fence_does_not_publish_it(self, repo: Path) -> None:
        (repo / "README.md").write_text(
            "# F\n\n```\n- **LibreChat feature parity: 2 / 4 capabilities (50.0%)**\n```\n\n"
            "- **LibreChat feature parity: 4 / 4 capabilities (100.0%)**\n",
            encoding="utf-8",
        )
        assert _run(repo) == 1

    def test_a_number_inside_an_html_comment_does_not_publish_it(self, repo: Path) -> None:
        (repo / "README.md").write_text(
            "# F\n\n<!-- **LibreChat feature parity: 2 / 4 capabilities (50.0%)** -->\n\n"
            "published below\n",
            encoding="utf-8",
        )
        assert _run(repo) == 1

    def test_a_second_claim_fails_even_when_the_first_is_right(self, repo: Path) -> None:
        """First-match-wins means a second line can say anything to a reader."""
        _rewrite(
            repo / "README.md",
            "- **LibreChat feature parity: 2 / 4 capabilities (50.0%)** — measured by "
            "`parity_ledger`.",
            "- **LibreChat feature parity: 2 / 4 capabilities (50.0%)** — measured.\n"
            "- **LibreChat feature parity: 4 / 4 capabilities (100.0%)** — marketing.",
        )
        assert _run(repo) == 1

    def test_the_numerator_rule_hidden_in_a_comment_does_not_declare_it(self, repo: Path) -> None:
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "> **Parity numerator:** a row counts toward parity when its status is "
            "`ADOPTED` or `SHIPPED`.",
            "> <!-- a row counts toward parity when its status is `ADOPTED` or `SHIPPED`. -->\n"
            "> **Parity numerator:** whatever the maintainer feels like today.",
        )
        assert _run(repo) == 1


class TestOneParserOneTruth:
    def test_a_structural_problem_outside_part_one_still_fails(self, repo: Path) -> None:
        """`fail += list(parsed.problems)` — the hand-off that makes parity refuse to count over
        a ledger the other gate cannot read. The test that named this rule passed through the
        empty-denominator guard instead, so the hand-off itself was unpinned. Breaking a PART 2
        header leaves Part 1 perfectly countable: without the hand-off the number computes and
        publishes cleanly over a file that is misread."""
        _rewrite(
            repo / "docs" / "FEATURES-V3.md",
            "| # | Capability | Rel. | Status | Gate |",
            "| # | Capability | Rel. | Status | Evidence |",
        )
        assert _run(repo) == 1
