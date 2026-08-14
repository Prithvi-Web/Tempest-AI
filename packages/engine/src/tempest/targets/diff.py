"""Unified-diff parsing over real `git diff` output. Renames are disabled (delete+add) so every
changed path is accounted for explicitly."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type FileStatus = Literal["modified", "added", "deleted"]


@dataclass(frozen=True)
class FileDiff:
    path: str
    status: FileStatus
    changed_head_lines: frozenset[int]
    changed_base_lines: frozenset[int]


class DiffError(Exception):
    pass


def changed_files(
    repo: Path,
    base_ref: str,
    head_ref: str,
    patterns: tuple[str, ...] = ("*.py",),
) -> list[FileDiff]:
    """Files matching `patterns` changed between two refs, with exact line sets per side."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--no-renames",
            "--no-color",
            "--unified=0",
            f"{base_ref}..{head_ref}",
            "--",
            *patterns,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DiffError(f"git diff failed: {result.stderr.strip()}")
    return _parse_unified(result.stdout)


def _parse_unified(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    path: str | None = None
    status: FileStatus = "modified"
    head_lines: set[int] = set()
    base_lines: set[int] = set()

    def flush() -> None:
        nonlocal path
        if path is not None:
            files.append(
                FileDiff(
                    path=path,
                    status=status,
                    changed_head_lines=frozenset(head_lines),
                    changed_base_lines=frozenset(base_lines),
                )
            )
        path = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            # `diff --git a/<path> b/<path>` — with --no-renames both sides name the same file.
            path = line.split(" b/", 1)[1]
            status = "modified"
            head_lines, base_lines = set(), set()
        elif line.startswith("new file mode"):
            status = "added"
        elif line.startswith("deleted file mode"):
            status = "deleted"
        elif line.startswith("@@ "):
            base_part, head_part = line.split(" ", 3)[1:3]
            base_lines |= _hunk_lines(base_part)
            head_lines |= _hunk_lines(head_part)
    flush()
    return sorted(files, key=lambda f: f.path)


def _hunk_lines(part: str) -> set[int]:
    """`-12,3` or `+7` → the concrete line numbers touched on that side."""
    raw = part[1:]
    start_s, _, count_s = raw.partition(",")
    start = int(start_s)
    count = int(count_s) if count_s else 1
    return set(range(start, start + count))
