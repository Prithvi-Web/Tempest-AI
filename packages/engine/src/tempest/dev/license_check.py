"""Phase 19.1 gate: `python -m tempest.dev.license_check --third-party-notices`.

Attribution maintained by discipline alone is the weaker guarantee — missing notices are an
avoidable legal problem discovered during enterprise procurement diligence, which is the worst
possible moment (v2 failure mode 10). This gate makes the obligation mechanical.

It checks five things, and every one of them is proven to fail on a violating tree:

1. **Tempest's own LICENSE** exists, is MIT, and carries a real `Copyright (c) <year> <holder>`
   line plus the permission grant. A repository published without a licence grants nothing —
   "open source" with no LICENSE file is all-rights-reserved by default.
2. **Package metadata declares MIT**, so a built wheel or published npm package carries the
   licence with it rather than leaving it behind in the repo.
3. **Every third-party project named in `THIRD_PARTY_LICENSES.md` reproduces its licence text
   verbatim.** Naming a dependency without its notice is precisely the MIT obligation missed.
4. **Every project marked `CODE DERIVED` names the derived modules** in its table. The status
   line is a claim; the table is the fact behind it (trap 37's class, applied to attribution).
5. **Every named project is credited in the README**, where users and reviewers actually look.

L25: adopted code carries its attribution at the moment of adoption, not at release.

`--platform-tree` (C1, L36.11) extends the gate over the vendored platform tree, and each of
these is likewise proven to fail on a violating tree:

6. **`packages/platform/LICENSE` exists and is the upstream MIT text** with a real copyright
   holder — the notice travels with the vendored work, at the root of the tree it covers.
7. **`packages/platform/UPSTREAM.md` exists and pins the adopted upstream commit** (40-hex).
   A vendored tree whose origin cannot be named cannot be merged, diffed, or audited.
8. **Every top-level vendored tree has a derivation row** in `THIRD_PARTY_LICENSES.md` —
   vendoring without attribution in the same commit is the debt this gate exists to prevent.
9. **No brand asset survives under `packages/platform/client/public`** — no image whose name or
   bytes match the upstream brand. MIT licenses code, never trademarks.
"""

import argparse
import json
import re
import sys
from pathlib import Path

_MIT_MARKERS = ("MIT License", "Permission is hereby granted")
_COPYRIGHT = re.compile(r"Copyright \(c\) (\d{4})(?:-\d{4})? +(\S.*)")
_DERIVED = "CODE DERIVED"
#: Table rows that carry no actual derivation — the empty-table placeholder.
_PLACEHOLDER_CELLS = {"", "—", "-", "*(none)*", "(none)", "(none yet)", "*(none yet)*", "n/a"}
#: A section is a real third-party project only if it carries the structured Upstream field.
#: Keying off structure rather than a loose substring is deliberate: prose that *discusses*
#: `CODE DERIVED` must not read as a section that *is* code-derived (trap 25's class — a grep
#: that matches the discussion of a thing instead of the thing).
_UPSTREAM_FIELD = "- **Upstream:**"
_STATUS_FIELD = "- **Adoption status:**"


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/parity.py`.

    A fixed `parents[N]` index would silently point somewhere meaningless the moment this file
    moves or ships inside a wheel; the marker either finds the repo or says so.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _check_own_license(root: Path, fail: list[str]) -> None:
    path = root / "LICENSE"
    if not path.is_file():
        fail.append(
            "LICENSE: missing — a repository published without a licence file is "
            "all-rights-reserved by default, which is the opposite of open source"
        )
        return
    body = path.read_text(encoding="utf-8", errors="replace")
    for marker in _MIT_MARKERS:
        if marker not in body:
            fail.append(f"LICENSE: not an MIT licence — missing {marker!r}")
    match = _COPYRIGHT.search(body)
    if match is None:
        fail.append(
            "LICENSE: no `Copyright (c) <year> <holder>` line — a licence with no "
            "copyright holder grants nothing to anyone"
        )


def _check_package_metadata(root: Path, fail: list[str]) -> None:
    """A wheel or npm package whose metadata omits the licence ships unlicensed downstream."""
    for rel in ("pyproject.toml", "packages/engine/pyproject.toml", "packages/api/pyproject.toml"):
        path = root / rel
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        if "[project]" in body and not re.search(r"^license\s*=\s*.*MIT", body, re.MULTILINE):
            fail.append(f'{rel}: [project] does not declare license = "MIT"')

    for path in sorted(root.glob("package.json")) + sorted(root.glob("packages/*/package.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - malformed json is its own bug
            fail.append(f"{path.relative_to(root)}: unreadable JSON ({exc})")
            continue
        if data.get("license") != "MIT":
            fail.append(f'{path.relative_to(root)}: does not declare "license": "MIT"')


def _sections(body: str) -> list[tuple[str, list[str], bool]]:
    """Split the notices file into (name, content_lines, has_license_block) per `##` section.

    Two rules keep the stub template from reading as a real adoption, both learned the hard way
    by this gate flagging its own documentation (trap 25's class — matching the discussion of a
    thing instead of the thing):

    * Headings inside fenced code blocks are not headings. Fence nesting follows CommonMark: a
      fence of N backticks closes only on a fence of at least N, so the 4-backtick stub wrapper
      survives the 3-backtick licence fence inside it.
    * `content_lines` excludes everything inside fences, so a `- **Upstream:**` line that is
      part of a *template* is never mistaken for a real project's field.
    """
    out: list[tuple[str, list[str], bool]] = []
    name: str | None = None
    lines: list[str] = []
    fenced = False
    open_fence = 0  # CommonMark: a fence of N backticks closes only on a fence of >= N.

    def flush() -> None:
        if name is not None:
            out.append((name, lines, fenced))

    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            ticks = len(stripped) - len(stripped.lstrip("`"))
            if open_fence == 0:
                open_fence = ticks
                if name is not None:
                    fenced = True
            elif ticks >= open_fence:
                open_fence = 0
            continue
        if open_fence:  # inside a fence: content, never structure
            continue
        if line.startswith("## "):
            flush()
            name, lines, fenced = line[3:].strip(), [], False
            continue
        if name is not None:
            lines.append(line)
    flush()
    return out


def _field(lines: list[str], prefix: str) -> str | None:
    for line in lines:
        if line.strip().startswith(prefix):
            return line.strip()[len(prefix) :].strip()
    return None


def _has_real_derivation_row(lines: list[str]) -> bool:
    """True when the derivation table names at least one actual module."""
    for raw in lines:
        line = raw.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0].lower().startswith("tempest module"):
            continue
        if cells[0] not in _PLACEHOLDER_CELLS and cells[1] not in _PLACEHOLDER_CELLS:
            return True
    return False


def _check_third_party(root: Path, fail: list[str]) -> list[str]:
    path = root / "THIRD_PARTY_LICENSES.md"
    if not path.is_file():
        fail.append(
            "THIRD_PARTY_LICENSES.md: missing — every adopted work is recorded at the "
            "moment of adoption, not at release (L25)"
        )
        return []
    body = path.read_text(encoding="utf-8")
    named: list[str] = []
    for name, lines, has_license_block in _sections(body):
        # Only sections carrying the structured Upstream field are third-party projects;
        # narrative sections and the stub template are not adoptions.
        if _field(lines, _UPSTREAM_FIELD) is None:
            continue
        named.append(name)
        if not has_license_block:
            fail.append(
                f"THIRD_PARTY_LICENSES.md: {name} names a dependency without reproducing its "
                "licence text — that is the MIT obligation missed"
            )
        status = _field(lines, _STATUS_FIELD) or ""
        if _DERIVED in status and not _has_real_derivation_row(lines):
            fail.append(
                f"THIRD_PARTY_LICENSES.md: {name} is marked {_DERIVED} but its derivation "
                "table names no module — the status is a claim, the table is the fact"
            )
    return named


#: The upstream brand string, matched case-insensitively over asset names AND bytes: an SVG
#: wordmark, a metadata title, or a renamed logo all carry it somewhere.
_BRAND = re.compile(rb"librechat", re.IGNORECASE)
_IMAGE_SUFFIXES = {".svg", ".png", ".ico", ".icns", ".webp", ".gif", ".jpg", ".jpeg"}


def _derivation_first_cells(body: str) -> list[str]:
    """First-column cells of every derivation table row, fences excluded (same discipline as
    `_sections`: the stub template's table must never read as real attribution)."""
    cells: list[str] = []
    for _, lines, _ in _sections(body):
        for raw in lines:
            line = raw.strip()
            if not line.startswith("|") or line.startswith("|---"):
                continue
            first = line.strip("|").split("|")[0].strip()
            if first and first not in _PLACEHOLDER_CELLS:
                cells.append(first.strip("`"))
    return cells


def _check_platform_tree(root: Path, fail: list[str]) -> None:
    """C1 checks 6-9: the vendored tree carries its licence, its origin, its attribution rows,
    and no upstream brand assets."""
    platform = root / "packages" / "platform"
    if not platform.is_dir():
        fail.append(
            "packages/platform: missing — --platform-tree asserts a vendored platform "
            "tree and there is none to check"
        )
        return

    lic = platform / "LICENSE"
    if not lic.is_file():
        fail.append(
            "packages/platform/LICENSE: missing — the upstream MIT text must travel at the "
            "root of the tree it covers"
        )
    else:
        body = lic.read_text(encoding="utf-8", errors="replace")
        for marker in _MIT_MARKERS:
            if marker not in body:
                fail.append(f"packages/platform/LICENSE: not an MIT licence — missing {marker!r}")
        if _COPYRIGHT.search(body) is None:
            fail.append("packages/platform/LICENSE: no `Copyright (c) <year> <holder>` line")

    upstream = platform / "UPSTREAM.md"
    if not upstream.is_file():
        fail.append(
            "packages/platform/UPSTREAM.md: missing — a vendored tree whose origin is "
            "unrecorded cannot be merged, diffed, or audited (L27)"
        )
    elif not re.search(
        r"- \*\*Adopted commit:\*\* [0-9a-f]{40}\b", upstream.read_text(encoding="utf-8")
    ):
        fail.append(
            "packages/platform/UPSTREAM.md: no `- **Adopted commit:** <40-hex>` line — "
            "the pin is the whole point of the file"
        )

    notices = root / "THIRD_PARTY_LICENSES.md"
    attributed = (
        _derivation_first_cells(notices.read_text(encoding="utf-8")) if notices.is_file() else []
    )
    for entry in sorted(platform.iterdir(), key=lambda p: p.name):
        if entry.name == "UPSTREAM.md":
            continue  # ours, not vendored
        rel = f"packages/platform/{entry.name}"
        # Boundary-aware: a row for `client-pkg/**` must not read as attribution for `client`.
        if not any(cell == rel or cell.startswith(rel + "/") for cell in attributed):
            fail.append(
                f"{rel}: vendored without a derivation row in THIRD_PARTY_LICENSES.md — "
                "attribution lands in the same commit as the code, never later"
            )

    public = platform / "client" / "public"
    if public.is_dir():
        for asset in sorted(public.rglob("*")):
            if not asset.is_file():
                continue
            rel_asset = asset.relative_to(root)
            if _BRAND.search(asset.name.encode()):
                fail.append(f"{rel_asset}: brand asset by NAME — trademarks are not licensed")
            elif asset.suffix.lower() in _IMAGE_SUFFIXES and _BRAND.search(asset.read_bytes()):
                fail.append(f"{rel_asset}: brand asset by CONTENT — trademarks are not licensed")


def _check_readme_credits(root: Path, named: list[str], fail: list[str]) -> None:
    path = root / "README.md"
    if not path.is_file():
        fail.append("README.md: missing — adopted work must be credited where users look")
        return
    body = path.read_text(encoding="utf-8")
    for name in named:
        if name not in body:
            fail.append(f"README.md: no attribution for {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--third-party-notices", action="store_true", required=True)
    parser.add_argument(
        "--platform-tree",
        action="store_true",
        help="also gate the vendored packages/platform tree (C1, L36.11)",
    )
    parser.add_argument(
        "--root", default=None, help="repository root to check (default: this repository)"
    )
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else _repo_root()

    fail: list[str] = []
    _check_own_license(root, fail)
    _check_package_metadata(root, fail)
    named = _check_third_party(root, fail)
    _check_readme_credits(root, named, fail)
    if args.platform_tree:
        _check_platform_tree(root, fail)

    for name in named:
        print(f"  third-party notice     {name}")
    if fail:
        print(f"license_check: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"LICENSE-GATE {problem}", file=sys.stderr)
        return 1
    print(
        f"license_check: MIT licence present, {len(named)} third-party notice(s) reproduced "
        "and credited — zero missing notices"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
