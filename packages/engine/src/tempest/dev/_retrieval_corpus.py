"""The fixture repository the retrieval benchmark asks its questions of.

**A real repository, really executed.** The questions are answered from a genuine index built over
these files — parsed by the same parser the prover uses, executed in the same sandbox — so the
benchmark measures the product rather than a mock of it (L4).

**The composition is chosen so fifteen questions are impossible from source text.** That is the
number F13's gate names, and it is only meaningful if the questions really are impossible. A
question is source-impossible here when reading every byte of these files, with unlimited care and
no execution, cannot settle it: what a function ACTUALLY returns for a given input, which
exception it ACTUALLY raises (as opposed to the one it mentions), whether anything has ever run
it. `round_refund` is the sharpest of them — its name and docstring say it rounds, its body
truncates, and only running it can tell you which.
"""

from __future__ import annotations

MONEY = '''"""Money parsing and formatting."""


def parse_amount(text):
    """Parse a money string into whole cents."""
    if text is None:
        raise ValueError("amount is required")
    cleaned = str(text).strip().replace("$", "").replace(",", "")
    if not cleaned:
        raise ValueError("amount is empty")
    return int(float(cleaned) * 100)


def format_amount(cents):
    """Render cents as a currency string."""
    return "$%.2f" % (cents / 100)


def round_refund(cents):
    """Round a refund to the nearest cent, in the customer's favour."""
    # The docstring says round. The code truncates. Only execution can tell you which.
    return int(cents)
'''

DISCOUNT = '''"""Discount arithmetic."""


def apply_discount(cents, percent):
    """Take `percent` off `cents`."""
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    return cents - (cents * percent) // 100


def best_discount(offers):
    """The largest offer on the table."""
    return max(offers)


def stack_discounts(first, second):
    """Apply one discount after another."""
    return apply_discount(apply_discount(first, second), second)
'''

CHARGE = '''"""The charging path."""

from money import format_amount, parse_amount
from discount import apply_discount


def charge(text, percent):
    """Parse an amount, discount it, and render the result."""
    cents = parse_amount(text)
    return format_amount(apply_discount(cents, percent))


def quote(text):
    """What the customer would pay with no discount."""
    return format_amount(parse_amount(text))
'''

AUDIT = '''"""Audit helpers that nothing in this repository calls."""


def shout_reason(reason):
    """Uppercase an audit reason. Nothing calls this."""
    return str(reason).upper()


def redact_card(number):
    """Mask all but the last four digits. Nothing calls this either."""
    text = str(number)
    return "*" * max(len(text) - 4, 0) + text[-4:]
'''

FILES: tuple[tuple[str, str], ...] = (
    ("money.py", MONEY),
    ("discount.py", DISCOUNT),
    ("charge.py", CHARGE),
    ("audit.py", AUDIT),
)
