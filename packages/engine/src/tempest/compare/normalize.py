"""THE normalization ruleset — the only place exception messages and stream text get rewritten
before comparison. Every rule carries a rationale for why it cannot mask a real divergence, and
every rule has both a masks-the-volatile test and a does-not-mask-real-differences test
(tests/unit/test_normalize.py). Over-normalization is failure mode §14.6.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    replacement: str
    rationale: str


RULES: tuple[Rule, ...] = (
    Rule(
        name="memory-address",
        pattern=re.compile(r"0x[0-9a-fA-F]{4,}"),
        replacement="0xADDR",
        rationale=(
            "Allocation addresses differ on every run by construction; the surrounding text "
            "(type names, verbs) is untouched, so any real difference still differs."
        ),
    ),
    Rule(
        name="temp-path",
        pattern=re.compile(r"(?:/private)?(?:/var/folders/\S+|/tmp/\S+)"),
        replacement="<TMPPATH>",
        rationale=(
            "OS-assigned temp directories are unique per process. Project-relative paths do not "
            "match the pattern and remain comparable."
        ),
    ),
    Rule(
        name="iso-timestamp",
        pattern=re.compile(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
        ),
        replacement="<TIMESTAMP>",
        rationale=(
            "Wall-clock text differs per run. The pattern requires a full date AND time, so bare "
            "numbers, counts, and version strings (e.g. 2.1.3) never match."
        ),
    ),
)


def normalize_message(text: str) -> str:
    for rule in RULES:
        text = rule.pattern.sub(rule.replacement, text)
    return text
