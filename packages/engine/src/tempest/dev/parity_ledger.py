"""C5 gate, pulled forward from C12 (ADR-0088): `python -m tempest.dev.parity_ledger
--print-percentage`.

L35 — feature parity is MEASURED, not asserted: `docs/FEATURES-V3.md` is a machine-readable
ledger, a feature is `ADOPTED` only when its verifying test ran green, and **the README
publishes the percentage**. 100% is required at GA.

Both halves of that law are load-bearing, so this gate enforces both. A percentage computed
but never published is a number nobody can be held to. A percentage published but never
computed is precisely the assertion L35 exists to stop — and until C5's close-out the README
carried no parity number at all, so the law had never once been satisfied.

**What counts toward parity (ADR-0088).** A row counts when its status is `ADOPTED` **or**
`SHIPPED`. `SHIPPED` marks a LibreChat capability that a pre-existing Tempest feature already
satisfies — subagents by P4, resumable streams by P2, the MCP client by P5/F16. The question
"does Tempest have this capability?" is answered yes in both cases, and it is the only question
a parity number is asked. Excluding `SHIPPED` would understate parity and, worse, would reward
re-implementing something the product already has in order to move a number. The alternative
reading is defensible; an unstated one is not, which is why the rule is declared in the ledger
itself, restated here, and cross-checked below — the document and the code may not disagree
about what parity MEANS, and changing it takes an ADR plus both edits, never one.

The denominator is **Part 1 only**. Part 2 rows are Tempest's own capabilities: counting them
would let the product raise its LibreChat-parity score by shipping features LibreChat does not
have, which measures the wrong thing in the most flattering possible direction.

Parsing is delegated to `feature_ledger` — one parser, one truth. A number derived from a file
the other gate cannot read is worse than no number, so a ledger with structural problems fails
here too rather than being counted anyway.
"""

import argparse
import re
import sys
from pathlib import Path

from tempest.dev import feature_ledger

PARITY_STATUSES = frozenset({"ADOPTED", "SHIPPED"})

# The rule, declared in the ledger so the document and this module cannot drift apart.
DECLARED_NUMERATOR_RULE = "a row counts toward parity when its status is `ADOPTED` or `SHIPPED`."

# What the README must publish. Visible prose, not a hidden comment: "published" means a
# reader sees it.
_README_PARITY = re.compile(
    r"LibreChat feature parity:\s*(\d+)\s*/\s*(\d+)\s*capabilities\s*"
    r"\(\s*(\d+(?:\.\d+)?)\s*%\s*\)"
)


def _percentage(numerator: int, denominator: int) -> str:
    return f"{100.0 * numerator / denominator:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-percentage", action="store_true")
    parser.add_argument("--root", default=None, help="repository root (default: this repository)")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else feature_ledger._repo_root()
    ledger_path = root / "docs" / "FEATURES-V3.md"
    readme_path = root / "README.md"

    fail: list[str] = []
    if not ledger_path.is_file():
        return _report(
            [
                f"{ledger_path}: missing — parity is a fraction over the ledger's Part 1, and "
                "there is no ledger to count"
            ]
        )

    parsed = feature_ledger.parse(ledger_path)
    fail += list(parsed.problems)
    fail += feature_ledger._check_identity(parsed.rows)
    fail += feature_ledger._check_denominator(parsed)

    # Read through the same stripper the parser uses. A rule sentence moved into an HTML
    # comment satisfied a raw substring test while the visible prose said something else
    # entirely — "parity counts whatever the maintainer feels like today" passed.
    body = feature_ledger._strip_non_structure(
        ledger_path.read_text(encoding="utf-8", errors="replace")
    )
    if DECLARED_NUMERATOR_RULE not in body:
        fail.append(
            "docs/FEATURES-V3.md does not declare the numerator rule this gate implements "
            f"({DECLARED_NUMERATOR_RULE!r}) — the ledger and the module that counts it would "
            "then disagree about what parity means, silently, in the direction whoever edited "
            "last preferred"
        )

    part_one = parsed.part_one()
    denominator = len(part_one)
    if denominator == 0:
        fail.append(
            f"{ledger_path}: Part 1 carries no capability rows — a parity percentage over an "
            "empty denominator is not a measurement"
        )
        return _report(fail)

    numerator = sum(1 for row in part_one if row.status_base in PARITY_STATUSES)
    adopted = sum(1 for row in part_one if row.status_base == "ADOPTED")
    shipped = sum(1 for row in part_one if row.status_base == "SHIPPED")
    percentage = _percentage(numerator, denominator)

    if not readme_path.is_file():
        fail.append(
            "README.md: missing — L35 requires the percentage to be PUBLISHED, and an "
            "unpublished number is an unmeasured claim"
        )
    else:
        # PUBLISHED means a reader sees it. Searching the raw file for the first match let the
        # README carry a correct number inside a code fence, or an HTML comment, while the
        # visible prose claimed 91% — and report green. Fences and comments are stripped, and
        # more than one claim is itself the failure: with first-match-wins, a second line means
        # the number a reader reads is not the number this gate checked.
        readme_body = feature_ledger._strip_non_structure(
            readme_path.read_text(encoding="utf-8", errors="replace")
        )
        claims = list(_README_PARITY.finditer(readme_body))
        if len(claims) > 1:
            fail.append(
                f"README.md publishes {len(claims)} parity claims — only the first is checked, "
                "so a second one can say anything to a reader. Publish exactly one"
            )
        published = claims[0] if claims else None
        if published is None and len(claims) <= 1:
            fail.append(
                "README.md publishes no parity number — L35's second half is not satisfied by "
                f"computing it. Publish: **LibreChat feature parity: {numerator} / "
                f"{denominator} capabilities ({percentage}%)**"
            )
        elif published is not None:
            said_numerator, said_denominator, said_percentage = published.groups()
            if (int(said_numerator), int(said_denominator)) != (numerator, denominator):
                fail.append(
                    f"README.md publishes {said_numerator}/{said_denominator} but the ledger "
                    f"counts {numerator}/{denominator} — the published number is stale, which "
                    "is the failure mode of every hand-copied statistic"
                )
            elif said_percentage != percentage:
                fail.append(
                    f"README.md publishes {said_percentage}% for {numerator}/{denominator}, "
                    f"which is {percentage}% — the fraction and its own percentage disagree"
                )

    if fail:
        return _report(fail)

    if args.print_percentage:
        print(
            f"parity_ledger: LibreChat feature parity {numerator}/{denominator} = "
            f"{percentage}% ({adopted} ADOPTED + {shipped} SHIPPED; "
            f"{denominator - numerator} remaining), published in README.md and matching — "
            "L35 holds"
        )
    else:
        print("parity_ledger: ledger consistent, README matches — L35 holds")
    return 0


def _report(fail: list[str]) -> int:
    print(f"parity_ledger: {len(fail)} problem(s) — FAIL")
    for problem in fail:
        print(f"PARITY-LEDGER {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
