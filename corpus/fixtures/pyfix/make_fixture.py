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
    for name, src in {**BEHAVIOR_BASE, **NOOP_BASE}.items():
        (target / name).write_text(src, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "base", "--no-gpg-sign")
    _git(target, "branch", "base")
    for name, src in {**BEHAVIOR_HEAD, **NOOP_HEAD}.items():
        (target / name).write_text(src, encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-m", "head: 12 behavior changes + 12 no-op refactors", "--no-gpg-sign")
    _git(target, "branch", "head")
    return target


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
