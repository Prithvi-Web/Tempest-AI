#!/usr/bin/env python3
"""Build the pyfix fixture repo: 12 seeded behavior changes + 12 true no-op refactors.

Usage: python make_fixture.py <target-dir>   (or import build() from tests)

The built repo has branches `base` and `head` and carries the first-party marker so the
engine's ProcessSandbox path is permitted for it (ADR-0003/0008).
"""

import subprocess
import sys
from pathlib import Path

MARKER = "tempest-first-party-fixture-v1"

# ---- 12 seeded behavior changes -------------------------------------------------------------
BEHAVIOR_BASE: dict[str, str] = {
    "b01.py": "def clamp(x: int) -> int:\n    return max(0, min(100, x))\n",
    "b02.py": "def pick_end(xs: list[int]) -> int:\n    return xs[0]\n",
    "b03.py": 'def squeeze(s: str) -> str:\n    return " ".join(s.split())\n',
    "b04.py": "def half_diff(a: int, b: int) -> int:\n    return (a - b) // 2\n",
    "b05.py": "def mean(xs: list[int]) -> float:\n    return sum(xs) / len(xs)\n",
    "b06.py": 'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
    "b07.py": "def is_non_negative(x: int) -> bool:\n    return x >= 0\n",
    "b08.py": "def dedupe(xs: list[int]) -> list[int]:\n    return list(dict.fromkeys(xs))\n",
    "b09.py": "def parse_int(s: str) -> int:\n    return int(s)\n",
    "b10.py": "def price_with_tax(p: float) -> float:\n    return round(p * 1.2, 2)\n",
    "b11.py": (
        "def check_positive(x: int) -> int:\n"
        "    if x < 0:\n"
        "        raise ValueError('negative')\n"
        "    return x\n"
    ),
    "b12.py": "def magnitude(x: float) -> float:\n    return abs(x) if x else 0.0\n",
}
BEHAVIOR_HEAD: dict[str, str] = {
    "b01.py": "def clamp(x: int) -> int:\n    return max(1, min(100, x))\n",
    "b02.py": "def pick_end(xs: list[int]) -> int:\n    return xs[-1]\n",
    "b03.py": 'def squeeze(s: str) -> str:\n    return s.replace("  ", " ")\n',
    "b04.py": "def half_diff(a: int, b: int) -> int:\n    return (a - b) / 2  # int→float\n",
    "b05.py": "def mean(xs: list[int]) -> float:\n    return sum(xs) / max(len(xs), 1)\n",
    "b06.py": 'def greet(name: str) -> str:\n    return f"Hello, {name}."\n',
    "b07.py": "def is_non_negative(x: int) -> bool:\n    return x > 0\n",
    "b08.py": "def dedupe(xs: list[int]) -> list[int]:\n    return sorted(set(xs))\n",
    "b09.py": "def parse_int(s: str) -> int:\n    return int(s) if s else 0\n",
    "b10.py": "def price_with_tax(p: float) -> float:\n    return p * 1.2\n",
    "b11.py": (
        "def check_positive(x: int) -> int:\n"
        "    if x < 0:\n"
        "        raise ValueError('negative value not allowed')\n"
        "    return x\n"
    ),
    "b12.py": "def magnitude(x: float) -> float:\n    return abs(x) if x else -0.0\n",
}

# ---- instance-method targets ---------------------------------------------------------------
# Kept OUT of BEHAVIOR_*, so the keyless 12/12 gate never depends on them.
#
# TWO RUNGS, and after Phase 19a (ADR-0048) they are exercised by DIFFERENT modules — which is
# the point of the split, because one fixture set cannot test a ladder's ordering.
#
#   c01/c02/c03 — `__init__` parameters are annotated and zero-valuable, so the DETERMINISTIC
#     rung constructs them with no key and no network. c01/c02 land DIVERGENT, c03 stays clean.
#     Before Phase 19a all three were UNPROVEN without a key; they are the measurement of what
#     the phase bought.
#   c08 — `__init__` takes an UNANNOTATED parameter, so there is nothing to derive a value from
#     and the deterministic rung must give up. It is the only instance target that still reaches
#     the LLM rung, and therefore the one that keeps ADR-0024 tested end to end: keyless it is
#     honestly UNPROVEN(TARGET_UNREACHABLE) naming the key, and with one it is SYNTHESIZED.
INSTANCE_BASE: dict[str, str] = {
    "c01.py": (
        "class Discounter:\n"
        "    def __init__(self, rate: float) -> None:\n"
        "        self.rate = rate\n"
        "\n"
        "    def apply(self, price: float) -> float:\n"
        "        return round(price * (1 - self.rate), 2)\n"
    ),
    "c02.py": (
        "class Wallet:\n"
        "    def __init__(self, balance: int) -> None:\n"
        "        self.balance = balance\n"
        "\n"
        "    def withdraw(self, amount: int) -> int:\n"
        "        if amount > self.balance:\n"
        "            raise ValueError('insufficient funds')\n"
        "        return self.balance - amount\n"
    ),
    "c03.py": (
        "class Tally:\n"
        "    def __init__(self, start: int) -> None:\n"
        "        self.start = start\n"
        "\n"
        "    def bump(self, xs: list[int]) -> int:\n"
        "        total = self.start\n"
        "        for x in xs:\n"
        "            total += x\n"
        "        return total\n"
    ),
    # UNANNOTATED `seed`: the deterministic rung has nothing to derive a value from and gives
    # up by design. Do NOT annotate it — that would silently delete the only end-to-end test of
    # the LLM constructor rung.
    "c08.py": (
        "class Ledger:\n"
        "    def __init__(self, seed) -> None:\n"
        "        self.seed = seed\n"
        "\n"
        "    def score(self, xs: list[int]) -> int:\n"
        "        total = self.seed\n"
        "        for x in xs:\n"
        "            total += x\n"
        "        return total\n"
    ),
}
INSTANCE_HEAD: dict[str, str] = {
    "c01.py": (
        "class Discounter:\n"
        "    def __init__(self, rate: float) -> None:\n"
        "        self.rate = rate\n"
        "\n"
        "    def apply(self, price: float) -> float:\n"
        "        return price * (1 - self.rate)\n"
    ),
    "c02.py": (
        "class Wallet:\n"
        "    def __init__(self, balance: int) -> None:\n"
        "        self.balance = balance\n"
        "\n"
        "    def withdraw(self, amount: int) -> int:\n"
        "        return max(0, self.balance - amount)\n"
    ),
    "c03.py": (
        "class Tally:\n"
        "    def __init__(self, start: int) -> None:\n"
        "        self.start = start\n"
        "\n"
        "    def bump(self, xs: list[int]) -> int:\n"
        "        return self.start + sum(xs)\n"
    ),
    # A seeded sign flip: divergent for every non-empty input.
    "c08.py": (
        "class Ledger:\n"
        "    def __init__(self, seed) -> None:\n"
        "        self.seed = seed\n"
        "\n"
        "    def score(self, xs: list[int]) -> int:\n"
        "        return self.seed - sum(xs)\n"
    ),
}

# ---- engine-depth targets (HANDOFF-WORLD-CLASS 2.5) — provable KEYLESS ---------------------
# c04 staticmethod / c05 classmethod: reachable through the class object, no instance needed.
# c06 typed dataclass: the deterministic TYPE-driven synthesizer constructs it (no LLM, no
# key). c07 async: the worker awaits it via asyncio.run. Kept out of BEHAVIOR_* so the
# original 12/12 gate stays byte-stable; the engine-depth gate asserts these separately.
DEPTH_BASE: dict[str, str] = {
    "c04.py": (
        "class Pricing:\n"
        "    @staticmethod\n"
        "    def with_tax(price: float, rate: float) -> float:\n"
        "        return round(price * (1 + rate), 2)\n"
    ),
    "c05.py": (
        "class Labeler:\n"
        "    @classmethod\n"
        "    def label(cls, name: str) -> str:\n"
        "        parts = [cls.__name__, name]\n"
        "        return '-'.join(parts)\n"
    ),
    "c06.py": (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Basket:\n"
        "    fee: int = 3\n"
        "\n"
        "    def total(self, xs: list[int]) -> int:\n"
        "        return sum(xs) + self.fee\n"
    ),
    "c07.py": ("async def combine(a: int, b: int) -> int:\n    return a * 10 + b\n"),
}
DEPTH_HEAD: dict[str, str] = {
    "c04.py": (
        "class Pricing:\n"
        "    @staticmethod\n"
        "    def with_tax(price: float, rate: float) -> float:\n"
        "        return price * (1 + rate)\n"
    ),
    "c05.py": (
        "class Labeler:\n"
        "    @classmethod\n"
        "    def label(cls, name: str) -> str:\n"
        "        return f'{cls.__name__}-{name}'\n"
    ),
    "c06.py": (
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Basket:\n"
        "    fee: int = 3\n"
        "\n"
        "    def total(self, xs: list[int]) -> int:\n"
        "        return sum(xs) + self.fee + 1\n"
    ),
    "c07.py": ("async def combine(a: int, b: int) -> int:\n    return a * 10 - b\n"),
}

# ---- 12 true no-op refactors ----------------------------------------------------------------
NOOP_BASE: dict[str, str] = {
    "n01.py": (
        "def total(xs: list[int]) -> int:\n"
        "    s = 0\n"
        "    for x in xs:\n"
        "        s += x\n"
        "    return s\n"
    ),
    "n02.py": 'def label(a: str, b: str) -> str:\n    return f"{a}-{b}"\n',
    "n03.py": "def squares(xs: list[int]) -> list[int]:\n    return [x * x for x in xs]\n",
    "n04.py": ("def max2(a: int, b: int) -> int:\n    if a > b:\n        return a\n    return b\n"),
    "n05.py": "def area(w: int, h: int) -> int:\n    return w * h\n",
    "n06.py": (
        "def rescale(value: int, factor: int) -> int:\n"
        "    result = value * factor\n"
        "    return result\n"
    ),
    "n07.py": (
        "def grade(score: int) -> str:\n"
        "    if score >= 90:\n"
        "        return 'A'\n"
        "    if score >= 80:\n"
        "        return 'B'\n"
        "    return 'C'\n"
    ),
    "n08.py": (
        "def join_csv(xs: list[str]) -> str:\n"
        "    parts = []\n"
        "    for x in xs:\n"
        "        parts.append(x)\n"
        "    return ','.join(parts)\n"
    ),
    "n09.py": ('def double(x: int) -> int:\n    """Return twice the input."""\n    return x * 2\n'),
    "n10.py": (
        "def rect_stats(w: int, h: int) -> tuple[int, int]:\n"
        "    area = w * h\n"
        "    perimeter = 2 * (w + h)\n"
        "    return area, perimeter\n"
    ),
    "n11.py": (
        "def big_len(xs: list[int]) -> int:\n"
        "    if (n := len(xs)) > 3:\n"
        "        return n\n"
        "    return 0\n"
    ),
    "n12.py": ("def neither(a: bool, b: bool) -> bool:\n    return not (a or b)\n"),
}
NOOP_HEAD: dict[str, str] = {
    "n01.py": "def total(xs: list[int]) -> int:\n    return sum(xs)\n",
    "n02.py": 'def label(a: str, b: str) -> str:\n    return a + "-" + b\n',
    "n03.py": (
        "def squares(xs: list[int]) -> list[int]:\n    return list(map(lambda x: x * x, xs))\n"
    ),
    "n04.py": "def max2(a: int, b: int) -> int:\n    return a if a > b else b\n",
    "n05.py": (
        "def _mul(w: int, h: int) -> int:\n"
        "    return w * h\n"
        "\n"
        "\n"
        "def area(w: int, h: int) -> int:\n"
        "    return _mul(w, h)\n"
    ),
    "n06.py": (
        "def rescale(value: int, factor: int) -> int:\n"
        "    scaled_value = value * factor\n"
        "    return scaled_value\n"
    ),
    "n07.py": (
        "def grade(score: int) -> str:\n"
        "    if score >= 90:\n"
        "        return 'A'\n"
        "    elif score >= 80:\n"
        "        return 'B'\n"
        "    else:\n"
        "        return 'C'\n"
    ),
    "n08.py": "def join_csv(xs: list[str]) -> str:\n    return ','.join(xs)\n",
    "n09.py": (
        "def double(x: int) -> int:\n"
        '    """Return the input multiplied by two."""\n'
        "    return x * 2\n"
    ),
    "n10.py": (
        "def rect_stats(w: int, h: int) -> tuple[int, int]:\n"
        "    perimeter = 2 * (w + h)\n"
        "    area = w * h\n"
        "    return area, perimeter\n"
    ),
    "n11.py": (
        "def big_len(xs: list[int]) -> int:\n"
        "    n = len(xs)\n"
        "    if n > 3:\n"
        "        return n\n"
        "    return 0\n"
    ),
    "n12.py": ("def neither(a: bool, b: bool) -> bool:\n    return (not a) and (not b)\n"),
}

BEHAVIOR_MODULES = sorted(m.removesuffix(".py") for m in BEHAVIOR_BASE)
NOOP_MODULES = sorted(m.removesuffix(".py") for m in NOOP_BASE)
INSTANCE_MODULES = sorted(m.removesuffix(".py") for m in INSTANCE_BASE)
DEPTH_MODULES = sorted(m.removesuffix(".py") for m in DEPTH_BASE)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "pyfix",
            "GIT_AUTHOR_EMAIL": "pyfix@tempest",
            "GIT_COMMITTER_NAME": "pyfix",
            "GIT_COMMITTER_EMAIL": "pyfix@tempest",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


def build(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    _git(target, "init", "-b", "main")
    (target / ".tempest-first-party").write_text(MARKER + "\n", encoding="utf-8")
    for name, src in {**BEHAVIOR_BASE, **NOOP_BASE, **INSTANCE_BASE, **DEPTH_BASE}.items():
        (target / name).write_text(src, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "base", "--no-gpg-sign")
    _git(target, "branch", "base")
    for name, src in {**BEHAVIOR_HEAD, **NOOP_HEAD, **INSTANCE_HEAD, **DEPTH_HEAD}.items():
        (target / name).write_text(src, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "head: 12 behavior changes + 12 no-op refactors", "--no-gpg-sign")
    _git(target, "branch", "head")
    return target


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
