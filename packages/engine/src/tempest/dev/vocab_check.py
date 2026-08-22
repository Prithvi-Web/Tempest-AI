"""C3 gate: `python -m tempest.dev.vocab_check --reserved-verdicts --platform-tree`.

L31 — verdict vocabulary is reserved. `DIVERGENT`, `EQUIVALENT_UNDER_BUDGET`, `UNPROVEN`,
`ERROR`, and (Phase 24's) `WEAK_EVIDENCE` are engine outputs; no adopted subsystem may write
into a verdict, confidence, or risk field, and none of the platform's confidence-shaped
affordances may borrow the vocabulary (L17 across the merge boundary). The failure this
prevents is the one the product cannot survive: platform features implying verification they
do not have.

Two mechanical checks over the vendored tree (`packages/platform/**`, seams excluded — the
`tempest/` seam directories are OUR integration code and legitimately carry proof context):

1. **Reserved tokens are absent.** The four distinctive SCREAMING_CASE tokens must not appear
   as whole words, case-sensitively, anywhere in vendored source. `ERROR` is ubiquitous
   English and cannot be linted as a token — its protection is check 2 plus the UI-integration
   review at each phase; stated here so the gap is a documented scope, not a silent one.
2. **No verdict-shaped field writes.** No vendored line writes or declares a `verdict`,
   `reason_code`, `confidence`, or `risk`/`risk_score` field. Measured zero across the whole
   vendored tree at C3; an upstream merge that introduces one fails here and gets a seam (or,
   with evidence that it is benign, a reviewed refinement of this rule — never a silent pass).

Scope note: L31 also names `packages/desktop/src/**`, where the vocabulary legitimately LIVES
(`vocabulary.tsx` is the rendering layer). The desktop-side rule — tokens rendered only
through the vocabulary layer — is defined when C3 absorbs the desktop views into the platform
client; a token-absence rule there today would flag every legitimate typed comparison.
"""

import argparse
import re
import sys
from pathlib import Path

_RESERVED_TOKENS = ("DIVERGENT", "EQUIVALENT_UNDER_BUDGET", "UNPROVEN", "WEAK_EVIDENCE")
#: A write or declaration of a verdict-shaped field: `verdict:`, `confidence =`, … but not
#: equality comparison (`verdict ===`), hence the negative lookahead on `=`.
_FIELD_WRITE = re.compile(
    r"\b(verdict|reason_code|confidence|risk|risk_score|riskScore)\s*[:=](?!=)"
)
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".yaml", ".yml"}
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "__pycache__"}


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/parity.py`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _is_seam(path: Path, platform: Path) -> bool:
    """`packages/platform/<pkg>/tempest/**` is OUR integration code, exempt by design."""
    relative = path.relative_to(platform).parts
    return len(relative) > 1 and relative[1] == "tempest"


def _platform_sources(platform: Path) -> list[Path]:
    out: list[Path] = []
    stack = [platform]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir(), key=lambda p: p.name):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not _is_seam(entry, platform):
                    stack.append(entry)
            elif entry.suffix.lower() in _SOURCE_SUFFIXES:
                out.append(entry)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reserved-verdicts", action="store_true", required=True)
    parser.add_argument("--platform-tree", action="store_true", required=True)
    parser.add_argument(
        "--root", default=None, help="repository root to check (default: this repository)"
    )
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else _repo_root()

    platform = root / "packages" / "platform"
    if not platform.is_dir():
        print("vocab_check: 1 problem(s) — FAIL")
        print(
            f"VOCAB-GATE {platform}: missing — --platform-tree asserts a vendored tree "
            "and there is none to check",
            file=sys.stderr,
        )
        return 1

    token_patterns = [(token, re.compile(rf"\b{re.escape(token)}\b")) for token in _RESERVED_TOKENS]
    fail: list[str] = []
    scanned = 0
    for path in _platform_sources(platform):
        scanned += 1
        body = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root)
        for token, pattern in token_patterns:
            if pattern.search(body):
                fail.append(
                    f"{rel}: carries the reserved verdict token {token} — only the engine "
                    "may speak it (L31)"
                )
        for line_number, line in enumerate(body.splitlines(), start=1):
            if _FIELD_WRITE.search(line):
                fail.append(
                    f"{rel}:{line_number}: writes a verdict-shaped field "
                    f"({line.strip()[:80]}) — verdicts, confidence, and risk are engine "
                    "outputs, never platform writes (L31/L17)"
                )

    if fail:
        print(f"vocab_check: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"VOCAB-GATE {problem}", file=sys.stderr)
        return 1
    print(
        f"vocab_check: {scanned} vendored source files scanned — zero reserved verdict "
        "tokens, zero verdict-shaped field writes outside the seams (L31 holds)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
