"""Phase 22's exit gate — F13's retrieval, measured on questions source text cannot answer.

    python -m tempest.dev.retrieval_bench --questions 40 --require-citations

**Forty questions, fifteen of them impossible from source.** The fifteen are the point. Anyone can
answer *"where is `parse_amount` defined?"* — grep does. Nobody else can answer *"what does
`round_refund` actually return?"*, because its docstring says it rounds and its body truncates, and
the only thing that settles that is having run it.

**Three bars, and they fail independently.**

1. **Every answer carries a citation.** An uncited answer is a failure, whatever it says. This is
   the bar F13 names and it is the one that stops the feature degrading into a chatbot.
2. **Every answer is RIGHT.** Each question carries an expectation, and a cited answer that does
   not contain it fails. A gate that checked only for citations would pass a confidently-wrong
   answer with a footnote, which is a worse product than no answer at all.
3. **The fifteen are grounded in EXECUTION.** A source citation does not satisfy them; the answer
   must cite an observation, or — for the one question that is about an absence — the run that
   exercised everything else. There is no observation of a thing that did not happen, and
   pretending otherwise would be inventing evidence to satisfy a gate.

**And a latency budget** (§5: codebase search p50 150 ms, p95 400 ms). Measured over the answering
only, with the index already built, because that is what a user waits for. The corpus here is four
files, not the 500k lines §5 names — so the number is reported as what it is, an upper bound on a
small repository, and the gate binds on it rather than pretending to a scale it has not measured.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from tempest.dev._retrieval_corpus import FILES
from tempest.index import query
from tempest.index.build import build_index
from tempest.index.store import index_for

#: What a real run of this fixture app touches. `audit.py` is never reached, which is what makes
#: "which functions have never been exercised?" a question with a real answer rather than an
#: empty set — the index records what RAN, and an exhaustive sweep would record everything and
#: therefore say nothing.
EXERCISED = frozenset(
    {
        "parse_amount",
        "format_amount",
        "round_refund",
        "apply_discount",
        "best_discount",
        "stack_discounts",
        "charge",
        "quote",
    }
)


@dataclass(frozen=True)
class Question:
    text: str
    #: A substring one of the answer's statements must contain. The answer being CITED is not
    #: enough; it also has to be the right answer.
    expect: str
    #: True when reading every byte of the fixture, with unlimited care and no execution, cannot
    #: settle it.
    source_impossible: bool = False


QUESTIONS: tuple[Question, ...] = (
    # ---- answerable from source: where things are -------------------------------------------
    Question("where is parse_amount defined?", "parse_amount"),
    Question("where is format_amount defined?", "format_amount"),
    Question("where is round_refund defined?", "round_refund"),
    Question("where is apply_discount defined?", "apply_discount"),
    Question("where is best_discount defined?", "best_discount"),
    Question("where is stack_discounts defined?", "stack_discounts"),
    Question("where is charge defined?", "charge"),
    Question("where is quote defined?", "quote"),
    Question("where is shout_reason defined?", "shout_reason"),
    Question("where is redact_card defined?", "redact_card"),
    # ---- answerable from source: the call graph ----------------------------------------------
    Question("who calls parse_amount?", "calls parse_amount"),
    Question("who calls format_amount?", "calls format_amount"),
    Question("who calls apply_discount?", "calls apply_discount"),
    Question("what does charge call?", "charge calls"),
    Question("what does quote call?", "quote calls"),
    Question("what does stack_discounts call?", "stack_discounts calls"),
    # ---- answerable from source: finding code by description --------------------------------
    Question("find the function that parses a money string", "parse_amount"),
    Question("find the function that masks a card number", "redact_card"),
    Question("where is the currency rendering defined?", "format_amount"),
    Question("find the audit helper that uppercases a reason", "shout_reason"),
    Question("where is the largest offer chosen?", "best_discount"),
    Question("find the function that applies one discount after another", "stack_discounts"),
    Question("where is the charging path defined?", "charge"),
    Question("find the function that quotes an undiscounted price", "quote"),
    Question("where is the refund rounding defined?", "round_refund"),
    # ---- IMPOSSIBLE from source: what actually ran -------------------------------------------
    Question("which functions have never been exercised?", "no recorded execution", True),
    Question("what exceptions does parse_amount actually raise?", "ValueError", True),
    Question("what exceptions does apply_discount actually raise?", "ValueError", True),
    Question("what exceptions does best_discount actually raise?", "ValueError", True),
    Question("what does round_refund actually return?", "round_refund", True),
    Question("what does format_amount actually return?", "format_amount", True),
    Question("what does parse_amount actually return?", "parse_amount", True),
    Question("what does apply_discount actually return?", "apply_discount", True),
    Question("what does charge actually return?", "charge", True),
    Question("what does quote actually return?", "quote", True),
    Question("what does stack_discounts actually return?", "stack_discounts", True),
    Question("what does best_discount actually return?", "best_discount", True),
    Question(
        "what actually happens when parse_amount is given an empty value?", "parse_amount", True
    ),
    Question(
        "what actually happens when apply_discount is given a negative percent?",
        "apply_discount",
        True,
    ),
    Question("what values does parse_amount actually return?", "parse_amount", True),
)


@dataclass(frozen=True)
class Row:
    question: Question
    answered: bool
    cited: bool
    correct: bool
    grounded: bool
    route: str
    detail: str
    seconds: float

    @property
    def ok(self) -> bool:
        if not (self.answered and self.cited and self.correct):
            return False
        return self.grounded if self.question.source_impossible else True


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "tempest-bench",
            "GIT_AUTHOR_EMAIL": "bench@tempest",
            "GIT_COMMITTER_NAME": "tempest-bench",
            "GIT_COMMITTER_EMAIL": "bench@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def make_repo(root: Path) -> Path:
    repo = root / "app"
    repo.mkdir(parents=True)
    for name, body in FILES:
        (repo / name).write_text(body, encoding="utf-8")
    (repo / ".tempest-first-party").write_text("", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fixture")
    return repo


def evaluate(repo: Path, questions: tuple[Question, ...]) -> tuple[list[Row], str]:
    with index_for(repo) as conn:
        report = build_index(conn, repo, observe=True, only=EXERCISED, max_inputs=16)
        rows: list[Row] = []
        for question in questions:
            started = time.perf_counter()
            answer = query.answer(conn, question.text)
            elapsed = time.perf_counter() - started
            correct = any(question.expect in s.text for s in answer.statements)
            # Computed HERE from the statements, not read off `answer.cited`. A gate that asks
            # the object it is measuring whether it passes is measuring the property's
            # implementation rather than the answers — the same shape as `agent_bench` asking a
            # `ProvenChange` whether it had a bundle id (trap 47). A mutation that made `cited`
            # unconditionally true survived the first version of this file.
            cited = bool(answer.statements) and all(s.citations for s in answer.statements)
            grounded = any(
                c.kind in {"observation", "run"}
                for statement in answer.statements
                for c in statement.citations
            )
            rows.append(
                Row(
                    question=question,
                    answered=bool(answer.statements),
                    cited=cited,
                    correct=correct,
                    grounded=grounded,
                    route=answer.route,
                    detail=(answer.unanswered or "; ".join(s.text for s in answer.statements[:2])),
                    seconds=elapsed,
                )
            )
    return rows, report.render()


def render(rows: list[Row], *, p95_bar: float) -> str:
    times = sorted(r.seconds for r in rows)
    p50 = statistics.median(times) if times else 0.0
    p95 = times[max(int(len(times) * 0.95) - 1, 0)] if times else 0.0
    impossible = [r for r in rows if r.question.source_impossible]
    lines = [f"{'question':<62} {'route':<11} ok   evidence"]
    for row in rows:
        flags = "".join(
            [
                "A" if row.answered else "-",
                "C" if row.cited else "-",
                "R" if row.correct else "-",
                "X" if row.grounded else "-",
            ]
        )
        lines.append(f"{row.question.text[:62]:<62} {row.route:<11} {flags}  {row.detail[:70]}")
    lines += [
        "",
        f"retrieval_bench: {sum(1 for r in rows if r.ok)}/{len(rows)} questions answered, cited "
        f"and correct",
        f"retrieval_bench: {sum(1 for r in impossible if r.ok)}/{len(impossible)} "
        f"source-impossible questions grounded in execution",
        f"retrieval_bench: retrieval p50 {p50 * 1000:.1f} ms, p95 {p95 * 1000:.1f} ms "
        f"(bar {p95_bar * 1000:.0f} ms) — measured on a 4-file fixture, so an upper bound for "
        f"this corpus and NOT the 500k-LOC number §5 asks for",
        "",
        "flags: A answered · C every statement cited · R contains the expected fact · "
        "X grounded in execution",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=len(QUESTIONS))
    parser.add_argument("--require-citations", action="store_true", default=True)
    parser.add_argument("--p95-seconds", type=float, default=0.400)
    args = parser.parse_args(argv)

    if args.questions > len(QUESTIONS):
        print(
            f"retrieval_bench: {args.questions} questions requested, the set holds "
            f"{len(QUESTIONS)} — refusing to report a rate over a smaller set than was asked for",
            file=sys.stderr,
        )
        return 2

    with TemporaryDirectory(prefix="tempest-retrieval-") as tmp:
        repo = make_repo(Path(tmp))
        rows, build_report = evaluate(repo, QUESTIONS)

    print(build_report)
    print("")
    print(render(rows, p95_bar=args.p95_seconds))

    failed = False
    for row in rows:
        if not row.answered:
            print(
                f"RETRIEVAL-BENCH {row.question.text}: unanswered — {row.detail}", file=sys.stderr
            )
            failed = True
        elif args.require_citations and not row.cited:
            print(
                f"RETRIEVAL-BENCH {row.question.text}: answered with no citation — an uncited "
                f"answer about a codebase is indistinguishable from a guess",
                file=sys.stderr,
            )
            failed = True
        elif not row.correct:
            print(
                f"RETRIEVAL-BENCH {row.question.text}: cited but wrong — expected "
                f"{row.question.expect!r} in the answer, got {row.detail!r}",
                file=sys.stderr,
            )
            failed = True
        elif row.question.source_impossible and not row.grounded:
            print(
                f"RETRIEVAL-BENCH {row.question.text}: answered from source only — this question "
                f"cannot be settled by reading the code, so a source citation is not evidence",
                file=sys.stderr,
            )
            failed = True

    times = sorted(r.seconds for r in rows)
    p95 = times[max(int(len(times) * 0.95) - 1, 0)] if times else 0.0
    if p95 > args.p95_seconds:
        print(
            f"RETRIEVAL-BENCH retrieval p95 {p95 * 1000:.1f} ms is over the "
            f"{args.p95_seconds * 1000:.0f} ms bar",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
