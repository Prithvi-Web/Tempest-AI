"""Corpus mining: harvest literal constants from the repo's own code, tests, and docstrings.
Real values find real bugs (master spec stage 5)."""

import ast
from pathlib import Path

_CAP = 500
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tempest"}


def mine_literals(root: Path) -> list[object]:
    mined: list[object] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            value = node.value
            if isinstance(value, bool) or value is None or value is Ellipsis:
                continue
            if isinstance(value, str) and (len(value) > 200 or value == ""):
                continue
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            mined.append(value)
            if len(mined) >= _CAP:
                return mined
    return mined
