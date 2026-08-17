#!/usr/bin/env python3
"""Build the tsfix fixture repo: TypeScript targets for the wave-1 execution gate
(ADR-0028) — seeded behavior changes, a no-op refactor, an async change, a shim-dependent
no-op (Date/Math.random pinned), and the honest UNPROVEN shapes (not exported, impure).

Usage: python make_fixture.py <target-dir>   (or import build() from tests)
"""

import subprocess
import sys
from pathlib import Path

MARKER = "tempest-first-party-fixture-v1"

TSCONFIG = '{\n  "compilerOptions": {\n    "strict": true,\n    "module": "nodenext"\n  }\n}\n'

BASE: dict[str, str] = {
    "s01.ts": (
        "export function clampTs(x: number): number {\n  return Math.max(0, Math.min(100, x));\n}\n"
    ),
    "s02.ts": ("export function greetTs(name: string): string {\n  return `Hello, ${name}!`;\n}\n"),
    "s03.ts": (
        "export function totalTs(xs: number[]): number {\n"
        "  let s = 0;\n"
        "  for (const x of xs) {\n"
        "    s += x;\n"
        "  }\n"
        "  return s;\n"
        "}\n"
    ),
    "s04.ts": (
        "export async function combineTs(a: number, b: number): Promise<number> {\n"
        "  return a * 10 + b;\n"
        "}\n"
    ),
    "s05.ts": (
        "export function stampTag(name: string): string {\n"
        "  const bucket = Math.floor(Date.now() / 1000) % 7;\n"
        "  const salt = Math.floor(Math.random() * 100);\n"
        "  return `${name}:${bucket}:${salt}`;\n"
        "}\n"
    ),
    "s06.ts": (
        "function hiddenHelper(x: number): number {\n"
        "  return x * 3;\n"
        "}\n"
        "\n"
        "export const KEEP = hiddenHelper(1);\n"
    ),
    "s07.ts": (
        "export async function fetchTitle(url: string): Promise<string> {\n"
        "  const res = await fetch(url);\n"
        "  return res.statusText;\n"
        "}\n"
    ),
}

HEAD: dict[str, str] = {
    "s01.ts": (
        "export function clampTs(x: number): number {\n  return Math.max(1, Math.min(100, x));\n}\n"
    ),
    "s02.ts": ("export function greetTs(name: string): string {\n  return `Hello, ${name}.`;\n}\n"),
    "s03.ts": (
        "export function totalTs(xs: number[]): number {\n"
        "  return xs.reduce((acc, x) => acc + x, 0);\n"
        "}\n"
    ),
    "s04.ts": (
        "export async function combineTs(a: number, b: number): Promise<number> {\n"
        "  return a * 10 - b;\n"
        "}\n"
    ),
    "s05.ts": (
        "export function stampTag(name: string): string {\n"
        "  const bucket = Math.floor(Date.now() / 1000) % 7;\n"
        "  const salt = Math.floor(Math.random() * 100);\n"
        "  return `${name}:${bucket}:${salt}`;  // formatting-only churn\n"
        "}\n"
    ),
    "s06.ts": (
        "function hiddenHelper(x: number): number {\n"
        "  return x * 4;\n"
        "}\n"
        "\n"
        "export const KEEP = hiddenHelper(1);\n"
    ),
    "s07.ts": (
        "export async function fetchTitle(url: string): Promise<string> {\n"
        "  const res = await fetch(url);\n"
        "  return res.statusText.trim();\n"
        "}\n"
    ),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "tempest-fixture",
            "GIT_AUTHOR_EMAIL": "fixture@tempest.dev",
            "GIT_COMMITTER_NAME": "tempest-fixture",
            "GIT_COMMITTER_EMAIL": "fixture@tempest.dev",
        },
    )


def build(target: Path) -> Path:
    repo = Path(target)
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    (repo / ".tempest-first-party").write_text(f"{MARKER}\n", encoding="utf-8")
    (repo / "tsconfig.json").write_text(TSCONFIG, encoding="utf-8")
    for name, src in BASE.items():
        (repo / name).write_text(src, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base", "--no-gpg-sign")
    _git(repo, "branch", "base")
    for name, src in HEAD.items():
        (repo / name).write_text(src, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head", "--no-gpg-sign")
    _git(repo, "branch", "head")
    return repo


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_fixture.py <target-dir>")
    print(build(Path(sys.argv[1])))
