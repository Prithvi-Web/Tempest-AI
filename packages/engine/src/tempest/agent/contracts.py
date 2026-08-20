"""F2 — Intent Contracts: natural language compiled to an executable equivalence relation.

The user says *"fix the rounding on refunds; nothing else changes"*. That sentence is a claim
about which symbols may change behaviour and which must not, and a differential engine can check
exactly that claim — but only once it is a **structure** rather than prose. This module is the
structure, the file it lives in, and the mechanical classifier that consumes it.

    intent (words)  →  IntentContract (typed)  →  per-divergence classification

**The safety property, which shapes every decision below.** F2's gate says *zero* unintended
divergences may be classified as intended: a false `INTENDED` is worse than not having the
feature, because it is the one outcome that turns evidence into false reassurance. So:

* `INTENDED` requires an **explicit** match in `may_change`. Nothing is inferred, nothing is
  fuzzy-matched, and no substring ever counts.
* Anything not explicitly permitted is `UNCLASSIFIED`, never `INTENDED`. Unclassified divergences
  are the ones surfaced *most* prominently — nobody predicted them.
* A symbol named in **both** lists is a contradiction, and it resolves to `UNINTENDED`. The safe
  side of an ambiguity is the side that shows the user the divergence.

**The model drafts; it does not decide.** A model may propose a contract (`draft_from_text`
parses its structured answer), but the contract is written to `.tempest/contracts/` as a file the
user reads and edits, and the *classification* is this module's mechanical function of the
contract. No model output reaches a classification (L17).

**Why TOML and not the YAML the feature sheet names.** `tomllib` is in the standard library; YAML
is not, and the engine ships frozen into a sidecar where a new C extension is a real cost. TOML is
already this project's config format (`tempest.toml`, the corpus specs), it supports comments —
which a contract the user is invited to edit genuinely needs — and reading it needs no dependency
at all. Recorded in ADR-0050.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Where a task's contract lives, relative to the repo. Committed on purpose: a contract is a
#: reviewable artifact, and a change to it should show up in a diff like any other decision.
CONTRACTS_DIR = Path(".tempest") / "contracts"

INTENDED = "INTENDED"
UNINTENDED = "UNINTENDED"
UNCLASSIFIED = "UNCLASSIFIED"

#: The three outcomes, closed. Deliberately NOT added to `Verdict` (L2 keeps that vocabulary at
#: four): a classification qualifies a divergence, it is not a verdict about a target.
CLASSIFICATIONS = (INTENDED, UNINTENDED, UNCLASSIFIED)


class ContractError(Exception):
    """A contract could not be read or is not well formed. Never used for a classification."""


@dataclass(frozen=True)
class IntentContract:
    """What the user said, compiled to what the engine can check.

    `may_change` and `must_not_change` hold fully-qualified symbol names, optionally ending in
    `.*` to name a module or class. A bare `*` is refused: "everything may change" is not an
    intent, it is the absence of one, and it would make every divergence INTENDED — the exact
    outcome the gate forbids.
    """

    intent: str
    may_change: tuple[str, ...] = ()
    must_not_change: tuple[str, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if not self.intent.strip():
            raise ContractError("a contract must record the intent it was compiled from")
        for pattern in (*self.may_change, *self.must_not_change):
            if not pattern.strip():
                raise ContractError("an empty symbol pattern matches nothing and means nothing")
            if pattern.strip() in {"*", ".*"}:
                raise ContractError(
                    "'*' is not an intent: a contract permitting every change would classify "
                    "every divergence INTENDED, which is the one thing F2's gate forbids"
                )

    def classify(self, qualname: str) -> str:
        """Which of the three this symbol's divergence is. Mechanical, total, and conservative.

        Order matters and is not arbitrary: `must_not_change` is checked FIRST, so a symbol
        named in both lists resolves to UNINTENDED. That is a contradiction in the contract, and
        the honest resolution of an ambiguity is the one that shows the user the divergence
        rather than the one that hides it.
        """
        if _matches_any(qualname, self.must_not_change):
            return UNINTENDED
        if _matches_any(qualname, self.may_change):
            return INTENDED
        return UNCLASSIFIED


def _matches_any(qualname: str, patterns: tuple[str, ...]) -> bool:
    """Exact name, or an explicit `prefix.*`. Never a substring, never a fuzzy match.

    `Refund.round` does NOT match `Refund.rounding`, and `pkg.a` does not match `pkg.ab` — a
    prefix rule written with `startswith` would do both, and each one is a false INTENDED waiting
    for a name that happens to share a stem.
    """
    for raw in patterns:
        pattern = raw.strip()
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            if qualname == prefix or qualname.startswith(prefix + "."):
                return True
        elif qualname == pattern:
            return True
    return False


# --------------------------------------------------------------------------------------------
# Persistence — a file the user can read and edit.
# --------------------------------------------------------------------------------------------


def path_for(repo: Path, task_id: str) -> Path:
    return Path(repo) / CONTRACTS_DIR / f"{_slug(task_id)}.toml"


def _slug(task_id: str) -> str:
    """A filesystem-safe name. Anything outside the allowlist becomes `-`, so a task id can
    never place the file outside the contracts directory."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", task_id).strip(".-")
    return cleaned or "task"


def render(contract: IntentContract) -> str:
    """The contract as the user sees it — with the comments that make it editable.

    Written by hand rather than by a serializer because the comments ARE the interface: a user
    who cannot tell what the two lists mean cannot correct one, and a contract nobody corrects is
    a contract nobody trusts.
    """
    lines = [
        "# Tempest intent contract — this file is yours to edit.",
        "#",
        "# It says which symbols are ALLOWED to change behaviour and which must not. Tempest",
        "# proves the change either way; this decides how each divergence is presented:",
        "#",
        "#   may_change       -> a divergence here is INTENDED",
        "#   must_not_change  -> a divergence here is UNINTENDED, and is a failure",
        "#   anything else    -> UNCLASSIFIED, and is shown most prominently of all, because",
        "#                       nobody predicted it",
        "#",
        "# Names are fully qualified. End one with `.*` to mean a module or class.",
        "# There is deliberately no way to say 'everything may change'.",
        "",
        f"version = {contract.version}",
        f"intent = {_toml_string(contract.intent)}",
        "",
        "may_change = [",
        *[f"    {_toml_string(s)}," for s in contract.may_change],
        "]",
        "",
        "must_not_change = [",
        *[f"    {_toml_string(s)}," for s in contract.must_not_change],
        "]",
        "",
    ]
    return "\n".join(lines)


def _toml_string(value: str) -> str:
    """A TOML basic string. Escapes the four characters that would otherwise end or reshape it."""
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
    return f'"{escaped}"'


def save(repo: Path, task_id: str, contract: IntentContract) -> Path:
    target = path_for(repo, task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(contract), encoding="utf-8")
    return target


def load(repo: Path, task_id: str) -> IntentContract | None:
    """The user's contract for this task, or None when there is none.

    None is a real answer and not an error: a task without a contract is proved exactly the same
    way, and every divergence comes back UNCLASSIFIED — which is the honest description of a run
    nobody stated an intent for.
    """
    source = path_for(repo, task_id)
    if not source.is_file():
        return None
    try:
        doc: dict[str, Any] = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ContractError(f"{source} is not valid TOML: {exc}") from exc
    return _from_document(doc, source)


def _from_document(doc: dict[str, Any], source: Path | str) -> IntentContract:
    intent = doc.get("intent")
    if not isinstance(intent, str):
        raise ContractError(f"{source}: `intent` must be a string")
    return IntentContract(
        intent=intent,
        may_change=_string_list(doc.get("may_change"), "may_change", source),
        must_not_change=_string_list(doc.get("must_not_change"), "must_not_change", source),
        version=int(doc.get("version", 1)),
    )


def _string_list(value: Any, field: str, source: Path | str) -> tuple[str, ...]:
    """A list of strings, or an error naming the field.

    A malformed list is refused rather than skipped. Skipping would silently empty
    `must_not_change`, turning a contract that forbids changes into one that forbids nothing —
    a typo becoming a permission.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ContractError(f"{source}: `{field}` must be a list of strings")
    return tuple(str(v) for v in value)


# --------------------------------------------------------------------------------------------
# Drafting — the model proposes, in a structure, and never decides.
# --------------------------------------------------------------------------------------------

DRAFT_SYSTEM_PROMPT = """You compile a developer's stated intent into a contract.

Answer with TOML and nothing else, in exactly this shape:

intent = "<the developer's words, copied verbatim>"
may_change = ["pkg.module.symbol", "pkg.module.Class.*"]
must_not_change = ["pkg.other.symbol"]

Rules:
- Names are fully qualified. `Class.*` or `module.*` names a whole class or module.
- Put a symbol in may_change ONLY if the developer's words clearly permit its behaviour to
  change. When in doubt, leave it out: an unlisted symbol is reported as unclassified and shown
  to the developer, which is the safe outcome. Guessing that something was intended is not.
- Never write "*" or any pattern that would permit everything.
- You are not deciding whether the change is correct. An execution engine does that."""


def draft_from_text(reply: str, *, intent: str) -> IntentContract:
    """Parse a model's TOML answer into a contract, keeping the USER's intent verbatim.

    The model's `intent` field is deliberately discarded in favour of the text the user actually
    typed. A contract is a record of what the user asked for, and a paraphrase — however
    faithful — would make the file a record of what a model understood instead.
    """
    body = _strip_fences(reply)
    try:
        doc: dict[str, Any] = tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        raise ContractError(f"the model's contract is not valid TOML: {exc}") from exc
    doc["intent"] = intent
    return _from_document(doc, "the model's reply")


def _strip_fences(reply: str) -> str:
    """Models fence code even when told not to. Accepting that is not a weakening: the fence is
    a formatting habit, and refusing over it would fail a contract that is otherwise exact."""
    text = reply.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
    return "\n".join(body)
