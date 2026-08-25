"""C5 gate, pulled forward from C10 (ADR-0088):
`python -m tempest.dev.feature_ledger --every-feature-classified --no-verdict-vocab-in-platform`.

L30 — every adopted feature declares its proof relationship, exactly one of `PROOF_NATIVE` /
`PROOF_ADJACENT` / `PLATFORM`. L31 — the verdict vocabulary is reserved, so a `PLATFORM` row may
not borrow it in its own text. L36.3 — zero unclassified features.

`docs/FEATURES-V3.md` opens by calling itself "normative and machine-read", and names this module
as one of the two that read it. Neither existed until C5's close-out, so for five phases the
ledger was a hand-maintained document asserting its own correctness. The first run of this gate
against the real tree found five disagreements, two of them rows that had shipped (ADR-0088).

The gate reads the ledger and asks, each arm proven to fail on a violating file:

1. **Every table is a table this gate understands.** The header row must match one of four
   declared schemas exactly. This is the arm that matters most: the characteristic failure of a
   ledger gate is not a wrong answer but a silent zero — a renamed column, a reshaped table, and
   the parser matches nothing and reports green over a file it never read. An unrecognised
   header FAILS rather than being skipped, and a ledger with no feature rows at all fails too.
2. **Every feature row is classified** (`--every-feature-classified`): a valid L30 relationship,
   a valid status, a non-empty capability, and a non-empty verifying test. A row that is not
   finished (`NOT_STARTED` / `IN_PROGRESS` / `PLANNED`) must additionally name the phase that
   will do it — undone work with no phase is undone work nobody owns. A finished row needs no
   future phase, which is why the shipped tables carry no `Phase` column at all.
3. **Identity holds**: ids are well-formed (`LC04`, `LC19b`, `T37`) and unique across the whole
   ledger, including across the known-open table — the same id meaning two things is how a
   ledger starts lying.
4. **The stated denominator is the counted denominator.** Part 1 ends with a
   `**Denominator: N rows.**` claim that parity is computed over. It is exactly the kind of
   hand-maintained integer that goes stale the moment a row is added, and it had: the session
   that split `LC19` left a document elsewhere still saying 76.
5. **No `PLATFORM` row borrows the verdict vocabulary** (`--no-verdict-vocab-in-platform`):
   L31 across the ledger itself. `vocab_check` proves this over the vendored source tree; the
   row that *declares* a feature `PLATFORM` while describing it in verdict words is the same
   violation one document earlier. Matching is by uppercase token with word boundaries, so
   lowercase English ("this claim is unproven") and substrings (`UNPROVENANCE`) are not the
   reserved vocabulary — a noisy vocabulary lint is one someone eventually silences.
6. **The known-open table cannot smuggle a claim.** Its rows carry a phase and a reason and no
   status word, so "carried honestly" cannot become a place to park a done-ness claim that
   escaped classification.

Scope, stated so the claim is exact: this gate proves the ledger is internally consistent,
completely classified, and honest about its own arithmetic. It does **not** prove a row's
verifying test exists or ran — a row saying `ADOPTED` with a test name that is fiction is
caught by running that test, which is what the phase gates do, not by parsing this file.
Fenced code blocks are documentation, never structure (the `license_check` lesson).
"""

import argparse
import dataclasses
import re
import sys
from pathlib import Path

RELATIONSHIPS = frozenset({"PROOF_NATIVE", "PROOF_ADJACENT", "PLATFORM"})
STATUSES = frozenset({"ADOPTED", "IN_PROGRESS", "NOT_STARTED", "SHIPPED", "PLANNED"})
UNFINISHED = frozenset({"IN_PROGRESS", "NOT_STARTED", "PLANNED"})
RESERVED_VERDICTS = frozenset(
    {"DIVERGENT", "EQUIVALENT_UNDER_BUDGET", "UNPROVEN", "ERROR", "WEAK_EVIDENCE"}
)

# The exact header schemas this gate understands. A table under any other header is a table it
# would have to guess at, and guessing is how a gate reports green over rows it never saw.
_FEATURE_SCHEMAS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("#", "capability", "rel.", "phase", "status", "verifying test"),
        ("#", "capability", "rel.", "phase", "status", "gate"),
        ("#", "capability", "rel.", "status", "gate"),
    }
)
_OPEN_SCHEMA: tuple[str, ...] = ("#", "item", "phase", "note")

# The EN DASH is deliberate alongside the em dash and the hyphen: all three are typed into
# ledger cells to mean "nothing here", and a placeholder this gate does not recognise is a
# blank it would accept as content.
_PLACEHOLDER_CELLS = frozenset(
    {"", "—", "-", "–", "*(none)*", "(none)", "n/a", "tbd"}  # noqa: RUF001
)
_ID = re.compile(r"^(?:LC|T)\d{1,3}[a-z]?$")
_PHASE_TOKEN = re.compile(r"\bC\d{1,2}\b|\b\d{1,2}\b|\bowner\b")
_STATUS_CELL = re.compile(r"^([A-Z][A-Z_]*)(?:\s*\((.*)\))?$")
_DENOMINATOR = re.compile(r"\*\*Denominator:\s*(\d+)\s*rows?\.")
_STATUS_WORD = re.compile(r"\b(?:" + "|".join(sorted(STATUSES)) + r")\b")
_DEFAULT_LEDGER = Path("docs") / "FEATURES-V3.md"
_DEFAULT_PLAN = Path("docs") / "PLAN-V3.md"
_PHASE_HEADING = re.compile(r"^## Phase (C\d+)\b")
#: Any list bullet, either case of tick. `- [X]` and `* [x]` both render as ticked boxes, and
#: a stricter pattern counted them as NEITHER done nor total — silently reopening a closed
#: phase and disarming the ownership arm.
_CHECKBOX = re.compile(r"^[-*+][ \t]+\[([ xX])\]")
_C_PHASE = re.compile(r"\bC0*(\d{1,2})\b")


# Tempest's OWN trees. The vendored platform tree is excluded except at its declared seams:
# a ledger row may not discharge itself by pointing at a test LibreChat wrote.
_SOURCE_ROOTS = (
    "packages/engine/src",
    "packages/engine/tests",
    "packages/api/src",
    "packages/api/tests",
    "packages/desktop/src",
    "packages/desktop/src-tauri/src",
    "packages/desktop/tests",
    "packages/desktop/e2e",
    "packages/ts-sidecar/src",
    "packages/ts-sidecar/tests",
    "packages/platform/client/tempest",
    "packages/platform/server/tempest",
    "scripts",
    ".github/workflows",
)
_SKIP_DIRS = frozenset(
    {"node_modules", "__pycache__", "target", "dist", "build", ".venv", "coverage", ".git"}
)
_INDEXED_SUFFIXES = frozenset({".py", ".rs", ".ts", ".tsx", ".sh", ".yml", ".yaml"})

# What counts as a VERIFIER: something that is a test or a gate, defined, never merely
# mentioned. The first version of this indexed every definition of any kind — which meant
# ordinary English cleared the bar, and a row reading "proven by the `read` path end to end"
# resolved because something somewhere is called `read`. An adversarial audit demonstrated
# `read`, `done`, `state`, `value`, `open`, `close`, `never`, `good`, `verify` and `check` all
# resolving. A parity claim has to name a TEST, so only tests and gates are indexed now.
#
# Anchoring matters as much as the narrowing: `\bfn NAME` unanchored matched inside comments
# and string literals, so a name mentioned in a `# TODO: … fn test_only_in_a_comment` became a
# definition. Rust tests are found through their `#[test]` attribute instead.
_PY_TESTS = re.compile(
    r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test_[A-Za-z0-9_]*)"
    r"|^[ \t]*class[ \t]+(Test[A-Za-z0-9_]*)",
    re.MULTILINE,
)
_RUST_TESTS = re.compile(
    r"#\[(?:\w+::)?test[^\]]*\][ \t]*\n(?:[ \t]*#\[[^\]]*\][ \t]*\n)*"
    r"[ \t]*(?:async[ \t]+)?fn[ \t]+([A-Za-z_]\w*)"
)
_TS_TESTS = re.compile(r"^[ \t]*(?:test|it|describe)[ \t]*\([ \t]*[\'\"`]([^\'\"`]+)", re.MULTILINE)
#: Files whose STEM is itself a citable verifier: a test module, a spec, a gate, a workflow.
_TEST_FILE = re.compile(r"^(?:test_.+|.+\.spec|.+\.test)$")
_SPEC_TITLE_WORD = re.compile(r"[^A-Za-z0-9]+")
_BACKTICK_SPAN = re.compile(r"`([^`]+)`")
# Leading digits, dots and hyphens are allowed so a spec file cites cleanly
# (`14-editor-budgets.spec`), which is how the e2e suite names its own tests.
_IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{3,}")
# A token shaped like a test or a gate. Rows legitimately cite non-test identifiers —
# `Range`, `llamacpp`, `stop()`, a file name — so "at least one cites something real" is the
# rule for the row as a whole; but a token that CLAIMS to be a test by its own naming
# convention has to exist, or a fiction can ride into the ledger beside a real citation.
# Written after exactly that happened: `test_platform_catalog`, invented while correcting
# LC03, passed the weaker rule because `provider_matrix` resolved in the same cell.
_TEST_SHAPED = re.compile(
    r"^(?:test[_-].+|TEST[_A-Z].*|Test[A-Z]\w*|.+[_-](?:bench|check|suite|test|e2e)"
    r"|.+\.(?:spec|test))$"
)


@dataclasses.dataclass(frozen=True)
class Row:
    """One parsed ledger row. `relationship`/`phase`/`status` are None when the row's table
    declares no such column — a shipped capability has no future phase, and a known-open item
    has neither relationship nor status by design."""

    ident: str
    text: str
    relationship: str | None
    phase: str | None
    status: str | None
    status_base: str | None
    evidence: str
    part: str
    #: Membership is POSITIONAL — between the `## Part 1` and `## Part 2` headings — not a
    #: string test on the nearest heading. Inserting one ordinary `## ` heading above a
    #: subsection re-parented fourteen LibreChat rows out of the parity denominator and raised
    #: published parity three points without deleting or moving a single row.
    in_part_one: bool
    is_feature: bool
    line: int


@dataclasses.dataclass(frozen=True)
class Parse:
    rows: tuple[Row, ...]
    denominator: int | None
    problems: tuple[str, ...]

    @property
    def features(self) -> tuple[Row, ...]:
        return tuple(row for row in self.rows if row.is_feature)

    def part_one(self) -> tuple[Row, ...]:
        """The parity denominator: Part 1's feature rows, the LibreChat capabilities."""
        return tuple(row for row in self.features if row.in_part_one)


def _repo_root() -> Path:
    """Walk up to the repository by marker, matching `dev/upstream_check.py`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages" / "desktop").is_dir():
            return parent
    raise SystemExit("run from the tempest repository")


def _strip_non_structure(body: str) -> str:
    """Blank out everything a reader does not see as a live ledger row, preserving line numbers.

    Three kinds, each of which was demonstrated to smuggle counted rows past this gate:

    * **Fenced blocks** — backtick AND tilde. Per CommonMark a fence closes only on the SAME
      character, at least as long as the opener, with nothing but whitespace after it. A
      documentation example of a row must never read as a live row.
    * **HTML comments.** A complete table wrapped in `<!-- -->` renders as nothing and parsed
      as ten `ADOPTED` capabilities, moving published parity nine points on rows no reader can
      see. Comments may open and close mid-line, so the scan is character-wise.
    * **Indented code blocks.** Four spaces makes a literal block on GitHub; the fenced form was
      already treated as documentation and the indented form was being counted as structure.

    Line count is preserved exactly, so every reported line number stays the reader's.
    """
    body = _blank_html_comments(body)
    out: list[str] = []
    fence_char = ""
    fence_len = 0
    for line in body.splitlines():
        stripped = line.lstrip()
        if fence_len == 0 and line.startswith("    ") and stripped.startswith("|"):
            out.append("")  # an indented block is documentation, exactly as a fenced one is
            continue
        if fence_len == 0:
            opener = next((ch for ch in "`~" if stripped.startswith(ch * 3)), None)
            if opener is None:
                out.append(line)
                continue
            fence_char = opener
            fence_len = len(stripped) - len(stripped.lstrip(opener))
            out.append("")
            continue
        if stripped.startswith(fence_char):
            run = len(stripped) - len(stripped.lstrip(fence_char))
            if run >= fence_len and not stripped[run:].strip():
                fence_len = 0
        out.append("")
    return "\n".join(out)


def _blank_html_comments(body: str) -> str:
    """Replace `<!-- … -->` spans with spaces, keeping every newline so lines still align."""
    out: list[str] = []
    index = 0
    while index < len(body):
        start = body.find("<!--", index)
        if start == -1:
            out.append(body[index:])
            break
        out.append(body[index:start])
        end = body.find("-->", start + 4)
        hidden = body[start:] if end == -1 else body[start : end + 3]
        out.append("".join("\n" if char == "\n" else " " for char in hidden))
        if end == -1:
            break
        index = end + 3
    return "".join(out)


def _split_cells(line: str) -> list[str]:
    """Split a table row on unescaped pipes, so a cell may contain a literal `\\|`."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
            current.append(char)
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _separator_row(cells: list[str]) -> bool:
    """True for `|---|`, `| --- |`, `|:---:|` and friends in any prettifier dialect."""
    return bool(cells) and all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _status_parts(cell: str) -> tuple[str | None, str | None, bool]:
    """(base, provenance, well_formed) for a status cell like `SHIPPED (P4)`."""
    match = _STATUS_CELL.match(cell)
    if match is None:
        return None, None, False
    return match.group(1), match.group(2), True


def _cell(cells: list[str], column: dict[str, int], name: str) -> str:
    """One named cell, or "" when this table declares no such column."""
    position = column.get(name)
    return "" if position is None else cells[position].strip()


def _optional(cells: list[str], column: dict[str, int], name: str) -> str | None:
    """None distinguishes "this table has no such column" from "the cell is empty" — a shipped
    capability legitimately has no phase, while a blank phase on an unfinished row is a defect."""
    return _cell(cells, column, name) if name in column else None


def parse(path: Path) -> Parse:
    """Parse the ledger. Structural problems (unknown tables, malformed rows) are collected
    here so that every arm reports together rather than one per run."""
    problems: list[str] = []
    rows: list[Row] = []
    body = _strip_non_structure(path.read_text(encoding="utf-8", errors="replace"))
    lines = body.splitlines()

    part = "(no part heading)"
    in_part_one = False
    part_headings: dict[str, int] = {"Part 1": 0, "Part 2": 0}
    consumed: set[int] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("## "):
            part = stripped[3:].strip()
            for name in part_headings:
                if part.startswith(name):
                    part_headings[name] += 1
                    in_part_one = name == "Part 1"
            index += 1
            continue
        if not stripped.startswith("|"):
            index += 1
            continue

        header = _split_cells(stripped)
        schema = tuple(cell.lower().strip("*` ") for cell in header)
        if index + 1 >= len(lines) or not _separator_row(_split_cells(lines[index + 1])):
            problems.append(
                f"line {index + 1}: a table row with no header separator beneath it — "
                "this gate cannot tell which column is which, so it refuses to guess"
            )
            consumed.add(index)
            index += 1
            continue

        is_feature = schema in _FEATURE_SCHEMAS
        is_open = schema == _OPEN_SCHEMA
        if not (is_feature or is_open):
            problems.append(
                f"line {index + 1}: unrecognised table header {' | '.join(header)!r} — "
                "the ledger's schema changed and this gate would have silently measured zero "
                "rows. Declare the new shape in feature_ledger._FEATURE_SCHEMAS, or restore "
                "the column names"
            )
            consumed.update({index, index + 1})
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                consumed.add(index)
                index += 1
            continue

        column = {name: position for position, name in enumerate(schema)}
        consumed.update({index, index + 1})
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            consumed.add(index)
            cells = _split_cells(lines[index])
            if len(cells) != len(schema):
                problems.append(
                    f"line {index + 1}: {len(cells)} cells under a {len(schema)}-column header "
                    "— a ragged row is a row whose columns cannot be trusted"
                )
                index += 1
                continue

            status_cell = _optional(cells, column, "status")
            base: str | None = None
            provenance: str | None = None
            well_formed = True
            if status_cell is not None:
                base, provenance, well_formed = _status_parts(status_cell)
                if not well_formed:
                    problems.append(
                        f"line {index + 1}: status {status_cell!r} is not a status — the "
                        f"vocabulary is {', '.join(sorted(STATUSES))}"
                    )
                elif provenance is not None and provenance.strip() in _PLACEHOLDER_CELLS:
                    problems.append(
                        f"line {index + 1}: status {status_cell!r} names an empty provenance — "
                        "a `SHIPPED (…)` row must name the capability that satisfies it"
                    )

            rows.append(
                Row(
                    ident=_cell(cells, column, "#").strip("*` "),
                    text=(
                        _cell(cells, column, "capability")
                        if is_feature
                        else _cell(cells, column, "item")
                    ),
                    relationship=_optional(cells, column, "rel."),
                    phase=_optional(cells, column, "phase"),
                    status=status_cell,
                    status_base=base,
                    evidence=(
                        _cell(cells, column, "verifying test")
                        or _cell(cells, column, "gate")
                        or _cell(cells, column, "note")
                    ),
                    part=part,
                    in_part_one=in_part_one,
                    is_feature=is_feature,
                    line=index + 1,
                )
            )
            index += 1

    for name, seen in part_headings.items():
        if seen != 1:
            problems.append(
                f"`## {name}` appears {seen} times — parity membership is decided by position "
                "between the two part headings, so exactly one of each must exist"
            )

    # Anything that LOOKS like a table row and was not read as one. A GFM row may legally omit
    # its outer pipes and a blockquoted row still renders to the reader, and neither reaches a
    # `startswith("|")` parser: dropping one row silently lowered the counted denominator by
    # one, and hiding the whole known-open table reported "0 open items carried with a phase
    # and a reason" without a single complaint. Invisible-to-the-parser must never be silent.
    for number, text in enumerate(lines):
        if number in consumed or not text.strip():
            continue
        if len(_split_cells(text)) >= 4 and text.count("|") >= 3:
            problems.append(
                f"line {number + 1}: this looks like a ledger row but was not read as one — a "
                "row missing its outer pipes, or inside a blockquote, still renders to a "
                "reader while being invisible here. Put it in its table, or fence it"
            )

    matches = list(_DENOMINATOR.finditer(body))
    denominator: int | None = None
    if len(matches) > 1:
        problems.append(
            f"Part 1 states its denominator {len(matches)} times — the first match wins, so a "
            "second claim lets the number a reader sees say anything"
        )
    elif matches:
        denominator = int(matches[0].group(1))
        claim_line = body[: matches[0].start()].count("\n") + 1
        late = [row for row in rows if row.is_feature and row.in_part_one and row.line > claim_line]
        for row in late:
            problems.append(
                f"line {row.line}: {row.ident} is a Part 1 row placed AFTER the denominator "
                f"claim on line {claim_line}, so the claim a reader reads is not a claim "
                "about it"
            )
    return Parse(rows=tuple(rows), denominator=denominator, problems=tuple(problems))


def _check_identity(rows: tuple[Row, ...]) -> list[str]:
    problems: list[str] = []
    seen: dict[str, int] = {}
    for row in rows:
        if not _ID.match(row.ident):
            problems.append(
                f"line {row.line}: {row.ident!r} is not a ledger id — ids are `LC04`, `LC19b`, "
                "`T37`; parity is counted over them, so a malformed one is uncountable"
            )
        if row.ident in seen:
            problems.append(
                f"line {row.line}: id {row.ident} is already used at line {seen[row.ident]} — "
                "one id meaning two things is how a ledger starts lying"
            )
        else:
            seen[row.ident] = row.line
    return problems


def _check_classification(rows: tuple[Row, ...]) -> list[str]:
    problems: list[str] = []
    for row in rows:
        if not row.is_feature:
            continue
        if row.relationship not in RELATIONSHIPS:
            problems.append(
                f"line {row.line}: {row.ident} declares no valid L30 relationship "
                f"(found {row.relationship or 'nothing'!r}) — every adopted feature declares "
                f"exactly one of {', '.join(sorted(RELATIONSHIPS))}"
            )
        if row.status_base is not None and row.status_base not in STATUSES:
            problems.append(
                f"line {row.line}: {row.ident} has status {row.status_base!r}, which is not in "
                f"the vocabulary ({', '.join(sorted(STATUSES))})"
            )
        if row.status is None or row.status.strip() in _PLACEHOLDER_CELLS:
            problems.append(f"line {row.line}: {row.ident} carries no status")
        if row.text.strip() in _PLACEHOLDER_CELLS:
            problems.append(
                f"line {row.line}: {row.ident} names no capability — a bare id is a claim"
            )
        if row.evidence.strip() in _PLACEHOLDER_CELLS:
            problems.append(
                f"line {row.line}: {row.ident} names no verifying test — under ledger rule 1 a "
                "row's status means nothing without the test that establishes it"
            )
        if row.status_base in UNFINISHED:
            if row.phase is None or row.phase.strip() in _PLACEHOLDER_CELLS:
                problems.append(
                    f"line {row.line}: {row.ident} is {row.status_base} but names no phase — "
                    "undone work with no phase is undone work nobody owns"
                )
            elif not _PHASE_TOKEN.search(row.phase):
                problems.append(
                    f"line {row.line}: {row.ident} names phase {row.phase!r}, which is not a "
                    "phase — use `C5`, `24`, `owner`, or a range like `C0 → 3`"
                )
            elif row.in_part_one and not _C_PHASE.search(row.phase):
                problems.append(
                    f"line {row.line}: {row.ident} is an unfinished LibreChat row owned by "
                    f"{row.phase!r}, which names no C-phase. A bare number is a v2 phase and is "
                    "invisible to the closed-phase check, so the row would be owned by nothing"
                )
    return problems


def _check_open_items(rows: tuple[Row, ...]) -> list[str]:
    problems: list[str] = []
    for row in rows:
        if row.is_feature:
            continue
        if row.phase is None or row.phase.strip() in _PLACEHOLDER_CELLS:
            problems.append(
                f"line {row.line}: open item {row.ident} names no phase — an open item with no "
                "phase is a debt with no owner"
            )
        elif not _PHASE_TOKEN.search(row.phase):
            problems.append(
                f"line {row.line}: open item {row.ident} names phase {row.phase!r}, which is "
                "not a phase"
            )
        if row.evidence.strip() in _PLACEHOLDER_CELLS:
            problems.append(
                f"line {row.line}: open item {row.ident} carries no note — a bare row records "
                "that something is open without recording what or why"
            )
        elif _STATUS_WORD.search(f"{row.text} {row.evidence}"):
            problems.append(
                f"line {row.line}: open item {row.ident} uses a status word in its note — the "
                "known-open table carries debts, and a done-ness claim made here is one that "
                "escaped classification entirely"
            )
    return problems


def verifier_index(root: Path) -> frozenset[str]:
    """Every name in Tempest's own trees that IS a test or a gate.

    Deliberately narrow. This set is the bar a finished row's citation has to clear, so
    anything in it that is not a verifier is a way for a row to discharge itself with a word.
    Indexed: Python `test_*` functions and `Test*` classes; Rust functions carrying a `#[test]`
    attribute; Playwright/vitest titles (verbatim and with punctuation folded to underscores,
    because a title is prose while the ledger cites it as an identifier); the stems of test
    modules, spec files, `tempest/dev/` gate modules, gate scripts and CI workflows.
    """
    names: set[str] = set()
    for relative in _SOURCE_ROOTS:
        base = root / relative
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in _INDEXED_SUFFIXES:
                continue
            if _SKIP_DIRS & set(path.relative_to(base).parts):
                continue
            parts = path.parts
            # A gate is identified by its OWN location, not by the root it was reached from:
            # `tempest/dev/agent_bench.py` is reached through `packages/engine/src`.
            gate = parts[-3:-1] == ("tempest", "dev") or parts[-2] in {"scripts", "workflows"}
            if gate or _TEST_FILE.match(path.stem) or "tests" in parts or "e2e" in parts:
                names.add(path.stem)
                names.add(path.stem.replace("-", "_"))
            text = path.read_text(encoding="utf-8", errors="replace")
            captured: list[str] = []
            for groups in _PY_TESTS.findall(text):
                captured.extend(name for name in groups if name)
            captured.extend(_RUST_TESTS.findall(text))
            captured.extend(_TS_TESTS.findall(text))
            for name in captured:
                names.add(name)
                folded = _SPEC_TITLE_WORD.sub("_", name).strip("_")
                if folded:
                    names.add(folded)
    return frozenset(names)


def _cited_identifiers(evidence: str) -> list[str]:
    """Identifiers cited inside backticks. Backticks are the ledger's own convention for
    naming a runnable thing, and prose outside them is commentary."""
    return [
        token for span in _BACKTICK_SPAN.findall(evidence) for token in _IDENTIFIER.findall(span)
    ]


def _check_verifying_tests_resolve(rows: tuple[Row, ...], names: frozenset[str]) -> list[str]:
    """Ledger rule 1, made mechanical for the rows that CLAIM to be finished.

    Scope, stated exactly: this proves the cited name is not fiction — that something by that
    name is defined in Tempest's own trees. It does NOT prove that test ran, or passed, or
    covers what the row says. Running it is the phase gate's job. The failure this arm exists
    to stop is the cheaper one: a row flipped to ADOPTED citing a test nobody wrote.
    """
    problems: list[str] = []
    for row in rows:
        if not row.is_feature or row.status_base not in {"ADOPTED", "SHIPPED"}:
            continue
        cited = _cited_identifiers(row.evidence)
        if not cited:
            problems.append(
                f"line {row.line}: {row.ident} is {row.status_base} but cites no verifying test "
                "by name — under ledger rule 1 the status IS the test, so an unnamed one cannot "
                "be re-run by a reviewer, or by the next session"
            )
            continue
        if not any(token in names for token in cited):
            problems.append(
                f"line {row.line}: {row.ident} is {row.status_base} and cites "
                f"{', '.join(sorted(set(cited))[:6])} — none of which is a test or a gate that "
                "exists in Tempest's own trees. Either the test moved, or the row names one "
                "that was never written"
            )
            continue
        for token in sorted({t for t in cited if _TEST_SHAPED.match(t) and t not in names}):
            problems.append(
                f"line {row.line}: {row.ident} cites `{token}`, which is named like a test but "
                "is defined nowhere in Tempest's own trees. A fiction cited beside a real test "
                "is the failure this arm exists to catch"
            )
    return problems


def closed_phases(plan_path: Path) -> frozenset[str]:
    """Phases whose every checkbox in `docs/PLAN-V3.md` is ticked.

    A phase with no boxes is not closed — it is unwritten, and treating an empty section as
    finished is the most flattering possible reading of a blank page.
    """
    counts: dict[str, list[int]] = {}
    phase: str | None = None
    plan = _strip_non_structure(plan_path.read_text(encoding="utf-8", errors="replace"))
    for line in plan.splitlines():
        stripped = line.strip()
        # ANY `## ` heading ends the phase's boxes. Without this an ordinary section — a
        # "Notes on C4" aside, or a phase heading someone reformatted — donates its unticked
        # boxes to whichever phase came before it, reopening a closed phase from outside.
        if stripped.startswith("## "):
            heading = _PHASE_HEADING.match(stripped)
            phase = heading.group(1) if heading else None
            if phase is not None:
                counts.setdefault(phase, [0, 0])
            continue
        box = _CHECKBOX.match(stripped)
        if phase is not None and box:
            counts[phase][0] += box.group(1) in "xX"
            counts[phase][1] += 1
    return frozenset(name for name, (done, total) in counts.items() if total > 0 and done == total)


def _check_open_phase_ownership(rows: tuple[Row, ...], closed: frozenset[str]) -> list[str]:
    """The disagreement nobody could previously see.

    C5's close-out found five unfinished ledger rows owned by C4 and two by C3. Either those
    capabilities are genuinely open — in which case the phase that owns them was closed too
    early — or the ledger is stale. Both are defects, and until this arm existed neither was
    visible from either document: the plan says a phase is done, the ledger says work remains
    inside it, and the two files are never read together.

    An unfinished row must therefore name a phase that is still open. Adopting the row, or
    moving it to the phase that will really do it, are both fine; leaving it pointing at
    finished work is not.
    """
    problems: list[str] = []
    for row in rows:
        if not row.is_feature or row.status_base not in UNFINISHED or row.phase is None:
            continue
        # Normalised, so `C05` cannot name C5 while dodging the comparison against it.
        for name in sorted({f"C{int(digits)}" for digits in _C_PHASE.findall(row.phase)}):
            if name in closed:
                problems.append(
                    f"line {row.line}: {row.ident} is {row.status_base} but is owned by {name}, "
                    f"a phase whose every box is ticked — either {name} was closed too early, "
                    "or this row is stale. Adopt it, or move it to the phase that will "
                    "actually do it"
                )
    return problems


def _check_denominator(parse_result: Parse) -> list[str]:
    counted = len(parse_result.part_one())
    if parse_result.denominator is None:
        return [
            "Part 1 states no `**Denominator: N rows.**` — parity is a fraction, and a "
            f"fraction with an unstated denominator is not a measurement (counted {counted})"
        ]
    if parse_result.denominator != counted:
        return [
            f"Part 1 states a denominator of {parse_result.denominator} rows but carries "
            f"{counted} — the stated arithmetic is stale, which is exactly the hand-maintained "
            "integer L35 exists to stop anyone trusting"
        ]
    return []


def _check_platform_vocabulary(rows: tuple[Row, ...]) -> list[str]:
    problems: list[str] = []
    for row in rows:
        if not row.is_feature or row.relationship != "PLATFORM":
            continue
        for token in sorted(RESERVED_VERDICTS):
            haystack = " ".join(
                part for part in (row.text, row.evidence, row.phase, row.status) if part
            )
            if re.search(rf"\b{token}\b", haystack):
                problems.append(
                    f"line {row.line}: {row.ident} is PLATFORM and uses the reserved verdict "
                    f"{token} — L31: a PLATFORM feature ships at full quality but may never "
                    "claim proof or borrow the verdict vocabulary, and a ledger that describes "
                    "it in verdict words has already made the claim"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--every-feature-classified", action="store_true")
    parser.add_argument("--no-verdict-vocab-in-platform", action="store_true")
    parser.add_argument("--verifying-tests-resolve", action="store_true")
    parser.add_argument("--no-unfinished-rows-in-closed-phases", action="store_true")
    parser.add_argument("--plan", default=None, help="plan path (default: docs/PLAN-V3.md)")
    parser.add_argument("--ledger", default=None, help="ledger path (default: docs/FEATURES-V3.md)")
    parser.add_argument("--root", default=None, help="repository root (default: this repository)")
    args = parser.parse_args(argv)

    if args.ledger is not None:
        ledger_path = Path(args.ledger)
    else:
        root = Path(args.root) if args.root else _repo_root()
        ledger_path = root / _DEFAULT_LEDGER

    if not ledger_path.is_file():
        print(f"feature_ledger: {ledger_path} — FAIL")
        print(
            f"FEATURE-LEDGER {ledger_path}: missing — the ledger is the instrument L30 and L35 "
            "are measured with; without it nothing is classified and nothing is counted",
            file=sys.stderr,
        )
        return 1

    parsed = parse(ledger_path)
    fail: list[str] = list(parsed.problems)
    fail += _check_identity(parsed.rows)
    fail += _check_denominator(parsed)
    fail += _check_open_items(parsed.rows)
    if not parsed.features:
        fail.append(
            f"{ledger_path}: zero feature rows parsed — a ledger gate that measures nothing "
            "reports green over a file it never read, which is worse than no gate at all"
        )
    if args.every_feature_classified:
        fail += _check_classification(parsed.rows)
    if args.no_verdict_vocab_in_platform:
        fail += _check_platform_vocabulary(parsed.rows)
    if args.verifying_tests_resolve:
        index_root = Path(args.root) if args.root else _repo_root()
        fail += _check_verifying_tests_resolve(parsed.rows, verifier_index(index_root))
    if args.no_unfinished_rows_in_closed_phases:
        plan_root = Path(args.root) if args.root else _repo_root()
        plan_path = Path(args.plan) if args.plan else plan_root / _DEFAULT_PLAN
        if not plan_path.is_file():
            fail.append(
                f"{plan_path}: missing — phase ownership cannot be checked against a plan that "
                "is not there, and passing this arm vacuously would be worse than not running it"
            )
        else:
            fail += _check_open_phase_ownership(parsed.rows, closed_phases(plan_path))

    if fail:
        print(f"feature_ledger: {len(fail)} problem(s) — FAIL")
        for problem in fail:
            print(f"FEATURE-LEDGER {problem}", file=sys.stderr)
        return 1

    features = parsed.features
    platform = sum(1 for row in features if row.relationship == "PLATFORM")
    print(
        f"feature_ledger: {len(features)} feature rows, every one classified "
        f"({len(features) - platform} proof-related, {platform} PLATFORM), "
        f"{len(parsed.part_one())} in the parity denominator as stated, "
        f"{len(parsed.rows) - len(features)} open items carried with a phase and a reason, "
        "zero PLATFORM rows borrowing the verdict vocabulary — L30 holds"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
